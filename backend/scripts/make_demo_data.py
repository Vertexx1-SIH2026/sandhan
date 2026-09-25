"""
Writes the corrected LIVE demo case files to data/demo/ (deterministic).

Three live cases, one folder each, all SYNTHETIC:

  CASE-2026-0001  KYC-fraud call centre, Noida
      * scamdesk01@okhdfc collects from 2 victims  -> subject (collector)
      * forwards 45,000 to rahulk.scam@icb          -> CONFIRMED link to historical CASE0113
      * forwards 74,000 to mule.acc02@okicici       -> leg 1 of a laundering cycle
  CASE-2026-0002  Investment scam, Delhi
      * suspect phone +919812345602 uses IMEI 356938035643809
                                                    -> CONFIRMED link to historical CASE0047
      * victim also paid freshmart19@icb (CASE0047's suspect UPI) - second signal
      * victim paid scamdesk01@okhdfc                -> links to live CASE-2026-0001
  CASE-2026-0003  Customs-parcel scam, Kolkata
      * mule.acc02 -> cashout.hub7 -> scamdesk01    -> closes the cycle
                                                       scamdesk01 -> mule.acc02 -> cashout.hub7 -> scamdesk01
      * pays vikram.t39@ybl (same handle as vikram.t39@okhdfcbank, suspect of CASE0082)
        AND anita.r59@icb (a counterparty of CASE0082)
                                                    -> PROBABLE link to CASE0082 (needs HITL verify)
  Hidden link for link prediction:
      +919812345601 (case 1) and +919812345604 (case 3) never call each other,
      but both call the same handler +919899900099 and share IP 103.21.244.10.

    python scripts/make_demo_data.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "demo"


def luhn_complete(first14: str) -> str:
    for d in "0123456789":
        s = first14 + d
        total = 0
        for i, ch in enumerate(s[::-1]):
            x = int(ch)
            if i % 2:
                x *= 2
                x = x - 9 if x > 9 else x
            total += x
        if total % 10 == 0:
            return s
    raise ValueError(first14)


IMEI_601 = "490154203237518"                   # valid Luhn
IMEI_602 = "356938035643809"                   # planted: historical CASE0047 suspect device
IMEI_604 = luhn_complete("35781234567890")

CDR_COLS = ["calling_number", "called_number", "call_date", "call_time", "duration_sec",
            "call_type", "imei_a", "imsi_a", "tower_location"]
UPI_COLS = ["txn_id", "timestamp", "payer_upi_id", "payee_upi_id", "amount", "payer_phone",
            "payer_account_no"]
IPDR_COLS = ["phone_number", "ip_address", "session_start", "session_end", "imei"]

CASES = {
    "CASE-2026-0001": {
        "cdr": [
            ["+919812345601", "+919811100011", "2026-01-04", "10:15:00", 182, "MOC", IMEI_601, "404101234560001", "Sector-18 Noida"],
            ["+919812345601", "+919811100011", "2026-01-04", "10:31:00", 245, "MOC", IMEI_601, "404101234560001", "Sector-18 Noida"],
            ["+919812345601", "+919811100012", "2026-01-04", "15:02:00", 310, "MOC", IMEI_601, "404101234560001", "Sector-18 Noida"],
            ["+919812345601", "+919811100012", "2026-01-05", "09:12:00", 95, "MTC", IMEI_601, "404101234560001", "Sector-62 Noida"],
            ["+919812345601", "+919899900099", "2026-01-04", "11:02:00", 45, "MOC", IMEI_601, "404101234560001", "Sector-18 Noida"],
            ["+919812345601", "+919899900099", "2026-01-05", "19:40:00", 61, "MOC", IMEI_601, "404101234560001", "Sector-62 Noida"],
        ],
        "upi": [
            ["UTR6001001", "2026-01-04 10:20:00", "ravi.kumar99@okaxis", "scamdesk01@okhdfc", 49999, "+919811100011", "50100234567801"],
            ["UTR6001002", "2026-01-04 15:10:00", "anil.m@ybl", "scamdesk01@okhdfc", 18000, "+919811100012", "50100234567804"],
            ["UTR6001003", "2026-01-04 18:05:00", "scamdesk01@okhdfc", "rahulk.scam@icb", 45000, "+919812345601", "50100234567803"],
            ["UTR6001004", "2026-01-05 12:00:00", "scamdesk01@okhdfc", "mule.acc02@okicici", 74000, "+919812345601", "50100234567803"],
        ],
        "ipdr": [
            ["+919812345601", "103.21.244.10", "2026-01-04 10:00:00", "2026-01-04 11:30:00", IMEI_601],
            ["+919812345601", "103.21.244.10", "2026-01-05 09:00:00", "2026-01-05 10:10:00", IMEI_601],
        ],
    },
    "CASE-2026-0002": {
        "cdr": [
            ["+919812345602", "+919811100022", "2026-01-06", "11:05:00", 300, "MOC", IMEI_602, "404101234560002", "Karol Bagh Delhi"],
            ["+919812345602", "+919811100022", "2026-01-07", "10:44:00", 412, "MOC", IMEI_602, "404101234560002", "Karol Bagh Delhi"],
            ["+919812345602", "+919811100022", "2026-01-08", "16:20:00", 128, "MOC", IMEI_602, "404101234560002", "Connaught Place, Delhi"],
            ["+919812345602", "+919883643122", "2026-01-07", "21:15:00", 76, "MOC", IMEI_602, "404101234560002", "Connaught Place, Delhi"],
        ],
        "upi": [
            ["UTR6002001", "2026-01-07 11:10:00", "priya.sh@ybl", "scamdesk01@okhdfc", 25000, "+919811100022", "50100234567802"],
            ["UTR6002002", "2026-01-08 16:40:00", "priya.sh@ybl", "freshmart19@icb", 12000, "+919811100022", "50100234567802"],
        ],
        "ipdr": [
            ["+919812345602", "45.114.32.88", "2026-01-06 10:55:00", "2026-01-06 12:00:00", IMEI_602],
        ],
    },
    "CASE-2026-0003": {
        "cdr": [
            ["+919812345604", "+919811100033", "2026-01-09", "08:10:00", 220, "MOC", IMEI_604, "404101234560004", "Salt Lake Kolkata"],
            ["+919812345604", "+919811100033", "2026-01-09", "08:55:00", 140, "MOC", IMEI_604, "404101234560004", "Salt Lake Kolkata"],
            ["+919812345604", "+919899900099", "2026-01-09", "09:30:00", 52, "MOC", IMEI_604, "404101234560004", "Salt Lake Kolkata"],
            ["+919812345604", "+919899900099", "2026-01-10", "20:05:00", 38, "MOC", IMEI_604, "404101234560004", "New Town Kolkata"],
        ],
        "upi": [
            ["UTR6003001", "2026-01-09 09:00:00", "sunita.d@ybl", "mule.acc02@okicici", 60500, "+919811100033", "50100234567805"],
            ["UTR6003002", "2026-01-09 13:30:00", "mule.acc02@okicici", "cashout.hub7@okaxis", 70000, "", "50100234567806"],
            ["UTR6003003", "2026-01-10 10:00:00", "cashout.hub7@okaxis", "scamdesk01@okhdfc", 68000, "", "50100234567807"],
            ["UTR6003004", "2026-01-10 11:20:00", "cashout.hub7@okaxis", "vikram.t39@ybl", 15000, "", "50100234567807"],
            ["UTR6003005", "2026-01-10 11:45:00", "cashout.hub7@okaxis", "anita.r59@icb", 9000, "", "50100234567807"],
        ],
        "ipdr": [
            ["+919812345604", "103.21.244.10", "2026-01-09 07:50:00", "2026-01-09 09:40:00", IMEI_604],
        ],
    },
}

FIRS = [
    {
        "fir_id": "FIR-2026-0001",
        "case_id": "CASE-2026-0001",
        "title": "FIR - CASE-2026-0001",
        "text": (
            "Complainant Ravi Kumar, resident of Sector 18, Noida, reported that on 04 January 2026 he "
            "received a call from mobile number +919812345601 from a person claiming to be a bank official, "
            "who said his account would be blocked unless the KYC was updated immediately. The caller asked "
            "him to install a screen-sharing application and transfer Rs. 49,999 to UPI ID scamdesk01@okhdfc "
            "for verification. The amount was debited without authorization. [SYNTHETIC RECORD]"
        ),
    },
    {
        "fir_id": "FIR-2026-0002",
        "case_id": "CASE-2026-0002",
        "title": "FIR - CASE-2026-0002",
        "text": (
            "Complainant Priya Sharma of Karol Bagh, Delhi, stated that she was added to a messaging group "
            "promoting a stock-trading scheme and was then called from +919812345602 by a person who assured "
            "fixed daily returns. She paid Rs. 25,000 to UPI ID scamdesk01@okhdfc and Rs. 12,000 to "
            "freshmart19@icb; the dashboard showed profits but withdrawals were never allowed. "
            "[SYNTHETIC RECORD]"
        ),
    },
    {
        "fir_id": "FIR-2026-0003",
        "case_id": "CASE-2026-0003",
        "title": "FIR - CASE-2026-0003",
        "text": (
            "Complainant Sunita Devi from Salt Lake, Kolkata, reported that she received a call from "
            "+919812345604 from a person posing as a customs officer, who said a parcel in her name contained "
            "contraband and threatened arrest unless a clearance fee was paid. Out of fear she paid Rs. 60,500 "
            "to UPI ID mule.acc02@okicici. [SYNTHETIC RECORD]"
        ),
    },
]


def _write(path: Path, cols: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        w.writerows(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for case_id, files in CASES.items():
        d = OUT / case_id
        d.mkdir(exist_ok=True)
        _write(d / "cdr.csv", CDR_COLS, files["cdr"])
        _write(d / "upi.csv", UPI_COLS, files["upi"])
        _write(d / "ipdr.csv", IPDR_COLS, files["ipdr"])
    (OUT / "fir_narratives.json").write_text(json.dumps(FIRS, indent=2), encoding="utf-8")
    print(f"Wrote demo cases to {OUT}")


if __name__ == "__main__":
    main()
