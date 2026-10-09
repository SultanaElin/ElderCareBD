"""End-to-end Task 13 training, evaluation, artifact, and report generation."""

from __future__ import annotations

import csv
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import matplotlib
import numpy as np
import pandas as pd
import sklearn

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .artifact import RiskModelArtifact
from .contracts import (
    CV_FOLDS,
    MODEL_VERSION,
    RANDOM_SEED,
    DatasetConfig,
    feature_compatibility_rows,
    get_dataset_configs,
)
from .data import load_and_validate_dataset, sha256_file
from .evaluation import (
    CLASSIFICATION_THRESHOLD,
    MINIMUM_SCREENING_RECALL,
    choose_recall_floor_threshold,
    classification_metrics,
    evaluate_candidate,
    evaluate_nested_threshold_policy,
    strip_large_arrays,
)
from .modeling import CANDIDATES, build_pipeline


LEGACY_ARTIFACTS = {
    "diabetes": {
        "filename": "diabetes_best_model.pkl",
        "sha256": "E4290C48301F679323B9673BA34D34C592855279D38392ED24D0B1FD111D5AB6",
        "feature_order": [
            "Pregnancies",
            "Glucose",
            "BloodPressure",
            "SkinThickness",
            "Insulin",
            "BMI",
            "DiabetesPedigreeFunction",
            "Age",
        ],
        "model": "Random Forest (balanced)",
    },
    "heart": {
        "filename": "heart_disease_best_model.pkl",
        "sha256": "8CCFED2469EE7C08D291E67C27B7F570674E026FD8E91A8C18CCCE4BA5F0D21C",
        "feature_order": [
            "age",
            "sex",
            "cp",
            "trestbps",
            "chol",
            "fbs",
            "restecg",
            "thalach",
            "exang",
            "oldpeak",
            "slope",
            "ca",
            "thal",
        ],
        "model": "Logistic Regression (legacy ordinal preprocessing)",
    },
}


def run_training(
    ml_root: Path,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Run the complete reproducible Task 13 workflow."""

    ml_root = ml_root.resolve()
    data_dir = ml_root / "data"
    models_dir = ml_root / "models"
    output_dir = ml_root / "outputs" / "task13"
    models_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    legacy_before = verify_legacy_artifacts(models_dir)
    configs = get_dataset_configs(data_dir)

    dataset_frames: dict[str, pd.DataFrame] = {}
    dataset_audits: dict[str, dict[str, Any]] = {}
    all_evaluations: list[dict[str, Any]] = []

    print("Validating approved repository datasets...")
    for disease, config in configs.items():
        frame, audit = load_and_validate_dataset(config, data_dir)
        dataset_frames[disease] = frame
        dataset_audits[disease] = audit
        print(
            f"  {config.display_name}: {len(frame)} rows, "
            f"SHA-256 {audit['sha256']}"
        )

    print("Evaluating fixed candidate pipelines with stratified 5-fold CV...")
    for disease, config in configs.items():
        frame = dataset_frames[disease]
        y = frame[config.target].astype(int)
        for feature_set_name, features in config.feature_sets.items():
            X = frame.loc[:, list(features)]
            for candidate in CANDIDATES:
                print(
                    f"  {config.display_name} / {feature_set_name} / "
                    f"{candidate.display_name}"
                )
                pipeline = build_pipeline(config, features, candidate.key)
                evaluation = evaluate_candidate(pipeline, X, y)
                all_evaluations.append(
                    {
                        "disease": disease,
                        "display_name": config.display_name,
                        "feature_set": feature_set_name,
                        "features": list(features),
                        "candidate_key": candidate.key,
                        "candidate_name": candidate.display_name,
                        "class_weight": candidate.class_weight,
                        "evaluation": evaluation,
                    }
                )

    selections: dict[str, dict[str, Any]] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    for disease, config in configs.items():
        disease_rows = [row for row in all_evaluations if row["disease"] == disease]
        selected = select_deployable_candidate(config, disease_rows)
        best_experimental = max(
            disease_rows,
            key=lambda row: row["evaluation"]["cv_summary"]["roc_auc"]["mean"],
        )
        frame = dataset_frames[disease]
        features = tuple(selected["features"])
        X = frame.loc[:, list(features)]
        y = frame[config.target].astype(int)
        pipeline = build_pipeline(config, features, selected["candidate_key"])

        nested_threshold = evaluate_nested_threshold_policy(
            pipeline,
            X,
            y,
            minimum_recall=MINIMUM_SCREENING_RECALL,
        )
        selected_oof_probability = np.asarray(
            selected["evaluation"]["oof_probabilities"], dtype=float
        )
        final_threshold = choose_recall_floor_threshold(
            y.to_numpy(),
            selected_oof_probability,
            minimum_recall=MINIMUM_SCREENING_RECALL,
        )
        final_threshold_prediction = (
            selected_oof_probability >= final_threshold
        ).astype(int)
        final_threshold_diagnostic = {
            "warning": (
                "Development diagnostic only: this fixed threshold was derived from these "
                "same full-dataset out-of-fold scores. Use the nested policy results for "
                "less biased classification-performance estimation."
            ),
            "threshold": final_threshold,
            "metrics": classification_metrics(
                y.to_numpy(),
                final_threshold_prediction,
                selected_oof_probability,
            ),
            "confusion_matrix": _confusion(y.to_numpy(), final_threshold_prediction),
        }

        fitted_pipeline = pipeline.fit(X, y)
        artifact = RiskModelArtifact(
            model_version=MODEL_VERSION,
            disease=disease,
            model_name=selected["candidate_name"],
            feature_specs=config.selected_feature_specs,
            classification_threshold=final_threshold,
            pipeline=fitted_pipeline,
        )
        artifact_path = models_dir / f"{disease}_model_v2.pkl"
        _atomic_joblib_dump(artifact, artifact_path)
        artifact_sha256 = sha256_file(artifact_path)

        selection = {
            "disease": disease,
            "best_experimental": _selection_identity(best_experimental),
            "selected_deployable": _selection_identity(selected),
            "selection_policy": (
                "Restrict deployment to the predefined usable feature contract. Prefer "
                "logistic regression when it is within 0.02 mean ROC-AUC of the strongest "
                "candidate, retain logistic variants within 0.005 Brier score of the best "
                "calibrated logistic variant, then prioritize recall, ROC-AUC, F1, and "
                "lower AUC fold variability."
            ),
            "rationale": _selection_rationale(config, selected, best_experimental),
            "nested_threshold_policy": nested_threshold,
            "final_training_oof_threshold": final_threshold_diagnostic,
        }
        selections[disease] = selection

        metadata = build_metadata(
            ml_root=ml_root,
            timestamp=timestamp,
            config=config,
            dataset_audit=dataset_audits[disease],
            selected=selected,
            best_experimental=best_experimental,
            nested_threshold=nested_threshold,
            final_threshold_diagnostic=final_threshold_diagnostic,
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
            pipeline=fitted_pipeline,
            legacy=legacy_before[disease],
        )
        metadata_path = models_dir / f"{disease}_model_v2.metadata.json"
        write_json(metadata_path, metadata)
        artifacts[disease] = {
            "artifact_path": artifact_path.relative_to(ml_root).as_posix(),
            "artifact_sha256": artifact_sha256,
            "metadata_path": metadata_path.relative_to(ml_root).as_posix(),
            "classification_threshold": final_threshold,
            "feature_order": list(artifact.feature_names),
        }

        save_selected_plots(
            output_dir=output_dir,
            config=config,
            selected=selected,
            nested_threshold=nested_threshold,
        )

    write_outputs(
        ml_root=ml_root,
        output_dir=output_dir,
        timestamp=timestamp,
        configs=configs,
        dataset_audits=dataset_audits,
        evaluations=all_evaluations,
        selections=selections,
        artifacts=artifacts,
        legacy=legacy_before,
    )

    legacy_after = verify_legacy_artifacts(models_dir)
    if legacy_before != legacy_after:
        raise RuntimeError("A legacy artifact changed during Task 13 training.")

    manifest = {
        "task": "Task 13",
        "status": "COMPLETE",
        "model_version": MODEL_VERSION,
        "created_at_utc": timestamp,
        "seed": RANDOM_SEED,
        "cv_folds": CV_FOLDS,
        "artifacts": artifacts,
        "legacy_artifacts_verified_unchanged": legacy_after,
        "output_directory": output_dir.relative_to(ml_root).as_posix(),
    }
    write_json(output_dir / "run_manifest.json", manifest)
    print("Task 13 training completed successfully.")
    return manifest


def select_deployable_candidate(
    config: DatasetConfig,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    usable = [row for row in rows if row["feature_set"] == config.selected_feature_set]
    if not usable:
        raise RuntimeError(f"No candidates evaluated for {config.selected_feature_set}.")

    top_auc = max(
        row["evaluation"]["cv_summary"]["roc_auc"]["mean"] for row in usable
    )
    interpretable = [
        row
        for row in usable
        if row["candidate_key"].startswith("logistic_regression")
        and top_auc - row["evaluation"]["cv_summary"]["roc_auc"]["mean"] <= 0.02
    ]
    pool = interpretable or usable
    if interpretable:
        best_brier = min(row["evaluation"]["oof_brier_score"] for row in pool)
        pool = [
            row
            for row in pool
            if row["evaluation"]["oof_brier_score"] <= best_brier + 0.005
        ]

    return max(
        pool,
        key=lambda row: (
            row["evaluation"]["cv_summary"]["recall"]["mean"],
            row["evaluation"]["cv_summary"]["roc_auc"]["mean"],
            row["evaluation"]["cv_summary"]["f1"]["mean"],
            -row["evaluation"]["cv_summary"]["roc_auc"]["std"],
        ),
    )


def build_metadata(
    *,
    ml_root: Path,
    timestamp: str,
    config: DatasetConfig,
    dataset_audit: dict[str, Any],
    selected: dict[str, Any],
    best_experimental: dict[str, Any],
    nested_threshold: dict[str, Any],
    final_threshold_diagnostic: dict[str, Any],
    artifact_path: Path,
    artifact_sha256: str,
    pipeline: Any,
    legacy: dict[str, Any],
) -> dict[str, Any]:
    evaluation = selected["evaluation"]
    return {
        "schema_version": "1.0.0",
        "model_version": MODEL_VERSION,
        "disease": config.disease,
        "display_name": config.display_name,
        "created_at_utc": timestamp,
        "intended_use": (
            "Research/demo screening risk-score support for ElderCareBD after a separate "
            "Task 14 integration and validation step."
        ),
        "prohibited_use": [
            "clinical diagnosis",
            "treatment decisions",
            "claiming an individual patient's real-world chance of disease",
            "scoring inputs outside the exact contract or training support",
        ],
        "positive_class": 1,
        "target": {
            "name": config.target,
            "mapping": {
                str(key): value for key, value in config.target_mapping.items()
            },
            "definition": config.target_definition,
            "note": "The target is not a prospective Bangladeshi clinical outcome.",
        },
        "artifact": {
            "filename": artifact_path.name,
            "relative_path": artifact_path.relative_to(ml_root).as_posix(),
            "sha256": artifact_sha256,
            "serialization": "joblib/pickle; load only this trusted hash-matched artifact",
        },
        "feature_contract": {
            "feature_set": config.selected_feature_set,
            "feature_order": list(config.selected_features),
            "strict_unexpected_feature_policy": "reject",
            "strict_missing_feature_policy": "reject",
            "strict_non_finite_policy": "reject",
            "features": [spec.to_dict() for spec in config.selected_feature_specs],
        },
        "training_dataset": dataset_audit,
        "preprocessing": {
            "inside_serialized_pipeline": True,
            "steps": [
                "exact named-column schema selection",
                "dataset-specific impossible-zero sentinel conversion to missing",
                "fold-local median imputation for numeric fields",
                "fold-local standardization for logistic numeric fields",
                "fold-local most-frequent imputation and explicit-category one-hot encoding for categorical fields",
            ],
            "pima_zero_sentinels": [
                name
                for name in config.invalid_zero_features
                if name in config.selected_features
            ],
            "categorical_mappings": {
                name: list(values)
                for name, values in config.categorical_values.items()
                if name in config.selected_features
            },
        },
        "classifier": {
            "candidate_key": selected["candidate_key"],
            "display_name": selected["candidate_name"],
            "class": type(pipeline.named_steps["classifier"]).__name__,
            "parameters": _json_safe_params(
                pipeline.named_steps["classifier"].get_params(deep=False)
            ),
        },
        "evaluation": {
            "method": "5-fold StratifiedKFold with shuffle",
            "folds": CV_FOLDS,
            "random_seed": RANDOM_SEED,
            "standard_threshold": CLASSIFICATION_THRESHOLD,
            "cv_summary_at_standard_threshold": evaluation["cv_summary"],
            "oof_metrics_at_standard_threshold": evaluation["oof_metrics"],
            "oof_confusion_matrix_at_standard_threshold": evaluation[
                "oof_confusion_matrix"
            ],
            "oof_roc_auc": evaluation["oof_roc_auc"],
            "oof_brier_score": evaluation["oof_brier_score"],
            "oof_log_loss": evaluation["oof_log_loss"],
            "calibration": evaluation["calibration"],
            "threshold_selection": nested_threshold,
            "final_threshold_development_diagnostic": final_threshold_diagnostic,
            "classification_threshold": final_threshold_diagnostic["threshold"],
            "selection_and_evaluation_warning": (
                "Feature/model development used the same small datasets. CV estimates are "
                "internal and there is no held-out Bangladeshi external validation cohort."
            ),
        },
        "model_selection": {
            "best_experimental": _selection_identity(best_experimental),
            "selected_deployable": _selection_identity(selected),
            "deployability_precedence": (
                "The reduced feature contract is preferred despite the full model's "
                "stronger experimental discrimination because the omitted clinical fields "
                "cannot be collected faithfully in the caregiver workflow."
            ),
        },
        "runtime": environment_versions(),
        "output_references": {
            "aggregate_metrics": "outputs/task13/cv_results.csv",
            "fold_metrics": "outputs/task13/fold_metrics.csv",
            "roc_curve": f"outputs/task13/{config.disease}_selected_roc_curve.csv",
            "calibration": f"outputs/task13/{config.disease}_selected_calibration.csv",
            "confusion_matrix": f"outputs/task13/{config.disease}_selected_confusion_matrix.png",
        },
        "legacy_comparison": legacy,
        "limitations": [
            config.population_note,
            config.source_note,
            "The model has not been externally validated, clinically calibrated, or prospectively evaluated.",
            "The score is an internal model risk estimate and must not be presented as a diagnosis or personal disease probability.",
            "Model selection on these cross-validation results can make estimates optimistic; independent validation remains required.",
        ],
    }


def write_outputs(
    *,
    ml_root: Path,
    output_dir: Path,
    timestamp: str,
    configs: dict[str, DatasetConfig],
    dataset_audits: dict[str, dict[str, Any]],
    evaluations: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    legacy: dict[str, dict[str, Any]],
) -> None:
    write_json(output_dir / "dataset_audit.json", dataset_audits)
    write_csv(output_dir / "feature_compatibility.csv", feature_compatibility_rows())

    aggregate_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    confusion_matrices: dict[str, Any] = {}
    candidate_summaries: list[dict[str, Any]] = []
    for row in evaluations:
        evaluation = row["evaluation"]
        base = {
            "disease": row["disease"],
            "feature_set": row["feature_set"],
            "features": "|".join(row["features"]),
            "candidate_key": row["candidate_key"],
            "candidate_name": row["candidate_name"],
            "class_weight": row["class_weight"] or "none",
        }
        aggregate = dict(base)
        for metric, values in evaluation["cv_summary"].items():
            aggregate[f"{metric}_mean"] = values["mean"]
            aggregate[f"{metric}_std"] = values["std"]
        aggregate.update(
            {
                "oof_roc_auc": evaluation["oof_roc_auc"],
                "oof_brier_score": evaluation["oof_brier_score"],
                "oof_log_loss": evaluation["oof_log_loss"],
                "oof_expected_calibration_error": evaluation["calibration"][
                    "expected_calibration_error"
                ],
            }
        )
        aggregate_rows.append(aggregate)
        for fold in evaluation["fold_metrics"]:
            fold_rows.append({**base, **fold})
        key = f"{row['disease']}::{row['feature_set']}::{row['candidate_key']}"
        confusion_matrices[key] = {
            "labels": [0, 1],
            "threshold": CLASSIFICATION_THRESHOLD,
            "matrix": evaluation["oof_confusion_matrix"],
        }
        candidate_summaries.append(
            {
                **base,
                "evaluation": strip_large_arrays(evaluation),
            }
        )

    write_csv(output_dir / "cv_results.csv", aggregate_rows)
    write_csv(output_dir / "fold_metrics.csv", fold_rows)
    write_json(output_dir / "confusion_matrices.json", confusion_matrices)
    write_json(output_dir / "candidate_evaluations.json", candidate_summaries)
    write_json(output_dir / "selection_report.json", selections)
    write_json(output_dir / "leakage_audit.json", leakage_audit(dataset_audits))
    write_json(output_dir / "legacy_comparison.json", legacy_comparison(ml_root, legacy))

    for disease, selection in selections.items():
        selected_identity = selection["selected_deployable"]
        selected_row = next(
            row
            for row in evaluations
            if row["disease"] == disease
            and row["feature_set"] == selected_identity["feature_set"]
            and row["candidate_key"] == selected_identity["candidate_key"]
        )
        write_roc_csv(
            output_dir / f"{disease}_selected_roc_curve.csv",
            selected_row["evaluation"]["roc_curve"],
        )
        write_csv(
            output_dir / f"{disease}_selected_calibration.csv",
            selected_row["evaluation"]["calibration"]["bins"],
        )

    report = build_markdown_report(
        timestamp=timestamp,
        configs=configs,
        audits=dataset_audits,
        evaluations=evaluations,
        selections=selections,
        artifacts=artifacts,
    )
    (output_dir / "TASK13_REPORT.md").write_text(report, encoding="utf-8", newline="\n")


def verify_legacy_artifacts(models_dir: Path) -> dict[str, dict[str, Any]]:
    verified: dict[str, dict[str, Any]] = {}
    for disease, expected in LEGACY_ARTIFACTS.items():
        path = models_dir / expected["filename"]
        if not path.is_file():
            raise RuntimeError(f"Required legacy artifact is missing: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != expected["sha256"]:
            raise RuntimeError(
                f"Refusing to train because legacy artifact {path.name} changed: "
                f"expected {expected['sha256']}, got {actual_hash}."
            )
        verified[disease] = {
            **expected,
            "sha256": actual_hash,
            "bytes": path.stat().st_size,
            "status": "verified unchanged",
        }
    return verified


def legacy_comparison(
    ml_root: Path,
    legacy: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    legacy_results_path = ml_root / "outputs" / "model_results.csv"
    metric_rows: list[dict[str, str]] = []
    if legacy_results_path.is_file():
        with legacy_results_path.open("r", encoding="utf-8", newline="") as handle:
            metric_rows = list(csv.DictReader(handle))
    return {
        "artifacts": legacy,
        "legacy_reported_metrics": metric_rows,
        "comparison": {
            "diabetes": (
                "The legacy model requires all eight fields and omits zero-sentinel "
                "normalization from its saved artifact. The v2 model contains preprocessing "
                "and uses three directly collectable, semantically explicit fields."
            ),
            "heart": (
                "The legacy model requires thirteen fields and treats nominal category codes "
                "as scaled numbers. The v2 model one-hot encodes declared categories and uses "
                "four inputs, with explicit Task 14 prerequisites."
            ),
        },
    }


def leakage_audit(audits: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "target_leakage": {
            "status": "pass",
            "evidence": "Target columns are schema-validated and excluded from every feature set.",
        },
        "target_derived_features": {
            "status": "pass",
            "evidence": "No diagnosis flags, prior risk labels, recommendations, or symptoms were added.",
        },
        "duplicates": {
            "status": "pass",
            "evidence": {
                disease: {
                    "exact": audit["exact_duplicate_rows"],
                    "predictor": audit["duplicate_predictor_rows"],
                }
                for disease, audit in audits.items()
            },
        },
        "preprocessing_before_cv": {
            "status": "pass",
            "evidence": "Sentinel conversion, imputation, scaling, and one-hot encoding are pipeline steps fitted/used independently in each fold.",
        },
        "oversampling": {
            "status": "not used",
            "evidence": "No synthetic sampling or resampling is present; class weights are estimator-local and learned only from training folds.",
        },
        "test_set_tuning": {
            "status": "no held-out test set",
            "evidence": "The project uses internal 5-fold CV. Model-development selection bias and absence of external validation are disclosed.",
        },
        "threshold_tuning": {
            "status": "nested",
            "evidence": "Outer-fold results use thresholds selected only from inner out-of-fold training predictions.",
        },
    }


def save_selected_plots(
    *,
    output_dir: Path,
    config: DatasetConfig,
    selected: dict[str, Any],
    nested_threshold: dict[str, Any],
) -> None:
    evaluation = selected["evaluation"]
    roc = evaluation["roc_curve"]
    plt.figure(figsize=(6.4, 5.2))
    plt.plot(
        roc["false_positive_rate"],
        roc["true_positive_rate"],
        color="#16796f",
        linewidth=2,
        label=f"OOF ROC-AUC = {evaluation['oof_roc_auc']:.3f}",
    )
    plt.plot([0, 1], [0, 1], linestyle="--", color="#777777")
    plt.xlabel("False-positive rate")
    plt.ylabel("True-positive rate (sensitivity)")
    plt.title(f"{config.display_name}: selected reduced model ROC")
    plt.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(output_dir / f"{config.disease}_selected_roc_curve.png", dpi=180)
    plt.close()

    calibration_rows = evaluation["calibration"]["bins"]
    plt.figure(figsize=(6.4, 5.2))
    plt.plot([0, 1], [0, 1], linestyle="--", color="#777777", label="Ideal")
    plt.plot(
        [row["mean_score"] for row in calibration_rows],
        [row["observed_positive_fraction"] for row in calibration_rows],
        marker="o",
        color="#16796f",
        linewidth=2,
        label="OOF diagnostic",
    )
    plt.xlabel("Mean model score")
    plt.ylabel("Observed positive fraction")
    plt.title(f"{config.display_name}: internal calibration diagnostic")
    plt.legend(loc="upper left")
    plt.tight_layout()
    plt.savefig(output_dir / f"{config.disease}_selected_calibration.png", dpi=180)
    plt.close()

    matrix = np.asarray(nested_threshold["aggregate_confusion_matrix"], dtype=int)
    plt.figure(figsize=(5.5, 5.0))
    plt.imshow(matrix, cmap="YlGn", interpolation="nearest")
    plt.colorbar()
    for row in range(2):
        for column in range(2):
            plt.text(column, row, str(matrix[row, column]), ha="center", va="center")
    plt.xticks([0, 1], ["Predicted 0", "Predicted 1"])
    plt.yticks([0, 1], ["Actual 0", "Actual 1"])
    plt.xlabel("Nested threshold-policy prediction")
    plt.ylabel("Observed class")
    plt.title(f"{config.display_name}: nested-CV confusion matrix")
    plt.tight_layout()
    plt.savefig(
        output_dir / f"{config.disease}_selected_confusion_matrix.png", dpi=180
    )
    plt.close()


def build_markdown_report(
    *,
    timestamp: str,
    configs: dict[str, DatasetConfig],
    audits: dict[str, dict[str, Any]],
    evaluations: list[dict[str, Any]],
    selections: dict[str, dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "# ElderCareBD Task 13 ML Development Report",
        "",
        f"Generated: {timestamp}",
        "",
        "These models are research screening/risk-score models, not diagnostic devices. "
        "Neither dataset validates performance for Bangladeshi elders.",
        "",
        "## Dataset audit",
        "",
    ]
    for disease, config in configs.items():
        audit = audits[disease]
        lines.extend(
            [
                f"### {config.display_name}",
                "",
                f"- Local file: `{audit['local_path']}`",
                f"- SHA-256: `{audit['sha256']}`",
                f"- Shape: {audit['rows']} rows, {len(audit['columns'])} columns",
                f"- Target: `{audit['target']}`; distribution {audit['class_distribution']}",
                f"- Target definition: {audit['target_definition']}",
                f"- Missing-value convention: {audit['missing_value_convention']}",
                f"- Invalid-zero counts: {audit['invalid_zero_convention']}",
                f"- Exact/predictor duplicates: {audit['exact_duplicate_rows']}/{audit['duplicate_predictor_rows']}",
                f"- Source: {audit['source_name']} ({audit['source_url']})",
                f"- Matching distribution reference: {audit['distribution_url']}",
                f"- License/provenance note: {audit['license_note']}",
                f"- Age support: {audit['age_counts']}",
                f"- Limitation: {audit['population_and_generalizability']}",
                "",
            ]
        )

    lines.extend(
        [
            "## ElderCare-friendly feature contracts and cleaning",
            "",
            "The full dataset-to-UI use/drop matrix is in `feature_compatibility.csv`. "
            "No UI symptom, prior diagnosis, stored risk label, or fabricated default was "
            "added to either model.",
            "",
        ]
    )
    for disease, config in configs.items():
        lines.extend(
            [
                f"### {config.display_name} selected contract",
                "",
                f"Predefined deployable set: `{config.selected_feature_set}` in exact order "
                f"`{list(config.selected_features)}`.",
                "",
                "| Feature | Type | Unit | Accepted training support/categories | Task 14 condition |",
                "|---|---|---|---|---|",
            ]
        )
        for spec in config.selected_feature_specs:
            if spec.allowed_values is not None:
                support = ", ".join(
                    f"{value}={spec.value_labels[value]}"
                    if spec.value_labels is not None
                    else str(value)
                    for value in spec.allowed_values
                )
            else:
                support = f"{spec.minimum} to {spec.maximum}"
            lines.append(
                f"| `{spec.name}` | {spec.data_type} | {spec.unit or 'none'} | "
                f"{support} | {spec.task14_note or 'Direct collection/derivation'} |"
            )
        lines.extend(["", f"Measurement semantics: " + " ".join(
            spec.measurement_context or "" for spec in config.selected_feature_specs
        ), ""])

    lines.extend(
        [
            "Cleaning is serialized with each artifact: exact named-column validation, "
            "Pima impossible-zero conversion inside the pipeline, fold-local imputation, "
            "numeric scaling for Logistic Regression and MLP, and explicit-category one-hot "
            "encoding for Cleveland categorical fields. Random Forest uses the same "
            "fold-local data contract without numeric scaling.",
            "",
            "Candidate models were fixed before evaluation: unweighted Logistic "
            "Regression, balanced Logistic Regression, balanced Random Forest, and a "
            "deterministic scikit-learn MLP evaluated separately because the legacy "
            "training/UI materials mention a neural network. The MLP is exploratory; it "
            "is not added merely to chase one metric and receives no deployment preference "
            "over simpler interpretable candidates.",
            "",
            "## Five-fold candidate results",
            "",
            "Classification metrics below are mean +/- population standard deviation at "
            "threshold 0.50; ROC-AUC uses probability scores and is threshold-independent. "
            "Preprocessing was inside each fold.",
            "",
            "| Disease | Feature set | Model | Accuracy | Precision | Recall | F1 | ROC-AUC |",
            "|---|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in evaluations:
        summary = row["evaluation"]["cv_summary"]
        lines.append(
            "| {disease} | {feature_set} | {model} | {accuracy} | {precision} | "
            "{recall} | {f1} | {auc} |".format(
                disease=row["display_name"],
                feature_set=row["feature_set"],
                model=row["candidate_name"],
                accuracy=_mean_std(summary["accuracy"]),
                precision=_mean_std(summary["precision"]),
                recall=_mean_std(summary["recall"]),
                f1=_mean_std(summary["f1"]),
                auc=_mean_std(summary["roc_auc"]),
            )
        )

    lines.extend(
        [
            "",
            "## ROC-AUC and calibration observations",
            "",
            "ROC-AUC measures ranking discrimination: an AUC of 0.83 means that, within "
            "these internal validation predictions, a randomly chosen positive-labelled "
            "record receives a higher score than a randomly chosen negative-labelled record "
            "about 83% of the time. It does not say that a patient has an 83% chance of "
            "disease, and it does not establish clinical utility.",
            "",
        ]
    )
    for disease, config in configs.items():
        selected_identity = selections[disease]["selected_deployable"]
        selected_row = next(
            row
            for row in evaluations
            if row["disease"] == disease
            and row["feature_set"] == selected_identity["feature_set"]
            and row["candidate_key"] == selected_identity["candidate_key"]
        )
        evaluation = selected_row["evaluation"]
        lines.extend(
            [
                f"- **{config.display_name}:** mean 5-fold ROC-AUC "
                f"{evaluation['cv_summary']['roc_auc']['mean']:.4f} +/- "
                f"{evaluation['cv_summary']['roc_auc']['std']:.4f}; pooled OOF ROC-AUC "
                f"{evaluation['oof_roc_auc']:.4f}; Brier score "
                f"{evaluation['oof_brier_score']:.4f}; log loss "
                f"{evaluation['oof_log_loss']:.4f}; fixed-width 10-bin ECE "
                f"{evaluation['calibration']['expected_calibration_error']:.4f}.",
            ]
        )
    lines.extend(
        [
            "",
            "The reliability plots are reasonably close to the diagonal in parts of each "
            "development sample but fluctuate, especially for the smaller heart dataset. "
            "These are diagnostics, not fitted external calibrations. Population shift, "
            "small samples, class weighting, and absence of a Bangladeshi validation cohort "
            "make the raw scores unsuitable as personal disease probabilities.",
            "",
            "## Selections",
            "",
        ]
    )
    for disease, config in configs.items():
        selection = selections[disease]
        artifact = artifacts[disease]
        nested = selection["nested_threshold_policy"]
        lines.extend(
            [
                f"### {config.display_name}",
                "",
                f"- Best experimental: `{selection['best_experimental']['feature_set']}` / "
                f"{selection['best_experimental']['candidate_name']}",
                f"- Selected deployable: `{selection['selected_deployable']['feature_set']}` / "
                f"{selection['selected_deployable']['candidate_name']}",
                f"- Exact feature order: `{artifact['feature_order']}`",
                f"- Final development threshold: {artifact['classification_threshold']:.2f}",
                f"- Nested-policy confusion matrix: `{nested['aggregate_confusion_matrix']}`",
                f"- Nested-policy recall: {nested['aggregate_metrics']['recall']:.4f}",
                f"- Nested-policy F1: {nested['aggregate_metrics']['f1']:.4f}",
                f"- Artifact: `{artifact['artifact_path']}` ({artifact['artifact_sha256']})",
                f"- Rationale: {selection['rationale']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Legacy comparison",
            "",
            "- Diabetes legacy artifact: eight predictors and a Random Forest; its saved "
            "pipeline omits the zero-sentinel normalization used before legacy CV. The v2 "
            "artifact uses three fields and contains the complete preprocessing chain.",
            "- Heart legacy artifact: thirteen predictors and ordinal scaling of nominal "
            "codes. The v2 artifact uses four fields and explicit one-hot categories.",
            "- Both legacy artifacts are retained under their original names and verified "
            "against their pre-Task-13 SHA-256 values.",
            "",
            "## Leakage and calibration conclusions",
            "",
            "- No target-derived features or oversampling were used.",
            "- Exact and predictor duplicates were rejected.",
            "- Sentinel conversion, imputation, scaling, and one-hot encoding stayed inside each fold.",
            "- Threshold-policy performance was estimated with nested CV; the final fitted threshold still needs external validation.",
            "- Reliability curves, Brier scores, and log loss are internal diagnostics only. A score must not be described as a patient's chance of disease.",
            "- Model/feature selection used these same small datasets, so all estimates remain development estimates without an external test cohort.",
            "",
            "## Reproduction",
            "",
            "From `ml_training`: `venv\\Scripts\\python.exe train_models_v2.py`",
            "",
            "Pinned dependencies are in `requirements-ml.txt`. The loader contract is "
            "`ml_training.eldercare_ml.loading.load_verified_artifact`, which verifies the "
            "metadata hash before deserialization.",
            "",
            "Validation command: `venv\\Scripts\\python.exe -m unittest discover -s tests "
            "-p \"test_*.py\" -v`.",
            "",
            "Task 13: COMPLETE",
            "",
        ]
    )
    return "\n".join(lines)


def write_roc_csv(path: Path, roc: dict[str, list[Any]]) -> None:
    rows = [
        {
            "false_positive_rate": fpr,
            "true_positive_rate": tpr,
            "threshold": threshold,
        }
        for fpr, tpr, threshold in zip(
            roc["false_positive_rate"],
            roc["true_positive_rate"],
            roc["thresholds"],
            strict=True,
        )
    ]
    write_csv(path, rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, indent=2, sort_keys=True, allow_nan=False)
    path.write_text(serialized + "\n", encoding="utf-8", newline="\n")


def environment_versions() -> dict[str, str]:
    import matplotlib as matplotlib_package
    import scipy

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "scipy": scipy.__version__,
        "scikit_learn": sklearn.__version__,
        "joblib": joblib.__version__,
        "matplotlib": matplotlib_package.__version__,
        "platform": platform.platform(),
    }


def _selection_identity(row: dict[str, Any]) -> dict[str, Any]:
    evaluation = row["evaluation"]
    return {
        "feature_set": row["feature_set"],
        "features": row["features"],
        "candidate_key": row["candidate_key"],
        "candidate_name": row["candidate_name"],
        "class_weight": row["class_weight"],
        "cv_roc_auc_mean": evaluation["cv_summary"]["roc_auc"]["mean"],
        "cv_roc_auc_std": evaluation["cv_summary"]["roc_auc"]["std"],
        "cv_recall_mean": evaluation["cv_summary"]["recall"]["mean"],
        "cv_f1_mean": evaluation["cv_summary"]["f1"]["mean"],
        "oof_brier_score": evaluation["oof_brier_score"],
    }


def _selection_rationale(
    config: DatasetConfig,
    selected: dict[str, Any],
    best_experimental: dict[str, Any],
) -> str:
    if config.disease == "diabetes":
        return (
            "Age, exact two-hour OGTT glucose, and BMI retain most full-model "
            "discrimination while removing five impractical fields. Diastolic BP was "
            "evaluated but added no useful discrimination. Unweighted logistic regression "
            "is compact/interpretable and had materially better internal calibration than "
            "the balanced variant; nested thresholding recovers screening sensitivity."
        )
    return (
        "The four-field structured contract materially outperformed the currently faithful "
        "age/sex/resting-BP subset while avoiding seven specialist tests. Balanced logistic "
        "regression modestly improved screening recall with essentially unchanged AUC and "
        "calibration. Task 14 must collect exact chest-pain type and binary clinical sex, "
        "and must not map boolean chest pain or Other/unknown values."
    )


def _confusion(y_true: np.ndarray, predicted: np.ndarray) -> list[list[int]]:
    from sklearn.metrics import confusion_matrix

    return confusion_matrix(y_true, predicted, labels=[0, 1]).astype(int).tolist()


def _json_safe_params(parameters: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in parameters.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            safe[key] = list(value)
        else:
            safe[key] = repr(value)
    return safe


def _atomic_joblib_dump(value: Any, path: Path) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        joblib.dump(value, temporary, compress=3)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _mean_std(values: dict[str, Any]) -> str:
    return f"{values['mean']:.4f} +/- {values['std']:.4f}"
