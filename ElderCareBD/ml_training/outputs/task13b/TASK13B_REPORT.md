# Task 13B — DiaBD evaluation and final diabetes-model decision

## Decision

**Option C:** retain Pima v2 unchanged as a historical/research comparator, and select the DiaBD v3 unweighted logistic model for ElderCareBD's eventual research/demo deployment. It screens for contemporaneous recorded diabetes status; it is not a diagnosis, future-onset model, or personal probability.

## Local dataset and integrity

- Exact file: `DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in Bangladesh.csv`
- SHA-256: `D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A`
- Shape: 5,288 rows × 15 columns
- Raw file was read only; no cleaned row-level copy is published.
- No missing cells, exact duplicates, duplicate predictor profiles, or unexpected categories were found.

The file matches the published filename/schema/counts/summaries, but exact byte identity with Mendeley V2/V3 is unknown because the repository has no source manifest and no external replacement was downloaded.

## Glucose semantics

`glucose` is random-session glucometer glucose in **mmol/L**. The source used repeated readings described as the most frequent/stable value. It is not documented as fasting, postprandial, or two-hour OGTT glucose. Meal timing, specimen matrix, device model, and exact aggregation rule are unknown.

## Class imbalance

- No: 4,946; Yes: 342; prevalence 6.4675%; negative:positive 14.462:1.
- Accuracy is not a selection metric: an all-No rule is already 93.53% accurate.
- AP (average precision) is used as the PR-AUC summary.

## Cleaning and outlier decisions

No row was deleted and no value was silently winsorized. Predeclared invalid cells become missing inside each pipeline and are median-imputed using only the corresponding training fold. Plausible extremes remain unchanged.

| Pattern | Count | Classification | Decision |
|---|---:|---|---|
| pulse_rate < 30 bpm | 3 | clearly invalid | set affected pulse cells to missing inside pipeline |
| glucose < 1 mmol/L | 18 | zero clearly invalid; positive sub-1 likely invalid | set affected glucose cells to missing; disclose <2 sensitivity |
| glucose 1 to <2 mmol/L | 8 | unknown; physiologically severe or possible source error | retain in primary analysis; evaluate <2-to-missing sensitivity |
| height < 1 metre | 3 | 0.36 clearly invalid; 0.64/0.99 likely invalid | set affected height cells to missing inside full baseline |
| weight < 20 kg | 1 | 3 kg clearly invalid for adult cohort | set affected weight cells to missing inside full baseline |
| weight 20 to <30 kg | 8 | plausible extreme | retain unchanged and document |
| BMI outside 10-80 kg/m^2 | 4 | clearly/likely invalid anthropometric combinations | set affected BMI cells to missing inside pipeline |
| BMI >50 to 80 kg/m^2 | 1 | plausible extreme | retain unchanged and document |
| pulse 30-39 or >120 bpm | 13 | plausible extreme | retain unchanged and document |
| systolic BP <80 or >220 mmHg | 6 | plausible extreme | retain unchanged and document |
| diastolic BP <50 or >110 mmHg | 133 | plausible extreme | retain unchanged and document |
| diastolic BP >= systolic BP | 0 | invalid paired measurement if present | none found; future inference adapter must reject |
| glucose >30 mmol/L | 2 | plausible severe hyperglycaemia / label discordance unknown | retain; never relabel target |
| age divisible by five | 3303 | unknown; possible age heaping | retain and disclose |

Stored BMI is formula-consistent for almost all rows: median absolute difference from weight/height² is 0.0770; 5,286/5,288 are within 1%.

## Leakage audit

- The target is current recorded status; its diagnostic gold standard and chronology are not documented.
- Random glucose may have contributed to the label, so incorporation bias cannot be excluded.
- Current hypertension produced most of the full-model lift and was excluded, along with CVD and stroke, because their pre-target timing is unknown.
- Height, weight, and BMI are redundant; only BMI is deployed.
- Site/person/time identifiers are absent. Row-order prevalence varies substantially, so random CV may be optimistic.

### Logistic-regression leakage ablations

| Ablation | Features | ROC-AUC | AP | Brier |
|---|---:|---:|---:|---:|
| full_14 | 14 | 0.8660 | 0.4289 | 0.0471 |
| without_hypertensive | 13 | 0.8270 | 0.2994 | 0.0534 |
| without_cvd_and_stroke | 12 | 0.8655 | 0.4298 | 0.0471 |
| without_all_history | 9 | 0.8241 | 0.2891 | 0.0538 |
| without_glucose | 13 | 0.8164 | 0.2984 | 0.0522 |
| without_glucose_or_history | 8 | 0.7382 | 0.1601 | 0.0582 |

Removing `hypertensive` accounts for most of the full-contract ROC-AUC drop, while removing only CVD/stroke changes little. This supports excluding temporally ambiguous diagnosis/history variables from the selected contract.

## Candidate results (5-fold shuffled StratifiedKFold, seed 42)

All imputation, scaling, and one-hot encoding occur inside folds. Metrics below are mean values at threshold 0.50; ROC-AUC and AP use scores.

| Contract | Model | Bal. acc | Precision | Recall | Specificity | F1 | ROC-AUC | AP | Brier |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| full_14 | Logistic Regression | 0.6022 | 0.6320 | 0.2131 | 0.9913 | 0.3173 | 0.8660 | 0.4289 | 0.0471 |
| full_14 | Logistic Regression (balanced) | 0.7863 | 0.2467 | 0.7280 | 0.8445 | 0.3679 | 0.8667 | 0.4217 | 0.1356 |
| full_14 | Random Forest (balanced) | 0.7164 | 0.3694 | 0.4914 | 0.9414 | 0.4203 | 0.8758 | 0.4428 | 0.0636 |
| eldercare_reduced_8 | Logistic Regression | 0.5356 | 0.4176 | 0.0789 | 0.9923 | 0.1313 | 0.8196 | 0.2898 | 0.0537 |
| eldercare_reduced_8 | Logistic Regression (balanced) | 0.7439 | 0.1801 | 0.7133 | 0.7746 | 0.2875 | 0.8191 | 0.2925 | 0.1669 |
| eldercare_reduced_8 | Random Forest (balanced) | 0.6752 | 0.3154 | 0.4121 | 0.9383 | 0.3569 | 0.8353 | 0.3014 | 0.0734 |
| current_ui_reduced_6 | Logistic Regression | 0.5339 | 0.3886 | 0.0760 | 0.9917 | 0.1254 | 0.8203 | 0.2896 | 0.0538 |
| current_ui_reduced_6 | Logistic Regression (balanced) | 0.7371 | 0.1764 | 0.7016 | 0.7725 | 0.2818 | 0.8201 | 0.2923 | 0.1675 |
| current_ui_reduced_6 | Random Forest (balanced) | 0.6680 | 0.3278 | 0.3916 | 0.9444 | 0.3565 | 0.8334 | 0.2997 | 0.0710 |
| compact_4 | Logistic Regression | 0.5370 | 0.3929 | 0.0820 | 0.9919 | 0.1336 | 0.7932 | 0.2657 | 0.0551 |
| compact_4 | Logistic Regression (balanced) | 0.7216 | 0.1710 | 0.6666 | 0.7766 | 0.2720 | 0.7923 | 0.2661 | 0.1771 |
| compact_4 | Random Forest (balanced) | 0.6715 | 0.2709 | 0.4206 | 0.9224 | 0.3281 | 0.8082 | 0.2693 | 0.0819 |
| minimal_no_glucose_4 | Logistic Regression | 0.5011 | 0.1000 | 0.0029 | 0.9994 | 0.0056 | 0.6664 | 0.1310 | 0.0593 |
| minimal_no_glucose_4 | Logistic Regression (balanced) | 0.6351 | 0.1074 | 0.6344 | 0.6357 | 0.1836 | 0.6668 | 0.1309 | 0.2286 |
| minimal_no_glucose_4 | Random Forest (balanced) | 0.5585 | 0.1123 | 0.2572 | 0.8599 | 0.1562 | 0.6482 | 0.1013 | 0.1258 |

The full baseline is research-only. Its lift is dominated by the temporally ambiguous `hypertensive` field. The six-field logistic model is within about 0.013 mean ROC-AUC of the reduced random forest, is simpler, and is much better calibrated than balanced alternatives.

## Selected model and threshold

- Feature order: `age, gender, systolic_bp, diastolic_bp, glucose, bmi`
- Model: unweighted Logistic Regression
- Mean ROC-AUC: 0.8203 ± 0.0319
- Mean AP/PR-AUC: 0.2896 ± 0.0338
- Mean Brier: 0.0538 ± 0.0014
- OOF ECE: 0.0083
- Final development threshold: 0.06
- Nested thresholds: `[0.06, 0.06, 0.05, 0.05, 0.06]`
- Nested confusion matrix: `[[3542, 1404], [77, 265]]`
- Nested recall: 0.7749
- Nested precision: 0.1588

The final threshold was fitted on full-data OOF predictions and is a development setting. Nested-CV classification metrics are the less biased estimate. At this prevalence, low precision means many flags are false positives relative to the dataset label.

## Low-glucose cleaning sensitivity

- Total rows below 2 mmol/L: 26
- Rows newly treated as missing beyond the primary <1 rule: 8
- Primary mean ROC-AUC: 0.8203
- Sensitivity mean ROC-AUC: 0.8206
- Primary mean AP: 0.2896
- Sensitivity mean AP: 0.2909
The primary 1 mmol/L plausibility floor is retained; the separate result shows the effect of treating every sub-2 value as missing without deleting rows.

## Pima v2 comparison

- Pima mean ROC-AUC: 0.8253
- Pima mean AP: 0.7143
- Pima mean Brier: 0.1604
- Pima requires age, BMI, and 2-hour OGTT plasma glucose in mg/dL; DiaBD requires six realistic caregiver fields including random-session mmol/L glucose.
- Pima is 768 Pima women with only 16 age>=65. DiaBD contains 5,288 Bangladeshi adults of both published gender categories and 605 age>=65.
- Different targets/prevalence make precision, AP, Brier, and calibration non-comparable as absolute superiority claims.

## Feature compatibility

| Feature | Current ElderCareBD | Practicality | Requirement | Decision |
|---|---|---|---|---|
| age | assessment/profile | easy | none | use |
| gender | profile Male/Female/Other | easy | self-report | use Female/Male only; Other/unknown must fall back |
| pulse_rate | absent | possible | pulse measurement | full baseline only |
| systolic_bp | assessment | reasonable | BP cuff | use |
| diastolic_bp | assessment | reasonable | BP cuff | use |
| glucose | generic integer plus paused OGTT field; neither is equivalent | possible | glucometer | use only as decimal random-session mmol/L with explicit context |
| height | assessment cm | reasonable | measurement | derive BMI only |
| weight | assessment kg | reasonable | measurement | derive BMI only |
| bmi | derived | easy | height and weight | use |
| family_diabetes | absent | reportable | history | exclude; sparse/inverse |
| hypertensive | profile history | reportable | diagnosis | exclude; timing/proxy leakage unresolved |
| family_hypertension | absent | reportable | history | exclude |
| cardiovascular_disease | heart history is not exact CVD | reportable | diagnosis | exclude; sparse/downstream risk |
| stroke | profile history | reportable | diagnosis | exclude; sparse/downstream |

## Task 14 compatibility note (no Task 14 code changed)

- The Pima-specific OGTT input becomes unnecessary for v3 inference, but existing nullable OGTT provenance must remain intact.
- The current generic integer glucose field cannot be reused unchanged. Task 14 needs a decimal random-session mmol/L field or a structured value+unit+context input.
- Add DiaBD provenance columns; do not rename old OGTT columns destructively.
- Reuse age/BP/BMI only after contract checks. Female/Male map from trusted metadata; Other/unknown must fall back.
- Known diabetes should skip screening. Preserve the existing heuristic as an explicit fallback.

## Artifact

- `models/diabetes_model_v3_diabd.pkl`
- SHA-256 `9A02FFDEF3A4117BE48E734F9D44CE0FB31FEFA5839F912426B55EEAB66BDBF4`
- Version `3.0.0`
- Pima v2 was not overwritten.

## Limitations

- No documented diagnostic reference standard or prospective target.
- Potential glucose incorporation bias and current-diagnosis proxy leakage.
- No external, site-grouped, participant-grouped, or temporal validation.
- Hidden batch/site heterogeneity and female-heavy sampling.
- Only 605 participants age>=65; elderly-subgroup discrimination is weaker.
- Values are repeated-session aggregates, whereas the app usually records one measurement.
- Model scores are not patient probabilities and the artifact is not clinically cleared.

## Reproducibility

Run `ml_training\venv\Scripts\python.exe -B ml_training\train_diabd_v3.py --created-at 2026-09-02T00:00:00+06:00`, then run the complete ML unittest suite.

Primary sources: https://pmc.ncbi.nlm.nih.gov/articles/PMC12221696/ ; https://data.mendeley.com/datasets/m8cgwxs9s6/2 ; https://creativecommons.org/licenses/by/4.0/
