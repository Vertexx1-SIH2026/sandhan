"""
Generates one SYNTHETIC FIR narrative per historical case
(data/historical/sandhan_historical_fir_narratives.csv) so SBERT M.O.
matching has a historical corpus to compare new FIRs against.

The narratives are template-generated from each case's own records (suspect
phone/UPI, most common city, total amount, date range) with paraphrased
sentence pools per modus operandi, so same-M.O. cases read differently but
stay semantically close. Deterministic: re-running produces the same file.

All content is fabricated for the hackathon demo -- no real complaints.

    python scripts/make_historical_firs.py
"""
from __future__ import annotations

import csv
import hashlib
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "historical"
INDEX = HIST / "sandhan_historical_case_index.csv"
RECORDS = HIST / "sandhan_historical_dummy_data.csv"
OUT = HIST / "sandhan_historical_fir_narratives.csv"

# Planted demo overlaps get the M.O. that matches the live demo FIRs.
FIXED_MO = {"CASE0113": "kyc_bank_impersonation", "CASE0047": "investment_scheme"}

COMPLAINANTS = [
    "Suresh Patil", "Anjali Mehta", "Farhan Qureshi", "Lakshmi Narayanan", "Gurpreet Kaur",
    "Arvind Joshi", "Neha Bansal", "Joseph Mathew", "Rekha Iyer", "Manoj Tiwari",
    "Shabnam Ali", "Kiran Reddy", "Deepak Chauhan", "Meenakshi Sundaram", "Harish Rao",
    "Pallavi Deshmukh", "Imran Shaikh", "Sangeeta Das", "Vivek Malhotra", "Bhavna Trivedi",
]

MO = {
    "kyc_bank_impersonation": [
        ["received a call from {phone} from a person claiming to be a bank official",
         "was contacted on {phone} by a caller who said he was from the bank's KYC department",
         "got repeated calls from {phone}; the caller posed as a customer-care executive of the bank"],
        ["who said the account would be blocked unless the KYC was updated immediately",
         "and was told the debit card would be suspended because KYC documents had expired",
         "who warned that the account would be frozen within the hour for pending KYC verification"],
        ["The caller asked the complainant to install a screen-sharing application and transfer Rs. {amount} to UPI ID {upi} for 'verification'.",
         "On the caller's instructions the complainant shared an OTP and moved Rs. {amount} to {upi} as a 'refundable verification charge'.",
         "The complainant was guided to open a remote-access app, after which Rs. {amount} was sent to UPI ID {upi}."],
    ],
    "investment_scheme": [
        ["was added to a messaging group promoting a stock-trading scheme and later contacted from {phone}",
         "received a message and then a call from {phone} offering guaranteed returns on an investment plan",
         "was approached on {phone} by a so-called portfolio manager of a crypto trading platform"],
        ["with the promise of doubling the money within a few weeks",
         "who showed fake screenshots of profits made by other members",
         "who assured fixed daily returns of five percent"],
        ["The complainant invested Rs. {amount} through UPI ID {upi}; the dashboard showed profits but withdrawals were never allowed.",
         "Over several days Rs. {amount} was paid to {upi}, after which the group admin stopped responding.",
         "Believing the returns were real, the complainant transferred Rs. {amount} to UPI ID {upi} and the platform then vanished."],
    ],
    "customs_parcel": [
        ["received a call from {phone} from a person posing as a customs officer",
         "was told on a call from {phone} that a parcel in the complainant's name had been seized at the airport",
         "got a call from {phone}; the caller claimed to be from the courier company and then transferred the call to a 'customs official'"],
        ["who said the parcel contained contraband and threatened arrest",
         "and demanded a clearance fee to avoid legal action",
         "who threatened a police case unless a penalty was paid immediately"],
        ["Out of fear the complainant paid Rs. {amount} to UPI ID {upi}.",
         "The complainant transferred Rs. {amount} to {upi} as the so-called customs duty.",
         "Rs. {amount} was sent to UPI ID {upi} before the complainant realised it was a fraud."],
    ],
    "job_task_fraud": [
        ["was offered a part-time online job by a person using {phone}",
         "received a message from {phone} about earning money by liking videos and rating hotels",
         "was contacted from {phone} with a work-from-home task offer"],
        ["and was initially paid small amounts to build trust",
         "and was asked to complete prepaid 'merchant tasks' to unlock higher commissions",
         "after which the tasks required depositing money first"],
        ["In total Rs. {amount} was deposited to UPI ID {upi} and none of it was returned.",
         "The complainant paid Rs. {amount} to {upi} for tasks and the promised commission never came.",
         "Rs. {amount} was transferred to UPI ID {upi} before the complainant was removed from the group."],
    ],
    "loan_app_extortion": [
        ["took a small loan through a mobile lending app and was then harassed from {phone}",
         "installed an instant-loan app and later started getting abusive calls from {phone}",
         "was threatened by recovery agents calling from {phone} after using a loan app"],
        ["who threatened to send morphed photos to the complainant's contacts",
         "who accessed the phone's contact list and threatened to shame the complainant",
         "demanding repayment far beyond the amount borrowed"],
        ["Under pressure the complainant paid Rs. {amount} to UPI ID {upi}.",
         "The complainant ended up paying Rs. {amount} to {upi} in several instalments.",
         "Rs. {amount} was extorted through UPI ID {upi}."],
    ],
    "electricity_bill": [
        ["received an SMS saying the electricity connection would be cut tonight and to call {phone}",
         "got a message about an unpaid electricity bill with the number {phone} to contact",
         "was called from {phone} by someone claiming to be from the electricity board"],
        ["and the caller asked the complainant to install an app to update the bill",
         "and the caller said the last payment had not been updated in the system",
         "and the caller insisted that a small verification payment was needed"],
        ["Rs. {amount} was then debited and sent to UPI ID {upi}.",
         "Soon after, Rs. {amount} was transferred to {upi} without consent.",
         "The complainant lost Rs. {amount}, which went to UPI ID {upi}."],
    ],
    "marketplace_buyer": [
        ["listed an item for sale online and was contacted by a 'buyer' using {phone}",
         "was approached on {phone} by a person claiming to be an army officer interested in buying furniture",
         "received a call from {phone} from a buyer who wanted to pay in advance"],
        ["who sent a UPI QR code saying it was to receive payment",
         "who asked the complainant to scan a code to 'receive' the amount",
         "who insisted on a small test transaction first"],
        ["Instead the complainant's account was debited Rs. {amount} to {upi}.",
         "The complainant lost Rs. {amount}, credited to UPI ID {upi}.",
         "Rs. {amount} went to {upi} and the buyer stopped answering."],
    ],
    "lottery_prize": [
        ["received a call from {phone} saying the complainant had won a lucky draw",
         "was told on a call from {phone} that a car had been won in a company lottery",
         "got a message and call from {phone} about a prize from a TV show"],
        ["and had to pay processing fees and GST to claim the prize",
         "but first needed to pay registration and delivery charges",
         "provided a small tax amount was paid upfront"],
        ["The complainant paid Rs. {amount} to UPI ID {upi} and never received anything.",
         "Rs. {amount} was transferred to {upi} for the fees.",
         "In total Rs. {amount} went to UPI ID {upi}."],
    ],
}


def _rng(case_id: str) -> random.Random:
    return random.Random(int(hashlib.sha256(case_id.encode()).hexdigest()[:12], 16))


def main() -> None:
    if not INDEX.exists() or not RECORDS.exists():
        sys.exit(f"Missing {INDEX} or {RECORDS}")
    index = list(csv.DictReader(open(INDEX, newline="", encoding="utf-8-sig")))
    recs = defaultdict(list)
    for r in csv.DictReader(open(RECORDS, newline="", encoding="utf-8-sig")):
        recs[r["case_id"]].append(r)

    mo_names = sorted(MO)
    rows = []
    for idx in index:
        cid = idx["case_id"]
        rng = _rng(cid)
        mo = FIXED_MO.get(cid) or rng.choice(mo_names)
        case_recs = recs.get(cid, [])
        locs = Counter(r["location"] for r in case_recs if r.get("location") and r["location"] != "N/A")
        city = (locs.most_common(1)[0][0] if locs else "Delhi")
        upi = idx["suspect_upi"]
        amount = sum(float(r["value"]) for r in case_recs
                     if r["record_type"] == "UPI" and upi in (r["dest_id"], r["source_id"]))
        amount = int(min(amount, 450000)) or 25000
        dates = sorted(r["timestamp"][:10] for r in case_recs if r.get("timestamp"))
        when = dates[0] if dates else "2024-01-01"
        who = rng.choice(COMPLAINANTS)
        p1, p2, p3 = (rng.choice(pool) for pool in MO[mo])
        fill = {"phone": idx["suspect_number"], "upi": upi, "amount": f"{amount:,}"}
        text = (f"Complainant {who}, resident of {city}, reported that on {when} the complainant "
                f"{p1.format(**fill)} {p2.format(**fill)}. {p3.format(**fill)} "
                f"The matter was reported to the cyber cell. [SYNTHETIC RECORD]")
        rows.append({"case_id": cid, "fir_id": f"HFIR-{cid}", "mo_category": mo, "narrative": text})

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["case_id", "fir_id", "mo_category", "narrative"])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} synthetic FIR narratives -> {OUT}")
    print(Counter(r["mo_category"] for r in rows))


if __name__ == "__main__":
    main()
