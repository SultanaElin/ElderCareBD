"""Task 13B DiaBD evaluation, selection, artifact, and report generation."""

from __future__ import annotations

import csv
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_curve, roc_curve

from .artifact import RiskModelArtifact
from .contracts import FeatureSpec, get_dataset_configs
from .data import load_and_validate_dataset
from .diabd import (
    BINARY_FEATURES,
    DIABD_CANDIDATES,
    DIABD_COLUMNS,
    DIABD_FILENAME,
    DIABD_SHA256,
    FEATURE_SETS,
    GENDER_MAPPING,
    PLAUSIBILITY_RANGES,
    build_diabd_pipeline,
    classification_metrics,
    encoded_xy,
    evaluate_candidate,
    evaluate_contiguous_block_sensitivity,
    evaluate_nested_threshold,
    json_ready_evaluation,
    load_raw_diabd,
    prevalence_brier,
    sha256_file,
)
from .diabd_loading import (
    DIABD_ARTIFACT_SHA256,
    DIABD_ARTIFACT_FILENAME,
    DIABD_FEATURE_ORDER,
    DIABD_METADATA_FILENAME,
    DIABD_MODEL_VERSION,
    load_verified_diabd_artifact_bytes,
)
from .evaluation import choose_recall_floor_threshold
from .loading import load_verified_artifact
from .modeling import build_pipeline as build_task13_pipeline


SELECTED_FEATURE_SET = "current_ui_reduced_6"
SELECTED_CANDIDATE = "logistic_regression"
PIMA_V2_ARTIFACT_SHA256 = (
    "2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07"
)
PIMA_DATA_SHA256 = "698C203A14AA31941D2251175330C9199F3CCDB31597ABBBA2A3E35416257A72"
KIDNEY_DATA_SHA256 = "4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199"


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_json(path: Path, value: Any) -> None:
    _write_text(
        path,
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
    )


def _write_text(path: Path, value: str) -> None:
    temporary_path = path.with_name(f".{path.name}.tmp")
    temporary_path.write_text(value, encoding="utf-8")
    temporary_path.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    temporary_path = path.with_name(f".{path.name}.tmp")
    with temporary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary_path.replace(path)


def _dataset_audit(raw: pd.DataFrame) -> dict[str, Any]:
    numeric = [
        "age",
        "pulse_rate",
        "systolic_bp",
        "diastolic_bp",
        "glucose",
        "height",
        "weight",
        "bmi",
    ]
    recomputed = raw["weight"] / raw["height"].pow(2)
    absolute_difference = (raw["bmi"] - recomputed).abs()
    relative_difference = absolute_difference / recomputed.abs()
    target_counts = raw["diabetic"].value_counts()
    summaries: dict[str, dict[str, float]] = {}
    for column in numeric:
        series = raw[column]
        summaries[column] = {
            "minimum": float(series.min()),
            "q1": float(series.quantile(0.25)),
            "median": float(series.median()),
            "q3": float(series.quantile(0.75)),
            "maximum": float(series.max()),
            "mean": float(series.mean()),
            "standard_deviation": float(series.std(ddof=1)),
        }
    return {
        "local_filename": DIABD_FILENAME,
        "local_path": f"data/{DIABD_FILENAME}",
        "sha256": DIABD_SHA256,
        "bytes": 286998,
        "rows": len(raw),
        "columns": list(raw.columns),
        "predictors": list(DIABD_COLUMNS[:-1]),
        "target": "diabetic",
        "target_mapping": {"No": 0, "Yes": 1},
        "target_distribution": {
            "No": int(target_counts["No"]),
            "Yes": int(target_counts["Yes"]),
            "positive_prevalence": float(target_counts["Yes"] / len(raw)),
            "negative_to_positive_ratio": float(
                target_counts["No"] / target_counts["Yes"]
            ),
        },
        "parsed_dtypes": {name: str(dtype) for name, dtype in raw.dtypes.items()},
        "explicit_missing_cells": int(raw.isna().sum().sum()),
        "exact_duplicate_rows": int(raw.duplicated().sum()),
        "duplicate_predictor_rows": int(
            raw.drop(columns="diabetic").duplicated(keep=False).sum()
        ),
        "numeric_summary": summaries,
        "categories": {
            "gender": raw["gender"].value_counts().sort_index().to_dict(),
            **{
                column: {
                    str(int(key)): int(value)
                    for key, value in raw[column].value_counts().sort_index().items()
                }
                for column in BINARY_FEATURES
            },
        },
        "age_counts": {
            "age_60_or_older": int((raw["age"] >= 60).sum()),
            "age_65_or_older": int((raw["age"] >= 65).sum()),
            "age_70_or_older": int((raw["age"] >= 70).sum()),
            "age_75_or_older": int((raw["age"] >= 75).sum()),
        },
        "bmi_recomputation": {
            "formula": "weight_kg / height_m^2",
            "mean_absolute_difference": float(absolute_difference.mean()),
            "median_absolute_difference": float(absolute_difference.median()),
            "p95_absolute_difference": float(absolute_difference.quantile(0.95)),
            "p99_absolute_difference": float(absolute_difference.quantile(0.99)),
            "maximum_absolute_difference": float(absolute_difference.max()),
            "absolute_difference_over_0_25": int((absolute_difference > 0.25).sum()),
            "absolute_difference_over_0_5": int((absolute_difference > 0.5).sum()),
            "within_one_percent": int((relative_difference <= 0.01).sum()),
        },
        "source": {
            "paper": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12221696/",
            "paper_doi": "10.1016/j.dib.2025.111746",
            "distribution": "https://data.mendeley.com/datasets/m8cgwxs9s6/2",
            "distribution_doi": "10.17632/m8cgwxs9s6.2",
            "license": "CC BY 4.0",
            "local_version_identity": (
                "Filename, schema, row count, categories, and published summaries "
                "match; exact byte identity with Mendeley V2/V3 is unverified because "
                "the repository has no source manifest and no external copy was downloaded."
            ),
            "collection": (
                "CHW household screening across 63 urban, semi-urban, and rural "
                "Bangladeshi Unions, 2021-04-10 through 2024-05-27."
            ),
        },
    }


def _cleaning_decisions(raw: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "pattern": "pulse_rate < 30 bpm",
            "count": int((raw["pulse_rate"] < 30).sum()),
            "classification": "clearly invalid",
            "decision": "set affected pulse cells to missing inside pipeline",
        },
        {
            "pattern": "glucose < 1 mmol/L",
            "count": int((raw["glucose"] < 1).sum()),
            "classification": "zero clearly invalid; positive sub-1 likely invalid",
            "decision": "set affected glucose cells to missing; disclose <2 sensitivity",
        },
        {
            "pattern": "glucose 1 to <2 mmol/L",
            "count": int(
                ((raw["glucose"] >= 1) & (raw["glucose"] < 2)).sum()
            ),
            "classification": "unknown; physiologically severe or possible source error",
            "decision": "retain in primary analysis; evaluate <2-to-missing sensitivity",
        },
        {
            "pattern": "height < 1 metre",
            "count": int((raw["height"] < 1).sum()),
            "classification": "0.36 clearly invalid; 0.64/0.99 likely invalid",
            "decision": "set affected height cells to missing inside full baseline",
        },
        {
            "pattern": "weight < 20 kg",
            "count": int((raw["weight"] < 20).sum()),
            "classification": "3 kg clearly invalid for adult cohort",
            "decision": "set affected weight cells to missing inside full baseline",
        },
        {
            "pattern": "weight 20 to <30 kg",
            "count": int(((raw["weight"] >= 20) & (raw["weight"] < 30)).sum()),
            "classification": "plausible extreme",
            "decision": "retain unchanged and document",
        },
        {
            "pattern": "BMI outside 10-80 kg/m^2",
            "count": int(((raw["bmi"] < 10) | (raw["bmi"] > 80)).sum()),
            "classification": "clearly/likely invalid anthropometric combinations",
            "decision": "set affected BMI cells to missing inside pipeline",
        },
        {
            "pattern": "BMI >50 to 80 kg/m^2",
            "count": int(((raw["bmi"] > 50) & (raw["bmi"] <= 80)).sum()),
            "classification": "plausible extreme",
            "decision": "retain unchanged and document",
        },
        {
            "pattern": "pulse 30-39 or >120 bpm",
            "count": int(
                (((raw["pulse_rate"] >= 30) & (raw["pulse_rate"] < 40)) | (
                    raw["pulse_rate"] > 120
                )).sum()
            ),
            "classification": "plausible extreme",
            "decision": "retain unchanged and document",
        },
        {
            "pattern": "systolic BP <80 or >220 mmHg",
            "count": int(
                ((raw["systolic_bp"] < 80) | (raw["systolic_bp"] > 220)).sum()
            ),
            "classification": "plausible extreme",
            "decision": "retain unchanged and document",
        },
        {
            "pattern": "diastolic BP <50 or >110 mmHg",
            "count": int(
                ((raw["diastolic_bp"] < 50) | (raw["diastolic_bp"] > 110)).sum()
            ),
            "classification": "plausible extreme",
            "decision": "retain unchanged and document",
        },
        {
            "pattern": "diastolic BP >= systolic BP",
            "count": int((raw["diastolic_bp"] >= raw["systolic_bp"]).sum()),
            "classification": "invalid paired measurement if present",
            "decision": "none found; future inference adapter must reject",
        },
        {
            "pattern": "glucose >30 mmol/L",
            "count": int((raw["glucose"] > 30).sum()),
            "classification": "plausible severe hyperglycaemia / label discordance unknown",
            "decision": "retain; never relabel target",
        },
        {
            "pattern": "age divisible by five",
            "count": int((raw["age"] % 5 == 0).sum()),
            "classification": "unknown; possible age heaping",
            "decision": "retain and disclose",
        },
    ]


def _compatibility_rows() -> list[dict[str, str]]:
    decisions = {
        "age": ("assessment/profile", "easy", "none", "use"),
        "gender": (
            "profile Male/Female/Other",
            "easy",
            "self-report",
            "use Female/Male only; Other/unknown must fall back",
        ),
        "pulse_rate": ("absent", "possible", "pulse measurement", "full baseline only"),
        "systolic_bp": ("assessment", "reasonable", "BP cuff", "use"),
        "diastolic_bp": ("assessment", "reasonable", "BP cuff", "use"),
        "glucose": (
            "generic integer plus paused OGTT field; neither is equivalent",
            "possible",
            "glucometer",
            "use only as decimal random-session mmol/L with explicit context",
        ),
        "height": ("assessment cm", "reasonable", "measurement", "derive BMI only"),
        "weight": ("assessment kg", "reasonable", "measurement", "derive BMI only"),
        "bmi": ("derived", "easy", "height and weight", "use"),
        "family_diabetes": ("absent", "reportable", "history", "exclude; sparse/inverse"),
        "hypertensive": (
            "profile history",
            "reportable",
            "diagnosis",
            "exclude; timing/proxy leakage unresolved",
        ),
        "family_hypertension": ("absent", "reportable", "history", "exclude"),
        "cardiovascular_disease": (
            "heart history is not exact CVD",
            "reportable",
            "diagnosis",
            "exclude; sparse/downstream risk",
        ),
        "stroke": ("profile history", "reportable", "diagnosis", "exclude; sparse/downstream"),
    }
    return [
        {
            "feature": feature,
            "available_in_diabd": "yes",
            "currently_available_in_eldercarebd": decisions[feature][0],
            "caregiver_can_reasonably_provide": decisions[feature][1],
            "measurement_or_lab_requirement": decisions[feature][2],
            "deployment_decision": decisions[feature][3],
        }
        for feature in DIABD_COLUMNS[:-1]
    ]


def _leakage_audit(raw: pd.DataFrame) -> dict[str, Any]:
    y = raw["diabetic"].eq("Yes")
    decile = np.minimum(np.arange(len(raw)) * 10 // len(raw), 9)
    decile_rates = [float(y[decile == index].mean()) for index in range(10)]
    return {
        "target_timing": (
            "Contemporaneous recorded diabetic status, not a future-onset endpoint. "
            "The diagnostic gold standard, diagnosis date, medication status, and "
            "temporal relationship to predictors are not documented."
        ),
        "glucose": (
            "Random-session glucose is a concurrent diagnostic measurement and may "
            "have contributed to the physician-reviewed label; incorporation bias is unknown."
        ),
        "hypertensive": {
            "risk": "current diagnosis/history may postdate diabetes or proxy care intensity",
            "positive_rate_when_zero": float(y[raw["hypertensive"] == 0].mean()),
            "positive_rate_when_one": float(y[raw["hypertensive"] == 1].mean()),
            "deployment": "excluded",
        },
        "cardiovascular_disease_and_stroke": (
            "Sparse current comorbidities with unknown chronology; excluded from deployment."
        ),
        "height_weight_bmi": "BMI is derived from height/weight; all three are redundant.",
        "family_history": (
            "Sparse and unexpectedly inverse-associated; excluded from selected contract."
        ),
        "row_order": {
            "decile_positive_rates": decile_rates,
            "minimum": min(decile_rates),
            "maximum": max(decile_rates),
            "warning": (
                "Strong row-order heterogeneity suggests hidden site/batch structure, "
                "but site/person/time identifiers are unavailable for grouped validation."
            ),
        },
        "known_diabetes": (
            "The ElderCareBD has_diabetes profile field is the target/history and must "
            "never be used as a predictor; known diabetes should bypass screening."
        ),
    }


def _evaluate_candidates(
    X: pd.DataFrame,
    y: pd.Series,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    evaluations: list[dict[str, Any]] = []
    cv_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    for feature_set, features in FEATURE_SETS.items():
        subset = X.loc[:, list(features)]
        for candidate in DIABD_CANDIDATES:
            result = evaluate_candidate(
                build_diabd_pipeline(features, candidate.key), subset, y
            )
            evaluations.append(
                {
                    "feature_set": feature_set,
                    "features": list(features),
                    "candidate_key": candidate.key,
                    "model": candidate.display_name,
                    "evaluation": json_ready_evaluation(result),
                    "_oof_probabilities": result["oof_probabilities"],
                }
            )
            row: dict[str, Any] = {
                "feature_set": feature_set,
                "features": "|".join(features),
                "candidate_key": candidate.key,
                "model": candidate.display_name,
            }
            for metric, summary in result["cv_summary"].items():
                row[f"{metric}_mean"] = summary["mean"]
                row[f"{metric}_std"] = summary["std"]
            cv_rows.append(row)
            for fold in result["fold_metrics"]:
                fold_rows.append(
                    {
                        "feature_set": feature_set,
                        "candidate_key": candidate.key,
                        "model": candidate.display_name,
                        **fold,
                    }
                )
    return evaluations, cv_rows, fold_rows


def _evaluate_leakage_ablations(
    X: pd.DataFrame,
    y: pd.Series,
    full_evaluation: dict[str, Any],
) -> list[dict[str, Any]]:
    full_features = FEATURE_SETS["full_14"]
    history_features = set(BINARY_FEATURES)
    contracts = {
        "full_14": full_features,
        "without_hypertensive": tuple(
            name for name in full_features if name != "hypertensive"
        ),
        "without_cvd_and_stroke": tuple(
            name
            for name in full_features
            if name not in {"cardiovascular_disease", "stroke"}
        ),
        "without_all_history": tuple(
            name for name in full_features if name not in history_features
        ),
        "without_glucose": tuple(
            name for name in full_features if name != "glucose"
        ),
        "without_glucose_or_history": tuple(
            name
            for name in full_features
            if name != "glucose" and name not in history_features
        ),
    }
    results: list[dict[str, Any]] = []
    for name, features in contracts.items():
        if name == "full_14":
            evaluation = full_evaluation
        else:
            evaluation = json_ready_evaluation(
                evaluate_candidate(
                    build_diabd_pipeline(features, "logistic_regression"),
                    X.loc[:, list(features)],
                    y,
                )
            )
        results.append(
            {
                "ablation": name,
                "features": list(features),
                "evaluation": evaluation,
            }
        )
    return results


def _evaluate_glucose_floor_sensitivity(
    X: pd.DataFrame,
    y: pd.Series,
    baseline_evaluation: dict[str, Any],
) -> dict[str, Any]:
    sensitivity_X = X.copy()
    affected = sensitivity_X["glucose"].lt(2.0)
    additionally_affected = sensitivity_X["glucose"].ge(1.0) & affected
    sensitivity_X.loc[affected, "glucose"] = np.nan
    features = FEATURE_SETS[SELECTED_FEATURE_SET]
    sensitivity = evaluate_candidate(
        build_diabd_pipeline(features, SELECTED_CANDIDATE),
        sensitivity_X,
        y,
    )
    return {
        "purpose": (
            "Assess whether additionally treating glucose values from 1.0 to below "
            "2.0 mmol/L as invalid materially changes internal discrimination/calibration."
        ),
        "baseline_plausibility_minimum_mmol_l": 1.0,
        "sensitivity_plausibility_minimum_mmol_l": 2.0,
        "total_cells_below_2": int(affected.sum()),
        "additional_cells_from_1_to_below_2": int(additionally_affected.sum()),
        "row_deletion": "none",
        "baseline": baseline_evaluation,
        "glucose_below_2_to_missing": json_ready_evaluation(sensitivity),
    }


def _selected_feature_specs() -> tuple[FeatureSpec, ...]:
    return (
        FeatureSpec(
            "age",
            "integer",
            "years",
            minimum=21,
            maximum=80,
            measurement_context="Completed age at assessment; DiaBD support is 21-80.",
            task14_note="Out-of-range ages require fallback; no extrapolation.",
        ),
        FeatureSpec(
            "gender",
            "integer",
            None,
            allowed_values=(0, 1),
            value_labels={0: "Female", 1: "Male"},
            measurement_context="DiaBD's published binary gender labels.",
            task14_note="Other/unknown is unsupported and must fall back, never be fabricated.",
        ),
        FeatureSpec(
            "systolic_bp",
            "integer",
            "mmHg",
            minimum=62,
            maximum=231,
            measurement_context="Measured BP; source used repeated stable CHW readings.",
            task14_note="A single home value is a domain shift and must be identified.",
        ),
        FeatureSpec(
            "diastolic_bp",
            "integer",
            "mmHg",
            minimum=45,
            maximum=119,
            measurement_context="Measured BP; source used repeated stable CHW readings.",
            task14_note="Require a valid paired BP measurement with diastolic below systolic.",
        ),
        FeatureSpec(
            "glucose",
            "number",
            "mmol/L",
            minimum=1.0,
            maximum=33.46,
            measurement_context=(
                "Random-session glucometer glucose. It is not fasting, postprandial, "
                "or OGTT; meal timing and specimen matrix are undocumented."
            ),
            task14_note=(
                "Use a decimal value plus explicit random-session and mmol/L context; "
                "never reuse the Pima OGTT field or silently convert a generic reading."
            ),
        ),
        FeatureSpec(
            "bmi",
            "number",
            "kg/m^2",
            minimum=11.47,
            maximum=54.08,
            measurement_context="BMI calculated from validated height and weight.",
            task14_note="Recalculate from current measurements and reject invalid anthropometrics.",
        ),
    )


def _pima_comparison(ml_root: Path) -> dict[str, Any]:
    deployed_artifact, deployed_metadata = load_verified_artifact(
        "diabetes", ml_root=ml_root
    )
    config = get_dataset_configs()["diabetes"]
    frame, _ = load_and_validate_dataset(config, ml_root / "data")
    X = frame.loc[:, list(config.selected_features)]
    y = frame[config.target].astype(int)
    pipeline = build_task13_pipeline(
        config, config.selected_features, "logistic_regression"
    )
    fixed = evaluate_candidate(pipeline, X, y)
    nested = evaluate_nested_threshold(pipeline, X, y)
    return {
        "comparison_kind": (
            "Same-method re-evaluation of the fixed Pima dataset/selected v2 contract; "
            "not a claim that stored artifact predictions are cross-validated."
        ),
        "dataset": "Pima Indians Diabetes benchmark",
        "dataset_sha256": PIMA_DATA_SHA256,
        "artifact": "diabetes_model_v2.pkl",
        "artifact_sha256": PIMA_V2_ARTIFACT_SHA256,
        "verified_existing_artifact_contract": deployed_artifact.contract_dict(),
        "verified_existing_metadata_version": deployed_metadata["model_version"],
        "features": ["Age", "Glucose", "BMI"],
        "glucose_semantics": "2-hour OGTT plasma glucose, mg/dL",
        "population": "768 Pima women age>=21; only 16 are age>=65",
        "target": "documented five-year onset benchmark interpretation",
        "fixed_threshold_0_5": json_ready_evaluation(fixed),
        "nested_threshold_policy": json_ready_evaluation(nested),
        "null_prevalence_brier": prevalence_brier(y),
        "comparison_warning": (
            "Targets and prevalence differ (34.90% Pima vs 6.47% DiaBD). Absolute "
            "precision, AP/PR-AUC, Brier, and ECE are not directly comparable, and "
            "neither dataset externally validates the other."
        ),
    }


def _save_diagnostic_outputs(
    output_dir: Path,
    y: pd.Series,
    probability: np.ndarray,
    threshold: float,
    calibration: dict[str, Any],
) -> None:
    fpr, tpr, roc_threshold = roc_curve(y, probability)
    precision, recall, pr_threshold = precision_recall_curve(y, probability)
    _write_csv(
        output_dir / "selected_roc_curve.csv",
        [
            {"false_positive_rate": a, "true_positive_rate": b, "threshold": c}
            for a, b, c in zip(fpr, tpr, roc_threshold)
        ],
    )
    pr_rows = []
    for index, (p_value, r_value) in enumerate(zip(precision, recall)):
        pr_rows.append(
            {
                "precision": p_value,
                "recall": r_value,
                "threshold": pr_threshold[index] if index < len(pr_threshold) else "",
            }
        )
    _write_csv(output_dir / "selected_pr_curve.csv", pr_rows)
    _write_csv(output_dir / "selected_calibration.csv", calibration["bins"])
    prediction = (probability >= threshold).astype(int)
    matrix = confusion_matrix(y, prediction, labels=[0, 1]).astype(int)
    _write_csv(
        output_dir / "selected_confusion_matrix.csv",
        [
            {"actual": "No", "predicted_No": matrix[0, 0], "predicted_Yes": matrix[0, 1]},
            {"actual": "Yes", "predicted_No": matrix[1, 0], "predicted_Yes": matrix[1, 1]},
        ],
    )

    plt.figure(figsize=(6, 5))
    plt.plot(fpr, tpr, label="DiaBD v3")
    plt.plot([0, 1], [0, 1], linestyle="--", color="grey")
    plt.xlabel("False-positive rate")
    plt.ylabel("True-positive rate")
    plt.title("DiaBD v3 out-of-fold ROC curve")
    plt.tight_layout()
    plt.savefig(output_dir / "selected_roc_curve.png", dpi=160)
    plt.close()

    figure, axis = plt.subplots(figsize=(6, 5))
    axis.plot(recall, precision, label="DiaBD v3")
    axis.axhline(
        float(y.mean()),
        linestyle="--",
        color="grey",
        label="Prevalence baseline",
    )
    axis.set_xlim(0.0, 1.0)
    axis.set_ylim(0.0, 1.02)
    axis.set_xticks(np.linspace(0.0, 1.0, 6))
    axis.set_yticks(np.linspace(0.0, 1.0, 6))
    axis.tick_params(axis="both", colors="black", labelbottom=True, labelleft=True)
    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_color("black")
    axis.set_xlabel("Recall")
    axis.set_ylabel("Precision")
    axis.set_title("DiaBD v3 out-of-fold precision-recall curve")
    axis.legend(loc="upper right")
    figure.tight_layout()
    figure.savefig(output_dir / "selected_pr_curve.png", dpi=160)
    plt.close(figure)

    bins = calibration["bins"]
    plt.figure(figsize=(6, 5))
    plt.plot(
        [row["mean_score"] for row in bins],
        [row["observed_positive_fraction"] for row in bins],
        marker="o",
    )
    plt.plot([0, 1], [0, 1], linestyle="--", color="grey")
    plt.xlabel("Mean model score")
    plt.ylabel("Observed positive fraction")
    plt.title("DiaBD v3 out-of-fold calibration")
    plt.tight_layout()
    plt.savefig(output_dir / "selected_calibration.png", dpi=160)
    plt.close()


def _build_report(
    audit: dict[str, Any],
    cleaning: list[dict[str, Any]],
    compatibility: list[dict[str, str]],
    cv_rows: list[dict[str, Any]],
    selection: dict[str, Any],
    pima: dict[str, Any],
    artifact_hash: str,
    created_at: str,
) -> str:
    selected = selection["selected_evaluation"]
    nested = selection["nested_threshold_policy"]
    glucose_sensitivity = selection["glucose_floor_sensitivity"]
    leakage_ablations = selection["leakage_ablations"]
    lines = [
        "# Task 13B — DiaBD evaluation and final diabetes-model decision",
        "",
        "## Decision",
        "",
        "**Option C:** retain Pima v2 unchanged as a historical/research comparator, "
        "and select the DiaBD v3 unweighted logistic model for ElderCareBD's eventual "
        "research/demo deployment. It screens for contemporaneous recorded diabetes "
        "status; it is not a diagnosis, future-onset model, or personal probability.",
        "",
        "## Local dataset and integrity",
        "",
        f"- Exact file: `{audit['local_filename']}`",
        f"- SHA-256: `{audit['sha256']}`",
        f"- Shape: {audit['rows']:,} rows × {len(audit['columns'])} columns",
        "- Raw file was read only; no cleaned row-level copy is published.",
        "- No missing cells, exact duplicates, duplicate predictor profiles, or "
        "unexpected categories were found.",
        "",
        "The file matches the published filename/schema/counts/summaries, but exact "
        "byte identity with Mendeley V2/V3 is unknown because the repository has no "
        "source manifest and no external replacement was downloaded.",
        "",
        "## Glucose semantics",
        "",
        "`glucose` is random-session glucometer glucose in **mmol/L**. The source used "
        "repeated readings described as the most frequent/stable value. It is not "
        "documented as fasting, postprandial, or two-hour OGTT glucose. Meal timing, "
        "specimen matrix, device model, and exact aggregation rule are unknown.",
        "",
        "## Class imbalance",
        "",
        "- No: 4,946; Yes: 342; prevalence 6.4675%; negative:positive 14.462:1.",
        "- Accuracy is not a selection metric: an all-No rule is already 93.53% accurate.",
        "- AP (average precision) is used as the PR-AUC summary.",
        "",
        "## Cleaning and outlier decisions",
        "",
        "No row was deleted and no value was silently winsorized. Predeclared invalid "
        "cells become missing inside each pipeline and are median-imputed using only "
        "the corresponding training fold. Plausible extremes remain unchanged.",
        "",
        "| Pattern | Count | Classification | Decision |",
        "|---|---:|---|---|",
    ]
    for row in cleaning:
        lines.append(
            f"| {row['pattern']} | {row['count']} | {row['classification']} | "
            f"{row['decision']} |"
        )
    lines.extend(
        [
            "",
            "Stored BMI is formula-consistent for almost all rows: median absolute "
            f"difference from weight/height² is {audit['bmi_recomputation']['median_absolute_difference']:.4f}; "
            f"{audit['bmi_recomputation']['within_one_percent']:,}/{audit['rows']:,} are within 1%.",
            "",
            "## Leakage audit",
            "",
            "- The target is current recorded status; its diagnostic gold standard and "
            "chronology are not documented.",
            "- Random glucose may have contributed to the label, so incorporation bias "
            "cannot be excluded.",
            "- Current hypertension produced most of the full-model lift and was excluded, "
            "along with CVD and stroke, because their pre-target timing is unknown.",
            "- Height, weight, and BMI are redundant; only BMI is deployed.",
            "- Site/person/time identifiers are absent. Row-order prevalence varies "
            "substantially, so random CV may be optimistic.",
            "",
            "### Logistic-regression leakage ablations",
            "",
            "| Ablation | Features | ROC-AUC | AP | Brier |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in leakage_ablations:
        summary = row["evaluation"]["cv_summary"]
        lines.append(
            f"| {row['ablation']} | {len(row['features'])} | "
            f"{summary['roc_auc']['mean']:.4f} | "
            f"{summary['pr_auc_average_precision']['mean']:.4f} | "
            f"{summary['brier_score']['mean']:.4f} |"
        )
    lines.extend(
        [
            "",
            "Removing `hypertensive` accounts for most of the full-contract ROC-AUC "
            "drop, while removing only CVD/stroke changes little. This supports excluding "
            "temporally ambiguous diagnosis/history variables from the selected contract.",
            "",
            "## Candidate results (5-fold shuffled StratifiedKFold, seed 42)",
            "",
            "All imputation, scaling, and one-hot encoding occur inside folds. Metrics "
            "below are mean values at threshold 0.50; ROC-AUC and AP use scores.",
            "",
            "| Contract | Model | Bal. acc | Precision | Recall | Specificity | F1 | ROC-AUC | AP | Brier |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in cv_rows:
        lines.append(
            "| {feature_set} | {model} | {balanced_accuracy_mean:.4f} | "
            "{precision_mean:.4f} | {recall_mean:.4f} | {specificity_mean:.4f} | "
            "{f1_mean:.4f} | {roc_auc_mean:.4f} | "
            "{pr_auc_average_precision_mean:.4f} | {brier_score_mean:.4f} |".format(
                **row
            )
        )
    lines.extend(
        [
            "",
            "The full baseline is research-only. Its lift is dominated by the temporally "
            "ambiguous `hypertensive` field. The six-field logistic model is within about "
            "0.013 mean ROC-AUC of the reduced random forest, is simpler, and is much "
            "better calibrated than balanced alternatives.",
            "",
            "## Selected model and threshold",
            "",
            "- Feature order: `age, gender, systolic_bp, diastolic_bp, glucose, bmi`",
            "- Model: unweighted Logistic Regression",
            f"- Mean ROC-AUC: {selected['cv_summary']['roc_auc']['mean']:.4f} ± {selected['cv_summary']['roc_auc']['std']:.4f}",
            f"- Mean AP/PR-AUC: {selected['cv_summary']['pr_auc_average_precision']['mean']:.4f} ± {selected['cv_summary']['pr_auc_average_precision']['std']:.4f}",
            f"- Mean Brier: {selected['cv_summary']['brier_score']['mean']:.4f} ± {selected['cv_summary']['brier_score']['std']:.4f}",
            f"- OOF ECE: {selected['calibration']['expected_calibration_error']:.4f}",
            f"- Final development threshold: {selection['classification_threshold']:.2f}",
            f"- Nested thresholds: `{nested['fold_thresholds']}`",
            f"- Nested confusion matrix: `{nested['aggregate_confusion_matrix']}`",
            f"- Nested recall: {nested['aggregate_metrics']['recall']:.4f}",
            f"- Nested precision: {nested['aggregate_metrics']['precision']:.4f}",
            "",
            "The final threshold was fitted on full-data OOF predictions and is a "
            "development setting. Nested-CV classification metrics are the less biased "
            "estimate. At this prevalence, low precision means many flags are false "
            "positives relative to the dataset label.",
            "",
            "## Low-glucose cleaning sensitivity",
            "",
            f"- Total rows below 2 mmol/L: {glucose_sensitivity['total_cells_below_2']}",
            f"- Rows newly treated as missing beyond the primary <1 rule: {glucose_sensitivity['additional_cells_from_1_to_below_2']}",
            f"- Primary mean ROC-AUC: {glucose_sensitivity['baseline']['cv_summary']['roc_auc']['mean']:.4f}",
            f"- Sensitivity mean ROC-AUC: {glucose_sensitivity['glucose_below_2_to_missing']['cv_summary']['roc_auc']['mean']:.4f}",
            f"- Primary mean AP: {glucose_sensitivity['baseline']['cv_summary']['pr_auc_average_precision']['mean']:.4f}",
            f"- Sensitivity mean AP: {glucose_sensitivity['glucose_below_2_to_missing']['cv_summary']['pr_auc_average_precision']['mean']:.4f}",
            "The primary 1 mmol/L plausibility floor is retained; the separate result "
            "shows the effect of treating every sub-2 value as missing without deleting rows.",
            "",
            "## Pima v2 comparison",
            "",
            f"- Pima mean ROC-AUC: {pima['fixed_threshold_0_5']['cv_summary']['roc_auc']['mean']:.4f}",
            f"- Pima mean AP: {pima['fixed_threshold_0_5']['cv_summary']['pr_auc_average_precision']['mean']:.4f}",
            f"- Pima mean Brier: {pima['fixed_threshold_0_5']['cv_summary']['brier_score']['mean']:.4f}",
            "- Pima requires age, BMI, and 2-hour OGTT plasma glucose in mg/dL; DiaBD "
            "requires six realistic caregiver fields including random-session mmol/L glucose.",
            "- Pima is 768 Pima women with only 16 age>=65. DiaBD contains 5,288 "
            "Bangladeshi adults of both published gender categories and 605 age>=65.",
            "- Different targets/prevalence make precision, AP, Brier, and calibration "
            "non-comparable as absolute superiority claims.",
            "",
            "## Feature compatibility",
            "",
            "| Feature | Current ElderCareBD | Practicality | Requirement | Decision |",
            "|---|---|---|---|---|",
        ]
    )
    for row in compatibility:
        lines.append(
            f"| {row['feature']} | {row['currently_available_in_eldercarebd']} | "
            f"{row['caregiver_can_reasonably_provide']} | "
            f"{row['measurement_or_lab_requirement']} | {row['deployment_decision']} |"
        )
    lines.extend(
        [
            "",
            "## Task 14 compatibility note (no Task 14 code changed)",
            "",
            "- The Pima-specific OGTT input becomes unnecessary for v3 inference, but "
            "existing nullable OGTT provenance must remain intact.",
            "- The current generic integer glucose field cannot be reused unchanged. "
            "Task 14 needs a decimal random-session mmol/L field or a structured value+unit+context input.",
            "- Add DiaBD provenance columns; do not rename old OGTT columns destructively.",
            "- Reuse age/BP/BMI only after contract checks. Female/Male map from trusted "
            "metadata; Other/unknown must fall back.",
            "- Known diabetes should skip screening. Preserve the existing heuristic as an explicit fallback.",
            "",
            "## Artifact",
            "",
            f"- `models/{DIABD_ARTIFACT_FILENAME}`",
            f"- SHA-256 `{artifact_hash}`",
            f"- Version `{DIABD_MODEL_VERSION}`",
            "- Pima v2 was not overwritten.",
            "",
            "## Limitations",
            "",
            "- No documented diagnostic reference standard or prospective target.",
            "- Potential glucose incorporation bias and current-diagnosis proxy leakage.",
            "- No external, site-grouped, participant-grouped, or temporal validation.",
            "- Hidden batch/site heterogeneity and female-heavy sampling.",
            "- Only 605 participants age>=65; elderly-subgroup discrimination is weaker.",
            "- Values are repeated-session aggregates, whereas the app usually records one measurement.",
            "- Model scores are not patient probabilities and the artifact is not clinically cleared.",
            "",
            "## Reproducibility",
            "",
            "Run `ml_training\\venv\\Scripts\\python.exe -B ml_training\\train_diabd_v3.py "
            f"--created-at {created_at}`, then run the complete ML unittest suite.",
            "",
            "Primary sources: https://pmc.ncbi.nlm.nih.gov/articles/PMC12221696/ ; "
            "https://data.mendeley.com/datasets/m8cgwxs9s6/2 ; "
            "https://creativecommons.org/licenses/by/4.0/",
        ]
    )
    return "\n".join(lines) + "\n"


def run_task13b(
    ml_root: Path,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Run Task 13B without touching raw datasets, Pima v2, or application code."""

    ml_root = ml_root.resolve()
    data_dir = ml_root / "data"
    models_dir = ml_root / "models"
    output_dir = ml_root / "outputs" / "task13b"
    models_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_path = data_dir / DIABD_FILENAME
    kidney_path = data_dir / "kidney_disease_dataset.csv"
    pima_data_path = data_dir / "diabetes.csv"
    pima_artifact_path = models_dir / "diabetes_model_v2.pkl"
    before = {
        "diabd": sha256_file(raw_path),
        "kidney": sha256_file(kidney_path),
        "pima_data": sha256_file(pima_data_path),
        "pima_v2": sha256_file(pima_artifact_path),
    }
    expected = {
        "diabd": DIABD_SHA256,
        "kidney": KIDNEY_DATA_SHA256,
        "pima_data": PIMA_DATA_SHA256,
        "pima_v2": PIMA_V2_ARTIFACT_SHA256,
    }
    if before != expected:
        raise ValueError(f"Protected input hash mismatch: expected={expected}, got={before}")

    raw = load_raw_diabd(data_dir)
    X, y = encoded_xy(raw)
    audit = _dataset_audit(raw)
    cleaning = _cleaning_decisions(raw)
    compatibility = _compatibility_rows()
    leakage = _leakage_audit(raw)
    evaluations, cv_rows, fold_rows = _evaluate_candidates(X, y)
    selected_entry = next(
        row
        for row in evaluations
        if row["feature_set"] == SELECTED_FEATURE_SET
        and row["candidate_key"] == SELECTED_CANDIDATE
    )
    full_logistic_entry = next(
        row
        for row in evaluations
        if row["feature_set"] == "full_14"
        and row["candidate_key"] == "logistic_regression"
    )
    selected_probability = selected_entry.pop("_oof_probabilities")
    for row in evaluations:
        row.pop("_oof_probabilities", None)

    leakage_ablations = _evaluate_leakage_ablations(
        X,
        y,
        full_logistic_entry["evaluation"],
    )
    leakage["model_ablations"] = leakage_ablations

    selected_features = FEATURE_SETS[SELECTED_FEATURE_SET]
    selected_X = X.loc[:, list(selected_features)]
    glucose_floor_sensitivity = _evaluate_glucose_floor_sensitivity(
        selected_X,
        y,
        selected_entry["evaluation"],
    )
    selected_pipeline = build_diabd_pipeline(
        selected_features, SELECTED_CANDIDATE
    )
    nested = evaluate_nested_threshold(selected_pipeline, selected_X, y)
    block_sensitivity = evaluate_contiguous_block_sensitivity(
        selected_pipeline, selected_X, y
    )
    final_threshold = choose_recall_floor_threshold(
        y.to_numpy(), selected_probability, minimum_recall=0.75
    )
    final_prediction = (selected_probability >= final_threshold).astype(int)
    final_diagnostic = {
        "warning": (
            "Development diagnostic: this fixed threshold was selected from the same "
            "full-data OOF scores. Use nested policy metrics for less biased performance."
        ),
        "threshold": final_threshold,
        "metrics": classification_metrics(
            y.to_numpy(), final_prediction, selected_probability
        ),
        "confusion_matrix": confusion_matrix(
            y, final_prediction, labels=[0, 1]
        )
        .astype(int)
        .tolist(),
    }

    age65_mask = raw["age"].ge(65).to_numpy()
    nested_probability = nested["oof_probabilities"]
    nested_prediction = nested["oof_predictions"]
    age65 = {
        "rows": int(age65_mask.sum()),
        "positive_rows": int(y.to_numpy()[age65_mask].sum()),
        "metrics": classification_metrics(
            y.to_numpy()[age65_mask],
            nested_prediction[age65_mask],
            nested_probability[age65_mask],
        ),
        "confusion_matrix": confusion_matrix(
            y.to_numpy()[age65_mask],
            nested_prediction[age65_mask],
            labels=[0, 1],
        )
        .astype(int)
        .tolist(),
        "warning": "Exploratory subgroup only; just 45 positives and no external validation.",
    }

    selected_pipeline.fit(selected_X, y)
    artifact = RiskModelArtifact(
        model_version=DIABD_MODEL_VERSION,
        disease="diabetes",
        model_name="Logistic Regression",
        feature_specs=_selected_feature_specs(),
        classification_threshold=final_threshold,
        pipeline=selected_pipeline,
    )
    artifact_path = models_dir / DIABD_ARTIFACT_FILENAME
    artifact_staging_path = models_dir / f".{DIABD_ARTIFACT_FILENAME}.staging"
    joblib.dump(artifact, artifact_staging_path)
    artifact_hash = sha256_file(artifact_staging_path)
    if artifact_hash != DIABD_ARTIFACT_SHA256:
        raise RuntimeError(
            "Rebuilt DiaBD artifact differs from the audited code-pinned hash: "
            f"expected {DIABD_ARTIFACT_SHA256}, got {artifact_hash}."
        )

    pima = _pima_comparison(ml_root)
    timestamp = created_at or datetime.now(timezone.utc).isoformat()
    selection = {
        "decision": (
            "Option C: preserve Pima v2 for historical/research comparison and select "
            "DiaBD v3 for eventual ElderCareBD research/demo current-status screening."
        ),
        "selected_feature_set": SELECTED_FEATURE_SET,
        "selected_features": list(selected_features),
        "selected_candidate": SELECTED_CANDIDATE,
        "classification_threshold": final_threshold,
        "threshold_policy": (
            "Largest 0.01-grid threshold whose full-development OOF recall is >=0.75; "
            "nested CV is the performance estimate."
        ),
        "selected_evaluation": selected_entry["evaluation"],
        "final_threshold_development_diagnostic": final_diagnostic,
        "nested_threshold_policy": json_ready_evaluation(nested),
        "contiguous_block_sensitivity": json_ready_evaluation(block_sensitivity),
        "glucose_floor_sensitivity": glucose_floor_sensitivity,
        "leakage_ablations": leakage_ablations,
        "age_65_or_older_sensitivity": age65,
        "selection_rationale": [
            "Bangladeshi population relevance and 605 participants age>=65.",
            "Six realistically collectable fields already largely present in ElderCareBD.",
            "ROC-AUC is tied with Pima v2 while glucose context is operationally easier than OGTT.",
            "Unweighted logistic regression is interpretable and better calibrated than weighting.",
            "Diagnosis-history fields responsible for full-model lift are excluded.",
        ],
    }

    metadata = {
        "schema_version": "1.0.0",
        "model_version": DIABD_MODEL_VERSION,
        "disease": "diabetes",
        "display_name": "DiaBD Bangladesh diabetes recorded-status screening model",
        "created_at": timestamp,
        "decision": selection["decision"],
        "artifact": {
            "filename": DIABD_ARTIFACT_FILENAME,
            "relative_path": f"models/{DIABD_ARTIFACT_FILENAME}",
            "sha256": artifact_hash,
            "serialization": "joblib/pickle; load only fixed, trusted hash-matched bytes",
        },
        "training_dataset": audit,
        "target": {
            "column": "diabetic",
            "mapping": {"No": 0, "Yes": 1},
            "positive_class": 1,
            "definition": (
                "Contemporaneous recorded diabetic status reviewed by the study team; "
                "diagnostic reference standard, timing, diabetes type, and medication "
                "status are not documented. This is not future incidence."
            ),
        },
        "feature_contract": {
            "feature_set": SELECTED_FEATURE_SET,
            "feature_order": list(DIABD_FEATURE_ORDER),
            "features": [spec.to_dict() for spec in artifact.feature_specs],
            "gender_mapping": {str(value): label for label, value in GENDER_MAPPING.items()},
            "strict_missing_policy": "reject at inference",
            "strict_unexpected_policy": "reject at inference",
        },
        "preprocessing": {
            "raw_file": "never modified",
            "category_normalization": {"Female": 0, "Male": 1},
            "plausibility_to_missing": {
                name: {"minimum": bounds[0], "maximum": bounds[1]}
                for name, bounds in PLAUSIBILITY_RANGES.items()
                if name in selected_features
            },
            "imputation": "median learned inside each training fold",
            "numeric_scaling": "StandardScaler learned inside each training fold",
            "categorical_encoding": "explicit OneHotEncoder categories inside pipeline",
            "row_deletion": "none",
        },
        "classifier": {
            "candidate_key": SELECTED_CANDIDATE,
            "class": "LogisticRegression",
            "display_name": "Logistic Regression",
            "class_weight": None,
            "solver": "lbfgs",
            "max_iter": 2000,
            "random_state": 42,
        },
        "evaluation": {
            "method": "5-fold shuffled StratifiedKFold, seed 42",
            "classification_threshold": final_threshold,
            "pr_auc_definition": "average precision summary of the precision-recall curve",
            "selected_cv": selected_entry["evaluation"],
            "final_threshold_development_diagnostic": final_diagnostic,
            "nested_threshold_policy": json_ready_evaluation(nested),
            "contiguous_block_sensitivity": json_ready_evaluation(block_sensitivity),
            "glucose_floor_sensitivity": glucose_floor_sensitivity,
            "leakage_ablations": leakage_ablations,
            "age_65_or_older_sensitivity": age65,
            "prevalence_null_brier": prevalence_brier(y),
        },
        "comparison_with_pima_v2": pima,
        "runtime": {
            "python": platform.python_version(),
            **{
                key: importlib.metadata.version(distribution)
                for key, distribution in {
                    "numpy": "numpy",
                    "pandas": "pandas",
                    "scipy": "scipy",
                    "scikit_learn": "scikit-learn",
                    "joblib": "joblib",
                }.items()
            },
        },
        "intended_use": (
            "Research/demo screening flag for recorded diabetes status in a contract-"
            "matched Bangladeshi adult; use only when all six inputs and contexts match."
        ),
        "prohibited_use": [
            "clinical diagnosis or treatment decisions",
            "claiming a personal probability or future diabetes risk",
            "scoring known diabetes as a risk predictor",
            "silently substituting fasting, postprandial, OGTT, mg/dL, or generic glucose",
            "fabricating Other/unknown gender",
            "use outside supported ranges without fallback",
        ],
        "limitations": [
            leakage["target_timing"],
            leakage["glucose"],
            leakage["row_order"]["warning"],
            "No external, grouped, site-aware, participant-aware, or temporal validation.",
            "Female-heavy sample and weak age>=65 subgroup discrimination.",
            "Source repeated-session aggregates differ from a single caregiver measurement.",
            "Low prevalence produces low positive predictive value at a sensitivity-oriented threshold.",
        ],
        "task14_compatibility": {
            "status": "Task 14 remains paused; no application code was changed.",
            "ogtt_field": "not used by DiaBD v3; preserve as nullable legacy provenance",
            "required_glucose_change": (
                "decimal random-session mmol/L value with explicit context; generic "
                "or OGTT values cannot be silently reused"
            ),
            "additional_inputs": ["published Female/Male gender category"],
            "reused_inputs": ["age", "systolic_bp", "diastolic_bp", "bmi"],
            "fallbacks": "Other/unknown gender, unsupported range/context, or unavailable model",
        },
    }
    metadata_path = models_dir / DIABD_METADATA_FILENAME
    metadata_staging_path = models_dir / f".{DIABD_METADATA_FILENAME}.staging"
    _write_json(metadata_staging_path, metadata)

    _write_json(output_dir / "dataset_audit.json", audit)
    _write_json(output_dir / "cleaning_decisions.json", cleaning)
    _write_csv(output_dir / "feature_compatibility.csv", compatibility)
    _write_json(output_dir / "leakage_audit.json", leakage)
    _write_json(output_dir / "glucose_floor_sensitivity.json", glucose_floor_sensitivity)
    _write_csv(
        output_dir / "leakage_ablation_results.csv",
        [
            {
                "ablation": row["ablation"],
                "feature_count": len(row["features"]),
                "features": "|".join(row["features"]),
                **{
                    f"{metric}_mean": summary["mean"]
                    for metric, summary in row["evaluation"]["cv_summary"].items()
                },
            }
            for row in leakage_ablations
        ],
    )
    _write_json(output_dir / "candidate_evaluations.json", evaluations)
    _write_csv(output_dir / "cv_results.csv", cv_rows)
    _write_csv(output_dir / "fold_metrics.csv", fold_rows)
    _write_json(output_dir / "selection_report.json", selection)
    _write_json(output_dir / "pima_v2_comparison.json", pima)
    _save_diagnostic_outputs(
        output_dir,
        y,
        selected_probability,
        final_threshold,
        selected_entry["evaluation"]["calibration"],
    )
    _write_text(
        output_dir / "TASK13B_REPORT.md",
        _build_report(
            audit,
            cleaning,
            compatibility,
            cv_rows,
            selection,
            pima,
            artifact_hash,
            timestamp,
        ),
    )

    after = {
        "diabd": sha256_file(raw_path),
        "kidney": sha256_file(kidney_path),
        "pima_data": sha256_file(pima_data_path),
        "pima_v2": sha256_file(pima_artifact_path),
    }
    if after != before:
        raise RuntimeError(f"Protected inputs changed during Task 13B: {before} -> {after}")

    load_verified_diabd_artifact_bytes(
        metadata_bytes=metadata_staging_path.read_bytes(),
        artifact_bytes=artifact_staging_path.read_bytes(),
    )
    artifact_staging_path.replace(artifact_path)
    metadata_staging_path.replace(metadata_path)
    manifest = {
        "task": "13B",
        "status": "COMPLETE",
        "created_at": timestamp,
        "decision": selection["decision"],
        "selected_artifact": {
            "filename": DIABD_ARTIFACT_FILENAME,
            "sha256": artifact_hash,
            "metadata_filename": DIABD_METADATA_FILENAME,
            "metadata_sha256": sha256_file(metadata_path),
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
        "feature_order": list(DIABD_FEATURE_ORDER),
        "classification_threshold": final_threshold,
        "candidate_count": len(evaluations),
        "fold_result_count": len(fold_rows),
        "raw_data_modified": False,
        "task14_modified": False,
        "task13c_started": False,
    }
    _write_json(output_dir / "run_manifest.json", manifest)
    return manifest
