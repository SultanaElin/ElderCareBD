"""Generated-output and preservation tests for Task 13C Outcome C."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
OUTPUT_DIR = ML_ROOT / "outputs" / "task13c"
EXPECTED_PROTECTED = {
    "diabetes_model_v3_diabd.pkl": (
        "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
    ),
    "diabetes_model_v3_diabd.metadata.json": (
        "53A33B967D807F94A0B37EB11CA616E7A1EF72A879DC2FE9FC5FA8BB169492BB"
    ),
    "heart_model_v2.pkl": (
        "E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103"
    ),
    "heart_model_v2.metadata.json": (
        "EE32EC47562066C63B82B50071DA0D715EC3B43BFC71F29FAC33379D7B41EE90"
    ),
    "diabetes_model_v2.pkl": (
        "2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07"
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


class KidneyOutputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (OUTPUT_DIR / "run_manifest.json").is_file():
            raise RuntimeError(
                "Run ml_training/train_kidney_audit.py before Task 13C output tests."
            )

    def test_required_reports_and_audits_exist(self) -> None:
        required = {
            "dataset_audit.json",
            "provenance_audit.json",
            "target_construction_audit.json",
            "target_formulation_decision.json",
            "feature_compatibility.csv",
            "cleaning_decisions.json",
            "candidate_evaluations.json",
            "cv_results.csv",
            "fold_metrics.csv",
            "comparison_summary.csv",
            "class_level_metrics.csv",
            "confusion_matrices.json",
            "calibration_diagnostic.json",
            "elderly_subgroup_analysis.json",
            "deployment_decision.json",
            "three_disease_contract_summary.json",
            "TARGET_CONSTRUCTION_REPORT.md",
            "TASK13C_REPORT.md",
            "run_manifest.json",
        }
        self.assertTrue(required.issubset({path.name for path in OUTPUT_DIR.iterdir()}))

    def test_outcome_c_creates_no_kidney_model_artifact(self) -> None:
        decision = json.loads(
            (OUTPUT_DIR / "deployment_decision.json").read_text(encoding="utf-8")
        )
        self.assertEqual(decision["outcome"], "C")
        self.assertFalse(decision["kidney_artifact_created"])
        self.assertIsNone(decision["authorized_runtime_feature_contract"])
        self.assertEqual(decision["task14_status"], "PAUSED")
        self.assertEqual(list((ML_ROOT / "models").glob("kidney_model*.pkl")), [])
        self.assertEqual(
            list((ML_ROOT / "models").glob("kidney_model*.metadata.json")), []
        )

    def test_existing_artifact_hashes_are_unchanged(self) -> None:
        for filename, expected in EXPECTED_PROTECTED.items():
            with self.subTest(filename=filename):
                self.assertEqual(_sha256(ML_ROOT / "models" / filename), expected)

    def test_manifest_proves_pre_and_post_hash_identity(self) -> None:
        manifest = json.loads(
            (OUTPUT_DIR / "run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["status"], "COMPLETE")
        self.assertEqual(manifest["deployment_outcome"], "C")
        self.assertFalse(manifest["kidney_artifact_created"])
        self.assertEqual(
            manifest["protected_hashes_before"], manifest["protected_hashes_after"]
        )

    def test_all_candidates_have_five_fold_results(self) -> None:
        evaluations = json.loads(
            (OUTPUT_DIR / "candidate_evaluations.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(evaluations), 24)
        for evaluation in evaluations:
            with self.subTest(
                formulation=evaluation["formulation"],
                feature_set=evaluation["feature_set"],
                model=evaluation["candidate_key"],
            ):
                self.assertEqual(evaluation["evaluation"]["folds"], 5)
                self.assertEqual(len(evaluation["evaluation"]["fold_metrics"]), 5)

    def test_feature_matrix_covers_all_42_predictors(self) -> None:
        with (OUTPUT_DIR / "feature_compatibility.csv").open(
            newline="", encoding="utf-8"
        ) as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 42)
        for row in rows:
            self.assertIn("no current deployment", row["deployment_decision"])

    def test_report_has_all_21_sections_and_paused_task14(self) -> None:
        report = (OUTPUT_DIR / "TASK13C_REPORT.md").read_text(encoding="utf-8")
        for number in range(1, 22):
            self.assertIn(f"## {number}.", report)
        self.assertIn("Task 13C: COMPLETE", report)
        self.assertIn("Task 14 remains PAUSED", report)

    def test_fresh_process_validates_raw_snapshot_and_decision(self) -> None:
        program = """
import json
from pathlib import Path
from ml_training.eldercare_ml.kidney import load_raw_kidney

root = Path('ml_training')
frame = load_raw_kidney(root / 'data')
decision = json.loads((root / 'outputs' / 'task13c' / 'deployment_decision.json').read_text())
print(json.dumps({'shape': list(frame.shape), 'outcome': decision['outcome']}))
"""
        completed = subprocess.run(
            [sys.executable, "-B", "-c", program],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        observed = json.loads(completed.stdout)
        self.assertEqual(observed, {"shape": [20_538, 43], "outcome": "C"})


if __name__ == "__main__":
    unittest.main()
