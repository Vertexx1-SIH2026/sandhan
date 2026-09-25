"""
normalizer.py -- turns ANY supported structured input into one canonical
record shape, and then into graph rows + identifier-index rows.

Supported inputs (column names are matched case-insensitively, with aliases):

  Historical / generic "records" format  (the SIH dummy historical DB)
      record_id, case_id, record_type(CDR|UPI|IPDR), timestamp,
      source_id, dest_id, device_or_ref, value, location

  Telecom CDR
      calling_number | phone_number | msisdn | a_party | caller
      called_number  | b_party | other_number | callee
      imei | imei_a,  imsi | imsi_a,  duration_sec | duration
      timestamp | (call_date + call_time),  call_type (MOC/MTC/incoming/outgoing)
      tower_location | location | first_cell_id

  UPI / bank transactions
      payer_upi_id | payer_vpa | from_upi,   payee_upi_id | payee_vpa | to_upi
      amount, timestamp, txn_id | utr | txn_ref
      payer_phone | phone_number,  payee_phone
      payer_account_no | bank_account_no,  payee_account_no

  IPDR
      phone_number | msisdn,  ip_address | public_ip | src_ip,  imei,
      session_start | timestamp,  session_end

Both the live upload path and scripts/load_historical.py go through this
module, so entity IDs are guaranteed identical -- which is what makes a new
case match the historical database.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from app.services import validators

# ----------------------------------------------------------------------
# Entity id helpers (single source of truth for ID formats)
# ----------------------------------------------------------------------
def phone_eid(raw) -> str | None:
    n = validators.validate_phone(raw) if raw is not None else None
    return f"PHONE:{n}" if n else None


def imei_eid(raw) -> str | None:
    n = validators.validate_imei(raw) if raw is not None else None
    return f"IMEI:{n}" if n else None


def upi_eid(raw) -> str | None:
    n = validators.normalize_upi(raw) if raw is not None else None
    return f"UPI:{n}" if n else None


def ip_eid(raw) -> str | None:
    n = validators.validate_ip(raw) if raw is not None else None
    return f"IP:{n}" if n else None


def acct_eid(raw) -> str | None:
    n = validators.normalize_account(raw) if raw is not None else None
    return f"ACCT:{n}" if n else None


ENTITY_TYPE_BY_PREFIX = {
    "PHONE": "Phone", "IMEI": "Device", "UPI": "UPIAccount", "IP": "IPAddress",
    "ACCT": "BankAccount", "PERSON": "Person", "LOCATION": "Location", "FIR": "FIR",
}


def entity_type_of(eid: str) -> str:
    return ENTITY_TYPE_BY_PREFIX.get(eid.split(":", 1)[0], "Entity")


def bare_value(eid: str | None) -> str | None:
    return eid.split(":", 1)[1] if eid else None


# ----------------------------------------------------------------------
# Canonical record
# ----------------------------------------------------------------------
@dataclass
class NormRecord:
    record_type: str                   # CDR | UPI | IPDR
    timestamp: str | None
    source: str | None                 # entity id
    dest: str | None                   # entity id
    device: str | None                 # entity id (IMEI) -- CDR/IPDR only
    value: float | None                # call duration (s) or amount (INR)
    location: str | None
    ref: str | None                    # txn ref / record id
    direction_reversed: bool = False   # incoming call: dest called source
    extra_links: list[tuple[str, str, str]] = field(default_factory=list)  # (a, b, rel)


def _clean(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() in ("nan", "none", "null", "n/a", "na"):
        return None
    return s


def _pick(row: dict, *aliases: str) -> str | None:
    for a in aliases:
        if a in row:
            v = _clean(row[a])
            if v is not None:
                return v
    return None


def _float(v) -> float | None:
    v = _clean(v)
    if v is None:
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


_TS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M", "%Y-%m-%d",
)


def _ts(v: str | None) -> str | None:
    v = _clean(v)
    if v is None:
        return None
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return v


def normalize_columns(records: Iterable[dict]) -> list[dict]:
    out = []
    for r in records:
        out.append({str(k).strip().lower().replace(" ", "_"): v for k, v in r.items()})
    return out


def detect_kind(columns: Iterable[str], declared: str | None = None) -> str:
    cols = set(columns)
    if "record_type" in cols and "source_id" in cols:
        return "records"
    if declared in ("cdr", "upi", "ipdr"):
        return declared
    if cols & {"payer_upi_id", "payee_upi_id", "payer_vpa", "payee_vpa", "from_upi", "to_upi"}:
        return "upi"
    if cols & {"ip_address", "public_ip", "src_ip"}:
        return "ipdr"
    return "cdr"


# ----------------------------------------------------------------------
# Row -> NormRecord
# ----------------------------------------------------------------------
def _cdr_row(row: dict) -> NormRecord:
    src_raw = _pick(row, "calling_number", "a_party", "msisdn", "phone_number", "caller", "source_id")
    dst_raw = _pick(row, "called_number", "b_party", "other_number", "callee", "dest_id")
    ts = _pick(row, "timestamp", "start_time", "datetime")
    if ts is None and _pick(row, "call_date"):
        ts = f"{_pick(row, 'call_date')} {_pick(row, 'call_time') or '00:00:00'}"
    call_type = (_pick(row, "call_type", "direction") or "").lower()
    return NormRecord(
        record_type="CDR",
        timestamp=_ts(ts),
        source=phone_eid(src_raw),
        dest=phone_eid(dst_raw),
        device=imei_eid(_pick(row, "imei_a", "imei", "device_or_ref")),
        value=_float(_pick(row, "duration_sec", "duration", "value")),
        location=_pick(row, "tower_location", "location", "first_cell_id", "cell_id"),
        ref=_pick(row, "record_id", "cdr_id"),
        direction_reversed=call_type in ("incoming", "mtc", "in"),
    )


def _upi_row(row: dict) -> NormRecord:
    payer = upi_eid(_pick(row, "payer_upi_id", "payer_vpa", "from_upi", "source_id"))
    payee = upi_eid(_pick(row, "payee_upi_id", "payee_vpa", "to_upi", "dest_id"))
    extra = []
    for col, owner, fn, rel in (
        (("payer_phone", "phone_number"), payer, phone_eid, "REGISTERED_MOBILE"),
        (("payee_phone",), payee, phone_eid, "REGISTERED_MOBILE"),
        (("payer_account_no", "bank_account_no", "payer_account"), payer, acct_eid, "LINKED_BANK"),
        (("payee_account_no", "payee_account"), payee, acct_eid, "LINKED_BANK"),
    ):
        target = fn(_pick(row, *col))
        if owner and target:
            extra.append((owner, target, rel))
    return NormRecord(
        record_type="UPI",
        timestamp=_ts(_pick(row, "timestamp", "txn_time", "datetime")),
        source=payer,
        dest=payee,
        device=None,
        value=_float(_pick(row, "amount", "value")),
        location=_pick(row, "location"),
        ref=_pick(row, "txn_id", "utr", "txn_ref", "device_or_ref", "record_id"),
        extra_links=extra,
    )


def _ipdr_row(row: dict) -> NormRecord:
    return NormRecord(
        record_type="IPDR",
        timestamp=_ts(_pick(row, "session_start", "timestamp", "start_time")),
        source=phone_eid(_pick(row, "phone_number", "msisdn", "calling_number", "source_id")),
        dest=ip_eid(_pick(row, "ip_address", "public_ip", "src_ip", "dest_id")),
        device=imei_eid(_pick(row, "imei", "imei_a", "device_or_ref")),
        value=None,
        location=_pick(row, "location", "tower_location"),
        ref=_pick(row, "record_id", "session_id"),
    )


_ROW_FN = {"CDR": _cdr_row, "UPI": _upi_row, "IPDR": _ipdr_row}


def normalize_records(records: list[dict], declared_type: str | None = None) -> tuple[list[NormRecord], dict]:
    """Returns (normalised records, stats). Rows with no usable identifier are
    counted as rejected rather than silently disappearing."""
    rows = normalize_columns(records)
    kind = detect_kind(rows[0].keys() if rows else [], declared_type)
    out: list[NormRecord] = []
    rejected = 0
    types = Counter()
    for row in rows:
        if kind == "records":
            rtype = (_clean(row.get("record_type")) or "").upper()
            fn = _ROW_FN.get(rtype)
            if fn is None:
                rejected += 1
                continue
            rec = fn(row)
        else:
            rec = _ROW_FN[kind.upper()](row)
        if not (rec.source or rec.dest or rec.device):
            rejected += 1
            continue
        types[rec.record_type] += 1
        out.append(rec)
    return out, {"kind": kind, "rows": len(rows), "accepted": len(out), "rejected": rejected,
                 "by_type": dict(types)}


# ----------------------------------------------------------------------
# Subject / counterparty roles
# ----------------------------------------------------------------------
def infer_subjects(records: list[NormRecord], explicit: set[str] | None = None) -> set[str]:
    """
    Which identifiers are the suspect side of this case?
      - explicit (e.g. the historical index's suspect number/IMEI/UPI, or IDs
        named in the FIR)                                         always
      - CDR/IPDR A-party phone + the IMEI it used + its IP        always
      - UPI: only when no explicit list is given (live uploads):
          * the statement holder -- account on >=40% of the UPI rows
          * collectors -- accounts receiving from >=2 distinct payers
    """
    subjects = set(explicit or ())
    upi_rows = [r for r in records if r.record_type == "UPI"]
    for r in records:
        if r.record_type in ("CDR", "IPDR"):
            if r.source:
                subjects.add(r.source)
            if r.device:
                subjects.add(r.device)
            if r.record_type == "IPDR" and r.dest:
                subjects.add(r.dest)
    if not explicit and upi_rows:
        presence = Counter()
        payers_of = defaultdict(set)
        for r in upi_rows:
            for eid in {r.source, r.dest} - {None}:
                presence[eid] += 1
            if r.source and r.dest:
                payers_of[r.dest].add(r.source)
        n = len(upi_rows)
        for eid, c in presence.items():
            if c >= 2 and c / n >= 0.4:
                subjects.add(eid)
        for eid, payers in payers_of.items():
            if len(payers) >= 2:
                subjects.add(eid)
    return subjects


# ----------------------------------------------------------------------
# Graph rows + identifier rows
# ----------------------------------------------------------------------
def _new_agg() -> dict:
    return {"count": 0, "total_amount": 0.0, "max_amount": 0.0, "total_duration": 0,
            "first_ts": None, "last_ts": None, "locations": [], "extra": {}}


def _bump(agg: dict, rec: NormRecord) -> None:
    agg["count"] += 1
    if rec.record_type == "UPI" and rec.value is not None:
        agg["total_amount"] += rec.value
        agg["max_amount"] = max(agg["max_amount"], rec.value)
    if rec.record_type == "CDR" and rec.value is not None:
        agg["total_duration"] += int(rec.value)
    if rec.timestamp:
        if agg["first_ts"] is None or rec.timestamp < agg["first_ts"]:
            agg["first_ts"] = rec.timestamp
        if agg["last_ts"] is None or rec.timestamp > agg["last_ts"]:
            agg["last_ts"] = rec.timestamp
    if rec.location and rec.location not in agg["locations"] and len(agg["locations"]) < 8:
        agg["locations"].append(rec.location)


@dataclass
class GraphRows:
    entities: dict[str, dict]                          # eid -> {entity_type, props, role, count}
    edges: dict[str, dict[tuple[str, str], dict]]      # rel -> {(a, b): agg}
    identifiers: list[dict]                            # identifier-index rows
    subjects: set[str]

    def entity_rows(self) -> list[dict]:
        return [{"entity_id": eid, **v} for eid, v in self.entities.items()]

    def edge_rows(self, rel: str) -> list[dict]:
        return [{"a": a, "b": b, **agg} for (a, b), agg in self.edges.get(rel, {}).items()]


def build_graph_rows(records: list[NormRecord], explicit_subjects: set[str] | None = None) -> GraphRows:
    subjects = infer_subjects(records, explicit_subjects)
    entities: dict[str, dict] = {}
    edges: dict[str, dict[tuple[str, str], dict]] = defaultdict(dict)

    def ent(eid: str | None, extra_props: dict | None = None):
        if not eid:
            return
        e = entities.get(eid)
        if e is None:
            etype = entity_type_of(eid)
            props: dict[str, Any] = {"value": bare_value(eid)}
            if etype == "Device":
                props["luhn_valid"] = validators.luhn_valid(bare_value(eid))
                props["tac"] = bare_value(eid)[:8]
            if etype == "UPIAccount":
                props["handle"] = validators.upi_handle(bare_value(eid))
                props["psp"] = bare_value(eid).split("@", 1)[1]
            e = entities[eid] = {"entity_type": etype, "props": props,
                                 "role": "subject" if eid in subjects else "counterparty",
                                 "count": 0}
        e["count"] += 1
        if extra_props:
            e["props"].update(extra_props)

    def edge(rel: str, a: str | None, b: str | None, rec: NormRecord):
        if not a or not b or a == b:
            return
        agg = edges[rel].get((a, b))
        if agg is None:
            agg = edges[rel][(a, b)] = _new_agg()
        _bump(agg, rec)

    for rec in records:
        for eid in (rec.source, rec.dest, rec.device):
            ent(eid)
        if rec.record_type == "CDR":
            a, b = (rec.dest, rec.source) if rec.direction_reversed else (rec.source, rec.dest)
            edge("CALLED", a, b, rec)
            edge("USED_DEVICE", rec.source, rec.device, rec)
        elif rec.record_type == "UPI":
            edge("TRANSFERRED", rec.source, rec.dest, rec)
        elif rec.record_type == "IPDR":
            edge("USED_IP", rec.source, rec.dest, rec)
            edge("USED_DEVICE", rec.source, rec.device, rec)
        for a, b, rel in rec.extra_links:
            ent(a)
            ent(b)
            edge(rel, a, b, rec)

    identifiers = [
        {
            "identifier": eid,
            "id_type": v["entity_type"],
            "role": v["role"],
            "handle": v["props"].get("handle"),
            "occurrences": v["count"],
        }
        for eid, v in entities.items()
    ]
    return GraphRows(entities=entities, edges=dict(edges), identifiers=identifiers, subjects=subjects)


def record_rows(records: list[NormRecord]) -> list[dict]:
    """Rows for Postgres case_records / historical_records (bare values, no prefixes)."""
    out = []
    for r in records:
        out.append({
            "record_type": r.record_type,
            "timestamp": r.timestamp,
            "source_id": bare_value(r.source),
            "dest_id": bare_value(r.dest),
            "device_or_ref": bare_value(r.device) if r.device else r.ref,
            "value": r.value,
            "location": r.location,
        })
    return out
