# ElderCareBD Task 13 ML Development Report

Generated: 2026-08-23T13:42:30+00:00

These models are research screening/risk-score models, not diagnostic devices. Neither dataset validates performance for Bangladeshi elders.

## Dataset audit

### Diabetes

- Local file: `data/diabetes.csv`
- SHA-256: `698C203A14AA31941D2251175330C9199F3CCDB31597ABBBA2A3E35416257A72`
- Shape: 768 rows, 9 columns
- Target: `Outcome`; distribution {'0': 500, '1': 268}
- Target definition: The commonly documented Pima benchmark outcome forecasts diabetes onset within five years under the source study's WHO-based criteria. Because the repository lacks a byte-level provenance manifest, this is retained as the source-label interpretation rather than asserted as a current clinical diagnosis.
- Missing-value convention: No explicit null markers are present. Zero is an invalid/missing sentinel for Glucose, BloodPressure, SkinThickness, Insulin, and BMI; zero Pregnancies is valid. Sentinel conversion occurs inside the pipeline.
- Invalid-zero counts: {'Glucose': 5, 'BloodPressure': 35, 'SkinThickness': 227, 'Insulin': 374, 'BMI': 11}
- Exact/predictor duplicates: 0/0
- Source: Pima Indians Diabetes Database, originally owned by the US National Institute of Diabetes and Digestive and Kidney Diseases (https://pmc.ncbi.nlm.nih.gov/articles/PMC2245318/)
- Matching distribution reference: https://www.kaggle.com/datasets/uciml/pima-indians-diabetes-database
- License/provenance note: The matching distribution page labels its copy CC0, but the repository does not include a provenance or license manifest tying that grant to these exact bytes.
- Age support: {'age_60_or_older': 32, 'age_65_or_older': 16}
- Limitation: All subjects were women at least 21 years old of Pima Indian heritage near Phoenix, Arizona. The data are not representative validation for Bangladeshi elders, men, or gender-diverse patients.

### Heart Disease

- Local file: `data/heart_cleveland_upload.csv`
- SHA-256: `386015BE85BCC9112CBAC782DAFD145AEEF7ABD4F8B9F2EE65F6C4C56ED82D9F`
- Shape: 297 rows, 14 columns
- Target: `condition`; distribution {'0': 160, '1': 137}
- Target definition: Binary recoding of the Cleveland diagnostic num target: 0 means no angiographic disease and 1 represents original values greater than zero.
- Missing-value convention: The 297-row derivative has no null or '?' markers. It is a complete-case transformation of the 303-row upstream Cleveland data, which does contain missing values.
- Invalid-zero counts: {}
- Exact/predictor duplicates: 0/0
- Source: UCI Heart Disease, Cleveland processed-data derivative (https://archive.ics.uci.edu/dataset/45/heart+disease)
- Matching distribution reference: https://www.kaggle.com/datasets/cherngs/heart-disease-cleveland-uci/data
- License/provenance note: UCI publishes the upstream dataset under CC BY 4.0. The repository does not include a local provenance/license manifest for this transformed copy.
- Age support: {'age_60_or_older': 91, 'age_65_or_older': 41}
- Limitation: Historical Cleveland clinical/referral cases are not a Bangladeshi or elderly-community cohort; only a small minority of local rows are age 65 or older. The target denotes disease presence, not future event risk.

## ElderCare-friendly feature contracts and cleaning

The full dataset-to-UI use/drop matrix is in `feature_compatibility.csv`. No UI symptom, prior diagnosis, stored risk label, or fabricated default was added to either model.

### Diabetes selected contract

Predefined deployable set: `eldercare_reduced_3` in exact order `['Age', 'Glucose', 'BMI']`.

| Feature | Type | Unit | Accepted training support/categories | Task 14 condition |
|---|---|---|---|---|
| `Age` | integer | years | 21 to 81 | Values outside the training range are unsupported and need a fallback. |
| `Glucose` | number | mg/dL | 44 to 199 | Clarify timing/test context and units in the assessment UI before model integration. |
| `BMI` | number | kg/m^2 | 18.2 to 67.1 | Values outside the training range are unsupported and need a fallback. |

Measurement semantics: Completed age at assessment; 21-81 is the observed source-data range. Two-hour plasma glucose from an oral glucose tolerance test, matching the Pima dataset; a generic, fasting, or random reading must not be silently substituted. BMI computed from measured height and weight; 18.2-67.1 is the observed non-missing source-data range.

### Heart Disease selected contract

Predefined deployable set: `eldercare_structured_cp_4` in exact order `['age', 'sex', 'cp', 'trestbps']`.

| Feature | Type | Unit | Accepted training support/categories | Task 14 condition |
|---|---|---|---|---|
| `age` | integer | years | 29 to 77 | Values outside the training range are unsupported and need a fallback. |
| `sex` | integer | none | 0=female, 1=male | The source dataset has no category for Other/unknown. Do not fabricate a mapping; route unsupported values to a non-model fallback. |
| `cp` | integer | none | 0=typical angina, 1=atypical angina, 2=non-anginal pain, 3=asymptomatic | Add a guided four-category field. Never derive this value from the current boolean chest_pain field. |
| `trestbps` | integer | mmHg | 94 to 200 | Use an explicitly resting systolic measurement; do not map diastolic BP. |

Measurement semantics: Completed age at assessment; 29-77 is the observed source-data range. Binary coding used by the Cleveland dataset. Four-level chest-pain type in this zero-based Cleveland derivative; it is not equivalent to a yes/no chest-pain symptom. Resting blood pressure matching the Cleveland trestbps field (conventionally systolic; source setting was hospital admission).

Cleaning is serialized with each artifact: exact named-column validation, Pima impossible-zero conversion inside the pipeline, fold-local imputation, numeric scaling for Logistic Regression and MLP, and explicit-category one-hot encoding for Cleveland categorical fields. Random Forest uses the same fold-local data contract without numeric scaling.

Candidate models were fixed before evaluation: unweighted Logistic Regression, balanced Logistic Regression, balanced Random Forest, and a deterministic scikit-learn MLP evaluated separately because the legacy training/UI materials mention a neural network. The MLP is exploratory; it is not added merely to chase one metric and receives no deployment preference over simpler interpretable candidates.

## Five-fold candidate results

Classification metrics below are mean +/- population standard deviation at threshold 0.50; ROC-AUC uses probability scores and is threshold-independent. Preprocessing was inside each fold.

| Disease | Feature set | Model | Accuracy | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---:|---:|---:|---:|---:|
| Diabetes | full_8 | Logistic Regression | 0.7721 +/- 0.0166 | 0.7261 +/- 0.0617 | 0.5711 +/- 0.0474 | 0.6358 +/- 0.0210 | 0.8366 +/- 0.0203 |
| Diabetes | full_8 | Logistic Regression (balanced) | 0.7473 +/- 0.0403 | 0.6234 +/- 0.0627 | 0.7274 +/- 0.0466 | 0.6688 +/- 0.0402 | 0.8362 +/- 0.0201 |
| Diabetes | full_8 | Random Forest (balanced) | 0.7630 +/- 0.0199 | 0.6458 +/- 0.0314 | 0.7166 +/- 0.0348 | 0.6785 +/- 0.0236 | 0.8320 +/- 0.0177 |
| Diabetes | full_8 | Neural Network (MLP, exploratory) | 0.7551 +/- 0.0259 | 0.7114 +/- 0.0790 | 0.5222 +/- 0.0761 | 0.5961 +/- 0.0459 | 0.8287 +/- 0.0205 |
| Diabetes | caregiver_no_lab_2 | Logistic Regression | 0.6914 +/- 0.0429 | 0.5981 +/- 0.1023 | 0.3693 +/- 0.0689 | 0.4543 +/- 0.0736 | 0.7349 +/- 0.0347 |
| Diabetes | caregiver_no_lab_2 | Logistic Regression (balanced) | 0.6575 +/- 0.0347 | 0.5111 +/- 0.0422 | 0.6566 +/- 0.0208 | 0.5733 +/- 0.0228 | 0.7352 +/- 0.0349 |
| Diabetes | caregiver_no_lab_2 | Random Forest (balanced) | 0.6601 +/- 0.0313 | 0.5135 +/- 0.0348 | 0.6604 +/- 0.0325 | 0.5762 +/- 0.0180 | 0.7174 +/- 0.0373 |
| Diabetes | caregiver_no_lab_2 | Neural Network (MLP, exploratory) | 0.6888 +/- 0.0272 | 0.5757 +/- 0.0510 | 0.3914 +/- 0.0881 | 0.4628 +/- 0.0760 | 0.7532 +/- 0.0400 |
| Diabetes | caregiver_no_glucose_3 | Logistic Regression | 0.6901 +/- 0.0357 | 0.5932 +/- 0.0856 | 0.3693 +/- 0.0593 | 0.4533 +/- 0.0621 | 0.7325 +/- 0.0362 |
| Diabetes | caregiver_no_glucose_3 | Logistic Regression (balanced) | 0.6549 +/- 0.0441 | 0.5092 +/- 0.0515 | 0.6565 +/- 0.0219 | 0.5720 +/- 0.0334 | 0.7321 +/- 0.0361 |
| Diabetes | caregiver_no_glucose_3 | Random Forest (balanced) | 0.6654 +/- 0.0420 | 0.5174 +/- 0.0469 | 0.6603 +/- 0.0582 | 0.5795 +/- 0.0483 | 0.7043 +/- 0.0364 |
| Diabetes | caregiver_no_glucose_3 | Neural Network (MLP, exploratory) | 0.6888 +/- 0.0279 | 0.6116 +/- 0.0918 | 0.3509 +/- 0.1291 | 0.4267 +/- 0.1058 | 0.7325 +/- 0.0316 |
| Diabetes | eldercare_reduced_3 | Logistic Regression | 0.7656 +/- 0.0289 | 0.7161 +/- 0.0708 | 0.5599 +/- 0.0340 | 0.6258 +/- 0.0316 | 0.8253 +/- 0.0305 |
| Diabetes | eldercare_reduced_3 | Logistic Regression (balanced) | 0.7395 +/- 0.0434 | 0.6171 +/- 0.0656 | 0.6937 +/- 0.0474 | 0.6512 +/- 0.0478 | 0.8255 +/- 0.0312 |
| Diabetes | eldercare_reduced_3 | Random Forest (balanced) | 0.7525 +/- 0.0333 | 0.6281 +/- 0.0491 | 0.7391 +/- 0.0290 | 0.6770 +/- 0.0237 | 0.8193 +/- 0.0411 |
| Diabetes | eldercare_reduced_3 | Neural Network (MLP, exploratory) | 0.7682 +/- 0.0281 | 0.7354 +/- 0.0844 | 0.5448 +/- 0.0790 | 0.6187 +/- 0.0549 | 0.8356 +/- 0.0352 |
| Diabetes | eldercare_reduced_4 | Logistic Regression | 0.7643 +/- 0.0275 | 0.7114 +/- 0.0682 | 0.5599 +/- 0.0340 | 0.6243 +/- 0.0322 | 0.8247 +/- 0.0299 |
| Diabetes | eldercare_reduced_4 | Logistic Regression (balanced) | 0.7369 +/- 0.0441 | 0.6148 +/- 0.0677 | 0.6900 +/- 0.0442 | 0.6480 +/- 0.0464 | 0.8239 +/- 0.0304 |
| Diabetes | eldercare_reduced_4 | Random Forest (balanced) | 0.7538 +/- 0.0414 | 0.6299 +/- 0.0586 | 0.7390 +/- 0.0362 | 0.6783 +/- 0.0393 | 0.8197 +/- 0.0393 |
| Diabetes | eldercare_reduced_4 | Neural Network (MLP, exploratory) | 0.7395 +/- 0.0233 | 0.7237 +/- 0.0923 | 0.4560 +/- 0.1140 | 0.5415 +/- 0.0766 | 0.8293 +/- 0.0262 |
| Heart Disease | full_13 | Logistic Regression | 0.8454 +/- 0.0483 | 0.8691 +/- 0.0647 | 0.7889 +/- 0.0724 | 0.8245 +/- 0.0547 | 0.9142 +/- 0.0387 |
| Heart Disease | full_13 | Logistic Regression (balanced) | 0.8387 +/- 0.0472 | 0.8452 +/- 0.0669 | 0.8034 +/- 0.0572 | 0.8219 +/- 0.0489 | 0.9137 +/- 0.0383 |
| Heart Disease | full_13 | Random Forest (balanced) | 0.8220 +/- 0.0621 | 0.8081 +/- 0.0554 | 0.8040 +/- 0.0939 | 0.8050 +/- 0.0719 | 0.9050 +/- 0.0474 |
| Heart Disease | full_13 | Neural Network (MLP, exploratory) | 0.7847 +/- 0.0492 | 0.7790 +/- 0.0684 | 0.7524 +/- 0.0450 | 0.7642 +/- 0.0481 | 0.8453 +/- 0.0372 |
| Heart Disease | inclusive_current_ui_2 | Logistic Regression | 0.6059 +/- 0.0768 | 0.5780 +/- 0.0931 | 0.5029 +/- 0.1164 | 0.5369 +/- 0.1068 | 0.6423 +/- 0.1154 |
| Heart Disease | inclusive_current_ui_2 | Logistic Regression (balanced) | 0.6328 +/- 0.0828 | 0.5868 +/- 0.0766 | 0.6632 +/- 0.1266 | 0.6216 +/- 0.0975 | 0.6416 +/- 0.1149 |
| Heart Disease | inclusive_current_ui_2 | Random Forest (balanced) | 0.5420 +/- 0.0255 | 0.5044 +/- 0.0306 | 0.5317 +/- 0.0737 | 0.5150 +/- 0.0407 | 0.5592 +/- 0.0341 |
| Heart Disease | inclusive_current_ui_2 | Neural Network (MLP, exploratory) | 0.5622 +/- 0.0348 | 0.4923 +/- 0.2780 | 0.1455 +/- 0.0977 | 0.2193 +/- 0.1387 | 0.6143 +/- 0.1195 |
| Heart Disease | current_ui_3 | Logistic Regression | 0.6533 +/- 0.0640 | 0.6363 +/- 0.0862 | 0.6198 +/- 0.0713 | 0.6232 +/- 0.0578 | 0.6991 +/- 0.0382 |
| Heart Disease | current_ui_3 | Logistic Regression (balanced) | 0.6366 +/- 0.0424 | 0.5989 +/- 0.0460 | 0.6714 +/- 0.0622 | 0.6300 +/- 0.0340 | 0.6996 +/- 0.0384 |
| Heart Disease | current_ui_3 | Random Forest (balanced) | 0.6163 +/- 0.0217 | 0.5686 +/- 0.0203 | 0.7146 +/- 0.0657 | 0.6312 +/- 0.0210 | 0.6616 +/- 0.0383 |
| Heart Disease | current_ui_3 | Neural Network (MLP, exploratory) | 0.5388 +/- 0.0044 | 0.0000 +/- 0.0000 | 0.0000 +/- 0.0000 | 0.0000 +/- 0.0000 | 0.6130 +/- 0.0853 |
| Heart Disease | structured_cp_no_sex_3 | Logistic Regression | 0.7309 +/- 0.0473 | 0.7093 +/- 0.0494 | 0.7090 +/- 0.0645 | 0.7081 +/- 0.0519 | 0.7976 +/- 0.0520 |
| Heart Disease | structured_cp_no_sex_3 | Logistic Regression (balanced) | 0.7173 +/- 0.0367 | 0.6840 +/- 0.0468 | 0.7310 +/- 0.0585 | 0.7044 +/- 0.0352 | 0.7981 +/- 0.0523 |
| Heart Disease | structured_cp_no_sex_3 | Random Forest (balanced) | 0.7210 +/- 0.0810 | 0.6832 +/- 0.0812 | 0.7315 +/- 0.1228 | 0.7047 +/- 0.0971 | 0.7888 +/- 0.0679 |
| Heart Disease | structured_cp_no_sex_3 | Neural Network (MLP, exploratory) | 0.6304 +/- 0.1046 | 0.6824 +/- 0.2646 | 0.3402 +/- 0.2660 | 0.3987 +/- 0.2840 | 0.6112 +/- 0.2027 |
| Heart Disease | eldercare_structured_cp_4 | Logistic Regression | 0.7747 +/- 0.0403 | 0.7595 +/- 0.0459 | 0.7529 +/- 0.0665 | 0.7545 +/- 0.0443 | 0.8364 +/- 0.0417 |
| Heart Disease | eldercare_structured_cp_4 | Logistic Regression (balanced) | 0.7781 +/- 0.0474 | 0.7562 +/- 0.0459 | 0.7677 +/- 0.0740 | 0.7607 +/- 0.0533 | 0.8366 +/- 0.0413 |
| Heart Disease | eldercare_structured_cp_4 | Random Forest (balanced) | 0.7578 +/- 0.0347 | 0.7322 +/- 0.0473 | 0.7598 +/- 0.0785 | 0.7421 +/- 0.0417 | 0.8097 +/- 0.0648 |
| Heart Disease | eldercare_structured_cp_4 | Neural Network (MLP, exploratory) | 0.5388 +/- 0.0044 | 0.0000 +/- 0.0000 | 0.0000 +/- 0.0000 | 0.0000 +/- 0.0000 | 0.4435 +/- 0.0801 |
| Heart Disease | structured_cp_plus_fbs_5 | Logistic Regression | 0.7747 +/- 0.0403 | 0.7595 +/- 0.0459 | 0.7529 +/- 0.0665 | 0.7545 +/- 0.0443 | 0.8351 +/- 0.0434 |
| Heart Disease | structured_cp_plus_fbs_5 | Logistic Regression (balanced) | 0.7747 +/- 0.0440 | 0.7480 +/- 0.0439 | 0.7749 +/- 0.0664 | 0.7599 +/- 0.0471 | 0.8353 +/- 0.0434 |
| Heart Disease | structured_cp_plus_fbs_5 | Random Forest (balanced) | 0.7511 +/- 0.0453 | 0.7240 +/- 0.0485 | 0.7526 +/- 0.0811 | 0.7351 +/- 0.0506 | 0.8147 +/- 0.0637 |
| Heart Disease | structured_cp_plus_fbs_5 | Neural Network (MLP, exploratory) | 0.6837 +/- 0.0868 | 0.7374 +/- 0.1326 | 0.4974 +/- 0.1446 | 0.5855 +/- 0.1195 | 0.7736 +/- 0.0756 |

## ROC-AUC and calibration observations

ROC-AUC measures ranking discrimination: an AUC of 0.83 means that, within these internal validation predictions, a randomly chosen positive-labelled record receives a higher score than a randomly chosen negative-labelled record about 83% of the time. It does not say that a patient has an 83% chance of disease, and it does not establish clinical utility.

- **Diabetes:** mean 5-fold ROC-AUC 0.8253 +/- 0.0305; pooled OOF ROC-AUC 0.8259; Brier score 0.1603; log loss 0.4847; fixed-width 10-bin ECE 0.0297.
- **Heart Disease:** mean 5-fold ROC-AUC 0.8366 +/- 0.0413; pooled OOF ROC-AUC 0.8336; Brier score 0.1652; log loss 0.5047; fixed-width 10-bin ECE 0.0574.

The reliability plots are reasonably close to the diagonal in parts of each development sample but fluctuate, especially for the smaller heart dataset. These are diagnostics, not fitted external calibrations. Population shift, small samples, class weighting, and absence of a Bangladeshi validation cohort make the raw scores unsuitable as personal disease probabilities.

## Selections

### Diabetes

- Best experimental: `full_8` / Logistic Regression
- Selected deployable: `eldercare_reduced_3` / Logistic Regression
- Exact feature order: `['Age', 'Glucose', 'BMI']`
- Final development threshold: 0.31
- Nested-policy confusion matrix: `[[350, 150], [62, 206]]`
- Nested-policy recall: 0.7687
- Nested-policy F1: 0.6603
- Artifact: `models/diabetes_model_v2.pkl` (2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07)
- Rationale: Age, exact two-hour OGTT glucose, and BMI retain most full-model discrimination while removing five impractical fields. Diastolic BP was evaluated but added no useful discrimination. Unweighted logistic regression is compact/interpretable and had materially better internal calibration than the balanced variant; nested thresholding recovers screening sensitivity.

### Heart Disease

- Best experimental: `full_13` / Logistic Regression
- Selected deployable: `eldercare_structured_cp_4` / Logistic Regression (balanced)
- Exact feature order: `['age', 'sex', 'cp', 'trestbps']`
- Final development threshold: 0.53
- Nested-policy confusion matrix: `[[128, 32], [37, 100]]`
- Nested-policy recall: 0.7299
- Nested-policy F1: 0.7435
- Artifact: `models/heart_model_v2.pkl` (E0007FA3135DBF97B5E15D2C9B0BEAF385928DE54D814566F4877D712FE4A103)
- Rationale: The four-field structured contract materially outperformed the currently faithful age/sex/resting-BP subset while avoiding seven specialist tests. Balanced logistic regression modestly improved screening recall with essentially unchanged AUC and calibration. Task 14 must collect exact chest-pain type and binary clinical sex, and must not map boolean chest pain or Other/unknown values.

## Legacy comparison

- Diabetes legacy artifact: eight predictors and a Random Forest; its saved pipeline omits the zero-sentinel normalization used before legacy CV. The v2 artifact uses three fields and contains the complete preprocessing chain.
- Heart legacy artifact: thirteen predictors and ordinal scaling of nominal codes. The v2 artifact uses four fields and explicit one-hot categories.
- Both legacy artifacts are retained under their original names and verified against their pre-Task-13 SHA-256 values.

## Leakage and calibration conclusions

- No target-derived features or oversampling were used.
- Exact and predictor duplicates were rejected.
- Sentinel conversion, imputation, scaling, and one-hot encoding stayed inside each fold.
- Threshold-policy performance was estimated with nested CV; the final fitted threshold still needs external validation.
- Reliability curves, Brier scores, and log loss are internal diagnostics only. A score must not be described as a patient's chance of disease.
- Model/feature selection used these same small datasets, so all estimates remain development estimates without an external test cohort.

## Reproduction

From `ml_training`: `venv\Scripts\python.exe train_models_v2.py`

Pinned dependencies are in `requirements-ml.txt`. The loader contract is `ml_training.eldercare_ml.loading.load_verified_artifact`, which verifies the metadata hash before deserialization.

Validation command: `venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v`.

Task 13: COMPLETE
