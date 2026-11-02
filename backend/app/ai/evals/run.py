"""Triage evaluation.

  python -m app.ai.evals.run            # rule pre-check only (offline, deterministic)
  python -m app.ai.evals.run --live     # also run the full LLM pipeline (needs ANTHROPIC_API_KEY)

Writes app/ai/evals/REPORT.md. LLM sections are marked NOT RUN unless --live succeeded.
"""

import argparse
import asyncio
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from app.ai.redflags import detect_red_flags

HERE = Path(__file__).parent
DEPARTMENTS = [
    "Cardiology",
    "Dermatology",
    "Emergency",
    "General Medicine",
    "Neurology",
    "Orthopedics",
    "Pediatrics",
]


def load_cases() -> list[dict]:
    return json.loads((HERE / "cases.json").read_text())


def rule_results(cases: list[dict]) -> dict:
    emergencies = [c for c in cases if c["expected_urgency"] == "emergency"]
    others = [c for c in cases if c["expected_urgency"] != "emergency"]
    missed = [c["id"] for c in emergencies if not detect_red_flags(c["message"])]
    false_pos = [c["id"] for c in others if detect_red_flags(c["message"])]
    return {
        "emergency_total": len(emergencies),
        "emergency_caught": len(emergencies) - len(missed),
        "missed": missed,
        "non_emergency_total": len(others),
        "false_positives": false_pos,
    }


async def live_results(cases: list[dict]) -> dict:
    from app.ai.client import AnthropicLLM
    from app.ai.guards import violates_safety
    from app.ai.prompts import load_prompt
    from app.ai.structured import complete_json
    from app.schemas.ai import TriageLLMOutput

    llm = AnthropicLLM()
    prompt = load_prompt("triage")
    rows = []
    for c in cases:
        if detect_red_flags(c["message"]):  # production path: rules short-circuit the LLM
            rows.append(
                {**c, "got_urgency": "emergency", "got_department": "Emergency", "source": "rules"}
            )
            continue
        system = (
            prompt.render(
                max_turns="1",
                patient_context=str({"age_years": c["age"]}),
                departments=", ".join(DEPARTMENTS),
            )
            + "\nThe patient has given all the information they will give: finish now with ready=true."
        )
        msgs = [{"role": "user", "content": f"<patient_message>{c['message']}</patient_message>"}]
        try:
            out, _ = await complete_json(
                llm, TriageLLMOutput, purpose="eval", system=system, messages=msgs
            )
            rows.append(
                {
                    **c,
                    "got_urgency": out.urgency,
                    "got_department": out.department,
                    "source": "llm",
                    "unsafe_reply": violates_safety(out.reply),
                }
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    **c,
                    "got_urgency": None,
                    "got_department": None,
                    "source": f"error:{type(exc).__name__}",
                }
            )
    n = len(rows)
    urg = sum(r["got_urgency"] == r["expected_urgency"] for r in rows)
    dep = sum(r["got_department"] == r["expected_department"] for r in rows)
    under = [
        r["id"]
        for r in rows
        if r["got_urgency"] in ("routine", "self-care")
        and r["expected_urgency"] in ("emergency", "urgent")
    ]
    return {
        "rows": rows,
        "n": n,
        "urgency_acc": urg / n,
        "department_acc": dep / n,
        "under_triaged": under,
        "model": llm.model,
        "prompt_version": prompt.version,
    }


def report(cases: list[dict], rules: dict, live: dict | None) -> str:
    mix = Counter(c["expected_urgency"] for c in cases)
    lines = [
        "# Triage evaluation report",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Cases: {len(cases)} ({dict(mix)}).",
        "",
        (
            "Caveat: the cases were written by the same team that wrote the rules. The rule results below show "
            "the rule set covers these cases, not that it generalises; extend `cases.json` with real, "
            "de-identified cases over time."
        ),
        "",
        "## 1. Rule-based red-flag pre-check (deterministic, no LLM)",
        f"- Emergency recall: **{rules['emergency_caught']}/{rules['emergency_total']}**"
        + (f" (missed: {', '.join(rules['missed'])})" if rules["missed"] else " (100%)"),
        f"- False positives on non-emergency cases: **{len(rules['false_positives'])}/{rules['non_emergency_total']}**"
        + (f" ({', '.join(rules['false_positives'])})" if rules["false_positives"] else ""),
        "",
        "## 2. Full pipeline with LLM (rules first, then model)",
    ]
    if live is None:
        lines.append(
            "**NOT RUN.** Run `python -m app.ai.evals.run --live` with `ANTHROPIC_API_KEY` set to fill this in."
        )
    else:
        lines += [
            f"- Model: `{live['model']}`, prompt `{live['prompt_version']}`",
            f"- Urgency accuracy: **{live['urgency_acc']:.0%}** ({round(live['urgency_acc'] * live['n'])}/{live['n']})",
            f"- Department accuracy: **{live['department_acc']:.0%}** ({round(live['department_acc'] * live['n'])}/{live['n']})",
            f"- Under-triaged (emergency/urgent predicted as routine/self-care): {live['under_triaged'] or 'none'}",
            "",
            "| id | expected | got | dept expected | dept got | source |",
            "|---|---|---|---|---|---|",
            *[
                f"| {r['id']} | {r['expected_urgency']} | {r['got_urgency']} | {r['expected_department']} | {r['got_department']} | {r['source']} |"
                for r in live["rows"]
            ],
        ]
    return "\n".join(lines) + "\n"


async def main(live: bool) -> None:
    cases = load_cases()
    rules = rule_results(cases)
    live_res = None
    if live:
        from app.ai.client import ai_configured
        if not ai_configured():
            raise SystemExit("ANTHROPIC_API_KEY not configured; cannot run --live")
        live_res = await live_results(cases)
    (HERE / "REPORT.md").write_text(report(cases, rules, live_res))
    print((HERE / "REPORT.md").read_text())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    asyncio.run(main(ap.parse_args().live))
