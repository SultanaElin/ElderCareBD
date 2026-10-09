"""Fast contract and negative-control tests for Task 13C."""

from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from ml_training.eldercare_ml.kidney import (
    BIOMARKER_EXCLUDED_FEATURES,
    CATEGORY_VALUES,
    COMPACT_HOME_FEATURES,
    ELDERCARE_NON_LAB_FEATURES,
    FEATURE_SETS,
    KIDNEY_COLUMNS,
    KIDNEY_FILE_BYTES,
    KIDNEY_FILENAME,
    KIDNEY_ROWS,
    KIDNEY_SHA256,
    NUMERIC_FEATURES,
    RENAL_AND_LAB_FEATURES,
    TARGET_CLASSES,
    TARGET_MAPPING,
    build_kidney_pipeline,
    cleaning_decisions,
    encoded_targets,
    feature_compatibility_rows,
    load_raw_kidney,
    sha256_file,
    suspicious_value_counts,
    target_construction_audit,
)


ML_ROOT = Path(__file__).resolve().parents[1]


class KidneyCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.path = ML_ROOT / "data" / KIDNEY_FILENAME
        cls.raw = load_raw_kidney(ML_ROOT / "data")
        cls.targets = encoded_targets(cls.raw)
        cls.sample = cls.raw.sample(n=3_000, random_state=42)
        cls.sample_X = cls.sample.loc[:, list(COMPACT_HOME_FEATURES)]
        cls.sample_y = cls.sample["Target"].ne("No_Disease").astype(int)
        cls.pipeline = build_kidney_pipeline(
            COMPACT_HOME_FEATURES, "logistic_regression_balanced"
        ).fit(cls.sample_X, cls.sample_y)

    def test_raw_hash_size_shape_and_schema_are_fixed(self) -> None:
        self.assertEqual(sha256_file(self.path), KIDNEY_SHA256)
        self.assertEqual(self.path.stat().st_size, KIDNEY_FILE_BYTES)
        self.assertEqual(self.raw.shape, (KIDNEY_ROWS, len(KIDNEY_COLUMNS)))
        self.assertEqual(tuple(self.raw.columns), KIDNEY_COLUMNS)
        self.assertEqual(self.raw.isna().sum().sum(), 0)
        self.assertEqual(self.raw.duplicated().sum(), 0)
        self.assertEqual(
            self.raw.drop(columns="Target").duplicated(keep=False).sum(), 0
        )

    def test_target_mapping_and_class_counts_are_exact(self) -> None:
        self.assertEqual(
            TARGET_MAPPING,
            {
                "No_Disease": 0,
                "Low_Risk": 1,
                "Moderate_Risk": 2,
                "High_Risk": 3,
                "Severe_Disease": 4,
            },
        )
        self.assertEqual(
            self.raw["Target"].value_counts().to_dict(),
            {
                "No_Disease": 16_432,
                "Low_Risk": 2_054,
                "Moderate_Risk": 821,
                "High_Risk": 821,
                "Severe_Disease": 410,
            },
        )
        self.assertEqual(
            set(self.targets["original_five_class"].unique()), set(range(5))
        )

    def test_category_mappings_cover_exact_source_values(self) -> None:
        self.assertEqual(len(CATEGORY_VALUES), 14)
        for column, expected in CATEGORY_VALUES.items():
            with self.subTest(column=column):
                self.assertEqual(set(self.raw[column].unique()), set(expected))

    def test_numeric_types_and_values_are_finite(self) -> None:
        numeric = self.raw.loc[:, list(NUMERIC_FEATURES)].to_numpy(dtype=float)
        self.assertTrue(np.isfinite(numeric).all())
        self.assertEqual(float(self.raw["Age of the patient"].min()), 5.0)
        self.assertEqual(float(self.raw["Age of the patient"].max()), 90.0)
        self.assertEqual(
            float(
                self.raw[
                    "Estimated Glomerular Filtration Rate (eGFR)"
                ].min()
            ),
            5.0,
        )
        self.assertEqual(
            float(
                self.raw[
                    "Estimated Glomerular Filtration Rate (eGFR)"
                ].max()
            ),
            120.0,
        )

    def test_target_validity_checks_expose_clinical_incoherence(self) -> None:
        counts = suspicious_value_counts(self.raw)
        self.assertEqual(counts["diabetes_no_but_duration_positive"], 9_963)
        self.assertEqual(counts["diabetes_duration_exceeds_age"], 2_498)
        self.assertEqual(counts["hypertension_no_but_duration_positive"], 9_879)
        self.assertEqual(counts["hypertension_duration_exceeds_age"], 2_503)
        self.assertEqual(counts["no_disease_with_egfr_below_15"], 1_491)
        self.assertEqual(counts["severe_disease_with_egfr_at_least_90"], 103)

        audit = target_construction_audit(self.raw)
        self.assertFalse(audit["clinical_or_independent_label_documentation_found"])
        self.assertLess(audit["egfr_band_target_association"]["cramers_v"], 0.03)
        correlations = audit["selected_clinical_correlations"]
        self.assertLess(abs(correlations["egfr_vs_serum_creatinine"]), 0.02)
        self.assertLess(abs(correlations["egfr_vs_cystatin_c"]), 0.02)

    def test_cleaning_rules_do_not_mutate_or_silently_delete(self) -> None:
        before = sha256_file(self.path)
        rules = cleaning_decisions(self.raw)
        self.assertGreaterEqual(len(rules), 10)
        decisions = " ".join(str(rule["decision"]).lower() for rule in rules)
        self.assertIn("do not relabel or delete", decisions)
        self.assertIn("preserve exactly", decisions)
        self.assertEqual(sha256_file(self.path), before)

    def test_feature_contracts_are_explicit_and_lab_free_where_declared(self) -> None:
        self.assertEqual(len(FEATURE_SETS["full_42"]), 42)
        self.assertEqual(len(BIOMARKER_EXCLUDED_FEATURES), 14)
        self.assertEqual(len(ELDERCARE_NON_LAB_FEATURES), 12)
        self.assertEqual(len(COMPACT_HOME_FEATURES), 7)
        for feature_set in (
            BIOMARKER_EXCLUDED_FEATURES,
            ELDERCARE_NON_LAB_FEATURES,
            COMPACT_HOME_FEATURES,
        ):
            self.assertTrue(set(feature_set).isdisjoint(RENAL_AND_LAB_FEATURES))
        rows = feature_compatibility_rows()
        self.assertEqual(len(rows), 42)
        self.assertEqual({row["feature"] for row in rows}, set(KIDNEY_COLUMNS[:-1]))

    def test_pipeline_rejects_missing_and_extra_features(self) -> None:
        row = self.sample_X.iloc[[0]].copy()
        with self.assertRaisesRegex(ValueError, "Missing required features"):
            self.pipeline.predict_proba(row.drop(columns=COMPACT_HOME_FEATURES[0]))
        extra = row.assign(fabricated_default=0)
        with self.assertRaisesRegex(ValueError, "Unexpected features"):
            self.pipeline.predict_proba(extra)

    def test_pipeline_rejects_unsupported_categories(self) -> None:
        row = self.sample_X.iloc[[0]].copy()
        row.loc[:, "Smoking status"] = "former"
        with self.assertRaisesRegex(ValueError, "unknown categories"):
            self.pipeline.predict_proba(row)

    def test_research_prediction_is_deterministic_and_probabilities_valid(self) -> None:
        second = build_kidney_pipeline(
            COMPACT_HOME_FEATURES, "logistic_regression_balanced"
        ).fit(self.sample_X, self.sample_y)
        rows = self.sample_X.iloc[:8]
        first_probability = self.pipeline.predict_proba(rows)
        second_probability = second.predict_proba(rows)
        self.assertEqual(first_probability.shape, (8, 2))
        self.assertTrue(np.isfinite(first_probability).all())
        self.assertTrue(
            ((first_probability >= 0.0) & (first_probability <= 1.0)).all()
        )
        np.testing.assert_allclose(first_probability.sum(axis=1), np.ones(8))
        np.testing.assert_array_equal(first_probability, second_probability)

    def test_target_classes_are_not_renamed_as_clinical_stages(self) -> None:
        self.assertEqual(
            TARGET_CLASSES,
            (
                "No_Disease",
                "Low_Risk",
                "Moderate_Risk",
                "High_Risk",
                "Severe_Disease",
            ),
        )
        self.assertNotIn("CKD stage", " ".join(TARGET_CLASSES))


if __name__ == "__main__":
    unittest.main()
