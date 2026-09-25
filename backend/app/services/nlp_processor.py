"""
Narrative-text NLP (FIR bodies only):

  - regex + validators -> phones / UPI IDs / IMEIs named in the FIR (always on)
  - spaCy NER          -> PERSON / GPE / LOC entities (if en_core_web_sm installed)
  - SBERT              -> cosine similarity of FIR narratives for M.O. matching
                          (if sentence-transformers installed)

SBERT output is advisory: it raises an "M.O. resembles case X" alert and adds
a *probable* (never confirmed) signal to the link engine. It never creates a
graph edge by itself.

The M.O. corpus = historical_firs (loaded with the historical DB) +
fir_narratives (live FIRs), both in Postgres, so it survives restarts.
Embeddings are cached in memory and computed lazily in one batch.
"""
from __future__ import annotations

import threading

from app.core.config import settings
from app.services import normalizer, validators

_spacy_nlp = None
_spacy_failed = False
_sbert_model = None
_sbert_failed: str | None = None
_lock = threading.RLock()

# fir_id -> {"case_id", "historical", "mo_category", "text", "vec"}
_corpus: dict[str, dict] = {}


# ----------------------------------------------------------------------
# Model loading (lazy, fail-soft)
# ----------------------------------------------------------------------
def _get_spacy():
    global _spacy_nlp, _spacy_failed
    if _spacy_nlp is None and not _spacy_failed:
        try:
            import spacy

            _spacy_nlp = spacy.load("en_core_web_sm")
        except Exception as exc:
            _spacy_failed = True
            print(f"[nlp] spaCy NER disabled ({exc}). Run: python -m spacy download en_core_web_sm")
    return _spacy_nlp


def spacy_available() -> bool:
    return _get_spacy() is not None


def _get_sbert():
    global _sbert_model, _sbert_failed
    with _lock:
        if _sbert_model is None and _sbert_failed is None:
            try:
                from sentence_transformers import SentenceTransformer

                _sbert_model = SentenceTransformer(settings.SANDHAN_SBERT_MODEL)
            except Exception as exc:
                _sbert_failed = str(exc)
                print(f"[nlp] SBERT M.O. matching disabled ({exc})")
    return _sbert_model


def sbert_available() -> bool:
    return _get_sbert() is not None


# ----------------------------------------------------------------------
# Entity extraction
# ----------------------------------------------------------------------
def extract_identifiers(text: str) -> list[str]:
    """Entity IDs (PHONE:/UPI:/IMEI:) named in free text."""
    found: list[str] = []
    for m in validators.UPI_REGEX.findall(text):
        eid = normalizer.upi_eid(m)
        if eid and eid not in found:
            found.append(eid)
    for m in validators.prefilter_phone_candidates(text):
        eid = normalizer.phone_eid(m)
        if eid and eid not in found:
            found.append(eid)
    for m in validators.IMEI_REGEX.findall(text):
        eid = normalizer.imei_eid(m)
        if eid and eid not in found:
            found.append(eid)
    return found


def extract_entities(text: str) -> dict[str, list[str]]:
    """spaCy NER -> {"PERSON": [...], "GPE": [...], "LOC": [...]}; {} without spaCy."""
    nlp = _get_spacy()
    if nlp is None:
        return {}
    doc = nlp(text)
    out: dict[str, list[str]] = {}
    for ent in doc.ents:
        if ent.label_ in ("PERSON", "GPE", "LOC"):
            val = ent.text.strip()
            if any(ch.isdigit() for ch in val) or "@" in val:
                continue
            out.setdefault(ent.label_, [])
            if val not in out[ent.label_]:
                out[ent.label_].append(val)
    return out


# ----------------------------------------------------------------------
# M.O. similarity
# ----------------------------------------------------------------------
def _refresh_corpus(db) -> None:
    from app.db import models

    model = _get_sbert()
    if model is None:
        raise RuntimeError(f"SBERT unavailable: {_sbert_failed}")
    with _lock:
        todo = []
        for f in db.query(models.HistoricalFIR).all():
            if f.fir_id not in _corpus:
                todo.append((f.fir_id, f.case_id, True, f.mo_category, f.narrative))
        for f in db.query(models.FIRNarrative).all():
            if f.fir_id not in _corpus or _corpus[f.fir_id]["text"] != f.narrative:
                todo.append((f.fir_id, f.case_id, False, None, f.narrative))
        if todo:
            vecs = model.encode([t[4] for t in todo], batch_size=64, normalize_embeddings=True,
                                show_progress_bar=False)
            for (fir_id, case_id, hist, mo, text), vec in zip(todo, vecs):
                _corpus[fir_id] = {"case_id": case_id, "historical": hist, "mo_category": mo,
                                   "text": text, "vec": vec}


def reset_corpus_cache() -> None:
    with _lock:
        _corpus.clear()


def find_similar_narratives(db, text: str, exclude_case: str | None = None,
                            top_k: int = 3, threshold: float | None = None) -> list[dict]:
    """Advisory M.O. matches for a piece of FIR text against the whole corpus."""
    import numpy as np

    threshold = settings.SANDHAN_MO_THRESHOLD if threshold is None else threshold
    _refresh_corpus(db)
    model = _get_sbert()
    q = model.encode([text], normalize_embeddings=True, show_progress_bar=False)[0]
    with _lock:
        items = [(fid, c) for fid, c in _corpus.items() if c["case_id"] != exclude_case]
    if not items:
        return []
    mat = np.stack([c["vec"] for _, c in items])
    sims = mat @ q
    order = np.argsort(-sims)
    out = []
    for i in order[: max(top_k * 3, top_k)]:
        fid, c = items[int(i)]
        s = float(sims[int(i)])
        if s < threshold:
            break
        out.append({
            "case_fir_id": fid, "case_id": c["case_id"], "historical": c["historical"],
            "mo_category": c["mo_category"], "similarity": round(s, 4), "excerpt": c["text"][:240],
        })
        if len(out) >= top_k:
            break
    return out


def case_mo_similarities(db, case_id: str) -> dict[str, dict]:
    """{other_case_id: {similarity, fir_id, mo_category, other_is_historical}} --
    best narrative match per other case, for the link engine."""
    import numpy as np

    _refresh_corpus(db)
    with _lock:
        mine = [c for c in _corpus.values() if c["case_id"] == case_id]
        others = [(fid, c) for fid, c in _corpus.items() if c["case_id"] != case_id]
    if not mine or not others:
        return {}
    mat = np.stack([c["vec"] for _, c in others])
    best: dict[str, dict] = {}
    for m in mine:
        sims = mat @ m["vec"]
        for (fid, c), s in zip(others, sims):
            s = float(s)
            cur = best.get(c["case_id"])
            if cur is None or s > cur["similarity"]:
                best[c["case_id"]] = {"similarity": s, "fir_id": fid, "mo_category": c["mo_category"],
                                      "other_is_historical": c["historical"]}
    thr = settings.SANDHAN_MO_THRESHOLD
    return {k: v for k, v in best.items() if v["similarity"] >= thr}
