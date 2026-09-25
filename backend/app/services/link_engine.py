"""
link_engine.py -- "given ANY case, which of the ~150-200 historical cases
(and other live cases) is it connected to, and why?"

Signals (all computed against Postgres identifier_index in a few indexed
queries, so it scales well past a few hundred cases):

  1. shared_identifier   exact match on a normalised phone / IMEI / UPI /
                         bank account / IP between the two cases
  2. alias_handle        same UPI handle at a different PSP
                         (vikram.t39@icb vs vikram.t39@paytm)
  3. mo_similarity       SBERT cosine similarity of FIR narratives (only when
                         the NLP models are installed)

Each signal gets a weight:
    weight = type_weight x role_factor x rarity
      type_weight  Device .90, BankAccount .85, Phone .75, UPI .75, Person .5, IP .35
      role_factor  subject on both sides 1.0 / one side .85 / neither .35
      rarity       1.0 if only these two cases share it, else 2/df
                   (df = number of cases containing the identifier, so a
                    common merchant shared by 30 cases barely counts)
and the case-pair score is the noisy-OR  1 - PROD(1 - weight).

Design rule: ONE weak coincidence (a single shared victim/merchant = 0.26,
a single look-alike UPI handle = 0.25, or a similar FIR narrative <= 0.28)
stays below the 0.30 lead threshold;
two independent weak signals (0.45) become a probable lead. This matters
with synthetic data, where small name vocabularies produce random collisions.

Status:
  confirmed  at least one "hard" signal: a shared Device or BankAccount, or a
             shared Phone/UPI that is on the suspect side in at least one of
             the cases -- and the identifier is not a hub (df <= HUB limit).
             Written to the graph as (:Case)-[:LINKED_VIA]->(:Case).
  probable   score >= SANDHAN_PROBABLE_LINK_MIN_SCORE but no hard signal.
             Shown as an unverified lead; joins the graph only after an
             investigator verifies it (HITL).
  (weaker pairs are dropped)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.data_structures.union_find import UnionFind
from app.db import models

TYPE_WEIGHT = {
    "Device": 0.90, "BankAccount": 0.85, "Phone": 0.75, "UPIAccount": 0.75,
    "Person": 0.50, "IPAddress": 0.35,
}
HARD_TYPES_ALWAYS = {"Device", "BankAccount"}
HARD_TYPES_IF_SUBJECT = {"Phone", "UPIAccount"}


@dataclass
class LinkResult:
    other_case_id: str
    other_is_historical: bool
    score: float
    status: str                      # confirmed | probable
    evidence: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "other_case_id": self.other_case_id,
            "other_is_historical": self.other_is_historical,
            "score": round(self.score, 4),
            "status": self.status,
            "evidence": self.evidence,
        }


def _rarity(df: int) -> float:
    return 1.0 if df <= 2 else 2.0 / df


def _role_factor(my_role: str, other_role: str) -> float:
    subj = (my_role == "subject") + (other_role == "subject")
    return {2: 1.0, 1: 0.85, 0: 0.35}[subj]


# ----------------------------------------------------------------------
# Pure scoring (no DB) -- unit-testable
# ----------------------------------------------------------------------
def score_links(
    matches: list[dict],
    alias_matches: list[dict] | None = None,
    mo_matches: dict[str, dict] | None = None,
    hub_limit: int | None = None,
    probable_min: float | None = None,
) -> list[LinkResult]:
    """
    matches:       [{other_case, other_is_historical, identifier, id_type, my_role, other_role, df}]
    alias_matches: [{other_case, other_is_historical, my_identifier, other_identifier, handle, df}]
    mo_matches:    {other_case: {"similarity": float, "other_is_historical": bool, "fir_id": ...}}
    """
    hub_limit = hub_limit if hub_limit is not None else settings.SANDHAN_HUB_CASE_LIMIT
    probable_min = probable_min if probable_min is not None else settings.SANDHAN_PROBABLE_LINK_MIN_SCORE

    per_case: dict[str, dict] = {}

    def bucket(case_id: str, is_hist: bool) -> dict:
        return per_case.setdefault(case_id, {"hist": is_hist, "signals": [], "hard": False})

    for m in matches:
        df = int(m["df"])
        hub = df > hub_limit
        w = TYPE_WEIGHT.get(m["id_type"], 0.3) * _role_factor(m["my_role"], m["other_role"]) * _rarity(df)
        if hub:
            w *= 0.3
        w = min(w, 0.95)
        hard = (not hub) and (
            m["id_type"] in HARD_TYPES_ALWAYS
            or (m["id_type"] in HARD_TYPES_IF_SUBJECT and "subject" in (m["my_role"], m["other_role"]))
        )
        b = bucket(m["other_case"], bool(m["other_is_historical"]))
        b["hard"] = b["hard"] or hard
        b["signals"].append({
            "signal": "shared_identifier",
            "identifier": m["identifier"],
            "id_type": m["id_type"],
            "my_role": m["my_role"],
            "other_role": m["other_role"],
            "cases_sharing": df,
            "hub": hub,
            "hard": hard,
            "weight": round(w, 4),
        })

    for a in alias_matches or []:
        df = int(a["df"])
        if df > hub_limit:
            continue
        w = 0.25 * _rarity(df)
        b = bucket(a["other_case"], bool(a["other_is_historical"]))
        b["signals"].append({
            "signal": "alias_handle",
            "identifier": a["my_identifier"],
            "other_identifier": a["other_identifier"],
            "handle": a["handle"],
            "cases_sharing": df,
            "hard": False,
            "weight": round(w, 4),
        })

    thr = settings.SANDHAN_MO_THRESHOLD
    for other_case, mo in (mo_matches or {}).items():
        sim = float(mo["similarity"])
        if sim < thr:
            continue
        # Same scam script is common (thousands of KYC frauds), so M.O. alone is
        # capped below the lead threshold -- it only strengthens other evidence.
        w = min(0.15 + 0.13 * (sim - thr) / max(1e-6, 1 - thr), 0.28)
        b = bucket(other_case, bool(mo.get("other_is_historical", True)))
        b["signals"].append({
            "signal": "mo_similarity",
            "similarity": round(sim, 4),
            "fir_id": mo.get("fir_id"),
            "mo_category": mo.get("mo_category"),
            "hard": False,
            "weight": round(w, 4),
        })

    results = []
    for other_case, b in per_case.items():
        # one identifier can surface through several signals -- noisy-OR over distinct evidence
        prod = 1.0
        for s in b["signals"]:
            prod *= 1.0 - s["weight"]
        score = 1.0 - prod
        if b["hard"]:
            status = "confirmed"
        elif score >= probable_min:
            status = "probable"
        else:
            continue
        b["signals"].sort(key=lambda s: (-s.get("hard", False), -s["weight"]))
        results.append(LinkResult(other_case, b["hist"], score, status, b["signals"]))

    results.sort(key=lambda r: (r.status != "confirmed", -r.score))
    return results


# ----------------------------------------------------------------------
# Identifier index maintenance
# ----------------------------------------------------------------------
def index_identifiers(db: Session, case_id: str, identifiers: list[dict], is_historical: bool) -> None:
    """Upsert identifier-index rows for one case. 'subject' wins over
    'counterparty' if the same identifier is seen in both roles."""
    if not identifiers:
        return
    table = models.IdentifierIndex.__table__
    # Postgres refuses ON CONFLICT DO UPDATE touching the same row twice in one
    # statement, so merge duplicates first (subject wins, occurrences add up).
    merged: dict[str, dict] = {}
    for i in identifiers:
        cur = merged.get(i["identifier"])
        if cur is None:
            merged[i["identifier"]] = {
                "identifier": i["identifier"],
                "id_type": i["id_type"],
                "role": i["role"],
                "handle": i.get("handle"),
                "case_id": case_id,
                "is_historical": is_historical,
                "occurrences": int(i.get("occurrences", 1)),
            }
        else:
            cur["occurrences"] += int(i.get("occurrences", 1))
            if i["role"] == "subject":
                cur["role"] = "subject"
            cur["handle"] = cur["handle"] or i.get("handle")
    rows = list(merged.values())
    for start in range(0, len(rows), 2000):
        chunk = rows[start : start + 2000]
        stmt = pg_insert(table).values(chunk)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_identifier_case",
            set_={
                "role": text(
                    "CASE WHEN identifier_index.role = 'subject' OR excluded.role = 'subject' "
                    "THEN 'subject' ELSE 'counterparty' END"
                ),
                "occurrences": table.c.occurrences + stmt.excluded.occurrences,
                "handle": stmt.excluded.handle,
            },
        )
        db.execute(stmt)
    db.commit()


_MATCH_SQL = text(
    """
    WITH mine AS (
        SELECT identifier, id_type, role FROM identifier_index WHERE case_id = :cid
    ), df AS (
        SELECT identifier, count(*) AS df FROM identifier_index
        WHERE identifier IN (SELECT identifier FROM mine) GROUP BY identifier
    )
    SELECT o.case_id AS other_case, o.is_historical AS other_is_historical,
           m.identifier, m.id_type, m.role AS my_role, o.role AS other_role, df.df
    FROM mine m
    JOIN identifier_index o ON o.identifier = m.identifier AND o.case_id <> :cid
    JOIN df ON df.identifier = m.identifier
    """
)

_ALIAS_SQL = text(
    """
    WITH mine AS (
        SELECT identifier, handle FROM identifier_index
        WHERE case_id = :cid AND handle IS NOT NULL AND length(handle) >= 5
    ), hdf AS (
        SELECT handle, count(DISTINCT case_id) AS df FROM identifier_index
        WHERE handle IN (SELECT handle FROM mine) GROUP BY handle
    )
    SELECT o.case_id AS other_case, o.is_historical AS other_is_historical,
           m.identifier AS my_identifier, o.identifier AS other_identifier, m.handle, hdf.df
    FROM mine m
    JOIN identifier_index o ON o.handle = m.handle AND o.identifier <> m.identifier
                            AND o.case_id <> :cid
    JOIN hdf ON hdf.handle = m.handle
    """
)


def discover_links(db: Session, case_id: str, include_mo: bool = True) -> list[LinkResult]:
    matches = [dict(r._mapping) for r in db.execute(_MATCH_SQL, {"cid": case_id})]
    aliases = [dict(r._mapping) for r in db.execute(_ALIAS_SQL, {"cid": case_id})]
    mo = {}
    if include_mo:
        try:
            from app.services import nlp_processor

            mo = nlp_processor.case_mo_similarities(db, case_id)
        except Exception as exc:  # models not installed -> link engine still works
            print(f"[link_engine] M.O. similarity skipped: {exc}")
    return score_links(matches, aliases, mo)


# ----------------------------------------------------------------------
# Persistence (Postgres case_links + graph LINKED_VIA)
# ----------------------------------------------------------------------
def persist_links(db: Session, case_id: str, results: list[LinkResult], store=None,
                  case_is_historical: bool = False) -> dict:
    """
    Upserts case_links for `case_id`. Investigator decisions (verified /
    dismissed) are never overwritten by a re-run. Confirmed + verified links
    are mirrored into the graph as LINKED_VIA.
    """
    existing = {
        row.other_case_id: row
        for row in db.query(models.CaseLink).filter(models.CaseLink.case_id == case_id).all()
    }
    seen = set()
    graph_rows = []
    for r in results:
        seen.add(r.other_case_id)
        row = existing.get(r.other_case_id)
        if row is None:
            row = models.CaseLink(case_id=case_id, other_case_id=r.other_case_id)
            db.add(row)
            row.status = r.status
        elif row.status not in ("verified", "dismissed"):
            row.status = r.status
        elif row.status == "dismissed" and r.status == "confirmed":
            # new hard evidence arrived after a dismissal -> re-open as confirmed
            row.status = "confirmed"
        row.other_is_historical = r.other_is_historical
        row.score = r.score
        row.evidence = r.evidence
        if row.status in ("confirmed", "verified"):
            graph_rows.append(_graph_link_row(case_id, r.other_case_id, r.score, row.status, r.evidence))

    removed = []
    for other, row in existing.items():
        if other not in seen and row.status in ("confirmed", "probable"):
            removed.append(other)
            db.delete(row)
    db.commit()

    if store is not None:
        if graph_rows:
            store.link_cases(graph_rows)
        for other in removed:
            store.unlink_cases(case_id, other)
    return {
        "confirmed": sum(1 for r in results if r.status == "confirmed"),
        "probable": sum(1 for r in results if r.status == "probable"),
    }


def _graph_link_row(a: str, b: str, score: float, status: str, evidence: list[dict]) -> dict:
    lo, hi = sorted((a, b))
    via = [s["identifier"] for s in evidence if s.get("signal") == "shared_identifier"][:10]
    kinds = sorted({s["signal"] for s in evidence})
    return {"a": lo, "b": hi, "score": round(score, 4), "status": status, "via": via,
            "kind": ",".join(kinds)}


def decide_link(db: Session, case_id: str, other_case_id: str, decision: str,
                investigator_id: str, store) -> models.CaseLink:
    row = (
        db.query(models.CaseLink)
        .filter(models.CaseLink.case_id == case_id, models.CaseLink.other_case_id == other_case_id)
        .first()
    )
    if row is None:
        raise KeyError(other_case_id)
    if decision == "verify":
        row.status = "verified"
        store.link_cases([_graph_link_row(case_id, other_case_id, row.score, "verified", row.evidence or [])])
    elif decision == "dismiss":
        row.status = "dismissed"
        store.unlink_cases(case_id, other_case_id)
    else:
        raise ValueError(decision)
    row.decided_by = investigator_id
    db.commit()
    return row


def case_cluster(db: Session, case_id: str) -> set[str]:
    """DSU over every confirmed/verified link -> the network this case is part of."""
    uf = UnionFind()
    uf.add(case_id)
    for a, b in db.query(models.CaseLink.case_id, models.CaseLink.other_case_id).filter(
        models.CaseLink.status.in_(("confirmed", "verified"))
    ):
        uf.union(a, b)
    return uf.group_of(case_id)


def links_report(db: Session, case_id: str) -> list[dict]:
    rows = (
        db.query(models.CaseLink)
        .filter(models.CaseLink.case_id == case_id)
        .order_by(models.CaseLink.score.desc())
        .all()
    )
    hist_ids = [r.other_case_id for r in rows if r.other_is_historical]
    hist = {
        h.case_id: h for h in db.query(models.HistoricalCase).filter(models.HistoricalCase.case_id.in_(hist_ids))
    } if hist_ids else {}
    firs = {
        f.case_id: f for f in db.query(models.HistoricalFIR).filter(models.HistoricalFIR.case_id.in_(hist_ids))
    } if hist_ids else {}
    order = {"confirmed": 0, "verified": 1, "probable": 2, "dismissed": 3}
    out = []
    for r in sorted(rows, key=lambda x: (order.get(x.status, 9), -x.score)):
        h = hist.get(r.other_case_id)
        f = firs.get(r.other_case_id)
        out.append({
            "other_case_id": r.other_case_id,
            "other_is_historical": r.other_is_historical,
            "score": round(r.score, 4),
            "status": r.status,
            "evidence": r.evidence or [],
            "historical_summary": {
                "period": f"{h.first_ts or '?'} to {h.last_ts or '?'}",
                "location": h.primary_location,
                "n_records": h.n_records,
                "mo_category": f.mo_category if f else None,
            } if h else None,
        })
    return out


__all__ = [
    "score_links", "index_identifiers", "discover_links", "persist_links", "decide_link",
    "case_cluster", "links_report", "LinkResult",
]
