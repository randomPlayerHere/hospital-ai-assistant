"""Rule-based emergency red-flag detection.

Runs BEFORE and INDEPENDENT of any LLM call. Deliberately conservative: it favours false
positives (an unnecessary "seek emergency care" banner) over missing a real emergency.
"""

import re
from dataclasses import dataclass

EMERGENCY_BANNER = (
    "This may be a medical emergency. Call your local emergency number or go to the nearest "
    "emergency department now. Do not wait for an appointment."
)


@dataclass(frozen=True)
class RedFlag:
    code: str
    label: str
    pattern: re.Pattern[str]


def _r(code: str, label: str, regex: str) -> RedFlag:
    return RedFlag(code, label, re.compile(regex, re.IGNORECASE))


_BREATH = r"breath(e|ing|less)"
RED_FLAGS: list[RedFlag] = [
    _r(
        "chest_pain",
        "Chest pain or pressure",
        r"chest\s+(pain|pressure|tightness|discomfort|heaviness)|pain\s+(in|across)\s+(my\s+|the\s+)?chest|"
        r"crushing\s+(pain|feeling)|heart\s+attack|squeezing\s+(in|around)\s+(my\s+)?chest|pain\s+radiating\s+(to|down)\s+(my\s+)?(left\s+)?arm|"
        r"(tearing|ripping)\s+(pain|sensation|feeling)",
    ),
    _r(
        "stroke",
        "Possible stroke signs",
        r"\bstroke\b|(face|facial|mouth)\s+(is\s+)?(droop|drooping|numb|sagging)|slurr(ed|ing)|speech\s+(is\s+|has\s+become\s+)?(garbled|jumbled|affected)|\bdroop|numbness\s+(in|on)\s+(my\s+|the\s+|his\s+|her\s+)?(face|one\s+side)|"
        r"(can'?t|cannot|unable\s+to|trouble)\s+(speak|talk|understand|find\s+words)|"
        r"sudden(ly)?\s+.{0,30}(weak|weakness|numb|numbness|confus|lost\s+(my\s+)?vision|loss\s+of\s+vision|can'?t\s+see|blind|dizz)|"
        r"one\s+side\s+of\s+(my|the|his|her)\s+(body|face)|(arm|leg)\s+(suddenly\s+)?(weak|numb|won'?t\s+move)|"
        r"worst\s+headache\s+of\s+(my|his|her)\s+life|thunderclap",
    ),
    _r(
        "severe_bleeding",
        "Severe or uncontrolled bleeding",
        r"(severe|heavy|massive|uncontrolled|profuse)\s+bleeding|bleeding\s+(heavily|profusely|a\s+lot|badly|won'?t\s+stop|through)|"
        r"won'?t\s+stop\s+bleeding|(coughing|vomiting|spitting)\s+(up\s+)?blood|blood\s+(in|with)\s+(my\s+)?(vomit|stool)|"
        r"bleeding\s+(heavily\s+)?(while|and)\s+pregnant|pregnan\w*.{0,40}bleeding|soaking\s+(through\s+)?(a\s+)?(pad|towel|bandage)",
    ),
    _r(
        "breathing",
        "Severe breathing difficulty",
        rf"(can'?t|cannot|unable\s+to|struggling\s+to|hard\s+to|difficulty|trouble|not\s+able\s+to)\s+{_BREATH}|"
        rf"severe\s+shortness\s+of\s+breath|short(ness)?\s+of\s+breath\s+(at\s+rest|and\s+(blue|chest))|gasping|"
        r"choking|turning\s+blue|blue\s+(lips|face|skin)|stopped\s+breathing|not\s+breathing|stridor|drooling.{0,30}(swallow|breath)",
    ),
    _r(
        "unconscious",
        "Loss of consciousness or seizure",
        r"unconscious|passed\s+out|blacked\s+out|unresponsive|not\s+responding|won'?t\s+wake|seizure|convuls|"
        r"fainted|collapsed|fitting|loss\s+of\s+consciousness|lost\s+consciousness",
    ),
    _r(
        "self_harm",
        "Suicidal thoughts or self-harm",
        r"suicid|kill\s+myself|end\s+(my\s+)?(life|it\s+all)|want\s+to\s+die|self[- ]harm|hurt\s+myself|overdos",
    ),
    _r(
        "anaphylaxis",
        "Severe allergic reaction",
        r"anaphyla|throat\s+(is\s+)?(closing|swelling|tight)|swelling\s+(of\s+)?(my\s+|the\s+)?(face|tongue|throat|lips)|"
        r"(face|tongue|throat|lips)\s+(is\s+|are\s+)?swelling|allergic\s+reaction.{0,40}(breath|swell)",
    ),
    _r(
        "poisoning",
        "Poisoning or overdose",
        r"poison|swallowed\s+(bleach|cleaning|pills|battery|chemical)|drank\s+(bleach|antifreeze)|took\s+too\s+many\s+(pills|tablets)|carbon\s+monoxide",
    ),
    _r(
        "trauma",
        "Serious injury",
        r"gunshot|shot\s+in|stabbed|stab\s+wound|severe\s+(head|burn|trauma)|head\s+injury.{0,60}(vomit|drows|unconscious|confus)|"
        r"(car|road|motorbike|bike)\s+(accident|crash)|fell\s+(from|off)\s+(a\s+)?(height|roof|ladder|stairs)|compound\s+fracture|bone\s+(is\s+)?(sticking|poking)\s+out",
    ),
    _r(
        "infant",
        "Very young infant with serious symptoms",
        r"(newborn|infant|baby|\d+[- ]?(day|week)[- ]old).{0,60}(fever|not\s+feeding|limp|floppy|hard\s+to\s+wake|blue|not\s+breathing)",
    ),
    _r(
        "cardiac",
        "Possible cardiac emergency",
        r"heart\s+(is\s+)?(racing|pounding)\s+and\s+(faint|dizzy|chest)|palpitations?\s+(with|and)\s+(chest|faint|passing\s+out|short)",
    ),
    _r(
        "meningitis",
        "Possible meningitis",
        r"stiff\s+neck.{0,60}(fever|rash|light|headache)|(fever|rash).{0,60}stiff\s+neck",
    ),
    _r(
        "sepsis",
        "Possible sepsis or septic shock",
        r"\bsepsis\b|\bseptic\b|mottled\s+skin|(shivering|rigors).{0,40}(fever|confus)|(fever|confus).{0,40}(shivering|rigors)|(confusion|confused).{0,40}(fever|temperature)",
    ),
]


def detect_red_flags(text: str) -> list[RedFlag]:
    return [f for f in RED_FLAGS if f.pattern.search(text)]
