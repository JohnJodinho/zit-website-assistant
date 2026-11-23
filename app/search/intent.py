from __future__ import annotations

import re

INTENT_PATTERNS = {
    "greeting": re.compile(r"^(hi|hello|hey|good (morning|afternoon|evening))\b", re.I),
    "thanks_bye": re.compile(r"\b(thanks?|thank you|bye|goodbye)\b", re.I),
    "contact": re.compile(
        r"\b(contact|call|phone|email|whatsapp|speak to|talk to|human|agent|address|location)\b",
        re.I,
    ),
    "apply": re.compile(
        r"\b(apply|application|enrol+|register|registration|admission|sign up|join)\b",
        re.I,
    ),
    "scholarship": re.compile(r"\b(scholarship|sponsor\w*|funding|grant)\b", re.I),
    "fee": re.compile(r"\b(fees?|tuition|cost|price|pay\w*|how much)\b", re.I),
    "duration": re.compile(r"\b(duration|how long|weeks|months|length)\b", re.I),
    "requirements": re.compile(
        r"\b(requirements?|qualifications?|eligib\w+|entry)\b",
        re.I,
    ),
    "list_courses": re.compile(
        r"\b(courses?|programmes?|programs?)\b.*\b(list|what|which|available|offer)\b",
        re.I,
    ),
    "compare": re.compile(r"\b(compare|difference|versus|vs)\b", re.I),
}


def detect_intents(text: str) -> frozenset[str]:
    return frozenset(name for name, pattern in INTENT_PATTERNS.items() if pattern.search(text))
