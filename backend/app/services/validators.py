"""
Structured field validation + normalisation (never touches SBERT):
  - Phone numbers: `phonenumbers` validation, normalised to E.164
  - IMEI: 15 digits; Luhn check digit recorded as a flag, NOT used to drop the
    record (207 of the 220 historical IMEIs fail Luhn -- dropping them silently
    removed almost every device from the graph)
  - UPI VPAs: lower-cased, split into handle@psp so the same handle at a
    different bank can be flagged as a possible alias
  - RapidFuzz: fuzzy matching for names
"""
from __future__ import annotations

import ipaddress
import re

import phonenumbers
from rapidfuzz import fuzz

PHONE_REGEX = re.compile(r"(?<![\w@])(\+?\d[\d\-\s]{8,14}\d)(?![\w@])")
IMEI_REGEX = re.compile(r"\b\d{15}\b")
UPI_REGEX = re.compile(r"\b([a-zA-Z0-9][a-zA-Z0-9.\-_]{1,63}@[a-zA-Z][a-zA-Z0-9]{1,31})\b")
_EMAIL_TLDS = {"com", "in", "org", "net", "co", "gov", "edu", "io"}


def prefilter_phone_candidates(text: str) -> list[str]:
    return [m.strip() for m in PHONE_REGEX.findall(text)]


def validate_phone(raw: str, default_region: str = "IN") -> str | None:
    """Returns the E.164-normalised number if valid, else None.
    Accepts '+919876543210', '919876543210', '09876543210', '98765 43210'."""
    if raw is None:
        return None
    candidate = str(raw).strip()
    if not candidate or candidate.lower() in ("nan", "none", "n/a"):
        return None
    digits = re.sub(r"\D", "", candidate)
    if not candidate.startswith("+") and len(digits) == 12 and digits.startswith("91"):
        candidate = "+" + digits
    try:
        parsed = phonenumbers.parse(candidate, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(digits[::-1]):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def validate_imei(raw: str) -> str | None:
    """Returns the 15-digit IMEI (spaces/dashes stripped) or None.
    Use luhn_valid() separately to record whether the check digit is right."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 16:          # IMEISV -> drop the 2-digit software version, keep TAC+serial
        digits = digits[:14] + str(_luhn_check_digit(digits[:14]))
    if len(digits) != 15:
        return None
    return digits


def _luhn_check_digit(first14: str) -> int:
    for d in range(10):
        if luhn_valid(first14 + str(d)):
            return d
    return 0


def normalize_upi(raw: str) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or "@" not in s or s in ("nan", "n/a"):
        return None
    handle, _, psp = s.partition("@")
    if not handle or not psp or "." in psp and psp.split(".")[-1] in _EMAIL_TLDS:
        return None  # looks like an e-mail address, not a VPA
    return s


def upi_handle(vpa: str) -> str:
    return vpa.split("@", 1)[0]


def validate_ip(raw: str) -> str | None:
    try:
        return str(ipaddress.ip_address(str(raw).strip()))
    except ValueError:
        return None


def normalize_account(raw: str) -> str | None:
    if raw is None:
        return None
    s = re.sub(r"[\s\-]", "", str(raw))
    return s if re.fullmatch(r"[A-Za-z0-9]{6,20}", s or "") else None


def fuzzy_match_score(a: str, b: str) -> float:
    """0-100 similarity score for names/addresses/account identifiers."""
    return fuzz.token_sort_ratio(a.strip().lower(), b.strip().lower())


def fuzzy_best_match(candidate: str, pool: list[str], threshold: float = 88.0) -> tuple[str | None, float]:
    best, best_score = None, 0.0
    for item in pool:
        score = fuzzy_match_score(candidate, item)
        if score > best_score:
            best, best_score = item, score
    return (best, best_score) if best_score >= threshold else (None, best_score)
