# ElderCareBD live disease-risk inference

Task 14 connects the final Task 13B DiaBD v3 and Task 13 Heart v2 research
artifacts to the authenticated FastAPI application. It does not retrain either
model and it does not treat a model score as a diagnosis or as a validated
personal probability of disease.

## Live workflow

```text
Caregiver provides model-compatible measurements
-> Flutter keeps the measurement context explicit
-> FastAPI authenticates the caregiver and verifies patient ownership
-> the backend validates the trusted model feature contract
-> the saved scikit-learn pipeline applies its fitted preprocessing
-> Logistic Regression generates a model risk score
-> the recorded threshold generates a binary screening classification
-> the backend stores the result and provenance with the assessment
-> result and history screens display the source and limitation
```

The two model calls are independent. Missing or unsupported input for one model
does not prevent the general health assessment or the other model from being
saved. In that case the unchanged client demonstration heuristic remains
available and is labelled `heuristic_demo_v1`; it is not presented as an ML
result.

## Trusted runtime

Only `diabetes_model_v3_diabd.pkl` and `heart_model_v2.pkl`, with their fixed
adjacent metadata files, are accepted by the application loader. Both the
metadata and artifact SHA-256 values are pinned in code and checked against the
same immutable bytes that are later parsed or deserialized. The loader then
verifies artifact/metadata identity, feature order and specifications, model
version, estimator identity, classification threshold, and output class order.
No runtime API accepts a caller-controlled model root or path. The historical
Pima v2 artifact remains unchanged as a research comparator but is not eligible
for primary application inference.

The service loads each model once per backend process. A missing dependency,
hash mismatch, metadata mismatch, deserialization error, or failed smoke test
disables only that model. FastAPI continues to serve authentication, health
records, history, medicine, and prescription functions. Prediction attempts
for a disabled model return a sanitized `503`; filesystem paths and Python
exceptions are never returned to Flutter.

The backend inference environment is pinned to Python 3.13 and these serialized
stack versions:

- NumPy 2.5.1
- pandas 3.0.3
- SciPy 1.18.0
- scikit-learn 1.9.0
- joblib 1.5.3

Matplotlib remains training/report-only and is not a backend dependency.

## Explicit feature contracts

DiaBD diabetes v3 uses, in exact order, `age`, `gender`, `systolic_bp`,
`diastolic_bp`, `glucose`, and `bmi`. Gender is the source dataset's exact
`Female=0` / `Male=1` mapping; `Other` and unknown values are unsupported.
Blood pressure must be a valid measured pair with DBP below SBP. `glucose` is a
decimal random-session glucometer reading in mmol/L (1.00-33.46), not the
historical Pima 2-hour OGTT field, a generic glucose value, or a silently
converted mg/dL value. The development threshold is 0.06. This model scores
contemporaneous recorded diabetic status in DiaBD; it is neither a future-risk
model nor a diagnosis. Patients with diabetes already recorded bypass DiaBD
screening and receive no fabricated score.

Heart v2 uses `age`, `sex`, `cp`, and `trestbps`. Clinical sex follows the
binary Cleveland metadata labels; an unknown or `Other` profile value is not
converted. `cp` is the four-category Cleveland chest-pain type and is never
derived from the yes/no symptom field. `trestbps` is explicitly confirmed
resting systolic blood pressure. The final development threshold is 0.53.

The UI obtains category labels and supported ranges from the authenticated
`GET /predictions/contracts` endpoint. Authenticated, ownership-scoped inference
is exposed only at `POST /predictions/diabetes` and
`POST /predictions/heart`. Inputs outside the observed Task 13 support are not scored;
the general assessment can still be saved with a recorded fallback status.

The only ML classification labels are:

- `below_model_threshold`
- `at_or_above_model_threshold`

There is no validated model `Medium` band and no combined overall ML score.

## Research basis and limitations

Task 13B selected the reduced six-feature unweighted Logistic Regression trained
on the local 5,288-row Bangladesh DiaBD snapshot. Its low 0.06 threshold is a
development screening operating point, not a clinical diagnostic cutoff.

The deployable heart model is the reduced four-feature class-balanced Logistic
Regression. It materially outperformed the currently faithful age/sex/resting
pressure subset while avoiding seven specialist-test features required by the
full thirteen-feature model. Its structured chest-pain type and clinical-sex
semantics are mandatory.

DiaBD is Bangladesh-specific but is not an elderly-only cohort and does not
document a diagnostic reference standard, diabetes type, medication status,
site/time/person identifiers, or prospective outcome. The heart data are small
historical Cleveland clinical/referral cases with limited elderly
representation. Model selection and thresholds were evaluated internally; no
prospective clinical validation or deployment-population calibration has been
performed. Every live score is therefore research/demo screening support only
and must be interpreted by a qualified clinician alongside the patient's full
context.

Kidney model integration was withheld because the audited dataset lacked
defensible target/provenance validity. No kidney model artifact, prediction
route, UI contract, assessment provenance, or result is deployed.

Detailed metrics, data provenance caveats, calibration plots, and selection
evidence remain in the Task 13, Task 13B, and Task 13C reports under
`ml_training/outputs/`.
