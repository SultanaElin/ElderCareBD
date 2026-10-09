"""Dataset and inference contracts used by the Task 13 training pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


RANDOM_SEED = 42
CV_FOLDS = 5
MODEL_VERSION = "2.0.0"


@dataclass(frozen=True)
class FeatureSpec:
    """One required inference field in a deployable artifact."""

    name: str
    data_type: str
    unit: str | None
    minimum: float | None = None
    maximum: float | None = None
    allowed_values: tuple[int, ...] | None = None
    value_labels: dict[int, str] | None = None
    measurement_context: str | None = None
    task14_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.data_type,
            "unit": self.unit,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "allowed_values": (
                list(self.allowed_values) if self.allowed_values is not None else None
            ),
            "value_labels": (
                {str(key): value for key, value in self.value_labels.items()}
                if self.value_labels is not None
                else None
            ),
            "measurement_context": self.measurement_context,
            "task14_note": self.task14_note,
        }


@dataclass(frozen=True)
class DatasetConfig:
    """Static schema and experiment design for one disease dataset."""

    disease: str
    display_name: str
    filename: str
    target: str
    required_columns: tuple[str, ...]
    target_mapping: dict[int, str]
    target_definition: str
    feature_sets: dict[str, tuple[str, ...]]
    selected_feature_set: str
    selected_feature_specs: tuple[FeatureSpec, ...]
    numerical_features: tuple[str, ...]
    categorical_values: dict[str, tuple[int, ...]]
    invalid_zero_features: tuple[str, ...]
    source_name: str
    source_url: str
    distribution_url: str | None
    license_note: str
    missing_value_convention: str
    source_note: str
    population_note: str

    @property
    def selected_features(self) -> tuple[str, ...]:
        return self.feature_sets[self.selected_feature_set]


DIABETES_COLUMNS = (
    "Pregnancies",
    "Glucose",
    "BloodPressure",
    "SkinThickness",
    "Insulin",
    "BMI",
    "DiabetesPedigreeFunction",
    "Age",
    "Outcome",
)

HEART_COLUMNS = (
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
    "condition",
)


def get_dataset_configs(data_dir: Path | None = None) -> dict[str, DatasetConfig]:
    """Return the fixed, clinically documented Task 13 experiment contracts."""

    del data_dir  # Kept in the signature for future multi-source configurations.

    diabetes_specs = (
        FeatureSpec(
            name="Age",
            data_type="integer",
            unit="years",
            minimum=21,
            maximum=81,
            measurement_context=(
                "Completed age at assessment; 21-81 is the observed source-data range."
            ),
            task14_note="Values outside the training range are unsupported and need a fallback.",
        ),
        FeatureSpec(
            name="Glucose",
            data_type="number",
            unit="mg/dL",
            minimum=44,
            maximum=199,
            measurement_context=(
                "Two-hour plasma glucose from an oral glucose tolerance test, matching "
                "the Pima dataset; a generic, fasting, or random reading must not be "
                "silently substituted."
            ),
            task14_note=(
                "Clarify timing/test context and units in the assessment UI before model "
                "integration."
            ),
        ),
        FeatureSpec(
            name="BMI",
            data_type="number",
            unit="kg/m^2",
            minimum=18.2,
            maximum=67.1,
            measurement_context=(
                "BMI computed from measured height and weight; 18.2-67.1 is the "
                "observed non-missing source-data range."
            ),
            task14_note="Values outside the training range are unsupported and need a fallback.",
        ),
    )

    heart_specs = (
        FeatureSpec(
            name="age",
            data_type="integer",
            unit="years",
            minimum=29,
            maximum=77,
            measurement_context=(
                "Completed age at assessment; 29-77 is the observed source-data range."
            ),
            task14_note="Values outside the training range are unsupported and need a fallback.",
        ),
        FeatureSpec(
            name="sex",
            data_type="integer",
            unit=None,
            allowed_values=(0, 1),
            value_labels={0: "female", 1: "male"},
            measurement_context="Binary coding used by the Cleveland dataset.",
            task14_note=(
                "The source dataset has no category for Other/unknown. Do not fabricate a "
                "mapping; route unsupported values to a non-model fallback."
            ),
        ),
        FeatureSpec(
            name="cp",
            data_type="integer",
            unit=None,
            allowed_values=(0, 1, 2, 3),
            value_labels={
                0: "typical angina",
                1: "atypical angina",
                2: "non-anginal pain",
                3: "asymptomatic",
            },
            measurement_context=(
                "Four-level chest-pain type in this zero-based Cleveland derivative; it "
                "is not equivalent to a yes/no chest-pain symptom."
            ),
            task14_note=(
                "Add a guided four-category field. Never derive this value from the "
                "current boolean chest_pain field."
            ),
        ),
        FeatureSpec(
            name="trestbps",
            data_type="integer",
            unit="mmHg",
            minimum=94,
            maximum=200,
            measurement_context=(
                "Resting blood pressure matching the Cleveland trestbps field "
                "(conventionally systolic; source setting was hospital admission)."
            ),
            task14_note=(
                "Use an explicitly resting systolic measurement; do not map diastolic BP."
            ),
        ),
    )

    return {
        "diabetes": DatasetConfig(
            disease="diabetes",
            display_name="Diabetes",
            filename="diabetes.csv",
            target="Outcome",
            required_columns=DIABETES_COLUMNS,
            target_mapping={
                0: "no diabetes onset within the five-year study horizon",
                1: "diabetes onset within the five-year study horizon",
            },
            target_definition=(
                "The commonly documented Pima benchmark outcome forecasts diabetes onset "
                "within five years under the source study's WHO-based criteria. Because "
                "the repository lacks a byte-level provenance manifest, this is retained "
                "as the source-label interpretation rather than asserted as a current "
                "clinical diagnosis."
            ),
            feature_sets={
                "full_8": DIABETES_COLUMNS[:-1],
                "caregiver_no_lab_2": ("Age", "BMI"),
                "caregiver_no_glucose_3": ("Age", "BMI", "BloodPressure"),
                "eldercare_reduced_3": ("Age", "Glucose", "BMI"),
                "eldercare_reduced_4": (
                    "Age",
                    "Glucose",
                    "BMI",
                    "BloodPressure",
                ),
            },
            selected_feature_set="eldercare_reduced_3",
            selected_feature_specs=diabetes_specs,
            numerical_features=DIABETES_COLUMNS[:-1],
            categorical_values={},
            invalid_zero_features=(
                "Glucose",
                "BloodPressure",
                "SkinThickness",
                "Insulin",
                "BMI",
            ),
            source_name=(
                "Pima Indians Diabetes Database, originally owned by the US National "
                "Institute of Diabetes and Digestive and Kidney Diseases"
            ),
            source_url="https://pmc.ncbi.nlm.nih.gov/articles/PMC2245318/",
            distribution_url=(
                "https://www.kaggle.com/datasets/uciml/pima-indians-diabetes-database"
            ),
            license_note=(
                "The matching distribution page labels its copy CC0, but the repository "
                "does not include a provenance or license manifest tying that grant to "
                "these exact bytes."
            ),
            missing_value_convention=(
                "No explicit null markers are present. Zero is an invalid/missing sentinel "
                "for Glucose, BloodPressure, SkinThickness, Insulin, and BMI; zero "
                "Pregnancies is valid. Sentinel conversion occurs inside the pipeline."
            ),
            source_note=(
                "The repository does not record the download URL, license, or chain of "
                "custody. Identification is based on the exact conventional 768-row "
                "schema and the original study; no replacement dataset was downloaded."
            ),
            population_note=(
                "All subjects were women at least 21 years old of Pima Indian heritage "
                "near Phoenix, Arizona. The data are not representative validation for "
                "Bangladeshi elders, men, or gender-diverse patients."
            ),
        ),
        "heart": DatasetConfig(
            disease="heart",
            display_name="Heart Disease",
            filename="heart_cleveland_upload.csv",
            target="condition",
            required_columns=HEART_COLUMNS,
            target_mapping={0: "no disease", 1: "disease present"},
            target_definition=(
                "Binary recoding of the Cleveland diagnostic num target: 0 means no "
                "angiographic disease and 1 represents original values greater than zero."
            ),
            feature_sets={
                "full_13": HEART_COLUMNS[:-1],
                "inclusive_current_ui_2": ("age", "trestbps"),
                "current_ui_3": ("age", "sex", "trestbps"),
                "structured_cp_no_sex_3": ("age", "cp", "trestbps"),
                "eldercare_structured_cp_4": ("age", "sex", "cp", "trestbps"),
                "structured_cp_plus_fbs_5": (
                    "age",
                    "sex",
                    "cp",
                    "trestbps",
                    "fbs",
                ),
            },
            selected_feature_set="eldercare_structured_cp_4",
            selected_feature_specs=heart_specs,
            numerical_features=("age", "trestbps", "chol", "thalach", "oldpeak"),
            categorical_values={
                "sex": (0, 1),
                "cp": (0, 1, 2, 3),
                "fbs": (0, 1),
                "restecg": (0, 1, 2),
                "exang": (0, 1),
                "slope": (0, 1, 2),
                "ca": (0, 1, 2, 3),
                "thal": (0, 1, 2),
            },
            invalid_zero_features=(),
            source_name="UCI Heart Disease, Cleveland processed-data derivative",
            source_url="https://archive.ics.uci.edu/dataset/45/heart+disease",
            distribution_url=(
                "https://www.kaggle.com/datasets/cherngs/heart-disease-cleveland-uci/data"
            ),
            license_note=(
                "UCI publishes the upstream dataset under CC BY 4.0. The repository does "
                "not include a local provenance/license manifest for this transformed copy."
            ),
            missing_value_convention=(
                "The 297-row derivative has no null or '?' markers. It is a complete-case "
                "transformation of the 303-row upstream Cleveland data, which does contain "
                "missing values."
            ),
            source_note=(
                "The local 297-row file appears to be the common complete-case, binary-"
                "target, zero-based recoding of the 303-row Cleveland dataset. The repo "
                "does not contain a provenance/transformation record, so this relationship "
                "is documented as an inference and the local file hash is authoritative."
            ),
            population_note=(
                "Historical Cleveland clinical/referral cases are not a Bangladeshi or "
                "elderly-community cohort; only a small minority of local rows are age 65 "
                "or older. The target denotes disease presence, not future event risk."
            ),
        ),
    }


def feature_compatibility_rows() -> list[dict[str, str]]:
    """Return the auditable dataset-to-app compatibility decision matrix."""

    return [
        {
            "disease": "diabetes",
            "feature": "Pregnancies",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "sometimes",
            "requires_lab_or_clinical_test": "no",
            "decision": "drop",
            "reason": "Not in the UI, excludes/does not apply to many patients, and is not portable beyond the all-female source cohort.",
        },
        {
            "disease": "diabetes",
            "feature": "Glucose",
            "available_in_dataset": "yes",
            "available_in_current_ui": "partially",
            "caregiver_can_reasonably_provide": "only from a measured result",
            "requires_lab_or_clinical_test": "yes",
            "decision": "use conditionally",
            "reason": "Strong predictor, but Pima semantics are two-hour OGTT plasma glucose; Task 14 must not treat an unqualified reading as equivalent.",
        },
        {
            "disease": "diabetes",
            "feature": "BloodPressure",
            "available_in_dataset": "yes",
            "available_in_current_ui": "yes (diastolic only)",
            "caregiver_can_reasonably_provide": "yes with a cuff",
            "requires_lab_or_clinical_test": "no",
            "decision": "evaluate, then drop",
            "reason": "Directly maps to diastolic BP, but the predefined reduced-set comparison showed no useful gain over Age+Glucose+BMI.",
        },
        {
            "disease": "diabetes",
            "feature": "SkinThickness",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "clinical measurement",
            "decision": "drop",
            "reason": "Requires standardized triceps skin-fold measurement and has many invalid zero sentinels.",
        },
        {
            "disease": "diabetes",
            "feature": "Insulin",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no without a result",
            "requires_lab_or_clinical_test": "yes",
            "decision": "drop",
            "reason": "Two-hour serum insulin is not a routine caregiver-entered value and has extensive missing-value sentinels.",
        },
        {
            "disease": "diabetes",
            "feature": "BMI",
            "available_in_dataset": "yes",
            "available_in_current_ui": "yes (derived)",
            "caregiver_can_reasonably_provide": "yes via height and weight",
            "requires_lab_or_clinical_test": "no",
            "decision": "use",
            "reason": "Direct dataset feature that the app can calculate without fabrication.",
        },
        {
            "disease": "diabetes",
            "feature": "DiabetesPedigreeFunction",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "no",
            "decision": "drop",
            "reason": "The derived pedigree function cannot be reconstructed faithfully from a basic family-history answer.",
        },
        {
            "disease": "diabetes",
            "feature": "Age",
            "available_in_dataset": "yes",
            "available_in_current_ui": "yes",
            "caregiver_can_reasonably_provide": "yes",
            "requires_lab_or_clinical_test": "no",
            "decision": "use",
            "reason": "Directly available with matching units.",
        },
        {
            "disease": "heart",
            "feature": "age",
            "available_in_dataset": "yes",
            "available_in_current_ui": "yes",
            "caregiver_can_reasonably_provide": "yes",
            "requires_lab_or_clinical_test": "no",
            "decision": "use",
            "reason": "Direct match, while extrapolation beyond the source age range remains a limitation.",
        },
        {
            "disease": "heart",
            "feature": "sex",
            "available_in_dataset": "yes (binary)",
            "available_in_current_ui": "partially (gender is Male/Female/Other, not automatically clinical sex)",
            "caregiver_can_reasonably_provide": "yes",
            "requires_lab_or_clinical_test": "no",
            "decision": "use only after Task 14 adds an exact binary clinical-sex contract",
            "reason": "Do not silently translate the current gender profile field; the dataset also cannot represent Other/unknown, which must never receive a fabricated code.",
        },
        {
            "disease": "heart",
            "feature": "cp",
            "available_in_dataset": "yes (four categories)",
            "available_in_current_ui": "no (current field is boolean)",
            "caregiver_can_reasonably_provide": "with a guided structured question",
            "requires_lab_or_clinical_test": "no, but interpretation can be difficult",
            "decision": "use after Task 14 contract change",
            "reason": "Adds substantial signal, but must be collected as the exact four-level chest-pain type; boolean chest pain is invalid.",
        },
        {
            "disease": "heart",
            "feature": "trestbps",
            "available_in_dataset": "yes",
            "available_in_current_ui": "partially (systolic BP)",
            "caregiver_can_reasonably_provide": "yes with a cuff",
            "requires_lab_or_clinical_test": "no",
            "decision": "use with resting context",
            "reason": "Task 14 must explicitly collect a resting systolic value; diastolic BP must not be substituted.",
        },
        {
            "disease": "heart",
            "feature": "chol",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "only from a result",
            "requires_lab_or_clinical_test": "yes",
            "decision": "drop",
            "reason": "Serum cholesterol adds burden and did not justify the full clinical contract for caregiver screening.",
        },
        {
            "disease": "heart",
            "feature": "fbs",
            "available_in_dataset": "yes (fasting >120 mg/dL flag)",
            "available_in_current_ui": "no faithful mapping",
            "caregiver_can_reasonably_provide": "only with fasting context",
            "requires_lab_or_clinical_test": "yes",
            "decision": "drop",
            "reason": "Generic glucose is not equivalent to the dataset's binary fasting-threshold field and the evaluated addition gave no useful gain.",
        },
        {
            "disease": "heart",
            "feature": "restecg",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "ECG",
            "decision": "drop",
            "reason": "Requires resting electrocardiographic interpretation.",
        },
        {
            "disease": "heart",
            "feature": "thalach",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no reliably",
            "requires_lab_or_clinical_test": "exercise testing",
            "decision": "drop",
            "reason": "Maximum achieved heart rate is not an ordinary resting caregiver measurement.",
        },
        {
            "disease": "heart",
            "feature": "exang",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no faithful mapping",
            "caregiver_can_reasonably_provide": "not reliably from current UI",
            "requires_lab_or_clinical_test": "exercise context",
            "decision": "drop",
            "reason": "Exercise-induced angina is not equivalent to generic chest pain or shortness of breath.",
        },
        {
            "disease": "heart",
            "feature": "oldpeak",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "exercise ECG",
            "decision": "drop",
            "reason": "Requires ST-depression measurement during exercise testing.",
        },
        {
            "disease": "heart",
            "feature": "slope",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "exercise ECG",
            "decision": "drop",
            "reason": "Requires clinical ECG interpretation.",
        },
        {
            "disease": "heart",
            "feature": "ca",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "fluoroscopy/angiography",
            "decision": "drop",
            "reason": "Major-vessel count is invasive/specialist information.",
        },
        {
            "disease": "heart",
            "feature": "thal",
            "available_in_dataset": "yes",
            "available_in_current_ui": "no",
            "caregiver_can_reasonably_provide": "no",
            "requires_lab_or_clinical_test": "specialist test",
            "decision": "drop",
            "reason": "Thalassemia/perfusion-test coding is not a caregiver screening input.",
        },
    ]
