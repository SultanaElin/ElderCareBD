import os
import warnings
import joblib
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from sklearn.model_selection import StratifiedKFold, cross_validate, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
    confusion_matrix,
    ConfusionMatrixDisplay,
)

warnings.filterwarnings("ignore")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
MODEL_DIR = os.path.join(BASE_DIR, "models")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


def load_diabetes_dataset():
    path = os.path.join(DATA_DIR, "diabetes.csv")
    df = pd.read_csv(path)

    target_col = "Outcome"

    # In Pima dataset, zero values for these medical features are unrealistic.
    # We replace zero with NaN, then impute median inside ML pipeline.
    zero_invalid_cols = [
        "Glucose",
        "BloodPressure",
        "SkinThickness",
        "Insulin",
        "BMI",
    ]

    for col in zero_invalid_cols:
        if col in df.columns:
            df[col] = df[col].replace(0, np.nan)

    X = df.drop(columns=[target_col])
    y = df[target_col]

    return X, y


def load_heart_dataset():
    path = os.path.join(DATA_DIR, "heart_cleveland_upload.csv")
    df = pd.read_csv(path)

    target_col = "condition"

    X = df.drop(columns=[target_col])
    y = df[target_col]

    return X, y


def get_models():
    return {
        "Logistic Regression": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    LogisticRegression(
                        max_iter=1000,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        ),
        "Random Forest": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestClassifier(
                        n_estimators=300,
                        max_depth=None,
                        min_samples_split=4,
                        min_samples_leaf=2,
                        class_weight="balanced",
                        random_state=42,
                    ),
                ),
            ]
        ),
        "Neural Network": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                (
                    "model",
                    MLPClassifier(
                        hidden_layer_sizes=(64, 32),
                        activation="relu",
                        solver="adam",
                        max_iter=700,
                        random_state=42,
                    ),
                ),
            ]
        ),
    }


def evaluate_model(dataset_name, model_name, model, X, y):
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    scoring = {
        "accuracy": "accuracy",
        "precision": "precision",
        "recall": "recall",
        "f1": "f1",
        "roc_auc": "roc_auc",
    }

    cv_results = cross_validate(
        model,
        X,
        y,
        cv=cv,
        scoring=scoring,
        return_train_score=False,
    )

    y_pred = cross_val_predict(model, X, y, cv=cv)

    try:
        y_proba = cross_val_predict(
            model,
            X,
            y,
            cv=cv,
            method="predict_proba",
        )[:, 1]
        auc_score = roc_auc_score(y, y_proba)
    except Exception:
        auc_score = np.nan

    accuracy = accuracy_score(y, y_pred)
    precision = precision_score(y, y_pred, zero_division=0)
    recall = recall_score(y, y_pred, zero_division=0)
    f1 = f1_score(y, y_pred, zero_division=0)

    cm = confusion_matrix(y, y_pred)

    save_confusion_matrix(
        cm=cm,
        dataset_name=dataset_name,
        model_name=model_name,
    )

    return {
        "Dataset": dataset_name,
        "Model": model_name,
        "CV Accuracy Mean": cv_results["test_accuracy"].mean(),
        "CV Precision Mean": cv_results["test_precision"].mean(),
        "CV Recall Mean": cv_results["test_recall"].mean(),
        "CV F1 Mean": cv_results["test_f1"].mean(),
        "CV ROC-AUC Mean": cv_results["test_roc_auc"].mean(),
        "Overall Accuracy": accuracy,
        "Overall Precision": precision,
        "Overall Recall": recall,
        "Overall F1": f1,
        "Overall ROC-AUC": auc_score,
    }


def save_confusion_matrix(cm, dataset_name, model_name):
    display = ConfusionMatrixDisplay(
        confusion_matrix=cm,
        display_labels=["Low/No Risk", "Risk"],
    )

    display.plot(values_format="d")
    plt.title(f"{dataset_name} - {model_name} Confusion Matrix")
    plt.tight_layout()

    safe_dataset = dataset_name.lower().replace(" ", "_")
    safe_model = model_name.lower().replace(" ", "_")

    output_path = os.path.join(
        OUTPUT_DIR,
        f"{safe_dataset}_{safe_model}_confusion_matrix.png",
    )

    plt.savefig(output_path, dpi=300)
    plt.close()


def train_and_save_best_model(dataset_name, X, y, results_df):
    dataset_results = results_df[results_df["Dataset"] == dataset_name].copy()

    # Best model selected using F1 first, then ROC-AUC.
    dataset_results = dataset_results.sort_values(
        by=["CV F1 Mean", "CV ROC-AUC Mean"],
        ascending=False,
    )

    best_model_name = dataset_results.iloc[0]["Model"]

    print(f"\nBest model for {dataset_name}: {best_model_name}")

    models = get_models()
    best_model = models[best_model_name]

    best_model.fit(X, y)

    safe_dataset = dataset_name.lower().replace(" ", "_")

    model_path = os.path.join(
        MODEL_DIR,
        f"{safe_dataset}_best_model.pkl",
    )

    joblib.dump(best_model, model_path)

    print(f"Saved best model: {model_path}")

    return best_model_name, model_path


def run_training():
    datasets = {
        "Diabetes": load_diabetes_dataset(),
        "Heart Disease": load_heart_dataset(),
    }

    all_results = []

    for dataset_name, (X, y) in datasets.items():
        print("\n" + "=" * 70)
        print(f"Dataset: {dataset_name}")
        print(f"Shape: {X.shape}")
        print(f"Class distribution:\n{y.value_counts()}")
        print("=" * 70)

        models = get_models()

        for model_name, model in models.items():
            print(f"\nTraining and evaluating: {model_name}")

            result = evaluate_model(
                dataset_name=dataset_name,
                model_name=model_name,
                model=model,
                X=X,
                y=y,
            )

            all_results.append(result)

            print(
                f"{model_name} | "
                f"Accuracy: {result['CV Accuracy Mean']:.4f} | "
                f"Precision: {result['CV Precision Mean']:.4f} | "
                f"Recall: {result['CV Recall Mean']:.4f} | "
                f"F1: {result['CV F1 Mean']:.4f} | "
                f"ROC-AUC: {result['CV ROC-AUC Mean']:.4f}"
            )

    results_df = pd.DataFrame(all_results)

    # Round values for clean reporting.
    metric_cols = [
        "CV Accuracy Mean",
        "CV Precision Mean",
        "CV Recall Mean",
        "CV F1 Mean",
        "CV ROC-AUC Mean",
        "Overall Accuracy",
        "Overall Precision",
        "Overall Recall",
        "Overall F1",
        "Overall ROC-AUC",
    ]

    results_df[metric_cols] = results_df[metric_cols].round(4)

    results_path = os.path.join(OUTPUT_DIR, "model_results.csv")
    results_df.to_csv(results_path, index=False)

    print("\n" + "=" * 70)
    print("MODEL RESULTS")
    print("=" * 70)
    print(results_df)
    print(f"\nSaved results table: {results_path}")

    best_summary = []

    for dataset_name, (X, y) in datasets.items():
        best_model_name, model_path = train_and_save_best_model(
            dataset_name=dataset_name,
            X=X,
            y=y,
            results_df=results_df,
        )

        best_summary.append(
            {
                "Dataset": dataset_name,
                "Best Model": best_model_name,
                "Saved Model Path": model_path,
            }
        )

    best_summary_df = pd.DataFrame(best_summary)
    best_summary_path = os.path.join(OUTPUT_DIR, "best_model_summary.csv")
    best_summary_df.to_csv(best_summary_path, index=False)

    print("\n" + "=" * 70)
    print("BEST MODEL SUMMARY")
    print("=" * 70)
    print(best_summary_df)
    print(f"\nSaved best model summary: {best_summary_path}")


if __name__ == "__main__":
    run_training()