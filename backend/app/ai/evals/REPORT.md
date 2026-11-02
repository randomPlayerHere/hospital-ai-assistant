# Triage evaluation report
Generated 2026-11-02 10:12 UTC. Cases: 60 ({'emergency': 23, 'urgent': 15, 'routine': 13, 'self-care': 9}).

Caveat: the cases were written by the same team that wrote the rules. The rule results below show the rule set covers these cases, not that it generalises; extend `cases.json` with real, de-identified cases over time.

## 1. Rule-based red-flag pre-check (deterministic, no LLM)
- Emergency recall: **23/23** (100%)
- False positives on non-emergency cases: **0/37**

## 2. Full pipeline with LLM (rules first, then model)
**NOT RUN.** Run `python -m app.ai.evals.run --live` with `ANTHROPIC_API_KEY` set to fill this in.
