"""Generate the reproducible Task 13C kidney audit and negative-control study."""

from __future__ import annotations

import csv
import importlib.metadata
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import precision_recall_fscore_support

from .kidney import (
    BINARY_METRICS,
    FEATURE_SETS,
    KIDNEY_CANDIDATES,
    KIDNEY_FILENAME,
    KIDNEY_SHA256,
    MULTICLASS_METRICS,
    TARGET_CLASSES,
    TARGET_COLUMN,
    build_kidney_pipeline,
    cleaning_decisions,
    dataset_audit,
    encoded_targets,
    evaluate_binary,
    evaluate_multiclass,
    feature_compatibility_rows,
    json_ready_evaluation,
    load_raw_kidney,
    sha256_file,
    subgroup_metrics,
    target_construction_audit,
)


TASK13C_STATUS = "COMPLETE"
DEPLOYMENT_OUTCOME = (
    "C. Dataset has serious target/provenance issues and should not be deployed"
)
AUDIT_REFERENCE_FORMULATION = "binary_any_non_no_disease"
AUDIT_REFERENCE_FEATURE_SET = "eldercare_non_lab_12"
AUDIT_REFERENCE_CANDIDATE = "logistic_regression_balanced"

PROTECTED_FILES = {
    "data/kidney_disease_dataset.csv": KIDNEY_SHA256,
    "data/DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in Bangladesh.csv": (
        "D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A"
    ),
    "models/diabetes_model_v3_diabd.pkl": (
        "9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4"
    ),
    "models/diabetes_model_v3_diabd.metadata.json": (
        "53A33B967D807F94A0B37EB11CA616E7A1EF72A879DC2FE9FC5FA8BB169492BB"
    ),
    "models/heart_model_v2.pkl": (
        "E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103"
    ),
    "models/heart_model_v2.metadata.json": (
        "EE32EC47562066C63B82B50071DA0D715EC3B43BFC71F29FAC33379D7B41EE90"
    ),
    "models/diabetes_model_v2.pkl": (
        "2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07"
    ),
}


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _write_text(
        path,
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty CSV: {path}")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _verify_protected(ml_root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for relative_path, expected_hash in PROTECTED_FILES.items():
        path = ml_root / relative_path
        if not path.is_file():
            raise FileNotFoundError(f"Protected Task 13/13B input is missing: {path}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"Protected file changed: {relative_path}; expected {expected_hash}, "
                f"got {actual_hash}."
            )
        observed[relative_path] = actual_hash
    return observed


def _provenance_audit() -> dict[str, Any]:
    return {
        "local_authority": (
            "The repository file and fixed SHA-256 are authoritative for this audit."
        ),
        "closest_public_listing": (
            "https://www.kaggle.com/datasets/amanik000/kidney-disease-dataset"
        ),
        "identity_limit": (
            "Filename, 5.48 MB display size, and 43-column description match the public "
            "listing. No external copy was downloaded, so byte identity is unverified."
        ),
        "original_source": "not stated",
        "publication_or_doi": "none stated",
        "population": "not stated",
        "country": "not stated",
        "clinical_setting": "not stated",
        "collection_period": "not stated",
        "sampling_method": "not stated",
        "diagnostic_adjudication": "not stated",
        "sample_generation_method": "not stated",
        "row_type": "real/synthetic/simulated/augmented/mixed status not stated",
        "age_range_in_local_file": "5 to 90 years",
        "license": "Unknown on the public listing; no local license file",
        "version": "public listing displays Version 1; local byte lineage unverified",
        "assessment": (
            "Provenance is insufficient for a health-screening model. The local data "
            "patterns strongly suggest simulation, but no source record proves the "
            "generation mechanism."
        ),
    }


def _target_formulation_decision(targets: dict[str, pd.Series]) -> dict[str, Any]:
    return {
        "A_original_five_class": {
            "counts": {
                TARGET_CLASSES[index]: int(count)
                for index, count in targets["original_five_class"]
                .value_counts()
                .sort_index()
                .items()
            },
            "decision": "reject for deployment; evaluate only as a source-label audit",
            "reason": (
                "The classes have no clinical definitions and are not demonstrated CKD "
                "stages, severity categories, or future-risk outcomes."
            ),
        },
        "B_binary_disease_vs_no_disease": {
            "construction": "No_Disease=0; every other supplied label=1",
            "counts": {
                str(label): int(count)
                for label, count in targets["binary_any_non_no_disease"]
                .value_counts()
                .sort_index()
                .items()
            },
            "decision": "reject for deployment; evaluate only as a negative control",
            "reason": (
                "Low_Risk, Moderate_Risk, and High_Risk are not documented disease "
                "diagnoses, so calling all four nonzero labels disease would be invented."
            ),
        },
        "C_elevated_or_severe_group": {
            "construction_considered": (
                "No_Disease and Low_Risk=0; Moderate_Risk, High_Risk, and "
                "Severe_Disease=1"
            ),
            "counts": {
                str(label): int(count)
                for label, count in targets["binary_moderate_high_or_severe"]
                .value_counts()
                .sort_index()
                .items()
            },
            "decision": "reject without modeling",
            "reason": (
                "No source threshold or outcome definition justifies this boundary. "
                "Merging labels only to create a prediction task would be arbitrary."
            ),
        },
        "D_do_not_deploy": {
            "decision": "selected",
            "outcome": DEPLOYMENT_OUTCOME,
            "reason": (
                "Unverifiable provenance and target construction, clinical incoherence, "
                "and chance-level full/reduced validation make deployment indefensible."
            ),
        },
    }


def _flatten_fold_row(
    formulation: str,
    feature_set: str,
    candidate_key: str,
    model: str,
    fold: dict[str, Any],
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "formulation": formulation,
        "feature_set": feature_set,
        "candidate_key": candidate_key,
        "model": model,
        "fold": fold["fold"],
    }
    for key, value in fold.items():
        if key == "fold":
            continue
        if key == "per_class_recall":
            for label, recall in value.items():
                row[f"recall_{label}"] = recall
        else:
            row[key] = value
    return row


def _evaluate_all(
    raw: pd.DataFrame,
    targets: dict[str, pd.Series],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[tuple[str, str, str], dict[str, Any]],
]:
    X = raw.drop(columns=TARGET_COLUMN)
    evaluations: list[dict[str, Any]] = []
    cv_rows: list[dict[str, Any]] = []
    fold_rows: list[dict[str, Any]] = []
    live_results: dict[tuple[str, str, str], dict[str, Any]] = {}
    formulations = ("original_five_class", "binary_any_non_no_disease")
    total = len(formulations) * len(FEATURE_SETS) * len(KIDNEY_CANDIDATES)
    completed = 0
    for formulation in formulations:
        y = targets[formulation]
        for feature_set, features in FEATURE_SETS.items():
            subset = X.loc[:, list(features)]
            for candidate in KIDNEY_CANDIDATES:
                completed += 1
                print(
                    f"[{completed:02d}/{total}] {formulation} / {feature_set} / "
                    f"{candidate.key}",
                    flush=True,
                )
                pipeline = build_kidney_pipeline(features, candidate.key)
                if formulation == "original_five_class":
                    result = evaluate_multiclass(pipeline, subset, y)
                    metrics = MULTICLASS_METRICS
                else:
                    result = evaluate_binary(pipeline, subset, y)
                    metrics = BINARY_METRICS
                key = (formulation, feature_set, candidate.key)
                live_results[key] = result
                evaluations.append(
                    {
                        "formulation": formulation,
                        "feature_set": feature_set,
                        "features": list(features),
                        "candidate_key": candidate.key,
                        "model": candidate.display_name,
                        "purpose": "negative-control/source-label audit; not deployable",
                        "evaluation": json_ready_evaluation(result),
                    }
                )
                row: dict[str, Any] = {
                    "formulation": formulation,
                    "feature_set": feature_set,
                    "feature_count": len(features),
                    "features": "|".join(features),
                    "candidate_key": candidate.key,
                    "model": candidate.display_name,
                }
                for metric in metrics:
                    row[f"{metric}_mean"] = result["cv_summary"][metric]["mean"]
                    row[f"{metric}_std"] = result["cv_summary"][metric]["std"]
                cv_rows.append(row)
                for fold in result["fold_metrics"]:
                    fold_rows.append(
                        _flatten_fold_row(
                            formulation,
                            feature_set,
                            candidate.key,
                            candidate.display_name,
                            fold,
                        )
                    )
    return evaluations, cv_rows, fold_rows, live_results


def _comparison_rows(
    evaluations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for formulation in ("original_five_class", "binary_any_non_no_disease"):
        primary = "macro_f1" if formulation == "original_five_class" else "roc_auc"
        for feature_set in FEATURE_SETS:
            candidates = [
                evaluation
                for evaluation in evaluations
                if evaluation["formulation"] == formulation
                and evaluation["feature_set"] == feature_set
            ]
            best = max(
                candidates,
                key=lambda item: item["evaluation"]["cv_summary"][primary]["mean"],
            )
            oof = best["evaluation"]["oof_metrics"]
            row = {
                "formulation": formulation,
                "feature_set": feature_set,
                "feature_count": len(FEATURE_SETS[feature_set]),
                "best_observed_candidate": best["model"],
                "selection_metric": primary,
                "selection_metric_cv_mean": best["evaluation"]["cv_summary"][primary][
                    "mean"
                ],
                "selection_metric_cv_std": best["evaluation"]["cv_summary"][primary][
                    "std"
                ],
                "oof_accuracy": oof["accuracy"],
                "oof_balanced_accuracy": oof["balanced_accuracy"],
                "interpretation": (
                    "Best observed internal audit comparator only; model selection on "
                    "the same CV results is optimistic and confers no deployment status."
                ),
            }
            if formulation == "original_five_class":
                row.update(
                    {
                        "oof_macro_precision": oof["macro_precision"],
                        "oof_macro_recall": oof["macro_recall"],
                        "oof_macro_f1": oof["macro_f1"],
                        "oof_weighted_f1": oof["weighted_f1"],
                        "oof_roc_auc": oof["multiclass_roc_auc_ovr_macro"],
                    }
                )
            else:
                row.update(
                    {
                        "oof_precision": oof["precision"],
                        "oof_recall": oof["recall"],
                        "oof_specificity": oof["specificity"],
                        "oof_f1": oof["f1"],
                        "oof_roc_auc": oof["roc_auc"],
                        "oof_pr_auc": oof["pr_auc_average_precision"],
                        "oof_brier": oof["brier_score"],
                    }
                )
            rows.append(row)
    return rows


def _class_level_rows(
    live_results: dict[tuple[str, str, str], dict[str, Any]],
    targets: dict[str, pd.Series],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, result in live_results.items():
        formulation, feature_set, candidate_key = key
        y = targets[formulation].to_numpy()
        predicted = result["oof_predictions"]
        if formulation == "original_five_class":
            labels = np.arange(len(TARGET_CLASSES))
            names = TARGET_CLASSES
        else:
            labels = np.asarray([0, 1])
            names = ("No_Disease", "Any_non_No_Disease_label")
        precision, recall, f1, support = precision_recall_fscore_support(
            y, predicted, labels=labels, zero_division=0
        )
        model = next(
            item.display_name for item in KIDNEY_CANDIDATES if item.key == candidate_key
        )
        for index, label in enumerate(names):
            rows.append(
                {
                    "formulation": formulation,
                    "feature_set": feature_set,
                    "candidate_key": candidate_key,
                    "model": model,
                    "class": label,
                    "precision": float(precision[index]),
                    "recall": float(recall[index]),
                    "f1": float(f1[index]),
                    "support": int(support[index]),
                }
            )
    return rows


def _confusion_matrices(
    live_results: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "formulation": key[0],
            "feature_set": key[1],
            "candidate_key": key[2],
            "labels": (
                list(TARGET_CLASSES)
                if key[0] == "original_five_class"
                else ["No_Disease", "Any_non_No_Disease_label"]
            ),
            "matrix": result["oof_confusion_matrix"],
        }
        for key, result in live_results.items()
    ]


def _elderly_analysis(
    raw: pd.DataFrame,
    targets: dict[str, pd.Series],
    result: dict[str, Any],
) -> dict[str, Any]:
    target = targets[AUDIT_REFERENCE_FORMULATION]
    original_labels = raw[TARGET_COLUMN]
    analyses: dict[str, Any] = {}
    for threshold in (60, 65):
        mask = raw["Age of the patient"] >= threshold
        analysis = subgroup_metrics(
            result,
            target,
            mask,
            formulation=AUDIT_REFERENCE_FORMULATION,
        )
        analysis["original_five_class_counts"] = {
            label: int(count)
            for label, count in original_labels.loc[mask]
            .value_counts()
            .reindex(TARGET_CLASSES, fill_value=0)
            .items()
        }
        analyses[f"age_{threshold}_or_older"] = analysis
    return {
        "model_status": "predeclared audit reference; not a selected/deployable model",
        "formulation": AUDIT_REFERENCE_FORMULATION,
        "feature_set": AUDIT_REFERENCE_FEATURE_SET,
        "candidate": AUDIT_REFERENCE_CANDIDATE,
        "analyses": analyses,
        "interpretation": (
            "Subgroups are numerically large, but invalid target construction prevents "
            "claims of elderly clinical validity regardless of precision."
        ),
    }


def _three_disease_summary() -> dict[str, Any]:
    return {
        "diabetes_diabd_v3": {
            "status": "research/demo artifact selected in Task 13B; not yet integrated",
            "inputs": 6,
            "exact_fields": [
                "age",
                "gender",
                "systolic_bp",
                "diastolic_bp",
                "glucose",
                "bmi",
            ],
            "measurement_burden": (
                "profile age/gender, resting BP, height/weight-derived BMI, and explicit "
                "random-session glucose in mmol/L"
            ),
            "classification_semantics": (
                "internal score for contemporaneous recorded diabetes status; not future risk"
            ),
            "main_limitations": (
                "internal validation only; glucose context and binary gender contract; "
                "known diabetes must bypass screening"
            ),
        },
        "heart_v2": {
            "status": "research/demo artifact selected in Task 13; not yet integrated",
            "inputs": 4,
            "exact_fields": ["age", "sex", "cp", "trestbps"],
            "measurement_burden": (
                "age, exact binary clinical-sex code, guided four-class chest-pain type, "
                "and explicitly resting systolic BP"
            ),
            "classification_semantics": (
                "Cleveland diagnostic disease-present class; not future cardiovascular risk"
            ),
            "main_limitations": (
                "small historical non-Bangladeshi referral cohort; exact sex and chest-pain "
                "semantics cannot be inferred from existing generic fields"
            ),
        },
        "kidney_task13c": {
            "status": "no model selected; Outcome C",
            "inputs": 0,
            "exact_fields": [],
            "measurement_burden": "none because no contract is authorized",
            "classification_semantics": "none; source labels are unverified",
            "main_limitations": (
                "unknown provenance/target construction, clinical incoherence, and "
                "chance-level internal discrimination"
            ),
        },
    }


def _runtime_versions() -> dict[str, str]:
    packages = ("numpy", "pandas", "scipy", "scikit-learn", "joblib", "matplotlib")
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        **{package: importlib.metadata.version(package) for package in packages},
    }


def _format_metric(value: Any) -> str:
    return f"{float(value):.4f}"


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def _target_report(audit: dict[str, Any], provenance: dict[str, Any]) -> str:
    associations = audit["egfr_band_target_association"]
    correlations = audit["selected_clinical_correlations"]
    counts = audit["internal_incoherence_counts"]
    return f"""# Task 13C target-construction report

## Conclusion

The supplied `Target` cannot be justified as an independently observed diagnosis,
clinical CKD stage, disease-severity measure, or prospective risk outcome. The five
labels therefore must not be deployed or presented as CKD stages.

## Evidence available

- No diagnostic rule, clinician adjudication, source institution, collection period,
  outcome horizon, or target derivation is documented.
- The closest public listing is {provenance['closest_public_listing']} and reports an
  unknown license; it does not fill these gaps.
- eGFR-band versus target Cramer's V is {_format_metric(associations['cramers_v'])}
  (chi-square p={associations['p_value']:.4g}), showing negligible association.
- eGFR versus serum creatinine correlation is
  {_format_metric(correlations['egfr_vs_serum_creatinine'])}; eGFR versus cystatin C is
  {_format_metric(correlations['egfr_vs_cystatin_c'])}.
- {counts['no_disease_with_egfr_below_15']:,} `No_Disease` rows have eGFR below 15,
  while {counts['severe_disease_with_egfr_at_least_90']:,} `Severe_Disease` rows have
  eGFR at least 90.
- {counts['diabetes_no_but_duration_positive']:,} rows say diabetes=no while recording
  positive diabetes duration; {counts['hypertension_no_but_duration_positive']:,}
  show the analogous hypertension contradiction.

## Interpretation

There is no evidence of a simple eGFR/creatinine rule leaking directly into the target.
That is not reassuring here: the target is essentially disconnected from clinically
related variables. The joint pattern strongly suggests independently simulated
predictors and labels, but the generation method is unverified and must be reported as
an inference rather than a fact.

CKD normally requires persistent kidney-structure/function abnormality and is classified
using cause, GFR, and albuminuria context. This file has no repeated dates/chronicity and
does not document its protein-to-creatinine units or equivalence to UACR.

Sources:

- https://kdigo.org/wp-content/uploads/2024/03/KDIGO-2024-CKD-Guideline.pdf
- https://www.niddk.nih.gov/health-information/professionals/clinical-tools-patient-management/kidney-disease/identify-manage-patients/evaluate-ckd
- https://www.niddk.nih.gov/health-information/professionals/advanced-search/quick-reference-uacr-gfr
"""


def _full_report(
    raw_audit: dict[str, Any],
    provenance: dict[str, Any],
    target_audit: dict[str, Any],
    target_decision: dict[str, Any],
    compatibility: list[dict[str, str]],
    cleaning: list[dict[str, Any]],
    comparisons: list[dict[str, Any]],
    reference: dict[str, Any],
    elderly: dict[str, Any],
    three_disease: dict[str, Any],
) -> str:
    target_rows = [
        [
            label,
            raw_audit["target_distribution"][label]["count"],
            f"{raw_audit['target_distribution'][label]['fraction']:.2%}",
        ]
        for label in TARGET_CLASSES
    ]
    comparison_rows: list[list[Any]] = []
    for row in comparisons:
        comparison_rows.append(
            [
                row["formulation"],
                row["feature_set"],
                row["feature_count"],
                row["best_observed_candidate"],
                _format_metric(row["oof_balanced_accuracy"]),
                _format_metric(row.get("oof_macro_f1", row.get("oof_f1"))),
                _format_metric(row["oof_roc_auc"]),
            ]
        )
    reference_metrics = reference["oof_metrics"]
    reference_matrix = reference["oof_confusion_matrix"]
    calibration = reference["calibration"]
    suspicious = raw_audit["suspicious_or_incoherent_values"]
    lab_count = sum(
        row["requires_laboratory_test"] == "yes" for row in compatibility
    )
    cleaning_rows = [
        [item["pattern"], item["count"], item["classification"], item["decision"]]
        for item in cleaning
    ]
    elderly_rows = []
    for group, result in elderly["analyses"].items():
        metrics = result["metrics"]
        elderly_rows.append(
            [
                group,
                result["rows"],
                _format_metric(metrics["balanced_accuracy"]),
                _format_metric(metrics["roc_auc"]),
                _format_metric(metrics["f1"]),
            ]
        )
    return f"""# ElderCareBD Task 13C kidney dataset report

## 1. Raw kidney dataset audit

- File: `data/{KIDNEY_FILENAME}`
- SHA-256: `{raw_audit['sha256']}`
- Size: {raw_audit['bytes']:,} bytes
- Shape: {raw_audit['rows']:,} rows, {raw_audit['columns_count']} columns,
  {raw_audit['predictor_count']} predictors, target `{TARGET_COLUMN}`
- Types: {len(raw_audit['feature_types']['numeric'])} numeric and
  {len(raw_audit['feature_types']['categorical'])} categorical predictors
- Missing/blank/non-finite cells: {raw_audit['missing_cells']}/
  {raw_audit['blank_cells']}/{raw_audit['non_finite_numeric_cells']}
- Exact duplicate rows/duplicate predictor profiles:
  {raw_audit['exact_duplicate_rows']}/{raw_audit['duplicate_predictor_profiles']}

{_markdown_table(['Class', 'Rows', 'Fraction'], target_rows)}

The raw CSV was read only and remains hash-identical. Detailed dtypes, mappings,
ranges, counts, and all 43 column names are in `dataset_audit.json`.

## 2. Provenance

The closest public listing is {provenance['closest_public_listing']}. Filename, displayed
size, and 43-column description match, but exact byte lineage was not verified by an
external download. Original source, publication/DOI, population, country, clinical
setting, collection period, sampling method, label adjudication, and real/synthetic
status are all unstated. The listing's license is `Unknown`; no local license accompanies
the CSV. This is inadequate provenance for health screening.

## 3. Target-construction audit

The five labels have no documented definitions. They are neither demonstrated clinician
diagnoses nor KDIGO GFR/CGA stages, and the data have no repeated measurements or outcome
horizon. eGFR-band versus target Cramer's V is
{target_audit['egfr_band_target_association']['cramers_v']:.4f}; key renal biomarker
means are essentially unchanged between labels. The dedicated findings are in
`TARGET_CONSTRUCTION_REPORT.md` and `target_construction_audit.json`.

## 4. Leakage assessment

Simple mechanical target leakage was not detected: target labels are nearly independent
of eGFR, creatinine, cystatin C, and UPCR. This exposes a more fundamental problem—the
unexplained target is clinically incoherent. Full, biomarker-excluded, and home-feature
models all remain near chance, so there is no hidden high-performing full model to
deploy. All preprocessing was fitted inside each CV training fold.

## 5. Feature compatibility matrix

`feature_compatibility.csv` contains all 42 predictors and every requested compatibility
dimension. {lab_count} fields require laboratory data; several urine fields also need
specialist interpretation. Age, home BP, derived BMI, and structured histories are
feasible in principle, but the source cannot validate a model using them. No field is
authorized for a kidney deployment contract.

## 6. Cleaning rules

{_markdown_table(['Pattern', 'Count', 'Classification', 'Decision'], cleaning_rows)}

No row was deleted, clipped, corrected, relabeled, or written to a cleaned dataset.
Median/mode imputers remain inside research pipelines but see no missing values in this
snapshot.

## 7. Target formulation decision

- A, original five-class: rejected for deployment; retained only to audit source labels.
- B, any non-`No_Disease` versus `No_Disease`: rejected for deployment; used only as a
  binary negative control because risk labels are not diagnoses.
- C, moderate/high/severe collapse: rejected without modeling because its boundary is
  arbitrary and undocumented.
- D, do not deploy: selected. Final outcome: **{DEPLOYMENT_OUTCOME}**.

## 8. Full-feature results

The table below reports the best observed candidate per formulation/feature set only for
compact comparison. It does not select a deployable model. Full candidate/fold metrics
are in `cv_results.csv`, `fold_metrics.csv`, and `candidate_evaluations.json`.

{_markdown_table(['Formulation', 'Feature set', 'N', 'Comparator', 'Balanced accuracy', 'Macro/binary F1', 'ROC-AUC'], comparison_rows)}

The 42-feature baseline does not establish predictive validity; accuracy is misleading
under the 80% majority class.

## 9. Leakage-safe results

Comparing the same models across `full_42`, `biomarker_excluded_14`, and
`eldercare_non_lab_12` shows no material clinically useful signal. Performance does not
collapse from an implausibly high full baseline; it stays at chance throughout. This is
consistent with labels that are independent of both biomarkers and non-lab features,
not evidence that the labels are safe.

## 10. ElderCare-friendly reduced-model results

The 12-field non-lab and 7-field compact contracts were evaluated. Neither provides
defensible discrimination. They are research comparisons only and no mobile input
contract was selected.

## 11. Five-fold CV metrics

Every evaluated pipeline used 5-fold shuffled stratified CV, seed 42, with fold-local
median/mode imputation, one-hot encoding, and numeric scaling where applicable. Mean,
population SD, and all five fold values are recorded for macro/class-weighted multiclass
metrics and binary precision, recall, specificity, F1, ROC-AUC, PR-AUC, Brier, and log
loss.

## 12. Confusion matrix and class-level metrics

The predeclared binary audit reference (`eldercare_non_lab_12`, balanced logistic
regression) produced OOF matrix `[[{reference_matrix[0][0]}, {reference_matrix[0][1]}],
[{reference_matrix[1][0]}, {reference_matrix[1][1]}]]` with precision
{reference_metrics['precision']:.4f}, recall {reference_metrics['recall']:.4f},
specificity {reference_metrics['specificity']:.4f}, and F1
{reference_metrics['f1']:.4f}. All matrices and per-class precision/recall/F1/support
are in `confusion_matrices.json` and `class_level_metrics.csv`.

## 13. Calibration results

For that negative-control reference, OOF Brier score is
{reference_metrics['brier_score']:.4f} and 10-bin ECE is
{calibration['expected_calibration_error']:.4f}. These diagnostics are not a personal
disease-probability validation because the labels themselves are unverified.

## 14. Elderly subgroup analysis

{_markdown_table(['Subgroup', 'Rows', 'Balanced accuracy', 'ROC-AUC', 'F1'], elderly_rows)}

Numerically adequate subgroup sizes cannot rescue invalid outcome semantics. No elderly
clinical validity is claimed.

## 15. Final deployment decision

**{DEPLOYMENT_OUTCOME}.** No kidney model is selected for ElderCareBD, including
research/demo screening. Scientific validity takes precedence over adding a third model.

## 16. Final feature contract if selected

None. No kidney feature order, category mapping, range, or threshold is authorized for
runtime use.

## 17. Saved artifact and metadata if selected

No `kidney_model_v1.pkl` and no deployable kidney metadata were created. Instead,
`deployment_decision.json` records Outcome C. Existing diabetes and heart artifacts were
hash-checked before and after the run.

## 18. Task 14 integration requirements

Task 14 remains paused and must not add a kidney model route, database field, Flutter
input, prediction result, or fabricated fallback mapping from this dataset. Acquire a
licensed, documented cohort with an independently defined outcome (including chronicity
or a clear prospective endpoint), then repeat Task 13C before kidney integration.

## 19. Three-disease contract summary

- DiaBD diabetes v3: {three_disease['diabetes_diabd_v3']['inputs']} inputs—
  {', '.join(three_disease['diabetes_diabd_v3']['exact_fields'])}. Explicit random-session
  mmol/L glucose context remains essential.
- Heart v2: {three_disease['heart_v2']['inputs']} inputs—
  {', '.join(three_disease['heart_v2']['exact_fields'])}. Exact binary clinical sex,
  four-class chest-pain type, and resting systolic BP are required.
- Kidney: no selected artifact and zero authorized inputs.

`three_disease_contract_summary.json` contains measurement burden, classification
semantics, and main limitations for all three.

## 20. Tests and results

The reproducible entry point performs hash gates and writes all audit outputs. Run the
complete suite from the repository root with:

```powershell
.\\ml_training\\venv\\Scripts\\python.exe -B -m unittest discover -s ml_training/tests -p "test_*.py" -v
```

The final task handoff records the exact observed test count/result. No backend, Flutter,
database, OCR, OTP, or Task 14 test is needed because those areas were not changed.

## 21. Limitations

- Public-page matching does not prove the local file's byte provenance.
- Dataset generation, sampling, country, setting, timing, label rules, and license are
  unknown.
- The CSV lacks longitudinal evidence needed to establish CKD chronicity.
- `Urine protein-to-creatinine ratio` has no documented unit and cannot be assumed UACR.
- Internal random CV cannot create validity when the outcome is unexplained; model
  selection on the same folds is also optimistic.
- The observed data patterns support, but do not prove, a synthetic-data inference.
- No score from this audit is a diagnosis, prognosis, treatment recommendation, or
  calibrated personal probability.

**Task 13C: {TASK13C_STATUS}. Task 14 remains PAUSED.**
"""


def run_task13c(ml_root: Path, *, created_at: str | None = None) -> dict[str, Any]:
    """Run Task 13C without creating or overwriting any deployable artifact."""

    ml_root = ml_root.resolve()
    output_dir = ml_root / "outputs" / "task13c"
    output_dir.mkdir(parents=True, exist_ok=True)
    before = _verify_protected(ml_root)

    raw_path = ml_root / "data" / KIDNEY_FILENAME
    raw = load_raw_kidney(ml_root / "data")
    raw_audit = dataset_audit(raw, raw_path)
    provenance = _provenance_audit()
    target_audit = target_construction_audit(raw)
    compatibility = feature_compatibility_rows()
    cleaning = cleaning_decisions(raw)
    targets = encoded_targets(raw)
    target_decision = _target_formulation_decision(targets)

    evaluations, cv_rows, fold_rows, live_results = _evaluate_all(raw, targets)
    comparisons = _comparison_rows(evaluations)
    class_rows = _class_level_rows(live_results, targets)
    matrices = _confusion_matrices(live_results)
    reference_key = (
        AUDIT_REFERENCE_FORMULATION,
        AUDIT_REFERENCE_FEATURE_SET,
        AUDIT_REFERENCE_CANDIDATE,
    )
    reference = live_results[reference_key]
    elderly = _elderly_analysis(raw, targets, reference)
    three_disease = _three_disease_summary()

    deployment_decision = {
        "task": "13C",
        "status": TASK13C_STATUS,
        "outcome": "C",
        "decision": DEPLOYMENT_OUTCOME,
        "kidney_artifact_created": False,
        "kidney_metadata_created": False,
        "authorized_runtime_feature_contract": None,
        "authorized_threshold": None,
        "task14_status": "PAUSED",
        "reason": (
            "The target and provenance are unverified, source records are clinically "
            "incoherent, and full/reduced negative-control evaluations remain near chance."
        ),
        "required_next_evidence": [
            "licensed and traceable cohort",
            "documented population, setting, dates, and sampling",
            "independently adjudicated CKD status with chronicity or prospective outcome",
            "units and measurement protocols",
            "patient/site/time identifiers for leakage-safe validation",
            "external elderly and Bangladesh-relevant validation",
        ],
    }
    calibration_rows = reference["calibration"]["bins"]

    _write_json(output_dir / "dataset_audit.json", raw_audit)
    _write_json(output_dir / "provenance_audit.json", provenance)
    _write_json(output_dir / "target_construction_audit.json", target_audit)
    _write_json(output_dir / "target_formulation_decision.json", target_decision)
    _write_csv(output_dir / "feature_compatibility.csv", compatibility)
    _write_json(output_dir / "cleaning_decisions.json", cleaning)
    _write_csv(output_dir / "cleaning_decisions.csv", cleaning)
    _write_json(output_dir / "candidate_evaluations.json", evaluations)
    _write_csv(output_dir / "cv_results.csv", cv_rows)
    _write_csv(output_dir / "fold_metrics.csv", fold_rows)
    _write_csv(output_dir / "comparison_summary.csv", comparisons)
    _write_csv(output_dir / "class_level_metrics.csv", class_rows)
    _write_json(output_dir / "confusion_matrices.json", matrices)
    _write_json(
        output_dir / "calibration_diagnostic.json",
        {
            "reference": {
                "formulation": AUDIT_REFERENCE_FORMULATION,
                "feature_set": AUDIT_REFERENCE_FEATURE_SET,
                "candidate": AUDIT_REFERENCE_CANDIDATE,
            },
            "brier_score": reference["oof_metrics"]["brier_score"],
            **reference["calibration"],
        },
    )
    _write_csv(output_dir / "calibration_diagnostic.csv", calibration_rows)
    _write_json(output_dir / "elderly_subgroup_analysis.json", elderly)
    _write_json(output_dir / "deployment_decision.json", deployment_decision)
    _write_json(output_dir / "three_disease_contract_summary.json", three_disease)
    _write_text(
        output_dir / "TARGET_CONSTRUCTION_REPORT.md",
        _target_report(target_audit, provenance),
    )
    _write_text(
        output_dir / "TASK13C_REPORT.md",
        _full_report(
            raw_audit,
            provenance,
            target_audit,
            target_decision,
            compatibility,
            cleaning,
            comparisons,
            reference,
            elderly,
            three_disease,
        ),
    )

    after = _verify_protected(ml_root)
    if before != after:
        raise RuntimeError("A protected dataset or existing artifact changed during Task 13C.")
    created_at_value = created_at or datetime.now(timezone.utc).isoformat()
    output_hashes = {
        path.name: sha256_file(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "run_manifest.json"
    }
    manifest = {
        "task": "13C",
        "status": TASK13C_STATUS,
        "created_at": created_at_value,
        "random_seed": 42,
        "cross_validation": "5-fold shuffled StratifiedKFold",
        "deployment_outcome": "C",
        "kidney_artifact_created": False,
        "task14_status": "PAUSED",
        "raw_dataset": {
            "filename": KIDNEY_FILENAME,
            "sha256": KIDNEY_SHA256,
        },
        "protected_hashes_before": before,
        "protected_hashes_after": after,
        "runtime": _runtime_versions(),
        "generated_output_hashes": output_hashes,
    }
    _write_json(output_dir / "run_manifest.json", manifest)
    return manifest
