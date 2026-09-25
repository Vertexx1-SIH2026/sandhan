"""
Postgres schema.

  Users / RBAC / cases / files / audit  (unchanged from the first prototype)
  Historical reference database         historical_sources, historical_cases,
                                        historical_records, historical_firs
  Live case records                     case_records, fir_narratives
  Cross-case identifier index           identifier_index  <- the lookup table
                                        every new case is matched against
  Link discovery decisions              case_links
  HITL predictions / escalations        predicted_links, escalations
"""
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, Boolean, JSON, Integer, Float,
    UniqueConstraint, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.postgres_client import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ----------------------------------------------------------------------
# Users / RBAC
# ----------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(16), nullable=False)  # "investigator" | "admin"
    full_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    assigned_cases = relationship(
        "CaseAssignment", back_populates="user", cascade="all, delete-orphan"
    )


class Case(Base):
    __tablename__ = "cases"

    id = Column(String(64), primary_key=True)  # e.g. "CASE-2026-0001"
    title = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    merkle_root = Column(String(64), nullable=True)
    status = Column(String(32), default="active")

    files = relationship("CaseFile", back_populates="case", cascade="all, delete-orphan")
    assignments = relationship("CaseAssignment", back_populates="case", cascade="all, delete-orphan")


class CaseAssignment(Base):
    __tablename__ = "case_assignments"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    case_id = Column(String(64), ForeignKey("cases.id"), nullable=False)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)

    case = relationship("Case", back_populates="assignments")
    user = relationship("User", back_populates="assigned_cases")


class CaseFile(Base):
    """Chain-of-custody metadata recorded at ingestion."""
    __tablename__ = "case_files"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    case_id = Column(String(64), ForeignKey("cases.id"), nullable=False)
    investigator_id = Column(UUID(as_uuid=False), nullable=False)
    source_filename = Column(String(255), nullable=False)
    file_type = Column(String(16), nullable=False)  # cdr | fir | upi | ipdr | records
    sha256_hash = Column(String(64), nullable=False)
    original_path = Column(Text, nullable=False)
    working_path = Column(Text, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    job_id = Column(String(64), nullable=True)

    case = relationship("Case", back_populates="files")


class CaseAuditLog(Base):
    __tablename__ = "case_audit_log"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    case_id = Column(String(64), nullable=False, index=True)
    investigator_id = Column(UUID(as_uuid=False), nullable=False)
    action = Column(String(32), nullable=False)  # view|query|escalate|verify|reject|export|upload
    target = Column(String(255), nullable=True)
    detail = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class SystemAuditLog(Base):
    __tablename__ = "system_audit_log"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    actor_id = Column(UUID(as_uuid=False), nullable=True)
    event_type = Column(String(64), nullable=False)
    detail = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class VerifiedNode(Base):
    """Kept for backwards compatibility -- one row per HITL-verified prediction."""
    __tablename__ = "verified_nodes"

    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    case_id = Column(String(64), nullable=False, index=True)
    node_id = Column(String(255), nullable=False)
    source_id = Column(String(255), nullable=True)
    target_id = Column(String(255), nullable=True)
    predicted_score = Column(String(32), nullable=True)
    verified_by = Column(UUID(as_uuid=False), nullable=False)
    verified_at = Column(DateTime, default=datetime.utcnow)


# ----------------------------------------------------------------------
# Historical reference database (loaded by scripts/load_historical.py)
# ----------------------------------------------------------------------
class HistoricalSource(Base):
    """Chain of custody for the historical DB itself: which file, which hash."""
    __tablename__ = "historical_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String(32), nullable=False)          # case_index | records | firs
    filename = Column(String(255), nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    row_count = Column(Integer, nullable=False)
    loaded_at = Column(DateTime, default=datetime.utcnow)


class HistoricalCase(Base):
    __tablename__ = "historical_cases"

    case_id = Column(String(64), primary_key=True)
    suspect_number = Column(String(32), nullable=True)
    suspect_imei = Column(String(32), nullable=True)
    suspect_upi = Column(String(128), nullable=True)
    n_records = Column(Integer, nullable=True)
    note = Column(Text, nullable=True)            # "planted_overlap" column of the index
    first_ts = Column(String(32), nullable=True)
    last_ts = Column(String(32), nullable=True)
    primary_location = Column(String(128), nullable=True)


class HistoricalRecord(Base):
    __tablename__ = "historical_records"

    record_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    record_type = Column(String(8), nullable=False)       # CDR | UPI | IPDR
    timestamp = Column(String(32), nullable=True)
    source_id = Column(String(128), nullable=True, index=True)
    dest_id = Column(String(128), nullable=True, index=True)
    device_or_ref = Column(String(128), nullable=True, index=True)
    value = Column(Float, nullable=True)
    location = Column(String(128), nullable=True)


class HistoricalFIR(Base):
    __tablename__ = "historical_firs"

    fir_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    mo_category = Column(String(64), nullable=True)
    narrative = Column(Text, nullable=False)


# ----------------------------------------------------------------------
# Live case data
# ----------------------------------------------------------------------
class CaseRecord(Base):
    """Every structured row ingested for a live case, in the same shape as
    historical_records -- this is what the Act-1 'baseline SQL lookup' and the
    link report read."""
    __tablename__ = "case_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), nullable=False, index=True)
    file_id = Column(String(64), nullable=True)
    record_type = Column(String(8), nullable=False)
    timestamp = Column(String(32), nullable=True)
    source_id = Column(String(128), nullable=True, index=True)
    dest_id = Column(String(128), nullable=True, index=True)
    device_or_ref = Column(String(128), nullable=True, index=True)
    value = Column(Float, nullable=True)
    location = Column(String(128), nullable=True)


class FIRNarrative(Base):
    """Live FIR narratives, persisted so M.O. matching survives a restart."""
    __tablename__ = "fir_narratives"

    fir_id = Column(String(64), primary_key=True)
    case_id = Column(String(64), nullable=False, index=True)
    narrative = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


# ----------------------------------------------------------------------
# Cross-case identifier index + link discovery
# ----------------------------------------------------------------------
class IdentifierIndex(Base):
    """
    Inverted index: identifier -> every case it appears in, with its role.
    One indexed self-join of this table compares a case against every
    historical case at once (scales far past 200 cases).
      role = "subject"      the suspect side (A-party phone + its IMEI,
                            statement-holder / collector UPI, FIR-named IDs)
             "counterparty" everything else (victims, callees, merchants)
    """
    __tablename__ = "identifier_index"
    __table_args__ = (
        UniqueConstraint("identifier", "case_id", name="uq_identifier_case"),
        Index("ix_identifier_index_handle", "handle"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    identifier = Column(String(160), nullable=False, index=True)   # e.g. PHONE:+9198...
    id_type = Column(String(32), nullable=False)                   # Phone|Device|UPIAccount|...
    role = Column(String(16), nullable=False)
    handle = Column(String(128), nullable=True)   # UPI local part, for cross-bank alias matching
    case_id = Column(String(64), nullable=False, index=True)
    is_historical = Column(Boolean, nullable=False, default=False)
    occurrences = Column(Integer, nullable=False, default=1)


class CaseLink(Base):
    """
    Output of the link-discovery engine for one (case, other case) pair.
      status: confirmed  -> hard identifier match; written to the graph
              probable   -> lead only (shared counterparties, alias handle,
                            M.O. similarity); NOT in the graph until verified
              verified   -> probable link an investigator confirmed
              dismissed  -> probable link an investigator rejected
    """
    __tablename__ = "case_links"
    __table_args__ = (UniqueConstraint("case_id", "other_case_id", name="uq_case_link"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), nullable=False, index=True)
    other_case_id = Column(String(64), nullable=False, index=True)
    other_is_historical = Column(Boolean, nullable=False, default=True)
    score = Column(Float, nullable=False, default=0.0)
    status = Column(String(16), nullable=False, default="probable")
    evidence = Column(JSON, nullable=True)
    decided_by = Column(UUID(as_uuid=False), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PredictedLink(Base):
    """Server-side record of every link-prediction lead, so the evidence
    export gate can't be bypassed by the client."""
    __tablename__ = "predicted_links"
    __table_args__ = (UniqueConstraint("case_id", "node_id", name="uq_predicted_link"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), nullable=False, index=True)
    node_id = Column(String(400), nullable=False)       # "<source>__<target>"
    source_id = Column(String(160), nullable=False)
    target_id = Column(String(160), nullable=False)
    score = Column(Float, nullable=False, default=0.0)
    detail = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending")  # pending|verified|dismissed
    decided_by = Column(UUID(as_uuid=False), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    decided_at = Column(DateTime, nullable=True)


class Escalation(Base):
    """DPDP masking lift for one entity in one case (logged + persisted)."""
    __tablename__ = "escalations"
    __table_args__ = (UniqueConstraint("case_id", "entity_id", name="uq_escalation"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(String(64), nullable=False, index=True)
    entity_id = Column(String(160), nullable=False)
    investigator_id = Column(UUID(as_uuid=False), nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
