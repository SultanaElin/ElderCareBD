from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.contracts import get_dataset_configs  # noqa: E402
from ml_training.eldercare_ml.data import (  # noqa: E402
    EXPECTED_DATASETS,
    load_and_validate_dataset,
    sha256_file,
)
from ml_training.eldercare_ml.modeling import ZeroSentinelToNaN  # noqa: E402


class DatasetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configs = get_dataset_configs(ML_ROOT / "data")

    def test_approved_dataset_snapshots_and_schemas(self) -> None:
        for disease, config in self.configs.items():
            with self.subTest(disease=disease):
                frame, audit = load_and_validate_dataset(config, ML_ROOT / "data")
                self.assertEqual(tuple(frame.columns), config.required_columns)
                self.assertEqual(len(frame), EXPECTED_DATASETS[disease]["rows"])
                self.assertEqual(audit["sha256"], EXPECTED_DATASETS[disease]["sha256"])
                self.assertEqual(set(frame[config.target].unique()), {0, 1})
                self.assertEqual(audit["exact_duplicate_rows"], 0)
                self.assertEqual(audit["duplicate_predictor_rows"], 0)

    def test_root_dataset_copies_are_identical_to_training_inputs(self) -> None:
        repository_root = ML_ROOT.parent
        for config in self.configs.values():
            with self.subTest(dataset=config.filename):
                self.assertEqual(
                    sha256_file(repository_root / config.filename),
                    sha256_file(ML_ROOT / "data" / config.filename),
                )

    def test_target_is_not_in_any_feature_set(self) -> None:
        for config in self.configs.values():
            for feature_set, features in config.feature_sets.items():
                with self.subTest(disease=config.disease, feature_set=feature_set):
                    self.assertNotIn(config.target, features)

    def test_pima_invalid_zero_normalization_is_feature_specific(self) -> None:
        transformer = ZeroSentinelToNaN(("Glucose", "BMI"))
        frame = pd.DataFrame(
            {"Pregnancies": [0, 2], "Glucose": [0, 120], "BMI": [0.0, 31.2]}
        )
        transformed = transformer.fit_transform(frame)
        self.assertEqual(transformed.loc[0, "Pregnancies"], 0)
        self.assertTrue(np.isnan(transformed.loc[0, "Glucose"]))
        self.assertTrue(np.isnan(transformed.loc[0, "BMI"]))
        self.assertEqual(transformed.loc[1, "Glucose"], 120)

    def test_missing_required_column_is_rejected(self) -> None:
        config = self.configs["diabetes"]
        frame = pd.read_csv(ML_ROOT / "data" / config.filename).drop(
            columns=["Glucose"]
        )
        with self._temporary_dataset(config.filename, frame) as data_dir:
            with self.assertRaisesRegex(ValueError, "schema mismatch"):
                load_and_validate_dataset(config, data_dir, enforce_approved_hash=False)

    def test_non_numeric_marker_is_rejected(self) -> None:
        config = self.configs["heart"]
        frame = pd.read_csv(ML_ROOT / "data" / config.filename)
        frame["trestbps"] = frame["trestbps"].astype(object)
        frame.loc[0, "trestbps"] = "?"
        with self._temporary_dataset(config.filename, frame) as data_dir:
            with self.assertRaisesRegex(ValueError, "must contain only numeric"):
                load_and_validate_dataset(config, data_dir, enforce_approved_hash=False)

    def test_invalid_target_is_rejected(self) -> None:
        config = self.configs["diabetes"]
        frame = pd.read_csv(ML_ROOT / "data" / config.filename)
        frame.loc[0, config.target] = 2
        with self._temporary_dataset(config.filename, frame) as data_dir:
            with self.assertRaisesRegex(ValueError, "target must contain exactly"):
                load_and_validate_dataset(config, data_dir, enforce_approved_hash=False)

    def test_invalid_categorical_value_is_rejected(self) -> None:
        config = self.configs["heart"]
        frame = pd.read_csv(ML_ROOT / "data" / config.filename)
        frame.loc[0, "cp"] = 9
        with self._temporary_dataset(config.filename, frame) as data_dir:
            with self.assertRaisesRegex(ValueError, "unsupported values"):
                load_and_validate_dataset(config, data_dir, enforce_approved_hash=False)

    def test_duplicate_predictor_rows_are_rejected(self) -> None:
        config = self.configs["heart"]
        frame = pd.read_csv(ML_ROOT / "data" / config.filename)
        predictors = [column for column in frame.columns if column != config.target]
        frame.loc[frame.index[-1], predictors] = frame.loc[frame.index[0], predictors]
        frame.loc[frame.index[-1], config.target] = 1 - int(frame.loc[0, config.target])
        with self._temporary_dataset(config.filename, frame) as data_dir:
            with self.assertRaisesRegex(ValueError, "duplicated predictors"):
                load_and_validate_dataset(config, data_dir, enforce_approved_hash=False)

    def test_changed_approved_file_hash_is_rejected_first(self) -> None:
        config = self.configs["diabetes"]
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            destination = data_dir / config.filename
            shutil.copyfile(ML_ROOT / "data" / config.filename, destination)
            content = destination.read_bytes()
            destination.write_bytes(content + b"\n")
            with self.assertRaisesRegex(ValueError, "hash differs"):
                load_and_validate_dataset(config, data_dir)

    from contextlib import contextmanager

    @contextmanager
    def _temporary_dataset(self, filename: str, frame: pd.DataFrame):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            frame.to_csv(data_dir / filename, index=False)
            yield data_dir


if __name__ == "__main__":
    unittest.main()
