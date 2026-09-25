"""
storage_client.py

The blueprint calls for MinIO with Object Lock/WORM on an "original" bucket
and a separate "working copy" bucket that the ETL pipeline actually touches.
For this local, Docker-free prototype we reproduce the same *shape* on the
filesystem:

    storage/original/<case_id>/<file_id>__<filename>   (chmod 0444 after write == WORM)
    storage/working/<case_id>/<file_id>__<filename>     (pipeline reads/writes here)
    storage/evidence/<case_id>/evidence_<ts>.pdf         (exported certificates)

Swapping this module for a real boto3/MinIO client later is a drop-in
replacement -- nothing else in the codebase should need to change, since all
callers go through save_original_and_copy() / open_working_copy().
"""
from __future__ import annotations

import os
import shutil
import stat
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.security import sha256_file


def _case_dir(root: str, case_id: str) -> Path:
    d = settings.storage_root / root / case_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_original_and_copy(case_id: str, filename: str, raw_bytes: bytes) -> dict:
    """
    Writes the file once, then:
      1. Locks it read-only in storage/original/<case_id>/  (WORM stand-in)
      2. Creates a mutable working copy in storage/working/<case_id>/
    The pipeline (etl_parser, nlp_processor, etc.) must only ever open the
    working copy -- see original_path vs working_path in CaseFile.
    """
    file_id = uuid.uuid4().hex[:12]
    safe_name = f"{file_id}__{filename}"

    original_path = _case_dir("original", case_id) / safe_name
    working_path = _case_dir("working", case_id) / safe_name

    original_path.write_bytes(raw_bytes)
    # WORM stand-in: strip write permission from owner/group/other.
    os.chmod(original_path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)

    shutil.copyfile(original_path, working_path)

    file_hash = sha256_file(str(original_path))

    return {
        "file_id": file_id,
        "original_path": str(original_path),
        "working_path": str(working_path),
        "sha256": file_hash,
    }


def open_working_copy(path: str) -> bytes:
    return Path(path).read_bytes()


def save_evidence_pdf(case_id: str, filename: str, pdf_bytes: bytes) -> str:
    d = _case_dir("evidence", case_id)
    out_path = d / filename
    out_path.write_bytes(pdf_bytes)
    return str(out_path)


def verify_original_untampered(case_id: str, file_id_prefix: str, expected_hash: str) -> bool:
    """Re-hashes the WORM original and compares -- proves the file used for
    a Merkle root hasn't drifted from what was ingested."""
    orig_dir = settings.storage_root / "original" / case_id
    for f in orig_dir.glob(f"{file_id_prefix}__*"):
        return sha256_file(str(f)) == expected_hash
    return False
