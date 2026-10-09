# Task 13C target-construction report

## Conclusion

The supplied `Target` cannot be justified as an independently observed diagnosis,
clinical CKD stage, disease-severity measure, or prospective risk outcome. The five
labels therefore must not be deployed or presented as CKD stages.

## Evidence available

- No diagnostic rule, clinician adjudication, source institution, collection period,
  outcome horizon, or target derivation is documented.
- The closest public listing is https://www.kaggle.com/datasets/amanik000/kidney-disease-dataset and reports an
  unknown license; it does not fill these gaps.
- eGFR-band versus target Cramer's V is 0.0121
  (chi-square p=0.9137), showing negligible association.
- eGFR versus serum creatinine correlation is
  -0.0041; eGFR versus cystatin C is
  -0.0060.
- 1,491 `No_Disease` rows have eGFR below 15,
  while 103 `Severe_Disease` rows have
  eGFR at least 90.
- 9,963 rows say diabetes=no while recording
  positive diabetes duration; 9,879
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
