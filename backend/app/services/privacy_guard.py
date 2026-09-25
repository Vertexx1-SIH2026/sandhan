"""
privacy_guard.py -- DPDP Sec.17(1)(c) third-party masking + escalation.

Default: phone numbers and bank account numbers that belong to the
counterparty side (victims, incidental callees) are partially redacted,
e.g. +91-XXXXXX-1234. They are shown in full only when:
  - the identifier is on the suspect ("subject") side in the case network, or
  - it is an endpoint of an investigator-verified predicted link, or
  - an investigator explicitly escalated it (logged + persisted in Postgres).

Masking is applied to everything the UI and the evidence PDF display. The raw
entity_id is still used as the API key for a node (a production build would
tokenise it) -- stated openly in the README.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import models
from app.services.audit_logger import log_case_event

MASKED_TYPES = {"Phone", "BankAccount"}


def mask_phone(e164_number: str) -> str:
    """+919876543210 -> +91-XXXXXX-3210 (last 4 digits visible)."""
    digits = e164_number.lstrip("+")
    if len(digits) <= 6:
        return "X" * len(digits)
    country, tail = digits[:2], digits[-4:]
    return f"+{country}-{'X' * (len(digits) - 6)}-{tail}"


def mask_account(acct: str) -> str:
    return "X" * max(0, len(acct) - 4) + acct[-4:]


def mask_value(entity_type: str, value: str) -> str:
    if entity_type == "Phone":
        return mask_phone(value)
    if entity_type == "BankAccount":
        return mask_account(value)
    return value


def escalated_ids(db: Session, case_id: str) -> set[str]:
    return {
        e for (e,) in db.query(models.Escalation.entity_id).filter(models.Escalation.case_id == case_id)
    }


def escalate_entity(db: Session, case_id: str, entity_id: str, investigator_id: str,
                    reason: str | None = None) -> dict:
    exists = (
        db.query(models.Escalation)
        .filter(models.Escalation.case_id == case_id, models.Escalation.entity_id == entity_id)
        .first()
    )
    if not exists:
        db.add(models.Escalation(case_id=case_id, entity_id=entity_id,
                                 investigator_id=investigator_id, reason=reason))
        db.commit()
    log_case_event(db, case_id, investigator_id, "escalate", target=entity_id, detail={"reason": reason})
    return {"entity_id": entity_id, "status": "escalated", "masking_lifted": True}


# Backwards-compatible helper used by older code paths
def apply_masking(case_id: str, entity_id: str, entity_type: str, display_value: str,
                  is_flagged_or_verified: bool) -> str:
    if entity_type not in MASKED_TYPES or is_flagged_or_verified:
        return display_value
    return mask_value(entity_type, display_value)
