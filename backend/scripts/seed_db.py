"""
Creates the demo accounts and live demo cases:
  - admin / admin123           (role: admin)
  - investigator1 / invest123  (role: investigator, assigned CASE-2026-0001..0003)

    python scripts/seed_db.py
"""
import _path  # noqa: F401

from app.core.security import hash_password
from app.db import models
from app.db.postgres_client import SessionLocal, init_db

DEMO_CASES = {
    "CASE-2026-0001": "KYC fraud call centre - Noida",
    "CASE-2026-0002": "Investment scam - Delhi",
    "CASE-2026-0003": "Customs parcel scam - Kolkata",
}


def get_or_create_user(db, username, password, role, full_name, reset_password=True):
    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        if reset_password:  # also migrates old bcrypt hashes from the first prototype
            user.password_hash = hash_password(password)
            db.commit()
        return user
    user = models.User(username=username, password_hash=hash_password(password), role=role, full_name=full_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    print(f"Created user: {username} ({role})")
    return user


def get_or_create_case(db, case_id, title):
    case = db.get(models.Case, case_id)
    if case:
        return case
    case = models.Case(id=case_id, title=title)
    db.add(case)
    db.commit()
    print(f"Created case: {case_id}")
    return case


def assign(db, user, case_id):
    exists = (
        db.query(models.CaseAssignment)
        .filter(models.CaseAssignment.user_id == user.id, models.CaseAssignment.case_id == case_id)
        .first()
    )
    if not exists:
        db.add(models.CaseAssignment(user_id=user.id, case_id=case_id))
        db.commit()
        print(f"Assigned {case_id} -> {user.username}")


def main():
    init_db()
    db = SessionLocal()
    try:
        get_or_create_user(db, "admin", "admin123", "admin", "System Administrator")
        investigator = get_or_create_user(db, "investigator1", "invest123", "investigator", "Investigator A. Sharma")
        for case_id, title in DEMO_CASES.items():
            get_or_create_case(db, case_id, title)
            assign(db, investigator, case_id)
        print("Seed complete. Login with admin/admin123 or investigator1/invest123")
    finally:
        db.close()


if __name__ == "__main__":
    main()
