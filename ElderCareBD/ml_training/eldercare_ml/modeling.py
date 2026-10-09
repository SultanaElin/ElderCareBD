"""Leakage-safe preprocessing and candidate-model construction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import DatasetConfig, RANDOM_SEED


class ExactSchemaSelector(BaseEstimator, TransformerMixin):
    """Require an exact feature set and preserve its declared order."""

    def __init__(self, required_features: tuple[str, ...]):
        self.required_features = required_features

    def fit(self, X: pd.DataFrame, y: object = None) -> "ExactSchemaSelector":
        self._validate(X)
        self.feature_names_in_ = np.asarray(self.required_features, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        self._validate(X)
        return X.loc[:, list(self.required_features)].copy()

    def get_feature_names_out(self, input_features: object = None) -> np.ndarray:
        del input_features
        return np.asarray(self.required_features, dtype=object)

    def _validate(self, X: pd.DataFrame) -> None:
        if not isinstance(X, pd.DataFrame):
            raise TypeError("Model input must be a pandas DataFrame with named columns.")
        expected = set(self.required_features)
        actual = set(X.columns)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            raise ValueError(f"Missing required features: {missing}")
        if unexpected:
            raise ValueError(f"Unexpected features: {unexpected}")


class ZeroSentinelToNaN(BaseEstimator, TransformerMixin):
    """Convert dataset-defined impossible zeros to missing values inside each fold."""

    def __init__(self, columns: tuple[str, ...]):
        self.columns = columns

    def fit(self, X: pd.DataFrame, y: object = None) -> "ZeroSentinelToNaN":
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        transformed = X.copy()
        present = [column for column in self.columns if column in transformed.columns]
        for column in present:
            # pandas 3 rejects assigning NaN into an integer block. Cast only the
            # documented sentinel columns so valid integer fields keep their type.
            numeric = transformed[column].astype(float)
            transformed[column] = numeric.mask(numeric == 0, np.nan)
        return transformed

    def get_feature_names_out(self, input_features: object = None) -> np.ndarray:
        if input_features is None:
            return self.feature_names_in_
        return np.asarray(input_features, dtype=object)


@dataclass(frozen=True)
class CandidateSpec:
    key: str
    display_name: str
    class_weight: str | None


CANDIDATES = (
    CandidateSpec(
        key="logistic_regression",
        display_name="Logistic Regression",
        class_weight=None,
    ),
    CandidateSpec(
        key="logistic_regression_balanced",
        display_name="Logistic Regression (balanced)",
        class_weight="balanced",
    ),
    CandidateSpec(
        key="random_forest_balanced",
        display_name="Random Forest (balanced)",
        class_weight="balanced",
    ),
    CandidateSpec(
        key="neural_network_mlp",
        display_name="Neural Network (MLP, exploratory)",
        class_weight=None,
    ),
)


def build_pipeline(
    config: DatasetConfig,
    features: tuple[str, ...],
    candidate_key: str,
) -> Pipeline:
    """Build an unfitted pipeline containing every learned preprocessing step."""

    candidate = next((item for item in CANDIDATES if item.key == candidate_key), None)
    if candidate is None:
        raise ValueError(f"Unknown candidate model: {candidate_key}")

    numerical = [feature for feature in features if feature in config.numerical_features]
    categorical = [feature for feature in features if feature in config.categorical_values]
    if set(numerical + categorical) != set(features):
        unknown = sorted(set(features) - set(numerical) - set(categorical))
        raise ValueError(f"Features lack preprocessing definitions: {unknown}")

    scale_numeric = candidate.key.startswith("logistic_regression") or (
        candidate.key == "neural_network_mlp"
    )
    numeric_steps: list[tuple[str, object]] = [
        ("imputer", SimpleImputer(strategy="median"))
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    transformers: list[tuple[str, object, list[str]]] = []
    if numerical:
        transformers.append(("numeric", Pipeline(numeric_steps), numerical))
    if categorical:
        categories = [list(config.categorical_values[name]) for name in categorical]
        categorical_pipeline = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="most_frequent")),
                (
                    "one_hot",
                    OneHotEncoder(
                        categories=categories,
                        handle_unknown="error",
                        sparse_output=False,
                    ),
                ),
            ]
        )
        transformers.append(("categorical", categorical_pipeline, categorical))

    preprocessor = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )

    if candidate.key.startswith("logistic_regression"):
        classifier = LogisticRegression(
            max_iter=2000,
            class_weight=candidate.class_weight,
            solver="lbfgs",
            random_state=RANDOM_SEED,
        )
    elif candidate.key == "random_forest_balanced":
        classifier = RandomForestClassifier(
            n_estimators=300,
            max_depth=None,
            min_samples_split=4,
            min_samples_leaf=2,
            max_features="sqrt",
            class_weight=candidate.class_weight,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )
    else:
        classifier = MLPClassifier(
            hidden_layer_sizes=(32, 16),
            activation="relu",
            solver="adam",
            alpha=0.001,
            max_iter=1000,
            early_stopping=True,
            validation_fraction=0.15,
            n_iter_no_change=30,
            random_state=RANDOM_SEED,
        )

    return Pipeline(
        [
            ("schema", ExactSchemaSelector(features)),
            (
                "invalid_zero_to_missing",
                ZeroSentinelToNaN(
                    tuple(
                        feature
                        for feature in config.invalid_zero_features
                        if feature in features
                    )
                ),
            ),
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )
