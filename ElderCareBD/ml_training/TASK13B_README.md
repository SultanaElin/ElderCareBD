# ElderCareBD Task 13B — DiaBD diabetes model evaluation

Task 13B evaluates the repository-owned Bangladesh DiaBD snapshot against the existing
Pima v2 diabetes benchmark. It does not integrate a model into FastAPI or Flutter and
does not change Task 14, the database, prescription/OCR, OTP, or kidney modelling.

## Protected local inputs

- `data/DiaBD_A Diabetes Dataset for Enhanced Risk Analysis and Research in Bangladesh.csv`
  - SHA-256: `D9F868C9CE8EEFE545294156ED1626F60FDB33F507F9CA021FD34FA4B575741A`
- `data/kidney_disease_dataset.csv`
  - SHA-256: `4A73DF2405F6E102257887502329CC5EC79DB3BD4729D00DA9C96698D8C05199`
- `models/diabetes_model_v2.pkl`
  - SHA-256: `2CF6B92BEF3A452DD680A9B37E1FAE5B788BADCB55B4A4EE6A4CFB90F46DCA07`

The command verifies these hashes before and after training. It never modifies either
raw dataset and never overwrites the Pima v2 artifact.

## Reproduce the audited run

From the repository root:

```powershell
.\ml_training\venv\Scripts\python.exe -B ml_training\train_diabd_v3.py --created-at 2026-09-02T00:00:00+06:00
```

Generated files are written to:

- `models/diabetes_model_v3_diabd.pkl`
- `models/diabetes_model_v3_diabd.metadata.json`
- `outputs/task13b/`

## Selected contract

The selected research/demo model is an unweighted logistic regression using this exact
order:

1. `age` in years
2. published DiaBD `gender` category encoded Female=`0`, Male=`1`
3. `systolic_bp` in mmHg
4. `diastolic_bp` in mmHg
5. random-session glucometer `glucose` in mmol/L
6. `bmi` in kg/m^2

Glucose is not documented as fasting, postprandial, or two-hour OGTT. Those contexts
must not be silently substituted. Other or unknown gender is outside the source
contract and must use a fallback rather than a fabricated category.

## Safe loading

The supported loader checks the fixed metadata schema and verifies the artifact's
SHA-256 before deserializing trusted repository bytes:

```python
from ml_training.eldercare_ml.diabd_loading import load_verified_diabd_artifact

model, metadata = load_verified_diabd_artifact()
score = model.predict_risk_score(
    {
        "age": 55,
        "gender": 1,
        "systolic_bp": 130,
        "diastolic_bp": 80,
        "glucose": 7.5,
        "bmi": 25.0,
    }
)
```

## Tests

Run training once, then execute:

```powershell
cd ml_training
.\venv\Scripts\python.exe -B -m unittest discover -s tests -p "test_*.py" -v
```

## Interpretation limits

- The DiaBD target is contemporaneous recorded diabetic status, not future onset.
- Random glucose may be a concurrent diagnostic proxy; incorporation bias is unknown.
- Internal random cross-validation is not external Bangladeshi elderly validation.
- The score is not a diagnosis, treatment recommendation, or calibrated personal risk.
- Task 14 must preserve the existing heuristic and Pima provenance when integration resumes.
