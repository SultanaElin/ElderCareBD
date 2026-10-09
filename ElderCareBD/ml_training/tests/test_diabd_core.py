from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml import diabd  # noqa: E402


EXPECTED_FILENAME = (
    "DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in "
    "Bangladesh.csv"
)
EXPECTED_SHA256 = "D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A"
EXPECTED_COLUMNS = (
    "age",
    "gender",
    "pulse_rate",
    "systolic_bp",
    "diastolic_bp",
    "glucose",
    "height",
    "weight",
    "bmi",
    "family_diabetes",
    "hypertensive",
    "family_hypertension",
    "cardiovascular_disease",
    "stroke",
    "diabetic",
)
EXPECTED_ROWS = 5288
PIMA_V2_SHA256 = "2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07"


class DiaBDCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data_dir = ML_ROOT / "data"
        cls.raw = diabd.load_raw_diabd(cls.data_dir)

    def test_local_snapshot_filename_hash_schema_and_row_count(self) -> None:
        path = self.data_dir / EXPECTED_FILENAME

        self.assertTrue(path.is_file())
        self.assertEqual(diabd.DIABD_FILENAME, EXPECTED_FILENAME)
        self.assertEqual(diabd.DIABD_SHA256, EXPECTED_SHA256)
        self.assertEqual(diabd.sha256_file(path), EXPECTED_SHA256)
        self.assertEqual(diabd.DIABD_COLUMNS, EXPECTED_COLUMNS)
        self.assertEqual(tuple(self.raw.columns), EXPECTED_COLUMNS)
        self.assertEqual(len(self.raw), EXPECTED_ROWS)

    def test_categorical_mappings_are_explicit_and_applied(self) -> None:
        self.assertEqual(diabd.GENDER_MAPPING, {"Female": 0, "Male": 1})
        self.assertEqual(diabd.TARGET_MAPPING, {"No": 0, "Yes": 1})
        for column in diabd.BINARY_FEATURES:
            with self.subTest(column=column):
                self.assertEqual(set(self.raw[column].unique()), {0, 1})

        X, y = diabd.encoded_xy(self.raw)

        self.assertNotIn(diabd.DIABD_TARGET, X.columns)
        self.assertEqual(set(X["gender"].unique()), {0, 1})
        self.assertEqual(set(y.unique()), {0, 1})
        for source, encoded in diabd.GENDER_MAPPING.items():
            with self.subTest(gender=source):
                self.assertTrue((X.loc[self.raw["gender"].eq(source), "gender"] == encoded).all())
        for source, encoded in diabd.TARGET_MAPPING.items():
            with self.subTest(target=source):
                self.assertTrue((y.loc[self.raw[diabd.DIABD_TARGET].eq(source)] == encoded).all())

    def test_every_feature_set_excludes_the_target(self) -> None:
        predictors = set(EXPECTED_COLUMNS) - {diabd.DIABD_TARGET}
        for name, features in diabd.FEATURE_SETS.items():
            with self.subTest(feature_set=name):
                self.assertNotIn(diabd.DIABD_TARGET, features)
                self.assertTrue(set(features).issubset(predictors))
                self.assertEqual(len(features), len(set(features)))

    def test_plausibility_transform_is_fixed_to_nan_and_never_deletes_rows(self) -> None:
        source = pd.DataFrame(
            {
                column: [minimum, maximum, minimum - 0.5, maximum + 0.5]
                for column, (minimum, maximum) in diabd.PLAUSIBILITY_RANGES.items()
            },
            index=[11, 22, 33, 44],
        )
        source["gender"] = [0, 1, 0, 1]
        unchanged = source.copy(deep=True)
        ranges = tuple(
            (column, minimum, maximum)
            for column, (minimum, maximum) in diabd.PLAUSIBILITY_RANGES.items()
        )
        transformer = diabd.DiaBDPlausibilityToNaN(ranges).fit(source)

        transformed = transformer.transform(source)

        pd.testing.assert_frame_equal(source, unchanged)
        self.assertEqual(transformed.shape, source.shape)
        self.assertEqual(transformed.index.tolist(), source.index.tolist())
        self.assertEqual(transformed.columns.tolist(), source.columns.tolist())
        pd.testing.assert_series_equal(transformed["gender"], source["gender"])
        for column, (minimum, maximum) in diabd.PLAUSIBILITY_RANGES.items():
            with self.subTest(column=column):
                self.assertEqual(transformed.loc[11, column], minimum)
                self.assertEqual(transformed.loc[22, column], maximum)
                self.assertTrue(np.isnan(transformed.loc[33, column]))
                self.assertTrue(np.isnan(transformed.loc[44, column]))

    def test_model_schema_rejects_missing_and_extra_features(self) -> None:
        features = diabd.FEATURE_SETS["compact_4"]
        X, _ = diabd.encoded_xy(self.raw)
        valid = X.loc[:, list(features)].head(3)
        selector = diabd.build_diabd_pipeline(
            features,
            "logistic_regression",
        ).named_steps["schema"]
        selector.fit(valid)

        with self.assertRaisesRegex(ValueError, "Missing required features"):
            selector.transform(valid.drop(columns=features[0]))
        with self.assertRaisesRegex(ValueError, "Unexpected features"):
            selector.transform(valid.assign(diabetic=0))

    def test_raw_loader_rejects_missing_and_extra_columns(self) -> None:
        altered_frames = {
            "missing": self.raw.drop(columns=["pulse_rate"]),
            "extra": self.raw.assign(unexpected_column=0),
        }
        for case, altered in altered_frames.items():
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                temporary_dir = Path(temporary)
                (temporary_dir / EXPECTED_FILENAME).touch()
                with (
                    patch.object(diabd, "sha256_file", return_value=EXPECTED_SHA256),
                    patch.object(diabd.pd, "read_csv", return_value=altered),
                    self.assertRaisesRegex(ValueError, "schema or column order"),
                ):
                    diabd.load_raw_diabd(temporary_dir)

    def test_evaluation_is_deterministic_and_scores_every_row(self) -> None:
        features = diabd.FEATURE_SETS["compact_4"]
        X, y = diabd.encoded_xy(self.raw)
        X = X.loc[:, list(features)]
        pipeline = diabd.build_diabd_pipeline(features, "logistic_regression")

        first = diabd.evaluate_candidate(pipeline, X, y)
        second = diabd.evaluate_candidate(pipeline, X, y)

        first_scores = first["oof_probabilities"]
        second_scores = second["oof_probabilities"]
        diabd.validate_probability_vector(first_scores, EXPECTED_ROWS)
        self.assertEqual(first_scores.shape, (EXPECTED_ROWS,))
        self.assertEqual(len(first["fold_metrics"]), diabd.CV_FOLDS)
        np.testing.assert_array_equal(first_scores, second_scores)
        self.assertEqual(first["oof_metrics"], second["oof_metrics"])
        self.assertEqual(first["oof_confusion_matrix"], second["oof_confusion_matrix"])

    def test_existing_pima_v2_artifact_hash_is_unchanged(self) -> None:
        artifact_path = ML_ROOT / "models" / "diabetes_model_v2.pkl"

        self.assertTrue(artifact_path.is_file())
        self.assertEqual(diabd.sha256_file(artifact_path), PIMA_V2_SHA256)


if __name__ == "__main__":
    unittest.main()
