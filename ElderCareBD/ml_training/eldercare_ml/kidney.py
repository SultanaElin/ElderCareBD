"""Task 13C kidney-dataset audit and leakage-safe research utilities.

The local CSV is immutable and hash-locked.  This module deliberately separates
research comparisons from deployment: the source does not document how its target
was obtained, and a fitted estimator is not evidence that the target is clinical.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .contracts import CV_FOLDS, RANDOM_SEED
from .modeling import ExactSchemaSelector


KIDNEY_FILENAME = "kidney_disease_dataset.csv"
KIDNEY_SHA256 = "4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199"
KIDNEY_FILE_BYTES = 5_483_328
KIDNEY_ROWS = 20_538
TARGET_COLUMN = "Target"

KIDNEY_COLUMNS = (
    "Age of the patient",
    "Blood pressure (mm/Hg)",
    "Specific gravity of urine",
    "Albumin in urine",
    "Sugar in urine",
    "Red blood cells in urine",
    "Pus cells in urine",
    "Pus cell clumps in urine",
    "Bacteria in urine",
    "Random blood glucose level (mg/dl)",
    "Blood urea (mg/dl)",
    "Serum creatinine (mg/dl)",
    "Sodium level (mEq/L)",
    "Potassium level (mEq/L)",
    "Hemoglobin level (gms)",
    "Packed cell volume (%)",
    "White blood cell count (cells/cumm)",
    "Red blood cell count (millions/cumm)",
    "Hypertension (yes/no)",
    "Diabetes mellitus (yes/no)",
    "Coronary artery disease (yes/no)",
    "Appetite (good/poor)",
    "Pedal edema (yes/no)",
    "Anemia (yes/no)",
    "Estimated Glomerular Filtration Rate (eGFR)",
    "Urine protein-to-creatinine ratio",
    "Urine output (ml/day)",
    "Serum albumin level",
    "Cholesterol level",
    "Parathyroid hormone (PTH) level",
    "Serum calcium level",
    "Serum phosphate level",
    "Family history of chronic kidney disease",
    "Smoking status",
    "Body Mass Index (BMI)",
    "Physical activity level",
    "Duration of diabetes mellitus (years)",
    "Duration of hypertension (years)",
    "Cystatin C level",
    "Urinary sediment microscopy results",
    "C-reactive protein (CRP) level",
    "Interleukin-6 (IL-6) level",
    TARGET_COLUMN,
)

NUMERIC_FEATURES = (
    "Age of the patient",
    "Blood pressure (mm/Hg)",
    "Specific gravity of urine",
    "Albumin in urine",
    "Sugar in urine",
    "Random blood glucose level (mg/dl)",
    "Blood urea (mg/dl)",
    "Serum creatinine (mg/dl)",
    "Sodium level (mEq/L)",
    "Potassium level (mEq/L)",
    "Hemoglobin level (gms)",
    "Packed cell volume (%)",
    "White blood cell count (cells/cumm)",
    "Red blood cell count (millions/cumm)",
    "Estimated Glomerular Filtration Rate (eGFR)",
    "Urine protein-to-creatinine ratio",
    "Urine output (ml/day)",
    "Serum albumin level",
    "Cholesterol level",
    "Parathyroid hormone (PTH) level",
    "Serum calcium level",
    "Serum phosphate level",
    "Body Mass Index (BMI)",
    "Duration of diabetes mellitus (years)",
    "Duration of hypertension (years)",
    "Cystatin C level",
    "C-reactive protein (CRP) level",
    "Interleukin-6 (IL-6) level",
)

CATEGORY_VALUES: dict[str, tuple[str, ...]] = {
    "Red blood cells in urine": ("normal", "abnormal"),
    "Pus cells in urine": ("normal", "abnormal"),
    "Pus cell clumps in urine": ("not present", "present"),
    "Bacteria in urine": ("not present", "present"),
    "Hypertension (yes/no)": ("no", "yes"),
    "Diabetes mellitus (yes/no)": ("no", "yes"),
    "Coronary artery disease (yes/no)": ("no", "yes"),
    "Appetite (good/poor)": ("good", "poor"),
    "Pedal edema (yes/no)": ("no", "yes"),
    "Anemia (yes/no)": ("no", "yes"),
    "Family history of chronic kidney disease": ("no", "yes"),
    "Smoking status": ("no", "yes"),
    "Physical activity level": ("low", "moderate", "high"),
    "Urinary sediment microscopy results": ("normal", "abnormal"),
}
CATEGORICAL_FEATURES = tuple(CATEGORY_VALUES)

TARGET_CLASSES = (
    "No_Disease",
    "Low_Risk",
    "Moderate_Risk",
    "High_Risk",
    "Severe_Disease",
)
TARGET_MAPPING = {label: index for index, label in enumerate(TARGET_CLASSES)}
TARGET_LABELS = {index: label for label, index in TARGET_MAPPING.items()}

RENAL_AND_LAB_FEATURES = (
    "Specific gravity of urine",
    "Albumin in urine",
    "Sugar in urine",
    "Red blood cells in urine",
    "Pus cells in urine",
    "Pus cell clumps in urine",
    "Bacteria in urine",
    "Random blood glucose level (mg/dl)",
    "Blood urea (mg/dl)",
    "Serum creatinine (mg/dl)",
    "Sodium level (mEq/L)",
    "Potassium level (mEq/L)",
    "Hemoglobin level (gms)",
    "Packed cell volume (%)",
    "White blood cell count (cells/cumm)",
    "Red blood cell count (millions/cumm)",
    "Estimated Glomerular Filtration Rate (eGFR)",
    "Urine protein-to-creatinine ratio",
    "Urine output (ml/day)",
    "Serum albumin level",
    "Cholesterol level",
    "Parathyroid hormone (PTH) level",
    "Serum calcium level",
    "Serum phosphate level",
    "Cystatin C level",
    "Urinary sediment microscopy results",
    "C-reactive protein (CRP) level",
    "Interleukin-6 (IL-6) level",
)

BIOMARKER_EXCLUDED_FEATURES = tuple(
    feature
    for feature in KIDNEY_COLUMNS[:-1]
    if feature not in RENAL_AND_LAB_FEATURES
)

ELDERCARE_NON_LAB_FEATURES = (
    "Age of the patient",
    "Blood pressure (mm/Hg)",
    "Hypertension (yes/no)",
    "Diabetes mellitus (yes/no)",
    "Coronary artery disease (yes/no)",
    "Appetite (good/poor)",
    "Pedal edema (yes/no)",
    "Anemia (yes/no)",
    "Family history of chronic kidney disease",
    "Smoking status",
    "Body Mass Index (BMI)",
    "Physical activity level",
)

COMPACT_HOME_FEATURES = (
    "Age of the patient",
    "Blood pressure (mm/Hg)",
    "Hypertension (yes/no)",
    "Diabetes mellitus (yes/no)",
    "Family history of chronic kidney disease",
    "Smoking status",
    "Body Mass Index (BMI)",
)

FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "full_42": KIDNEY_COLUMNS[:-1],
    "biomarker_excluded_14": BIOMARKER_EXCLUDED_FEATURES,
    "eldercare_non_lab_12": ELDERCARE_NON_LAB_FEATURES,
    "compact_home_7": COMPACT_HOME_FEATURES,
}


@dataclass(frozen=True)
class KidneyCandidate:
    key: str
    display_name: str
    class_weight: str | None


KIDNEY_CANDIDATES = (
    KidneyCandidate("logistic_regression", "Logistic Regression", None),
    KidneyCandidate(
        "logistic_regression_balanced",
        "Logistic Regression (balanced)",
        "balanced",
    ),
    KidneyCandidate(
        "random_forest_balanced",
        "Random Forest (balanced)",
        "balanced_subsample",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_raw_kidney(data_dir: Path) -> pd.DataFrame:
    """Load and strictly validate the untouched authoritative local snapshot."""

    path = data_dir / KIDNEY_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"Required local kidney dataset is missing: {path}")
    actual_hash = sha256_file(path)
    if actual_hash != KIDNEY_SHA256:
        raise ValueError(
            f"Kidney dataset SHA-256 changed: expected {KIDNEY_SHA256}, "
            f"got {actual_hash}."
        )
    if path.stat().st_size != KIDNEY_FILE_BYTES:
        raise ValueError("Kidney dataset byte size differs from the audited snapshot.")

    frame = pd.read_csv(path)
    if tuple(frame.columns) != KIDNEY_COLUMNS:
        raise ValueError("Kidney schema or column order differs from the audit contract.")
    if len(frame) != KIDNEY_ROWS:
        raise ValueError("Kidney row count differs from the audited 20,538-row snapshot.")
    if frame.isna().any().any():
        raise ValueError("Kidney dataset unexpectedly contains missing values.")
    if frame.astype(str).apply(lambda column: column.str.strip().eq("")).any().any():
        raise ValueError("Kidney dataset unexpectedly contains blank values.")
    if frame.duplicated().any():
        raise ValueError("Kidney dataset unexpectedly contains exact duplicate rows.")
    if frame.drop(columns=TARGET_COLUMN).duplicated(keep=False).any():
        raise ValueError("Kidney dataset contains duplicate predictor profiles.")

    for column, expected in CATEGORY_VALUES.items():
        observed = set(frame[column].astype(str).unique())
        if observed != set(expected):
            raise ValueError(
                f"Kidney category values changed for '{column}': {sorted(observed)}."
            )
    if set(frame[TARGET_COLUMN].astype(str).unique()) != set(TARGET_CLASSES):
        raise ValueError("Kidney target classes differ from the audited mapping.")
    numeric = frame.loc[:, list(NUMERIC_FEATURES)].to_numpy(dtype=float)
    if not np.isfinite(numeric).all():
        raise ValueError("Kidney dataset contains non-finite numeric values.")
    return frame


def encoded_targets(raw: pd.DataFrame) -> dict[str, pd.Series]:
    multiclass = raw[TARGET_COLUMN].map(TARGET_MAPPING)
    if multiclass.isna().any():
        raise ValueError("Kidney target contains an unsupported value.")
    return {
        "original_five_class": multiclass.astype(int),
        "binary_any_non_no_disease": raw[TARGET_COLUMN]
        .ne("No_Disease")
        .astype(int),
        "binary_moderate_high_or_severe": raw[TARGET_COLUMN]
        .isin(("Moderate_Risk", "High_Risk", "Severe_Disease"))
        .astype(int),
    }


def _numeric_summary(series: pd.Series) -> dict[str, float]:
    return {
        "minimum": float(series.min()),
        "q1": float(series.quantile(0.25)),
        "median": float(series.median()),
        "q3": float(series.quantile(0.75)),
        "maximum": float(series.max()),
        "mean": float(series.mean()),
        "standard_deviation": float(series.std(ddof=1)),
    }


def suspicious_value_counts(raw: pd.DataFrame) -> dict[str, int]:
    diabetes = raw["Diabetes mellitus (yes/no)"]
    diabetes_duration = raw["Duration of diabetes mellitus (years)"]
    hypertension = raw["Hypertension (yes/no)"]
    hypertension_duration = raw["Duration of hypertension (years)"]
    age = raw["Age of the patient"]
    target = raw[TARGET_COLUMN]
    egfr = raw["Estimated Glomerular Filtration Rate (eGFR)"]
    creatinine = raw["Serum creatinine (mg/dl)"]
    upcr = raw["Urine protein-to-creatinine ratio"]
    return {
        "age_below_18": int((age < 18).sum()),
        "diabetes_no_but_duration_positive": int(
            ((diabetes == "no") & (diabetes_duration > 0)).sum()
        ),
        "diabetes_yes_but_duration_zero": int(
            ((diabetes == "yes") & (diabetes_duration == 0)).sum()
        ),
        "diabetes_duration_exceeds_age": int((diabetes_duration > age).sum()),
        "hypertension_no_but_duration_positive": int(
            ((hypertension == "no") & (hypertension_duration > 0)).sum()
        ),
        "hypertension_yes_but_duration_zero": int(
            ((hypertension == "yes") & (hypertension_duration == 0)).sum()
        ),
        "hypertension_duration_exceeds_age": int(
            (hypertension_duration > age).sum()
        ),
        "no_disease_with_egfr_below_15": int(
            ((target == "No_Disease") & (egfr < 15)).sum()
        ),
        "severe_disease_with_egfr_at_least_90": int(
            ((target == "Severe_Disease") & (egfr >= 90)).sum()
        ),
        "no_disease_with_creatinine_above_10": int(
            ((target == "No_Disease") & (creatinine > 10)).sum()
        ),
        "no_disease_with_upcr_above_3": int(
            ((target == "No_Disease") & (upcr > 3)).sum()
        ),
    }


def dataset_audit(raw: pd.DataFrame, path: Path) -> dict[str, Any]:
    target_counts = raw[TARGET_COLUMN].value_counts()
    blank_cells = int(
        raw.astype(str).apply(lambda column: column.str.strip().eq("")).sum().sum()
    )
    numeric = raw.loc[:, list(NUMERIC_FEATURES)].to_numpy(dtype=float)
    return {
        "local_filename": KIDNEY_FILENAME,
        "local_path": "data/kidney_disease_dataset.csv",
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": len(raw),
        "columns_count": len(raw.columns),
        "predictor_count": len(raw.columns) - 1,
        "columns": list(raw.columns),
        "target_column": TARGET_COLUMN,
        "target_classes": list(TARGET_CLASSES),
        "target_distribution": {
            label: {
                "count": int(target_counts[label]),
                "fraction": float(target_counts[label] / len(raw)),
            }
            for label in TARGET_CLASSES
        },
        "parsed_dtypes": {name: str(dtype) for name, dtype in raw.dtypes.items()},
        "feature_types": {
            "numeric": list(NUMERIC_FEATURES),
            "categorical": list(CATEGORICAL_FEATURES),
        },
        "categorical_mappings_for_research_models": {
            name: {value: index for index, value in enumerate(values)}
            for name, values in CATEGORY_VALUES.items()
        },
        "target_mapping_for_research_models": TARGET_MAPPING,
        "missing_cells": int(raw.isna().sum().sum()),
        "blank_cells": blank_cells,
        "non_finite_numeric_cells": int((~np.isfinite(numeric)).sum()),
        "exact_duplicate_rows": int(raw.duplicated().sum()),
        "duplicate_predictor_profiles": int(
            raw.drop(columns=TARGET_COLUMN).duplicated(keep=False).sum()
        ),
        "numeric_summary": {
            column: _numeric_summary(raw[column]) for column in NUMERIC_FEATURES
        },
        "category_counts": {
            column: {
                str(label): int(count)
                for label, count in raw[column].value_counts().sort_index().items()
            }
            for column in CATEGORICAL_FEATURES
        },
        "suspicious_or_incoherent_values": suspicious_value_counts(raw),
        "age_subgroups": {
            "age_60_or_older": int((raw["Age of the patient"] >= 60).sum()),
            "age_65_or_older": int((raw["Age of the patient"] >= 65).sum()),
        },
    }


def _cramers_v(table: pd.DataFrame) -> dict[str, float]:
    chi_square, p_value, _, _ = chi2_contingency(table, correction=False)
    observations = float(table.to_numpy().sum())
    denominator = max(1, min(table.shape[0] - 1, table.shape[1] - 1))
    return {
        "chi_square": float(chi_square),
        "p_value": float(p_value),
        "cramers_v": float(np.sqrt((chi_square / observations) / denominator)),
    }


def target_construction_audit(raw: pd.DataFrame) -> dict[str, Any]:
    egfr = raw["Estimated Glomerular Filtration Rate (eGFR)"]
    egfr_band = pd.cut(
        egfr,
        bins=[-np.inf, 15, 30, 45, 60, 90, np.inf],
        labels=["G5_<15", "G4_15-29", "G3b_30-44", "G3a_45-59", "G2_60-89", "G1_>=90"],
        right=False,
    )
    egfr_table = pd.crosstab(egfr_band, raw[TARGET_COLUMN]).reindex(
        columns=TARGET_CLASSES, fill_value=0
    )
    class_means = (
        raw.groupby(TARGET_COLUMN, observed=True)[
            [
                "Estimated Glomerular Filtration Rate (eGFR)",
                "Serum creatinine (mg/dl)",
                "Blood urea (mg/dl)",
                "Urine protein-to-creatinine ratio",
                "Cystatin C level",
            ]
        ]
        .mean()
        .reindex(TARGET_CLASSES)
    )
    correlations = raw[
        [
            "Estimated Glomerular Filtration Rate (eGFR)",
            "Serum creatinine (mg/dl)",
            "Age of the patient",
            "Cystatin C level",
            "Urine protein-to-creatinine ratio",
        ]
    ].corr()
    target_counts = raw[TARGET_COLUMN].value_counts()
    return {
        "clinical_or_independent_label_documentation_found": False,
        "target_name": TARGET_COLUMN,
        "observed_labels": list(TARGET_CLASSES),
        "observed_class_fractions": {
            label: float(target_counts[label] / len(raw)) for label in TARGET_CLASSES
        },
        "what_the_labels_mean": (
            "Unverified. The source page names the labels but supplies no diagnostic "
            "criteria, adjudication protocol, outcome horizon, or construction rules."
        ),
        "ckd_stage_status": (
            "The five labels are not KDIGO GFR stages or CGA classes and must not be "
            "presented as clinical CKD stages."
        ),
        "temporal_status": (
            "No dates, repeated measurements, follow-up period, or event horizon are "
            "present, so neither CKD chronicity nor future-risk semantics can be shown."
        ),
        "mechanical_derivation_finding": (
            "The labels do not behave as if mechanically derived from eGFR, creatinine, "
            "UPCR, cystatin C, or the other supplied predictors. This avoids evidence of "
            "simple circular rules but does not validate the target; it instead exposes "
            "a clinically incoherent, unexplained label process."
        ),
        "egfr_band_by_target_counts": {
            str(index): {label: int(value) for label, value in row.items()}
            for index, row in egfr_table.iterrows()
        },
        "egfr_band_target_association": _cramers_v(egfr_table),
        "renal_biomarker_means_by_target": {
            str(index): {name: float(value) for name, value in row.items()}
            for index, row in class_means.iterrows()
        },
        "selected_clinical_correlations": {
            "egfr_vs_serum_creatinine": float(
                correlations.loc[
                    "Estimated Glomerular Filtration Rate (eGFR)",
                    "Serum creatinine (mg/dl)",
                ]
            ),
            "egfr_vs_age": float(
                correlations.loc[
                    "Estimated Glomerular Filtration Rate (eGFR)",
                    "Age of the patient",
                ]
            ),
            "egfr_vs_cystatin_c": float(
                correlations.loc[
                    "Estimated Glomerular Filtration Rate (eGFR)",
                    "Cystatin C level",
                ]
            ),
            "egfr_vs_upcr": float(
                correlations.loc[
                    "Estimated Glomerular Filtration Rate (eGFR)",
                    "Urine protein-to-creatinine ratio",
                ]
            ),
        },
        "internal_incoherence_counts": suspicious_value_counts(raw),
        "synthetic_or_simulated_assessment": (
            "Unverified but strongly suspected. Independently uniform-looking fields, "
            "near-balanced random categories, fixed-looking class proportions, weak "
            "clinical correlations, and many logical contradictions are collectively "
            "consistent with independently simulated predictors and labels. No generator "
            "or source record was found, so this is an evidence-based inference, not a "
            "claim of known generation methodology."
        ),
        "fitness_conclusion": (
            "The target cannot be justified as an independently observed CKD diagnosis, "
            "stage, severity, or prospective outcome. It is unsuitable for clinical or "
            "ElderCareBD research/demo disease screening."
        ),
    }


def cleaning_decisions(raw: pd.DataFrame) -> list[dict[str, Any]]:
    counts = suspicious_value_counts(raw)
    return [
        {
            "pattern": "explicit missing, blank, or non-finite values",
            "count": int(raw.isna().sum().sum()),
            "classification": "clearly invalid if present",
            "decision": "none present; no imputation is activated by the audited CSV",
        },
        {
            "pattern": "age below 18 years",
            "count": counts["age_below_18"],
            "classification": "valid pediatric age but outside adult/elderly scope",
            "decision": "retain for source audit; exclude only by declared subgroup analysis",
        },
        {
            "pattern": "diabetes=no with positive diabetes duration",
            "count": counts["diabetes_no_but_duration_positive"],
            "classification": "likely invalid paired history",
            "decision": "retain in full research baseline; exclude duration from reduced contracts",
        },
        {
            "pattern": "diabetes=yes with zero diabetes duration",
            "count": counts["diabetes_yes_but_duration_zero"],
            "classification": "unknown (new diagnosis possible)",
            "decision": "retain; do not invent duration",
        },
        {
            "pattern": "diabetes duration greater than age",
            "count": counts["diabetes_duration_exceeds_age"],
            "classification": "clearly invalid",
            "decision": "retain only to expose source quality; exclude duration from reduced contracts",
        },
        {
            "pattern": "hypertension=no with positive hypertension duration",
            "count": counts["hypertension_no_but_duration_positive"],
            "classification": "likely invalid paired history",
            "decision": "retain in full research baseline; exclude duration from reduced contracts",
        },
        {
            "pattern": "hypertension=yes with zero hypertension duration",
            "count": counts["hypertension_yes_but_duration_zero"],
            "classification": "unknown (new diagnosis possible)",
            "decision": "retain; do not invent duration",
        },
        {
            "pattern": "hypertension duration greater than age",
            "count": counts["hypertension_duration_exceeds_age"],
            "classification": "clearly invalid",
            "decision": "retain only to expose source quality; exclude duration from reduced contracts",
        },
        {
            "pattern": "No_Disease label with eGFR below 15",
            "count": counts["no_disease_with_egfr_below_15"],
            "classification": "clinically discordant; target semantics unknown",
            "decision": "do not relabel or delete; treat as target-validity evidence",
        },
        {
            "pattern": "Severe_Disease label with eGFR at least 90",
            "count": counts["severe_disease_with_egfr_at_least_90"],
            "classification": "discordant with any simple eGFR severity interpretation",
            "decision": "do not relabel or delete; treat as target-validity evidence",
        },
        {
            "pattern": "No_Disease label with serum creatinine above 10 mg/dl",
            "count": counts["no_disease_with_creatinine_above_10"],
            "classification": "clinically discordant or unit/source error",
            "decision": "do not relabel or delete; target and provenance are unverified",
        },
        {
            "pattern": "all individually bounded numeric values",
            "count": len(raw) * len(NUMERIC_FEATURES),
            "classification": "mostly plausible ranges; distribution shape suspicious",
            "decision": "preserve exactly; no value clipping, row deletion, or cleaned copy",
        },
    ]


def feature_compatibility_rows() -> list[dict[str, str]]:
    """Return one deployment-burden row for every source predictor."""

    home_measurements = {
        "Age of the patient": ("yes (profile/assessment)", "yes", "self/report", "no", "no"),
        "Blood pressure (mm/Hg)": ("partial; systolic and diastolic are separate", "yes", "BP cuff", "no", "no"),
        "Body Mass Index (BMI)": ("yes (derived from height and weight)", "yes", "scale and height", "no", "no"),
    }
    self_report = {
        "Hypertension (yes/no)": "yes (history)",
        "Diabetes mellitus (yes/no)": "yes (history)",
        "Coronary artery disease (yes/no)": "partial; heart-disease history is not exact CAD",
        "Appetite (good/poor)": "no structured field",
        "Pedal edema (yes/no)": "no structured field",
        "Anemia (yes/no)": "no structured field",
        "Family history of chronic kidney disease": "no structured field",
        "Smoking status": "no structured field",
        "Physical activity level": "no structured field",
        "Duration of diabetes mellitus (years)": "no structured field",
        "Duration of hypertension (years)": "no structured field",
    }
    specialist_features = {
        "Red blood cells in urine",
        "Pus cells in urine",
        "Pus cell clumps in urine",
        "Bacteria in urine",
        "Urinary sediment microscopy results",
    }
    target_defining_candidates = {
        "Albumin in urine",
        "Serum creatinine (mg/dl)",
        "Estimated Glomerular Filtration Rate (eGFR)",
        "Urine protein-to-creatinine ratio",
        "Cystatin C level",
        "Urinary sediment microscopy results",
    }

    rows: list[dict[str, str]] = []
    for feature in KIDNEY_COLUMNS[:-1]:
        if feature in home_measurements:
            current, caregiver, home, lab, specialist = home_measurements[feature]
            role = (
                "no current deployment; potential home-contract candidate only "
                "after a valid target/source"
            )
        elif feature in self_report:
            current = self_report[feature]
            caregiver = "yes, with an explicit definition"
            home = "self/history report"
            lab = "no"
            specialist = "no"
            role = (
                "no current deployment; potential non-lab candidate only after a "
                "valid target/source"
            )
        else:
            current = "no"
            caregiver = "only by transcribing a documented result"
            home = "no"
            lab = "yes"
            specialist = "yes" if feature in specialist_features else "usually clinician/lab context"
            role = (
                "no current deployment; research baseline only; exclude from mobile "
                "home screening"
            )
        leakage = (
            "high if used to construct the label; construction is undocumented"
            if feature in target_defining_candidates
            else "unknown because label construction and measurement timing are undocumented"
        )
        reason = (
            "No predictor can be deployed from this source under Outcome C. "
            + (
                "The field is burdensome and may be circular."
                if feature in RENAL_AND_LAB_FEATURES
                else "The field itself is feasible, but the dataset does not validate its use."
            )
        )
        rows.append(
            {
                "feature": feature,
                "available_in_dataset": "yes",
                "currently_available_in_eldercarebd": current,
                "caregiver_can_reasonably_provide": caregiver,
                "home_measurement_possible": home,
                "requires_laboratory_test": lab,
                "requires_specialist_interpretation": specialist,
                "leakage_concern": leakage,
                "deployment_decision": role,
                "reason": reason,
            }
        )
    return rows


def build_kidney_pipeline(
    features: tuple[str, ...],
    candidate_key: str,
) -> Pipeline:
    candidate = next(
        (item for item in KIDNEY_CANDIDATES if item.key == candidate_key), None
    )
    if candidate is None:
        raise ValueError(f"Unknown kidney candidate: {candidate_key}")
    unknown = set(features) - set(NUMERIC_FEATURES) - set(CATEGORICAL_FEATURES)
    if unknown:
        raise ValueError(f"Kidney features lack preprocessing: {sorted(unknown)}")

    numeric = [name for name in features if name in NUMERIC_FEATURES]
    categorical = [name for name in features if name in CATEGORICAL_FEATURES]
    numeric_steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy="median"))
    ]
    if candidate_key.startswith("logistic_regression"):
        numeric_steps.append(("scaler", StandardScaler()))
    transformers: list[tuple[str, Any, list[str]]] = []
    if numeric:
        transformers.append(("numeric", Pipeline(numeric_steps), numeric))
    if categorical:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "one_hot",
                            OneHotEncoder(
                                categories=[list(CATEGORY_VALUES[name]) for name in categorical],
                                handle_unknown="error",
                                sparse_output=False,
                            ),
                        ),
                    ]
                ),
                categorical,
            )
        )
    preprocessor = ColumnTransformer(
        transformers=transformers,
        remainder="drop",
        sparse_threshold=0.0,
        verbose_feature_names_out=True,
    )

    if candidate_key.startswith("logistic_regression"):
        classifier: Any = LogisticRegression(
            max_iter=2_000,
            solver="lbfgs",
            class_weight=candidate.class_weight,
            random_state=RANDOM_SEED,
        )
    else:
        classifier = RandomForestClassifier(
            n_estimators=120,
            max_depth=12,
            min_samples_split=10,
            min_samples_leaf=5,
            max_features="sqrt",
            class_weight=candidate.class_weight,
            random_state=RANDOM_SEED,
            n_jobs=1,
        )
    return Pipeline(
        [
            ("schema", ExactSchemaSelector(features)),
            ("preprocessor", preprocessor),
            ("classifier", classifier),
        ]
    )


def calibration_diagnostic(
    y_true: np.ndarray,
    probability: np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, Any]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    indices = np.clip(np.digitize(probability, edges[1:-1]), 0, bins - 1)
    rows: list[dict[str, float | int]] = []
    expected_calibration_error = 0.0
    for index in range(bins):
        mask = indices == index
        count = int(mask.sum())
        if count == 0:
            continue
        mean_score = float(probability[mask].mean())
        observed = float(y_true[mask].mean())
        expected_calibration_error += count / len(y_true) * abs(mean_score - observed)
        rows.append(
            {
                "bin_lower": float(edges[index]),
                "bin_upper": float(edges[index + 1]),
                "count": count,
                "mean_score": mean_score,
                "observed_positive_fraction": observed,
            }
        )
    return {
        "method": "10 fixed-width bins",
        "expected_calibration_error": float(expected_calibration_error),
        "bins": rows,
        "interpretation": (
            "Negative-control internal diagnostic only. Unverified labels make these "
            "scores unsuitable as personal kidney-disease probabilities."
        ),
    }


MULTICLASS_METRICS = (
    "accuracy",
    "balanced_accuracy",
    "macro_precision",
    "macro_recall",
    "macro_f1",
    "weighted_f1",
    "multiclass_roc_auc_ovr_macro",
    "log_loss",
)
BINARY_METRICS = (
    "accuracy",
    "balanced_accuracy",
    "precision",
    "recall",
    "specificity",
    "f1",
    "roc_auc",
    "pr_auc_average_precision",
    "brier_score",
    "log_loss",
)


def multiclass_metrics(
    y_true: np.ndarray,
    predicted: np.ndarray,
    probability: np.ndarray,
) -> dict[str, Any]:
    labels = np.arange(len(TARGET_CLASSES))
    per_class = recall_score(
        y_true, predicted, labels=labels, average=None, zero_division=0
    )
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "macro_precision": float(
            precision_score(y_true, predicted, average="macro", zero_division=0)
        ),
        "macro_recall": float(
            recall_score(y_true, predicted, average="macro", zero_division=0)
        ),
        "macro_f1": float(
            f1_score(y_true, predicted, average="macro", zero_division=0)
        ),
        "weighted_f1": float(
            f1_score(y_true, predicted, average="weighted", zero_division=0)
        ),
        "multiclass_roc_auc_ovr_macro": float(
            roc_auc_score(
                y_true,
                probability,
                labels=labels,
                multi_class="ovr",
                average="macro",
            )
        ),
        "log_loss": float(log_loss(y_true, probability, labels=labels)),
        "per_class_recall": {
            TARGET_LABELS[index]: float(value)
            for index, value in enumerate(per_class)
        },
    }


def binary_metrics(
    y_true: np.ndarray,
    predicted: np.ndarray,
    probability: np.ndarray,
) -> dict[str, float]:
    matrix = confusion_matrix(y_true, predicted, labels=[0, 1])
    true_negative, false_positive, _, _ = matrix.ravel()
    specificity = true_negative / max(1, true_negative + false_positive)
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, predicted)),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "specificity": float(specificity),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "pr_auc_average_precision": float(
            average_precision_score(y_true, probability)
        ),
        "brier_score": float(brier_score_loss(y_true, probability)),
        "log_loss": float(log_loss(y_true, probability, labels=[0, 1])),
    }


def _fold_summary(
    fold_rows: list[dict[str, Any]], metrics: tuple[str, ...]
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for metric in metrics:
        values = np.asarray([row[metric] for row in fold_rows], dtype=float)
        summary[metric] = {
            "mean": float(values.mean()),
            "std": float(values.std(ddof=0)),
            "fold_values": values.tolist(),
        }
    return summary


def evaluate_multiclass(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
) -> dict[str, Any]:
    splitter = StratifiedKFold(
        n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED
    )
    probability = np.full((len(y), len(TARGET_CLASSES)), np.nan, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    for fold, (train, validation) in enumerate(splitter.split(X, y), start=1):
        fitted = clone(pipeline)
        fitted.fit(X.iloc[train], y.iloc[train])
        fold_probability = fitted.predict_proba(X.iloc[validation])
        classes = fitted.named_steps["classifier"].classes_.astype(int)
        aligned = np.zeros((len(validation), len(TARGET_CLASSES)), dtype=float)
        aligned[:, classes] = fold_probability
        probability[validation] = aligned
        predicted = aligned.argmax(axis=1)
        fold_rows.append(
            {
                "fold": fold,
                **multiclass_metrics(
                    y.iloc[validation].to_numpy(), predicted, aligned
                ),
            }
        )
    if np.isnan(probability).any():
        raise RuntimeError("Multiclass cross-validation did not score every row.")
    predicted = probability.argmax(axis=1)
    return {
        "folds": CV_FOLDS,
        "random_seed": RANDOM_SEED,
        "fold_metrics": fold_rows,
        "cv_summary": _fold_summary(fold_rows, MULTICLASS_METRICS),
        "oof_metrics": multiclass_metrics(y.to_numpy(), predicted, probability),
        "oof_confusion_matrix": confusion_matrix(
            y, predicted, labels=np.arange(len(TARGET_CLASSES))
        )
        .astype(int)
        .tolist(),
        "oof_probabilities": probability,
        "oof_predictions": predicted,
    }


def evaluate_binary(
    pipeline: Pipeline,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    splitter = StratifiedKFold(
        n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED
    )
    probability = np.full(len(y), np.nan, dtype=float)
    fold_rows: list[dict[str, Any]] = []
    for fold, (train, validation) in enumerate(splitter.split(X, y), start=1):
        fitted = clone(pipeline)
        fitted.fit(X.iloc[train], y.iloc[train])
        fold_probability = fitted.predict_proba(X.iloc[validation])[:, 1]
        probability[validation] = fold_probability
        predicted = (fold_probability >= threshold).astype(int)
        fold_rows.append(
            {
                "fold": fold,
                **binary_metrics(
                    y.iloc[validation].to_numpy(), predicted, fold_probability
                ),
            }
        )
    if np.isnan(probability).any():
        raise RuntimeError("Binary cross-validation did not score every row.")
    predicted = (probability >= threshold).astype(int)
    return {
        "folds": CV_FOLDS,
        "random_seed": RANDOM_SEED,
        "threshold": threshold,
        "fold_metrics": fold_rows,
        "cv_summary": _fold_summary(fold_rows, BINARY_METRICS),
        "oof_metrics": binary_metrics(y.to_numpy(), predicted, probability),
        "oof_confusion_matrix": confusion_matrix(y, predicted, labels=[0, 1])
        .astype(int)
        .tolist(),
        "calibration": calibration_diagnostic(y.to_numpy(), probability),
        "observed_positive_prevalence": float(y.mean()),
        "oof_probabilities": probability,
        "oof_predictions": predicted,
    }


def json_ready_evaluation(result: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.tolist() if isinstance(value, np.ndarray) else value
        for key, value in result.items()
        if key not in {"oof_probabilities", "oof_predictions"}
    }


def subgroup_metrics(
    result: dict[str, Any],
    y: pd.Series,
    mask: pd.Series,
    *,
    formulation: str,
) -> dict[str, Any]:
    probability = result["oof_probabilities"][mask.to_numpy()]
    predicted = result["oof_predictions"][mask.to_numpy()]
    observed = y.loc[mask].to_numpy()
    if formulation == "original_five_class":
        metrics = multiclass_metrics(observed, predicted, probability)
        matrix = confusion_matrix(
            observed, predicted, labels=np.arange(len(TARGET_CLASSES))
        )
    else:
        metrics = binary_metrics(observed, predicted, probability)
        matrix = confusion_matrix(observed, predicted, labels=[0, 1])
    return {
        "rows": int(mask.sum()),
        "class_counts": {
            str(label): int(count)
            for label, count in pd.Series(observed).value_counts().sort_index().items()
        },
        "metrics": metrics,
        "confusion_matrix": matrix.astype(int).tolist(),
    }
