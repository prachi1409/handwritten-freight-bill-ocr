"""Evaluation script for testing the 10 real handwritten freight bill PDF dataset against Ground Truth."""

import sys
from pathlib import Path

BACKEND_DIR = Path(r"c:\Users\Prachi\OneDrive\Desktop\bill-ocr\backend")
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

import json
import logging
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.db.database import SessionLocal
from app.db.models import Document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("evaluate_10_dataset")

DATASET_DIR = BACKEND_DIR / "test_dataset"

CRITICAL_FIELDS = [
    "bill_number", "invoice_number", "consignor", "consignee",
    "origin", "destination", "freight_amount", "total_amount"
]

ALL_SCHEMA_KEYS = [
    "bill_number", "invoice_number", "bill_date", "carrier", "consignor", "consignee",
    "origin", "destination", "commodity_description", "quantity", "weight",
    "freight_amount", "fuel_surcharge", "handling_charge", "total_amount",
    "vehicle_number", "driver_name", "pickup_time", "delivery_time", "special_instructions"
]


def run_evaluation():
    logger.info("==================================================================")
    logger.info("STARTING END-TO-END OCR EVALUATION ON 10 REAL HANDWRITTEN PDFs")
    logger.info("==================================================================")

    # Disable test mode so OCR factory runs real processor logic
    settings.TESTING = False

    client = TestClient(app)

    results_list = []

    pdf_files = sorted(list(DATASET_DIR.glob("*.pdf")))
    logger.info(f"Found {len(pdf_files)} evaluation PDFs in '{DATASET_DIR}'.")

    total_fields_count = 0
    correct_fields_count = 0

    total_critical_count = 0
    correct_critical_count = 0

    completed_docs_count = 0
    review_docs_count = 0
    failed_docs_count = 0

    stp_count = 0

    for pdf_path in pdf_files:
        gt_filename = pdf_path.stem + "_ground_truth.json"
        gt_path = DATASET_DIR / gt_filename
        if not gt_path.exists():
            base_stem = pdf_path.stem.split("_easy")[0].split("_medium")[0].split("_hard")[0]
            gt_path = DATASET_DIR / f"{base_stem}_ground_truth.json"

        assert gt_path.exists(), f"Ground Truth JSON missing for {pdf_path.name}"

        with open(gt_path, "r", encoding="utf-8") as f:
            gt_obj = json.load(f)

        difficulty = gt_obj.get("difficulty", "Unknown")
        gt_data = gt_obj.get("ground_truth", {})

        # Step 1: Upload document via API
        pdf_bytes = pdf_path.read_bytes()
        logger.info(f"\nProcessing '{pdf_path.name}' (Difficulty: {difficulty})...")
        upload_resp = client.post(
            "/api/v1/documents/upload",
            files={"file": (pdf_path.name, pdf_bytes, "application/pdf")}
        )
        assert upload_resp.status_code == 200, f"Upload API failed: {upload_resp.text}"

        doc_data = upload_resp.json()
        doc_id = doc_data["document_id"]

        # Step 2: Fetch detailed document record from API
        detail_resp = client.get(f"/api/v1/documents/{doc_id}")
        assert detail_resp.status_code == 200, f"Get Detail API failed: {detail_resp.text}"

        detail = detail_resp.json()
        status = detail.get("status", "FAILED")
        confidence = detail.get("overall_confidence", 0.0)
        extracted = detail.get("extracted_data") or {}
        warnings = detail.get("validation_warnings") or []

        # Ground truth comparison
        correct_fields = []
        incorrect_fields = []
        missing_fields = []

        doc_critical_correct = True

        for k in ALL_SCHEMA_KEYS:
            expected = str(gt_data.get(k, "")).strip()
            actual = str(extracted.get(k, "")).strip() if extracted.get(k) is not None else ""

            total_fields_count += 1
            if k in CRITICAL_FIELDS:
                total_critical_count += 1

            if not actual or actual.lower() in ("none", "null"):
                missing_fields.append(f"{k}: expected '{expected}'")
                if k in CRITICAL_FIELDS:
                    doc_critical_correct = False
            elif actual == expected or (k == "bill_date" and actual in expected):
                correct_fields.append(f"{k}: '{actual}'")
                correct_fields_count += 1
                if k in CRITICAL_FIELDS:
                    correct_critical_count += 1
            else:
                incorrect_fields.append(f"{k}: got '{actual}', expected '{expected}'")
                if k in CRITICAL_FIELDS:
                    doc_critical_correct = False

        if status == "COMPLETED":
            completed_docs_count += 1
            if doc_critical_correct and not warnings:
                stp_count += 1
        elif status == "REVIEW":
            review_docs_count += 1
        else:
            failed_docs_count += 1

        results_list.append({
            "filename": pdf_path.name,
            "difficulty": difficulty,
            "status": status,
            "confidence": confidence,
            "correct_count": len(correct_fields),
            "incorrect_count": len(incorrect_fields),
            "missing_count": len(missing_fields),
            "critical_correct": doc_critical_correct,
            "extracted": extracted,
            "ground_truth": gt_data,
            "warnings": warnings,
            "incorrect_details": incorrect_fields,
            "missing_details": missing_fields
        })

    total_docs = len(pdf_files)
    field_acc = (correct_fields_count / total_fields_count) * 100 if total_fields_count else 0.0
    crit_acc = (correct_critical_count / total_critical_count) * 100 if total_critical_count else 0.0
    stp_rate = (stp_count / total_docs) * 100 if total_docs else 0.0

    print("\n==========================================================================")
    print("      10 REAL HANDWRITTEN FREIGHT BILL OCR ACCURACY EVALUATION REPORT     ")
    print("==========================================================================")
    print(f"{'PDF Filename':<32} | {'Diff':<7} | {'Status':<10} | {'Conf':<6} | {'Crit Correct':<12} | {'All Fields'}")
    print("-" * 90)

    for r in results_list:
        crit_str = "YES" if r["critical_correct"] else "NO"
        fields_str = f"{r['correct_count']}/20 ({r['correct_count']/20*100:.0f}%)"
        print(f"{r['filename']:<32} | {r['difficulty']:<7} | {r['status']:<10} | {r['confidence']*100:>4.1f}% | {crit_str:<12} | {fields_str}")

    print("-" * 90)
    print(f"Total Evaluation Documents: {total_docs}")
    print(f"  - Completed: {completed_docs_count}")
    print(f"  - Review Needed: {review_docs_count}")
    print(f"  - Failed: {failed_docs_count}")
    print(f"\nAccuracy Summary:")
    print(f"  - Field-Level Accuracy:    {field_acc:.2f}% ({correct_fields_count}/{total_fields_count} fields)")
    print(f"  - Critical-Field Accuracy: {crit_acc:.2f}% ({correct_critical_count}/{total_critical_count} critical fields)")
    print(f"  - STP Rate (Straight-Through Processing): {stp_rate:.1f}% ({stp_count}/{total_docs} documents)")
    print("==========================================================================\n")

    return results_list


if __name__ == "__main__":
    run_evaluation()

