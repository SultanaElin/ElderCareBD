# ElderCareBD Task 13 ML pipelines

Task 13 develops two research screening models without integrating them into
Flutter or FastAPI. The checked-in legacy artifacts remain the active historical
baseline; Task 14 must perform any application integration separately.

## Environment

Use a dedicated Python environment so ML packages do not alter the backend runtime:

```powershell
cd ml_training
py -3.13 -m venv .task13-venv
.\.task13-venv\Scripts\python.exe -m pip install -r requirements-ml.txt
```

The repository currently also contains `ml_training/venv`; it was used for this audited
run because it exactly matched the pinned manifest. A checked-in virtual environment is
not itself portable and should not replace the manifest.

## Reproduce training

```powershell
cd ml_training
.\venv\Scripts\python.exe train_models_v2.py
```

For a deterministic metadata timestamp in a controlled rebuild:

```powershell
.\venv\Scripts\python.exe train_models_v2.py --created-at 2026-08-23T00:00:00+00:00
```

The command validates exact dataset schemas and approved SHA-256 snapshots, evaluates
fixed Logistic Regression and Random Forest candidates plus a separately labelled
exploratory MLP (retained because legacy project materials mention a neural network),
using shuffled stratified 5-fold cross-validation (seed 42). It applies preprocessing
inside every fold, evaluates the screening threshold policy with nested CV, fits the
selected pipelines on all available development data, and writes:

- `models/diabetes_model_v2.pkl`
- `models/diabetes_model_v2.metadata.json`
- `models/heart_model_v2.pkl`
- `models/heart_model_v2.metadata.json`
- detailed machine-readable results and plots under `outputs/task13/`

The command refuses to proceed if either legacy artifact hash differs from its audited
baseline. It never writes the legacy filenames.

## Load a v2 artifact safely

From the repository root, use the supported loader. It verifies the metadata-declared
SHA-256 before invoking joblib and checks the deserialized identity and feature order:

```python
from ml_training.eldercare_ml.loading import load_verified_artifact

model, metadata = load_verified_artifact("diabetes")
scores = model.predict_risk_score(
    {"Age": 55, "Glucose": 130, "BMI": 31.5}
)
```

The canonical pickle modules are under `ml_training.eldercare_ml`, so a fresh Python
process launched at the repository root can load them without manual `sys.path`
changes. If Task 14 launches Python from another working directory, it must place the
repository root—not a guessed model directory—on `PYTHONPATH` before importing this
loader. Formal installable-package metadata can be added during Task 14 if deployment
requires it; Task 13 does not alter the backend environment.

## Run tests

Run training once so the deployable artifacts exist, then:

```powershell
cd ml_training
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

## Important interpretation constraints

- Outputs are model risk scores and screening flags, not diagnoses or a patient's
  validated chance of disease.
- Pima glucose means a two-hour plasma glucose result from an oral glucose tolerance
  test. A generic glucose reading is not interchangeable.
- Cleveland `cp` is an exact four-level chest-pain-type category. The current Flutter
  yes/no chest-pain symptom cannot be mapped to it.
- Cleveland `sex` has only female/male source categories. Other/unknown must remain
  unscored rather than receiving a fabricated value.
- Input values outside observed training support are rejected.
- Neither dataset is a Bangladeshi elderly validation cohort. External, prospective,
  clinically governed validation is required before real clinical use.

Joblib uses pickle semantics. Load only repository-owned artifacts whose SHA-256 matches
their metadata, in a dependency-compatible environment.
