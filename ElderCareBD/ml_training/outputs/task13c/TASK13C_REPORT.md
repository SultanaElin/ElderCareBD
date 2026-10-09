# ElderCareBD Task 13C kidney dataset report

## 1. Raw kidney dataset audit

- File: `data/kidney_disease_dataset.csv`
- SHA-256: `4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199`
- Size: 5,483,328 bytes
- Shape: 20,538 rows, 43 columns,
  42 predictors, target `Target`
- Types: 28 numeric and
  14 categorical predictors
- Missing/blank/non-finite cells: 0/
  0/0
- Exact duplicate rows/duplicate predictor profiles:
  0/0

| Class | Rows | Fraction |
| --- | --- | --- |
| No_Disease | 16432 | 80.01% |
| Low_Risk | 2054 | 10.00% |
| Moderate_Risk | 821 | 4.00% |
| High_Risk | 821 | 4.00% |
| Severe_Disease | 410 | 2.00% |

The raw CSV was read only and remains hash-identical. Detailed dtypes, mappings,
ranges, counts, and all 43 column names are in `dataset_audit.json`.

## 2. Provenance

The closest public listing is https://www.kaggle.com/datasets/amanik000/kidney-disease-dataset. Filename, displayed
size, and 43-column description match, but exact byte lineage was not verified by an
external download. Original source, publication/DOI, population, country, clinical
setting, collection period, sampling method, label adjudication, and real/synthetic
status are all unstated. The listing's license is `Unknown`; no local license accompanies
the CSV. This is inadequate provenance for health screening.

## 3. Target-construction audit

The five labels have no documented definitions. They are neither demonstrated clinician
diagnoses nor KDIGO GFR/CGA stages, and the data have no repeated measurements or outcome
horizon. eGFR-band versus target Cramer's V is
0.0121; key renal biomarker
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
dimension. 28 fields require laboratory data; several urine fields also need
specialist interpretation. Age, home BP, derived BMI, and structured histories are
feasible in principle, but the source cannot validate a model using them. No field is
authorized for a kidney deployment contract.

## 6. Cleaning rules

| Pattern | Count | Classification | Decision |
| --- | --- | --- | --- |
| explicit missing, blank, or non-finite values | 0 | clearly invalid if present | none present; no imputation is activated by the audited CSV |
| age below 18 years | 3150 | valid pediatric age but outside adult/elderly scope | retain for source audit; exclude only by declared subgroup analysis |
| diabetes=no with positive diabetes duration | 9963 | likely invalid paired history | retain in full research baseline; exclude duration from reduced contracts |
| diabetes=yes with zero diabetes duration | 358 | unknown (new diagnosis possible) | retain; do not invent duration |
| diabetes duration greater than age | 2498 | clearly invalid | retain only to expose source quality; exclude duration from reduced contracts |
| hypertension=no with positive hypertension duration | 9879 | likely invalid paired history | retain in full research baseline; exclude duration from reduced contracts |
| hypertension=yes with zero hypertension duration | 330 | unknown (new diagnosis possible) | retain; do not invent duration |
| hypertension duration greater than age | 2503 | clearly invalid | retain only to expose source quality; exclude duration from reduced contracts |
| No_Disease label with eGFR below 15 | 1491 | clinically discordant; target semantics unknown | do not relabel or delete; treat as target-validity evidence |
| Severe_Disease label with eGFR at least 90 | 103 | discordant with any simple eGFR severity interpretation | do not relabel or delete; treat as target-validity evidence |
| No_Disease label with serum creatinine above 10 mg/dl | 5637 | clinically discordant or unit/source error | do not relabel or delete; target and provenance are unverified |
| all individually bounded numeric values | 575064 | mostly plausible ranges; distribution shape suspicious | preserve exactly; no value clipping, row deletion, or cleaned copy |

No row was deleted, clipped, corrected, relabeled, or written to a cleaned dataset.
Median/mode imputers remain inside research pipelines but see no missing values in this
snapshot.

## 7. Target formulation decision

- A, original five-class: rejected for deployment; retained only to audit source labels.
- B, any non-`No_Disease` versus `No_Disease`: rejected for deployment; used only as a
  binary negative control because risk labels are not diagnoses.
- C, moderate/high/severe collapse: rejected without modeling because its boundary is
  arbitrary and undocumented.
- D, do not deploy: selected. Final outcome: **C. Dataset has serious target/provenance issues and should not be deployed**.

## 8. Full-feature results

The table below reports the best observed candidate per formulation/feature set only for
compact comparison. It does not select a deployable model. Full candidate/fold metrics
are in `cv_results.csv`, `fold_metrics.csv`, and `candidate_evaluations.json`.

| Formulation | Feature set | N | Comparator | Balanced accuracy | Macro/binary F1 | ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| original_five_class | full_42 | 42 | Random Forest (balanced) | 0.1995 | 0.1795 | 0.4937 |
| original_five_class | biomarker_excluded_14 | 14 | Random Forest (balanced) | 0.1993 | 0.1873 | 0.4925 |
| original_five_class | eldercare_non_lab_12 | 12 | Random Forest (balanced) | 0.1955 | 0.1928 | 0.4957 |
| original_five_class | compact_home_7 | 7 | Random Forest (balanced) | 0.2039 | 0.2022 | 0.5036 |
| binary_any_non_no_disease | full_42 | 42 | Logistic Regression | 0.5000 | 0.0000 | 0.5111 |
| binary_any_non_no_disease | biomarker_excluded_14 | 14 | Logistic Regression | 0.5000 | 0.0000 | 0.5065 |
| binary_any_non_no_disease | eldercare_non_lab_12 | 12 | Logistic Regression | 0.5000 | 0.0000 | 0.5069 |
| binary_any_non_no_disease | compact_home_7 | 7 | Logistic Regression (balanced) | 0.4995 | 0.2838 | 0.5028 |

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
regression) produced OOF matrix `[[8414, 8018],
[2046, 2060]]` with precision
0.2044, recall 0.5017,
specificity 0.5120, and F1
0.2905. All matrices and per-class precision/recall/F1/support
are in `confusion_matrices.json` and `class_level_metrics.csv`.

## 13. Calibration results

For that negative-control reference, OOF Brier score is
0.2500 and 10-bin ECE is
0.2995. These diagnostics are not a personal
disease-probability validation because the labels themselves are unverified.

## 14. Elderly subgroup analysis

| Subgroup | Rows | Balanced accuracy | ROC-AUC | F1 |
| --- | --- | --- | --- | --- |
| age_60_or_older | 7411 | 0.5042 | 0.5015 | 0.2372 |
| age_65_or_older | 6247 | 0.5026 | 0.5000 | 0.2299 |

Numerically adequate subgroup sizes cannot rescue invalid outcome semantics. No elderly
clinical validity is claimed.

## 15. Final deployment decision

**C. Dataset has serious target/provenance issues and should not be deployed.** No kidney model is selected for ElderCareBD, including
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

- DiaBD diabetes v3: 6 inputs—
  age, gender, systolic_bp, diastolic_bp, glucose, bmi. Explicit random-session
  mmol/L glucose context remains essential.
- Heart v2: 4 inputs—
  age, sex, cp, trestbps. Exact binary clinical sex,
  four-class chest-pain type, and resting systolic BP are required.
- Kidney: no selected artifact and zero authorized inputs.

`three_disease_contract_summary.json` contains measurement burden, classification
semantics, and main limitations for all three.

## 20. Tests and results

The reproducible entry point performs hash gates and writes all audit outputs. Run the
complete suite from the repository root with:

```powershell
.\ml_training\venv\Scripts\python.exe -B -m unittest discover -s ml_training/tests -p "test_*.py" -v
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

**Task 13C: COMPLETE. Task 14 remains PAUSED.**
