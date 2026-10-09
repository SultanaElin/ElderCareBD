# ElderCareBD Task 13C — kidney dataset audit

Task 13C evaluates the repository-owned kidney CSV without changing FastAPI, Flutter,
the authoritative database, prescription/OCR, OTP, or paused Task 14 code.

## Protected raw input

- `data/kidney_disease_dataset.csv`
- SHA-256: `4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199`
- Size: 5,483,328 bytes

The command verifies this file plus the existing DiaBD v3, heart v2, and Pima v2
artifacts before and after analysis. It never edits the raw CSV.

## Reproduce the audited run

From the repository root:

```powershell
.\ml_training\venv\Scripts\python.exe -B ml_training\train_kidney_audit.py --created-at 2026-09-06T00:00:00+06:00
```

Outputs are written only to `outputs/task13c/`. The run uses 5-fold shuffled stratified
cross-validation with seed 42 and fits imputation, scaling, and categorical encoding
inside each training fold.

## Decision

Task 13C returns Outcome C: the dataset has serious target/provenance problems and must
not be deployed. The five labels have no documented clinical definitions and show no
coherent association with eGFR, creatinine, cystatin C, or other kidney measurements.
Many history/duration combinations are internally impossible.

No kidney model artifact or runtime feature contract is created. The fitted estimators
are negative-control research comparisons only; they are not saved.

## Tests

```powershell
.\ml_training\venv\Scripts\python.exe -B -m unittest discover -s ml_training/tests -p "test_*.py" -v
```

Task 14 remains paused. A new licensed, traceable cohort with an independently defined
CKD outcome and elderly/Bangladesh-relevant validation is required before integration.
