from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np

_runtime_root = (
    os.environ.get("PREDICT_MCP_WORKDIR")
    or os.environ.get("DATA_MODELING_MCP_WORKDIR")
    or os.environ.get("SHIELD_MCP_WORKDIR")
)
_mpl_root = Path(_runtime_root or tempfile.gettempdir()) / ".data_modeling_mpl"
_mpl_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_mpl_root))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from .data import write_json
from .utils import safe_name


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray, timeseries: bool = False) -> dict[str, Any]:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    mask = y_true != 0
    metrics: dict[str, Any] = {
        "MAE": round(float(mean_absolute_error(y_true, y_pred)), 6),
        "RMSE": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 6),
        "R2": round(float(r2_score(y_true, y_pred)), 6),
        "MAPE_percent": round(float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100), 6)
        if mask.any()
        else None,
    }
    if timeseries and len(y_true) > 1:
        actual_direction = np.sign(np.diff(y_true))
        predicted_direction = np.sign(np.diff(y_pred))
        metrics["direction_accuracy"] = round(float(np.mean(actual_direction == predicted_direction)), 6)
    return metrics


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray | None,
) -> dict[str, Any]:
    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    classes = np.unique(np.concatenate([y_true, y_pred]))
    average = "binary" if len(classes) == 2 else "weighted"
    result: dict[str, Any] = {
        "Accuracy": round(float(accuracy_score(y_true, y_pred)), 6),
        "Precision": round(float(precision_score(y_true, y_pred, average=average, zero_division=0)), 6),
        "Recall": round(float(recall_score(y_true, y_pred, average=average, zero_division=0)), 6),
        "F1": round(float(f1_score(y_true, y_pred, average=average, zero_division=0)), 6),
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classification_report": classification_report(y_true, y_pred, output_dict=True, zero_division=0),
    }
    if y_prob is not None:
        try:
            if len(classes) == 2:
                scores = y_prob[:, 1] if y_prob.ndim == 2 else y_prob
                result["AUC_ROC"] = round(float(roc_auc_score(y_true, scores)), 6)
            else:
                result["AUC_ROC"] = round(
                    float(roc_auc_score(y_true, y_prob, multi_class="ovr", average="weighted")), 6
                )
        except ValueError:
            pass
    return result


def _plot_regression(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    metrics: dict[str, Any],
    output_dir: Path,
    model_name: str,
) -> list[str]:
    paths: list[str] = []
    fig, axis = plt.subplots(figsize=(14, 5))
    axis.plot(y_true, label="Actual", linewidth=1)
    axis.plot(y_pred, label="Predicted", linewidth=1)
    axis.set_title(f"{model_name} - Actual vs Predicted | RMSE={metrics['RMSE']:.4f}, R2={metrics['R2']:.4f}")
    axis.set_xlabel("Sample")
    axis.legend()
    axis.grid(True, alpha=0.3)
    fig.tight_layout()
    path = output_dir / "pred_vs_actual.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path))

    residuals = y_true - y_pred
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].scatter(y_pred, residuals, s=12, alpha=0.35)
    axes[0].axhline(0, color="black", linewidth=1)
    axes[0].set_xlabel("Predicted")
    axes[0].set_ylabel("Residual")
    axes[0].grid(True, alpha=0.3)
    axes[1].hist(residuals, bins=min(50, max(10, len(residuals) // 5)), alpha=0.75)
    axes[1].set_xlabel("Residual")
    axes[1].set_ylabel("Count")
    fig.suptitle(f"{model_name} - Residual Analysis")
    fig.tight_layout()
    path = output_dir / "residuals.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path))

    fig, axis = plt.subplots(figsize=(7, 7))
    axis.scatter(y_true, y_pred, s=12, alpha=0.35)
    minimum = float(min(y_true.min(), y_pred.min()))
    maximum = float(max(y_true.max(), y_pred.max()))
    axis.plot([minimum, maximum], [minimum, maximum], "r--")
    axis.set_xlabel("Actual")
    axis.set_ylabel("Predicted")
    axis.set_title(f"{model_name} - Prediction Scatter")
    axis.grid(True, alpha=0.3)
    fig.tight_layout()
    path = output_dir / "scatter_pred_actual.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path))
    return paths


def _plot_classification(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray | None,
    metrics: dict[str, Any],
    output_dir: Path,
    model_name: str,
) -> list[str]:
    paths: list[str] = []
    matrix = np.asarray(metrics["confusion_matrix"])
    fig, axis = plt.subplots(figsize=(8, 6))
    sns.heatmap(matrix, annot=True, fmt="d", cmap="Blues", ax=axis)
    axis.set_xlabel("Predicted")
    axis.set_ylabel("Actual")
    axis.set_title(f"{model_name} - Confusion Matrix | Accuracy={metrics['Accuracy']:.4f}")
    fig.tight_layout()
    path = output_dir / "confusion_matrix.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(str(path))

    if y_prob is not None and len(np.unique(y_true)) == 2:
        from sklearn.metrics import roc_curve

        scores = y_prob[:, 1] if y_prob.ndim == 2 else y_prob
        fpr, tpr, _ = roc_curve(y_true, scores)
        fig, axis = plt.subplots(figsize=(7, 7))
        axis.plot(fpr, tpr, linewidth=2, label=f"AUC={metrics.get('AUC_ROC', 'N/A')}")
        axis.plot([0, 1], [0, 1], "r--")
        axis.set_xlabel("False Positive Rate")
        axis.set_ylabel("True Positive Rate")
        axis.set_title(f"{model_name} - ROC")
        axis.legend()
        axis.grid(True, alpha=0.3)
        fig.tight_layout()
        path = output_dir / "roc_curve.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths.append(str(path))
    return paths


def _load_estimator(model_info: dict[str, Any], task_type: str):
    model_type = model_info["model_type"]
    if model_type == "xgboost":
        import xgboost as xgb

        estimator = xgb.XGBClassifier() if task_type == "classification" else xgb.XGBRegressor()
        estimator.load_model(model_info["model_path"])
        return estimator
    if model_info.get("is_torch"):
        return None
    return joblib.load(model_info["model_path"])


def _plot_feature_importance(
    estimator: Any,
    features: list[str],
    output_dir: Path,
    model_name: str,
) -> str | None:
    if estimator is None:
        return None
    if hasattr(estimator, "feature_importances_"):
        importance = np.asarray(estimator.feature_importances_)
    elif hasattr(estimator, "coef_"):
        coefficients = np.asarray(estimator.coef_)
        importance = np.mean(np.abs(coefficients), axis=0) if coefficients.ndim > 1 else np.abs(coefficients)
    else:
        return None
    if len(importance) != len(features):
        return None
    indices = np.argsort(importance)[::-1][: min(15, len(features))]
    fig, axis = plt.subplots(figsize=(10, max(4, len(indices) * 0.45)))
    axis.barh(range(len(indices)), importance[indices][::-1])
    axis.set_yticks(range(len(indices)))
    axis.set_yticklabels([features[index] for index in indices][::-1])
    axis.set_xlabel("Importance")
    axis.set_title(f"{model_name} - Feature Importance")
    axis.grid(True, alpha=0.3, axis="x")
    fig.tight_layout()
    path = output_dir / "feature_importance.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def evaluate_training_results(training_results: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    task_type = training_results["task_type"]
    evaluations: list[dict[str, Any]] = []
    for model_info in training_results["models"]:
        model_dir = destination / safe_name(model_info["model_type"])
        model_dir.mkdir(parents=True, exist_ok=True)
        payload = joblib.load(model_info["test_payload_path"])
        y_true = np.asarray(payload["y_true"])
        y_pred = np.asarray(payload["y_pred"])
        y_prob = None if payload.get("y_prob") is None else np.asarray(payload["y_prob"])
        if task_type == "classification":
            metrics = classification_metrics(y_true, y_pred, y_prob)
            plots = _plot_classification(y_true, y_pred, y_prob, metrics, model_dir, model_info["model_name"])
        else:
            metrics = regression_metrics(y_true, y_pred, timeseries=task_type == "timeseries")
            plots = _plot_regression(y_true, y_pred, metrics, model_dir, model_info["model_name"])
        estimator = _load_estimator(model_info, "classification" if task_type == "classification" else "regression")
        importance = _plot_feature_importance(
            estimator,
            training_results["features"],
            model_dir,
            model_info["model_name"],
        )
        if importance:
            plots.append(importance)
        if model_info.get("loss_plot"):
            plots.append(model_info["loss_plot"])
        evaluations.append(
            {
                "model_type": model_info["model_type"],
                "model_name": model_info["model_name"],
                "metrics": metrics,
                "plots": plots,
            }
        )

    numeric_keys = [
        key
        for key, value in evaluations[0]["metrics"].items()
        if isinstance(value, (int, float)) and value is not None
    ]
    comparison_path = None
    if len(evaluations) > 1 and numeric_keys:
        fig, axes = plt.subplots(1, len(numeric_keys), figsize=(5 * len(numeric_keys), 5))
        if len(numeric_keys) == 1:
            axes = [axes]
        names = [entry["model_name"] for entry in evaluations]
        for axis, key in zip(axes, numeric_keys):
            values = [entry["metrics"].get(key, 0) or 0 for entry in evaluations]
            axis.bar(names, values)
            axis.set_title(key)
            axis.tick_params(axis="x", rotation=20)
            axis.grid(True, alpha=0.3, axis="y")
        fig.suptitle("Model Comparison")
        fig.tight_layout()
        path = destination / "model_comparison.png"
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        comparison_path = str(path)
    result = {"task_type": task_type, "models": evaluations, "comparison_plot": comparison_path}
    write_json(destination / "evaluation_results.json", result)
    return result
