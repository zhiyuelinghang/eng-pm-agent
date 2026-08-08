from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from .data import (
    filter_preprocessing_rows,
    fit_preprocessor,
    transform_features,
    write_json,
)
from .errors import DomainError as WorkflowError
from .utils import safe_name


LOGGER = logging.getLogger(__name__)

SUPPORTED_MODELS = ("xgboost", "random_forest", "svm", "linear", "lstm", "cnn1d", "mlp")

DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "xgboost": {
        "n_estimators": 100,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.0,
        "reg_lambda": 1.0,
    },
    "random_forest": {
        "n_estimators": 100,
        "max_depth": None,
        "min_samples_split": 2,
        "min_samples_leaf": 1,
    },
    "svm": {"C": 1.0, "kernel": "rbf", "gamma": "scale"},
    "linear": {},
    "lstm": {
        "hidden_size": 64,
        "num_layers": 2,
        "dropout": 0.2,
        "learning_rate": 0.001,
        "epochs": 100,
        "batch_size": 32,
        "seq_length": 10,
    },
    "cnn1d": {
        "channels": [32, 64],
        "kernel_size": 3,
        "dropout": 0.2,
        "learning_rate": 0.001,
        "epochs": 100,
        "batch_size": 32,
        "seq_length": 10,
    },
    "mlp": {
        "hidden_layers": [128, 64, 32],
        "dropout": 0.2,
        "learning_rate": 0.001,
        "epochs": 100,
        "batch_size": 32,
    },
}


def model_parameter_options(task_type: str) -> dict[str, dict[str, Any]]:
    """Return every server-supported manual parameter and its validation constraints."""
    linear_parameters = (
        ["C", "solver", "penalty", "fit_intercept"]
        if task_type == "classification"
        else ["fit_intercept", "positive"]
    )
    linear_constraints = (
        [
            "C 必须大于 0",
            "solver 可选 lbfgs、liblinear、newton-cg、newton-cholesky、sag、saga",
            "penalty 可选 null、l1、l2；l1 仅兼容 liblinear 或 saga",
            "fit_intercept 必须为布尔值",
        ]
        if task_type == "classification"
        else [
            "fit_intercept 必须为布尔值",
            "positive 必须为布尔值",
        ]
    )
    return {
        "xgboost": {
            "allowed_parameters": [
                "n_estimators",
                "max_depth",
                "learning_rate",
                "subsample",
                "colsample_bytree",
                "reg_alpha",
                "reg_lambda",
            ],
            "default_params": DEFAULT_PARAMS["xgboost"],
            "constraints": [
                "n_estimators、max_depth 为大于等于 1 的整数",
                "learning_rate 大于 0",
                "subsample、colsample_bytree 在 (0, 1] 范围",
                "reg_alpha、reg_lambda 大于等于 0",
            ],
        },
        "random_forest": {
            "allowed_parameters": [
                "n_estimators",
                "max_depth",
                "min_samples_split",
                "min_samples_leaf",
            ],
            "default_params": DEFAULT_PARAMS["random_forest"],
            "constraints": [
                "n_estimators、min_samples_split、min_samples_leaf 为大于等于 1 的整数",
                "max_depth 可为 null 或大于等于 1 的整数",
            ],
        },
        "svm": {
            "allowed_parameters": ["C", "kernel", "gamma"],
            "default_params": DEFAULT_PARAMS["svm"],
            "constraints": [
                "C 大于 0",
                "kernel 可选 linear、poly、rbf、sigmoid",
                "gamma 可选 scale、auto 或大于 0 的数值",
            ],
        },
        "linear": {
            "allowed_parameters": linear_parameters,
            "default_params": DEFAULT_PARAMS["linear"],
            "constraints": linear_constraints,
        },
        "lstm": {
            "allowed_parameters": [
                "hidden_size",
                "num_layers",
                "dropout",
                "learning_rate",
                "epochs",
                "batch_size",
                "seq_length",
            ],
            "default_params": DEFAULT_PARAMS["lstm"],
            "constraints": [
                "hidden_size、num_layers、epochs、batch_size、seq_length 为正整数",
                "dropout 在 [0, 1) 范围",
                "learning_rate 大于 0",
            ],
        },
        "cnn1d": {
            "allowed_parameters": [
                "channels",
                "kernel_size",
                "dropout",
                "learning_rate",
                "epochs",
                "batch_size",
                "seq_length",
            ],
            "default_params": DEFAULT_PARAMS["cnn1d"],
            "constraints": [
                "channels 为非空正整数列表",
                "kernel_size、epochs、batch_size、seq_length 为正整数",
                "dropout 在 [0, 1) 范围",
                "learning_rate 大于 0",
            ],
        },
        "mlp": {
            "allowed_parameters": [
                "hidden_layers",
                "dropout",
                "learning_rate",
                "epochs",
                "batch_size",
            ],
            "default_params": DEFAULT_PARAMS["mlp"],
            "constraints": [
                "hidden_layers 为非空正整数列表",
                "epochs、batch_size 为正整数",
                "dropout 在 [0, 1) 范围",
                "learning_rate 大于 0",
            ],
        },
    }


def _require_number(
    model: str,
    name: str,
    value: Any,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    integer: bool = False,
) -> None:
    valid_type = isinstance(value, int) and not isinstance(value, bool) if integer else isinstance(value, (int, float)) and not isinstance(value, bool)
    if not valid_type:
        expected = "整数" if integer else "数值"
        raise WorkflowError(f"{model}.{name} 必须为{expected}")
    if minimum is not None and value < minimum:
        raise WorkflowError(f"{model}.{name} 必须大于等于 {minimum}")
    if maximum is not None and value > maximum:
        raise WorkflowError(f"{model}.{name} 必须小于等于 {maximum}")


def validate_model_params(model: str, params: dict[str, Any], task_type: str) -> None:
    common_allowed: dict[str, set[str]] = {
        "xgboost": {
            "n_estimators", "max_depth", "learning_rate", "subsample",
            "colsample_bytree", "reg_alpha", "reg_lambda",
        },
        "random_forest": {
            "n_estimators", "max_depth", "min_samples_split", "min_samples_leaf",
        },
        "svm": {"C", "kernel", "gamma"},
        "lstm": {
            "hidden_size", "num_layers", "dropout", "learning_rate",
            "epochs", "batch_size", "seq_length",
        },
        "cnn1d": {
            "channels", "kernel_size", "dropout", "learning_rate",
            "epochs", "batch_size", "seq_length",
        },
        "mlp": {
            "hidden_layers", "dropout", "learning_rate", "epochs", "batch_size",
        },
    }
    if model == "linear":
        allowed = {"C", "solver", "penalty", "fit_intercept"} if task_type == "classification" else {"fit_intercept", "positive"}
    else:
        allowed = common_allowed[model]
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise WorkflowError(f"{model} 包含不支持或由服务器管理的参数: {unknown}")

    for name in ("n_estimators", "max_depth", "min_samples_split", "min_samples_leaf"):
        if name in params and params[name] is not None:
            _require_number(model, name, params[name], minimum=1, integer=True)
    for name in ("hidden_size", "num_layers", "epochs", "batch_size", "seq_length", "kernel_size"):
        if name in params:
            _require_number(model, name, params[name], minimum=1, integer=True)
    for name in ("learning_rate", "C"):
        if name in params:
            _require_number(model, name, params[name], minimum=1e-12)
    for name in ("subsample", "colsample_bytree"):
        if name in params:
            _require_number(model, name, params[name], minimum=1e-12, maximum=1.0)
    for name in ("reg_alpha", "reg_lambda"):
        if name in params:
            _require_number(model, name, params[name], minimum=0)
    if "dropout" in params:
        _require_number(model, "dropout", params["dropout"], minimum=0, maximum=0.999999)
    for name in ("channels", "hidden_layers"):
        if name in params:
            value = params[name]
            if not isinstance(value, list) or not value:
                raise WorkflowError(f"{model}.{name} 必须为非空正整数列表")
            for item in value:
                _require_number(model, name, item, minimum=1, integer=True)
    if model == "svm":
        if "kernel" in params and params["kernel"] not in {"linear", "poly", "rbf", "sigmoid"}:
            raise WorkflowError("svm.kernel 必须为 linear、poly、rbf 或 sigmoid")
        if "gamma" in params:
            gamma = params["gamma"]
            if isinstance(gamma, str):
                if gamma not in {"scale", "auto"}:
                    raise WorkflowError("svm.gamma 字符串必须为 scale 或 auto")
            else:
                _require_number(model, "gamma", gamma, minimum=1e-12)
    if model == "linear" and task_type == "classification":
        solver = params.get("solver", "lbfgs")
        penalty = params.get("penalty", "l2")
        if solver not in {"lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"}:
            raise WorkflowError("linear.solver 不受支持")
        if penalty not in {None, "l1", "l2"}:
            raise WorkflowError("linear.penalty 仅支持 None、l1 或 l2")
        if penalty == "l1" and solver not in {"liblinear", "saga"}:
            raise WorkflowError("linear.penalty=l1 需要 solver=liblinear 或 saga")
    for name in ("fit_intercept", "positive"):
        if name in params and not isinstance(params[name], bool):
            raise WorkflowError(f"linear.{name} 必须为布尔值")


def validate_training_configuration(
    selected_models: list[str],
    task_type: str,
    split_method: str,
    tuning: str,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
    n_trials: int,
    model_params: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if split_method not in {"random", "sequential", "kfold"}:
        raise WorkflowError("split_method 必须为 random、sequential 或 kfold")
    if tuning not in {"default", "grid", "random", "bayesian"}:
        raise WorkflowError("tuning 必须为 default、grid、random 或 bayesian")
    ratios = (train_ratio, val_ratio, test_ratio)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in ratios):
        raise WorkflowError("训练集、验证集、测试集比例必须为数值")
    if min(ratios) <= 0 or not np.isclose(sum(ratios), 1.0, atol=1e-6):
        raise WorkflowError("训练集、验证集、测试集比例必须均大于 0 且总和为 1")
    if isinstance(n_trials, bool) or not isinstance(n_trials, int) or not 1 <= n_trials <= 500:
        raise WorkflowError("n_trials 必须为 1 到 500 的整数")
    if task_type == "timeseries" and split_method == "random":
        raise WorkflowError("时序任务禁止随机划分，请选择 sequential 或 kfold")
    deep = sorted(set(selected_models) & {"lstm", "cnn1d", "mlp"})
    if split_method == "kfold" and deep:
        raise WorkflowError(f"KFold 暂不支持深度学习模型，避免伪交叉验证: {deep}")
    if tuning != "default" and deep:
        raise WorkflowError(f"当前调参搜索仅支持传统模型；深度学习模型请使用 default: {deep}")

    normalized = {str(model): dict(params) for model, params in (model_params or {}).items()}
    unknown_models = sorted(set(normalized) - set(selected_models))
    if unknown_models:
        raise WorkflowError(f"model_params 包含未选择的模型: {unknown_models}")
    model_task_type = "classification" if task_type == "classification" else "regression"
    for model in selected_models:
        validate_model_params(model, normalized.get(model, {}), model_task_type)
    return normalized


def infer_task_type(series: pd.Series, requested: str = "auto", has_time: bool = False) -> str:
    if requested != "auto":
        if requested not in {"regression", "classification", "timeseries"}:
            raise WorkflowError("task_type 必须为 auto、regression、classification 或 timeseries")
        return requested
    if has_time and pd.api.types.is_numeric_dtype(series):
        return "timeseries"
    if not pd.api.types.is_numeric_dtype(series):
        return "classification"
    unique = int(series.nunique(dropna=True))
    if unique <= max(20, int(len(series) * 0.02)) and np.allclose(
        series.dropna().astype(float), series.dropna().astype(float).round()
    ):
        return "classification"
    return "regression"


def recommendation_for(
    rows: int,
    feature_count: int,
    task_type: str,
    has_time: bool,
) -> dict[str, Any]:
    recommendations: list[dict[str, Any]] = []

    def add(model: str, reason: str, recommended: bool = False) -> None:
        recommendations.append(
            {
                "model": model,
                "recommended": recommended,
                "reason": reason,
                "default_params": DEFAULT_PARAMS[model],
            }
        )

    if has_time or task_type == "timeseries":
        if rows >= 500:
            add("lstm", "数据具有明确的时间或顺序依赖，适合捕捉长期变化", True)
            add("cnn1d", "适合提取有序特征序列中的局部模式")
        add("xgboost", "可通过当前与滞后特征建立高精度且可解释的基线", rows < 500)
        add("random_forest", "对噪声和异常值较稳健")
    elif rows < 500:
        add("xgboost", "小样本非线性问题通常表现稳定", True)
        add("random_forest", "对噪声稳健且参数敏感度低")
        add("linear", "提供可解释的线性基线")
        if feature_count <= 50:
            add("svm", "适合小样本和中等维度特征")
    elif rows <= 5000:
        add("xgboost", "适合中等规模表格数据并提供特征重要性", True)
        add("random_forest", "提供稳定的非线性基线")
        add("mlp", "可拟合多参数之间的非线性映射")
        add("linear", "用于判断线性基线与复杂模型的收益")
    else:
        add("xgboost", "适合大规模表格数据并兼顾精度和可解释性", True)
        add("mlp", "数据量足以支持通用神经网络")
        add("random_forest", "作为鲁棒树模型基线")

    if task_type == "classification" and not any(item["model"] == "linear" for item in recommendations):
        add("linear", "Logistic Regression 提供高可解释性分类基线")
    return {
        "task_type": task_type,
        "rows": rows,
        "feature_count": feature_count,
        "has_time_structure": has_time,
        "models": recommendations,
        "supported_models": list(SUPPORTED_MODELS),
    }


def _prepare_target(series: pd.Series, task_type: str, output_dir: Path) -> tuple[np.ndarray, dict[str, Any] | None]:
    if task_type in {"regression", "timeseries"}:
        values = pd.to_numeric(series, errors="coerce")
        if values.isna().any():
            raise WorkflowError("回归或时序任务的目标变量必须为数值型且不能含缺失值")
        return values.to_numpy(dtype=float), None
    from sklearn.preprocessing import LabelEncoder

    encoder = LabelEncoder()
    values = encoder.fit_transform(series.astype(str))
    path = output_dir / "target_encoder.joblib"
    joblib.dump(encoder, path)
    return values.astype(int), {"path": str(path), "classes": encoder.classes_.tolist()}


def _safe_stratify(y: np.ndarray) -> np.ndarray | None:
    values, counts = np.unique(y, return_counts=True)
    return y if len(values) > 1 and counts.min() >= 3 else None


def split_row_indices(
    y: np.ndarray,
    method: str,
    task_type: str,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
) -> dict[str, Any]:
    if len(y) < 20:
        raise WorkflowError("有效样本少于 20 条，无法可靠划分训练/验证/测试集")
    indices = np.arange(len(y))
    if method == "sequential" or (method == "kfold" and task_type == "timeseries"):
        train_end = int(len(indices) * train_ratio)
        val_end = train_end + int(len(indices) * val_ratio)
        train_indices = indices[:train_end]
        val_indices = indices[train_end:val_end]
        test_indices = indices[val_end:]
    else:
        from sklearn.model_selection import train_test_split

        stratify = _safe_stratify(y) if task_type == "classification" else None
        development, test_indices = train_test_split(
            indices,
            test_size=test_ratio,
            random_state=42,
            stratify=stratify,
        )
        relative_val = val_ratio / (train_ratio + val_ratio)
        development_y = y[development]
        stratify_development = _safe_stratify(development_y) if task_type == "classification" else None
        train_indices, val_indices = train_test_split(
            development,
            test_size=relative_val,
            random_state=42,
            stratify=stratify_development,
        )
    cv_folds = None
    if method == "kfold":
        development_y = y[np.concatenate([train_indices, val_indices])]
        if task_type == "timeseries":
            cv_folds = 3
        elif task_type == "classification":
            counts = np.unique(development_y, return_counts=True)[1]
            cv_folds = min(5, int(counts.min())) if len(counts) >= 2 else 0
        else:
            cv_folds = 5
        if cv_folds < 2:
            raise WorkflowError("开发集样本不足，无法执行 KFold")
    result = {
        "train_indices": np.asarray(train_indices),
        "val_indices": np.asarray(val_indices),
        "test_indices": np.asarray(test_indices),
        "split_info": {
            "method": method,
            "train_size": int(len(train_indices)),
            "val_size": int(len(val_indices)),
            "test_size": int(len(test_indices)),
            "cross_validation_folds": cv_folds,
            "test_set_held_out": True,
        },
    }
    if min(len(result["train_indices"]), len(result["val_indices"]), len(result["test_indices"])) == 0:
        raise WorkflowError("划分结果包含空分区，请调整数据量或比例")
    return result


def split_dataset(
    X: np.ndarray,
    y: np.ndarray,
    method: str,
    task_type: str,
    train_ratio: float,
    val_ratio: float,
    test_ratio: float,
) -> dict[str, Any]:
    if method not in {"random", "sequential", "kfold"}:
        raise WorkflowError("split_method 必须为 random、sequential 或 kfold")
    if min(train_ratio, val_ratio, test_ratio) <= 0 or not np.isclose(
        train_ratio + val_ratio + test_ratio, 1.0, atol=1e-6
    ):
        raise WorkflowError("训练集、验证集、测试集比例必须均大于 0 且总和为 1")
    indices = split_row_indices(
        y,
        method,
        task_type,
        train_ratio,
        val_ratio,
        test_ratio,
    )
    result = {
        "X_train": X[indices["train_indices"]],
        "X_val": X[indices["val_indices"]],
        "X_test": X[indices["test_indices"]],
        "y_train": y[indices["train_indices"]],
        "y_val": y[indices["val_indices"]],
        "y_test": y[indices["test_indices"]],
        "split_info": indices["split_info"],
    }
    return result


def _scale_data(data: dict[str, Any], output_dir: Path, model_type: str) -> tuple[dict[str, Any], str]:
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler()
    scaled = dict(data)
    scaled["X_train"] = scaler.fit_transform(data["X_train"])
    scaled["X_val"] = scaler.transform(data["X_val"])
    scaled["X_test"] = scaler.transform(data["X_test"])
    scaler_path = output_dir / f"scaler_{safe_name(model_type)}.joblib"
    joblib.dump(scaler, scaler_path)
    return scaled, str(scaler_path)


def _cv_strategy(task_type: str, split_method: str, y: np.ndarray):
    if split_method == "sequential":
        from sklearn.model_selection import TimeSeriesSplit

        return TimeSeriesSplit(n_splits=3)
    if task_type == "classification":
        from sklearn.model_selection import StratifiedKFold

        counts = np.unique(y, return_counts=True)[1]
        if len(counts) < 2 or counts.min() < 2:
            raise WorkflowError("每个类别至少需要 2 条训练样本才能执行交叉验证")
        n_splits = min(5, int(counts.min()))
        return StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    from sklearn.model_selection import KFold

    return KFold(n_splits=5, shuffle=True, random_state=42)


def _base_estimator(model_type: str, task_type: str, params: dict[str, Any]):
    classification = task_type == "classification"
    if model_type == "xgboost":
        try:
            import xgboost as xgb
        except ImportError as exc:
            raise WorkflowError("XGBoost 模型需要安装 xgboost") from exc
        cls = xgb.XGBClassifier if classification else xgb.XGBRegressor
        extra = {"eval_metric": "logloss"} if classification else {}
        return cls(**params, random_state=42, n_jobs=-1, **extra)
    if model_type == "random_forest":
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

        cls = RandomForestClassifier if classification else RandomForestRegressor
        extra = {"class_weight": "balanced"} if classification else {}
        return cls(**params, random_state=42, n_jobs=-1, **extra)
    if model_type == "svm":
        from sklearn.svm import SVC, SVR

        if classification:
            return SVC(**params, probability=True, class_weight="balanced")
        return SVR(**params)
    if model_type == "linear":
        if classification:
            from sklearn.linear_model import LogisticRegression

            return LogisticRegression(max_iter=2000, class_weight="balanced", **params)
        from sklearn.linear_model import LinearRegression

        return LinearRegression(**params)
    raise WorkflowError(f"不是传统机器学习模型: {model_type}")


def _parameter_space(model_type: str) -> dict[str, list[Any]]:
    if model_type == "xgboost":
        return {
            "n_estimators": [50, 100, 200, 300],
            "max_depth": [3, 4, 6, 8],
            "learning_rate": [0.01, 0.05, 0.1, 0.2],
            "subsample": [0.6, 0.8, 1.0],
            "colsample_bytree": [0.6, 0.8, 1.0],
        }
    if model_type == "random_forest":
        return {
            "n_estimators": [50, 100, 200, 300],
            "max_depth": [None, 5, 10, 20],
            "min_samples_split": [2, 5, 10],
            "min_samples_leaf": [1, 2, 4],
        }
    if model_type == "svm":
        return {"C": [0.1, 1.0, 10.0, 100.0], "kernel": ["rbf", "linear"], "gamma": ["scale", "auto"]}
    return {}


def _cross_validate_raw(
    dataframe: pd.DataFrame,
    y: np.ndarray,
    features: list[str],
    preprocessing_config: dict[str, Any],
    model_type: str,
    task_type: str,
    params: dict[str, Any],
    *,
    sequential: bool,
) -> float:
    from sklearn.metrics import f1_score, mean_squared_error
    from sklearn.preprocessing import StandardScaler

    cv = _cv_strategy(task_type, "sequential" if sequential else "kfold", y)
    scores: list[float] = []
    for train_indices, validation_indices in cv.split(dataframe, y):
        fold_train = dataframe.iloc[train_indices]
        fold_validation = dataframe.iloc[validation_indices]
        X_train_frame, artifact = fit_preprocessor(
            fold_train,
            features,
            preprocessing_config,
        )
        X_validation_frame, _ = transform_features(fold_validation, artifact)
        X_train = X_train_frame.to_numpy(dtype=float)
        X_validation = X_validation_frame.to_numpy(dtype=float)
        if model_type == "svm":
            scaler = StandardScaler()
            X_train = scaler.fit_transform(X_train)
            X_validation = scaler.transform(X_validation)
        estimator = _base_estimator(model_type, task_type, params)
        estimator.fit(X_train, y[train_indices])
        prediction = estimator.predict(X_validation)
        if task_type == "classification":
            score = float(f1_score(y[validation_indices], prediction, average="weighted", zero_division=0))
        else:
            score = -float(np.sqrt(mean_squared_error(y[validation_indices], prediction)))
        scores.append(score)
    return float(np.mean(scores))


def _search_raw_params(
    dataframe: pd.DataFrame,
    y: np.ndarray,
    features: list[str],
    preprocessing_config: dict[str, Any],
    model_type: str,
    task_type: str,
    method: str,
    fixed_params: dict[str, Any],
    n_trials: int,
    *,
    sequential: bool,
) -> tuple[dict[str, Any], float]:
    from sklearn.model_selection import ParameterGrid, ParameterSampler

    if model_type == "linear":
        params = dict(fixed_params)
        score = _cross_validate_raw(
            dataframe, y, features, preprocessing_config, model_type, task_type, params,
            sequential=sequential,
        )
        return params, score

    space = {key: values for key, values in _parameter_space(model_type).items() if key not in fixed_params}
    if method == "bayesian":
        try:
            import optuna
        except ImportError as exc:
            raise WorkflowError("贝叶斯调参需要安装 optuna") from exc

        def objective(trial):
            if model_type == "xgboost":
                suggested = {
                    "n_estimators": trial.suggest_int("n_estimators", 50, 300),
                    "max_depth": trial.suggest_int("max_depth", 3, 10),
                    "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                    "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                    "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                    "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                    "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
                }
            elif model_type == "random_forest":
                suggested = {
                    "n_estimators": trial.suggest_int("n_estimators", 50, 300),
                    "max_depth": trial.suggest_int("max_depth", 3, 20),
                    "min_samples_split": trial.suggest_int("min_samples_split", 2, 10),
                    "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 4),
                }
            else:
                suggested = {
                    "C": trial.suggest_float("C", 0.1, 100.0, log=True),
                    "kernel": trial.suggest_categorical("kernel", ["rbf", "linear", "poly"]),
                    "gamma": trial.suggest_categorical("gamma", ["scale", "auto"]),
                }
            params = {**DEFAULT_PARAMS[model_type], **suggested, **fixed_params}
            return _cross_validate_raw(
                dataframe,
                y,
                features,
                preprocessing_config,
                model_type,
                task_type,
                params,
                sequential=sequential,
            )

        optuna.logging.set_verbosity(optuna.logging.WARNING)
        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials)
        return {**DEFAULT_PARAMS[model_type], **study.best_params, **fixed_params}, float(study.best_value)

    if not space:
        candidates = [{}]
    elif method == "grid":
        candidates = list(ParameterGrid(space))
    else:
        total = int(np.prod([len(values) for values in space.values()]))
        candidates = list(
            ParameterSampler(
                space,
                n_iter=min(n_trials, total),
                random_state=42,
            )
        )
    best_params: dict[str, Any] | None = None
    best_score = -float("inf")
    for candidate in candidates:
        params = {**DEFAULT_PARAMS[model_type], **candidate, **fixed_params}
        score = _cross_validate_raw(
            dataframe,
            y,
            features,
            preprocessing_config,
            model_type,
            task_type,
            params,
            sequential=sequential,
        )
        if score > best_score:
            best_score = score
            best_params = params
    if best_params is None:
        raise WorkflowError(f"{model_type} 未生成有效的调参候选")
    return best_params, best_score


def _predictions(estimator: Any, X: np.ndarray, task_type: str) -> tuple[np.ndarray, np.ndarray | None]:
    prediction = estimator.predict(X)
    probabilities = None
    if task_type == "classification" and hasattr(estimator, "predict_proba"):
        probabilities = estimator.predict_proba(X)
    return np.asarray(prediction), None if probabilities is None else np.asarray(probabilities)


def _train_traditional(
    model_type: str,
    task_type: str,
    data: dict[str, Any],
    params: dict[str, Any],
    tuning: str,
    split_method: str,
    n_trials: int,
    output_dir: Path,
    raw_development: pd.DataFrame,
    raw_development_y: np.ndarray,
    original_features: list[str],
    preprocessing_config: dict[str, Any],
) -> dict[str, Any]:
    working = data
    scaler_path = None
    if model_type == "svm":
        working, scaler_path = _scale_data(data, output_dir, model_type)
    X_train_val = np.vstack([working["X_train"], working["X_val"]])
    y_train_val = np.concatenate([working["y_train"], working["y_val"]])
    tuned_score = None
    if tuning == "default":
        final_params = {**DEFAULT_PARAMS[model_type], **params}
        if split_method == "kfold":
            tuned_score = _cross_validate_raw(
                raw_development,
                raw_development_y,
                original_features,
                preprocessing_config,
                model_type,
                task_type,
                final_params,
                sequential=bool(preprocessing_config.get("causal")),
            )
        estimator = _base_estimator(model_type, task_type, final_params)
        estimator.fit(X_train_val, y_train_val)
    elif tuning in {"grid", "random", "bayesian"}:
        final_params, tuned_score = _search_raw_params(
            raw_development,
            raw_development_y,
            original_features,
            preprocessing_config,
            model_type,
            task_type,
            tuning,
            params,
            n_trials,
            sequential=bool(preprocessing_config.get("causal")),
        )
        estimator = _base_estimator(model_type, task_type, final_params)
        estimator.fit(X_train_val, y_train_val)
    else:
        raise WorkflowError(f"未知调参方式: {tuning}")

    if model_type == "xgboost":
        model_path = output_dir / "model_xgboost.json"
        estimator.save_model(model_path)
    else:
        model_path = output_dir / f"model_{safe_name(model_type)}.joblib"
        joblib.dump(estimator, model_path)
    y_pred, y_prob = _predictions(estimator, working["X_test"], task_type)
    payload_path = output_dir / f"test_payload_{safe_name(model_type)}.joblib"
    joblib.dump(
        {"y_true": working["y_test"], "y_pred": y_pred, "y_prob": y_prob},
        payload_path,
    )
    return {
        "model_type": model_type,
        "model_name": {
            "xgboost": "XGBoost",
            "random_forest": "Random Forest",
            "svm": "SVM",
            "linear": "Linear/Logistic Regression",
        }[model_type],
        "model_path": str(model_path),
        "scaler_path": scaler_path,
        "params": final_params,
        "tuning_score": tuned_score,
        "test_payload_path": str(payload_path),
        "is_torch": False,
    }


def _make_sequences(X: np.ndarray, y: np.ndarray, length: int) -> tuple[np.ndarray, np.ndarray]:
    if len(X) <= length:
        raise WorkflowError(f"序列长度 {length} 不得大于或等于数据分区样本数 {len(X)}")
    return (
        np.asarray([X[index : index + length] for index in range(len(X) - length)]),
        np.asarray([y[index + length] for index in range(len(y) - length)]),
    )


def _make_sequences_with_history(
    X: np.ndarray,
    y: np.ndarray,
    length: int,
    history_X: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if len(history_X) < length:
        raise WorkflowError(f"历史上下文少于序列长度 {length}")
    combined = np.vstack([history_X[-length:], X])
    sequences = np.asarray([combined[index : index + length] for index in range(len(X))])
    return sequences, np.asarray(y)


def _train_torch(
    model_type: str,
    task_type: str,
    data: dict[str, Any],
    params: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError as exc:
        raise WorkflowError("LSTM、1D-CNN 和 MLP 需要安装 torch") from exc

    torch.manual_seed(42)
    config = {**DEFAULT_PARAMS[model_type], **params}
    working, scaler_path = _scale_data(data, output_dir, model_type)
    classification = task_type == "classification"
    output_size = int(len(np.unique(data["y_train"]))) if classification else 1
    input_size = int(working["X_train"].shape[1])

    if model_type in {"lstm", "cnn1d"}:
        seq_length = int(config["seq_length"])
        X_train, y_train = _make_sequences(working["X_train"], working["y_train"], seq_length)
        X_val, y_val = _make_sequences_with_history(
            working["X_val"],
            working["y_val"],
            seq_length,
            working["X_train"],
        )
        X_test, y_test = _make_sequences_with_history(
            working["X_test"],
            working["y_test"],
            seq_length,
            np.vstack([working["X_train"], working["X_val"]]),
        )
    else:
        seq_length = None
        X_train, y_train = working["X_train"], working["y_train"]
        X_val, y_val = working["X_val"], working["y_val"]
        X_test, y_test = working["X_test"], working["y_test"]

    class MLP(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            layers: list[nn.Module] = []
            previous = input_size
            for hidden in config["hidden_layers"]:
                layers.extend([nn.Linear(previous, int(hidden)), nn.ReLU(), nn.Dropout(float(config["dropout"]))])
                previous = int(hidden)
            layers.append(nn.Linear(previous, output_size))
            self.net = nn.Sequential(*layers)

        def forward(self, value):
            return self.net(value)

    class LSTM(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.lstm = nn.LSTM(
                input_size,
                int(config["hidden_size"]),
                int(config["num_layers"]),
                batch_first=True,
                dropout=float(config["dropout"]) if int(config["num_layers"]) > 1 else 0.0,
            )
            self.fc = nn.Linear(int(config["hidden_size"]), output_size)

        def forward(self, value):
            output, _ = self.lstm(value)
            return self.fc(output[:, -1, :])

    class CNN1D(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            layers: list[nn.Module] = []
            channels_in = input_size
            for channels_out in config["channels"]:
                layers.extend(
                    [
                        nn.Conv1d(channels_in, int(channels_out), int(config["kernel_size"]), padding="same"),
                        nn.ReLU(),
                        nn.Dropout(float(config["dropout"])),
                    ]
                )
                channels_in = int(channels_out)
            self.conv = nn.Sequential(*layers)
            self.pool = nn.AdaptiveAvgPool1d(1)
            self.fc = nn.Linear(channels_in, output_size)

        def forward(self, value):
            value = value.permute(0, 2, 1)
            return self.fc(self.pool(self.conv(value)).squeeze(-1))

    model = {"mlp": MLP, "lstm": LSTM, "cnn1d": CNN1D}[model_type]()
    criterion = nn.CrossEntropyLoss() if classification else nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=float(config["learning_rate"]))
    X_train_tensor = torch.as_tensor(np.array(X_train, copy=True), dtype=torch.float32)
    X_val_tensor = torch.as_tensor(np.array(X_val, copy=True), dtype=torch.float32)
    X_test_tensor = torch.as_tensor(np.array(X_test, copy=True), dtype=torch.float32)
    y_dtype = torch.long if classification else torch.float32
    y_train_tensor = torch.as_tensor(np.array(y_train, copy=True), dtype=y_dtype)
    y_val_tensor = torch.as_tensor(np.array(y_val, copy=True), dtype=y_dtype)
    loader = DataLoader(
        TensorDataset(X_train_tensor, y_train_tensor),
        batch_size=int(config["batch_size"]),
        shuffle=model_type == "mlp",
    )
    best_state: dict[str, Any] | None = None
    best_loss = float("inf")
    train_losses: list[float] = []
    val_losses: list[float] = []
    for _ in range(int(config["epochs"])):
        model.train()
        total = 0.0
        batches = 0
        for batch_X, batch_y in loader:
            optimizer.zero_grad()
            output = model(batch_X)
            loss = criterion(output, batch_y if classification else batch_y.reshape(-1, 1))
            loss.backward()
            optimizer.step()
            total += float(loss.item())
            batches += 1
        train_losses.append(total / max(batches, 1))
        model.eval()
        with torch.no_grad():
            output = model(X_val_tensor)
            val_loss = criterion(output, y_val_tensor if classification else y_val_tensor.reshape(-1, 1))
        value = float(val_loss.item())
        val_losses.append(value)
        if value < best_loss:
            best_loss = value
            best_state = {key: tensor.detach().clone() for key, tensor in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        test_output = model(X_test_tensor)
        if classification:
            y_pred = test_output.argmax(dim=1).cpu().numpy()
            y_prob = torch.softmax(test_output, dim=1).cpu().numpy()
        else:
            y_pred = test_output.reshape(-1).cpu().numpy()
            y_prob = None

    example = X_train_tensor[:1]
    traced = torch.jit.trace(model, example)
    model_path = output_dir / f"model_{safe_name(model_type)}.pt"
    # The C++ path overload used by ScriptModule.save is not Unicode-safe on
    # every Windows/PyTorch combination. Python's file handle is Unicode-safe.
    with model_path.open("wb") as model_file:
        torch.jit.save(traced, model_file)
    loss_path = output_dir / f"loss_{safe_name(model_type)}.png"
    fig, axis = plt.subplots(figsize=(10, 5))
    axis.plot(train_losses, label="Train Loss")
    axis.plot(val_losses, label="Validation Loss")
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Loss")
    axis.set_title(f"{model_type.upper()} Training Loss")
    axis.legend()
    axis.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(loss_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    payload_path = output_dir / f"test_payload_{safe_name(model_type)}.joblib"
    joblib.dump({"y_true": y_test, "y_pred": y_pred, "y_prob": y_prob}, payload_path)
    return {
        "model_type": model_type,
        "model_name": {"lstm": "LSTM", "cnn1d": "1D-CNN", "mlp": "MLP"}[model_type],
        "model_path": str(model_path),
        "scaler_path": scaler_path,
        "params": config,
        "tuning_score": None,
        "test_payload_path": str(payload_path),
        "loss_plot": str(loss_path),
        "is_torch": True,
        "sequence_length": seq_length,
        "input_size": input_size,
        "output_size": output_size,
    }


def train_selected_models(
    dataframe: pd.DataFrame,
    features: list[str],
    target: str,
    task_type: str,
    models: list[str],
    training_config: dict[str, Any],
    output_dir: str | Path,
    *,
    preprocessing_config: dict[str, Any],
) -> dict[str, Any]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    unknown = [model for model in models if model not in SUPPORTED_MODELS]
    if unknown:
        raise WorkflowError(f"不支持的模型: {unknown}")
    if not models:
        raise WorkflowError("至少选择一个模型")
    normalized_params = validate_training_configuration(
        models,
        task_type,
        str(training_config["split_method"]),
        str(training_config.get("tuning", "default")),
        training_config["train_ratio"],
        training_config["val_ratio"],
        training_config["test_ratio"],
        training_config.get("n_trials", 30),
        training_config.get("model_params"),
    )
    training_config = {**training_config, "model_params": normalized_params}

    filtered, dropped_rows = filter_preprocessing_rows(
        dataframe,
        features,
        target,
        preprocessing_config,
    )
    filtered = filtered.reset_index(drop=True)
    if task_type in {"regression", "timeseries"}:
        raw_target = pd.to_numeric(filtered[target], errors="coerce")
        if raw_target.isna().any():
            raise WorkflowError("回归或时序任务的目标变量必须为数值型")
        split_target = raw_target.to_numpy(dtype=float)
    else:
        split_target = filtered[target].astype(str).to_numpy()

    index_split = split_row_indices(
        split_target,
        str(training_config["split_method"]),
        task_type,
        float(training_config["train_ratio"]),
        float(training_config["val_ratio"]),
        float(training_config["test_ratio"]),
    )
    train_indices = index_split["train_indices"]
    val_indices = index_split["val_indices"]
    test_indices = index_split["test_indices"]

    target_encoder = None
    if task_type == "classification":
        from sklearn.preprocessing import LabelEncoder

        encoder = LabelEncoder()
        encoder.fit(split_target[train_indices])
        try:
            y = encoder.transform(split_target)
        except ValueError as exc:
            raise WorkflowError("验证集或测试集出现训练集中从未见过的目标类别") from exc
        encoder_path = destination / "target_encoder.joblib"
        joblib.dump(encoder, encoder_path)
        target_encoder = {"path": str(encoder_path), "classes": encoder.classes_.tolist()}
    else:
        y = split_target.astype(float)

    preprocessing_dir = destination / "preprocessing"
    X_train_frame, artifact = fit_preprocessor(
        filtered.iloc[train_indices],
        features,
        preprocessing_config,
        preprocessing_dir,
    )
    X_val_frame, _ = transform_features(filtered.iloc[val_indices], artifact)
    X_test_frame, _ = transform_features(filtered.iloc[test_indices], artifact)
    final_features = artifact["final_features"]
    split = {
        "X_train": X_train_frame.to_numpy(dtype=float),
        "X_val": X_val_frame.to_numpy(dtype=float),
        "X_test": X_test_frame.to_numpy(dtype=float),
        "y_train": y[train_indices],
        "y_val": y[val_indices],
        "y_test": y[test_indices],
        "split_info": {
            **index_split["split_info"],
            "preprocessor_fit_rows": int(len(train_indices)),
            "rows_dropped_before_split": dropped_rows,
        },
    }
    model_task_type = "classification" if task_type == "classification" else "regression"
    development_indices = np.concatenate([train_indices, val_indices])
    raw_development = filtered.iloc[development_indices].reset_index(drop=True)
    development_y = y[development_indices]
    results: list[dict[str, Any]] = []
    for model_type in models:
        started = time.perf_counter()
        model_dir = destination / safe_name(model_type)
        model_dir.mkdir(parents=True, exist_ok=True)
        params = dict(training_config.get("model_params", {}).get(model_type, {}))
        if model_type in {"lstm", "cnn1d", "mlp"}:
            result = _train_torch(model_type, model_task_type, split, params, model_dir)
        else:
            result = _train_traditional(
                model_type,
                model_task_type,
                split,
                params,
                str(training_config.get("tuning", "default")),
                str(training_config["split_method"]),
                int(training_config.get("n_trials", 30)),
                model_dir,
                raw_development,
                development_y,
                features,
                preprocessing_config,
            )
        result["duration_seconds"] = round(time.perf_counter() - started, 3)
        results.append(result)
    summary = {
        "task_type": task_type,
        "target": target,
        "original_features": features,
        "features": final_features,
        "split_info": split["split_info"],
        "target_encoder": target_encoder,
        "preprocessor_path": artifact["artifact_path"],
        "preprocessor_fit_scope": "training_partition_only",
        "models": results,
    }
    write_json(destination / "training_results.json", summary)
    return summary
