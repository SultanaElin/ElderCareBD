from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score


ML_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ML_ROOT.parent
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ml_training.eldercare_ml.contracts import (  # noqa: E402
    RANDOM_SEED,
    get_dataset_configs,
)
from ml_training.eldercare_ml.data import load_and_validate_dataset  # noqa: E402
from ml_training.eldercare_ml.evaluation import (  # noqa: E402
    choose_recall_floor_threshold,
    evaluate_candidate,
)
from ml_training.eldercare_ml.modeling import CANDIDATES, build_pipeline  # noqa: E402


class EvaluationReproducibilityTests(unittest.TestCase):
    def test_required_candidate_families_are_defined(self) -> None:
        keys = {candidate.key for candidate in CANDIDATES}
        self.assertIn("logistic_regression", keys)
        self.assertIn("random_forest_balanced", keys)
        self.assertIn("neural_network_mlp", keys)

    def test_probability_based_roc_auc_and_repeated_cv_are_reproducible(self) -> None:
        config = get_dataset_configs()["diabetes"]
        frame, _ = load_and_validate_dataset(config, ML_ROOT / "data")
        features = config.selected_features
        X = frame.loc[:, list(features)]
        y = frame[config.target].astype(int)

        first = evaluate_candidate(
            build_pipeline(config, features, "logistic_regression"), X, y
        )
        second = evaluate_candidate(
            build_pipeline(config, features, "logistic_regression"), X, y
        )
        first_probabilities = np.asarray(first["oof_probabilities"])
        second_probabilities = np.asarray(second["oof_probabilities"])

        np.testing.assert_array_equal(first_probabilities, second_probabilities)
        self.assertEqual(RANDOM_SEED, 42)
        self.assertAlmostEqual(
            first["oof_roc_auc"],
            roc_auc_score(y, first_probabilities),
            places=14,
        )
        self.assertTrue(np.any((first_probabilities > 0) & (first_probabilities < 1)))

    def test_recall_floor_threshold_rule_is_deterministic(self) -> None:
        y = np.asarray([0, 0, 0, 1, 1, 1, 1])
        scores = np.asarray([0.1, 0.2, 0.7, 0.3, 0.4, 0.8, 0.9])
        first = choose_recall_floor_threshold(y, scores, minimum_recall=0.75)
        second = choose_recall_floor_threshold(y, scores, minimum_recall=0.75)
        self.assertEqual(first, second)
        self.assertEqual(first, 0.4)


if __name__ == "__main__":
    unittest.main()
