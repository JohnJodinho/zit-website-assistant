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
    "injection": re.compile(
        r"\b(ignore|disregard|override)\b.{0,50}\b(instructions?|system prompt|safety|filters?|"
        r"retrieved context|website facts)\b"
        r"|\b(reveal|expose|return|output|show|tell)\b.{0,40}\b(password|api key|secret|"
        r"system prompt|instructions?)\b"
        r"|\b(pretend|act as)\b.{0,40}\b(bot|assistant|billing bot)\b"
        r"|\b(add|invent|make up|fabricate)\b.{0,60}\b(fake|discount|tuition|deadline|"
        r"phone number|course)\b"
        r"|\b(use only)\b.{0,40}\b(personal knowledge)\b"
        r"|\b(repeat)\b.{0,40}\b(previous assistant message)\b"
        r"|\b(say|claim)\b.{0,60}\b(course|fact|discount)\b.{0,40}\b(not listed|not offered|fake)\b"
        r"|\b(call a tool|delete (the )?published content|change the active release|"
        r"disable (all )?filters|steal\w* user data|raw html|scripts?)\b",
        re.I,
    ),
}


def detect_intents(text: str) -> frozenset[str]:
    return frozenset(name for name, pattern in INTENT_PATTERNS.items() if pattern.search(text))
