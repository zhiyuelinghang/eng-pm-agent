from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from typing import Any

import numpy as np
import pandas as pd

from .modeling import (
    DEFAULT_PARAMS,
    SUPPORTED_MODELS,
    model_parameter_options,
    recommendation_for,
)
from .errors import DomainError as WorkflowError


MODEL_NAMES = {
    "xgboost": "XGBoost",
    "random_forest": "Random Forest",
    "svm": "SVM",
    "linear": "Linear/Logistic Regression",
    "lstm": "LSTM",
    "cnn1d": "1D-CNN",
    "mlp": "MLP",
}

MODEL_COST = {
    "linear": "low",
    "random_forest": "low",
    "xgboost": "medium",
    "svm": "medium",
    "mlp": "medium",
    "cnn1d": "high",
    "lstm": "high",
}


def build_preprocessing_plan(
    dataframe: pd.DataFrame,
    features: list[str],
    target: str,
    task_type: str,
    review: dict[str, Any],
    *,
    has_time: bool,
) -> dict[str, Any]:
    """Recommend a conservative preprocessing configuration and expose alternatives."""
    causal = task_type == "timeseries" or has_time
    missing_per_column: dict[str, str] = {}
    reasons: list[str] = []
    warnings: list[str] = []

    for item in review["missing"]:
        column = item["column"]
        ratio = float(item["ratio"])
        if column == target:
            method = "drop"
            reasons.append(f"目标字段 {column} 的缺失行不能插补，推荐删除这些无标签样本")
        elif not pd.api.types.is_numeric_dtype(dataframe[column]):
            method = "mode"
            reasons.append(f"类别字段 {column} 使用众数填补，避免引入不存在的连续数值关系")
        elif causal:
            method = "ffill"
            reasons.append(f"时序字段 {column} 使用前向填充，避免读取未来值")
        else:
            method = "median"
            reasons.append(f"数值字段 {column} 使用中位数填补，对异常值更稳健")
        missing_per_column[column] = method
        if ratio > 0.3:
            warnings.append(
                f"字段 {column} 缺失率为 {ratio:.1%}；自动方案可运行，但建议结合业务判断是否移除该特征"
            )

    encoding = {
        item["column"]: item["recommendation"]
        for item in review["categorical"]
    }
    for item in review["categorical"]:
        reasons.append(
            f"类别字段 {item['column']} 有 {item['unique_count']} 个取值，"
            f"推荐 {item['recommendation']} 编码"
        )

    denoise = {"method": "none"}
    if review["potentially_noisy"]:
        reasons.append("检测到波动较大的数值字段，但默认不降噪，避免在缺少领域依据时抹除有效信号")
    else:
        reasons.append("未发现必须降噪的证据，默认保留原始信号")
    if causal:
        reasons.append("预处理按因果模式执行；插补和移动平均只能使用当前及历史数据")

    missing_options = [
        {
            "method": "mean",
            "available": True,
            "best_for": "近似对称分布的数值字段",
            "constraint": "仅适用于数值字段，且对异常值敏感",
        },
        {
            "method": "median",
            "available": True,
            "best_for": "偏态或含异常值的数值字段",
            "constraint": "仅适用于数值字段",
        },
        {
            "method": "interpolate",
            "available": True,
            "best_for": "有可靠顺序的连续数值字段",
            "constraint": "时序任务会退化为因果前向填充，不读取未来值",
        },
        {
            "method": "drop",
            "available": True,
            "best_for": "缺失很少或目标变量缺失",
            "constraint": "会减少可训练样本数",
        },
        {
            "method": "knn",
            "available": True,
            "best_for": "多个相关数值字段共同存在缺失",
            "constraint": "计算成本较高，仅适用于数值字段",
        },
        {
            "method": "ffill",
            "available": True,
            "best_for": "具有明确顺序的时序或流程数据",
            "constraint": "数据必须已按业务时间或顺序排序",
        },
        {
            "method": "mode",
            "available": True,
            "best_for": "类别字段或离散数值字段",
            "constraint": "高缺失率时可能放大多数类别",
        },
    ]
    encoding_options = [
        {
            "method": "onehot",
            "available": True,
            "best_for": "低基数无序类别",
            "constraint": "高基数字段会显著增加特征维度",
        },
        {
            "method": "label",
            "available": True,
            "best_for": "高基数类别或树模型",
            "constraint": "会引入整数顺序；线性模型和 SVM 需谨慎",
        },
        {
            "method": "drop",
            "available": True,
            "best_for": "标识符、泄漏字段或无业务意义的类别字段",
            "constraint": "会完全移除该输入特征",
        },
    ]
    denoise_options = [
        {
            "method": "none",
            "available": True,
            "causal": True,
            "best_for": "默认安全选项，保留原始信息",
        },
        {
            "method": "moving_average",
            "available": True,
            "causal": True,
            "best_for": "有顺序的高频波动信号；使用尾随窗口",
            "constraint": "需要选择数值字段和窗口大小",
        },
        {
            "method": "wavelet",
            "available": _installed("pywt") and not causal,
            "causal": False,
            "best_for": "非时序因果场景的多尺度噪声",
            "constraint": "时序任务禁用；需要 PyWavelets",
            "unavailable_reason": (
                "时序任务禁止非因果降噪"
                if causal
                else None if _installed("pywt") else "需要安装 PyWavelets"
            ),
        },
        {
            "method": "savgol",
            "available": _installed("scipy") and not causal,
            "causal": False,
            "best_for": "非时序因果场景的平滑连续曲线",
            "constraint": "时序任务禁用；需要 scipy，并设置奇数窗口和多项式阶数",
            "unavailable_reason": (
                "时序任务禁止非因果降噪"
                if causal
                else None if _installed("scipy") else "需要安装 scipy"
            ),
        },
    ]
    return {
        "recommended_config": {
            "missing_default": "median",
            "missing_per_column": missing_per_column,
            "encoding": encoding,
            "denoise": denoise,
            "causal": causal,
        },
        "recommendation_reasons": reasons,
        "available_options": {
            "missing_methods": missing_options,
            "encoding_methods": encoding_options,
            "denoise_methods": denoise_options,
            "column_diagnostics": review,
        },
        "warnings": warnings,
    }


def dataframe_fingerprint(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> str:
    selected = dataframe[columns]
    row_hashes = pd.util.hash_pandas_object(selected, index=True).to_numpy()
    schema = [(column, str(selected[column].dtype)) for column in columns]
    digest = hashlib.sha256()
    digest.update(json.dumps(schema, ensure_ascii=False).encode("utf-8"))
    digest.update(row_hashes.tobytes())
    return digest.hexdigest()


def _installed(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def model_availability() -> dict[str, dict[str, Any]]:
    torch_available = _installed("torch")
    availability = {
        "xgboost": (_installed("xgboost"), "需要安装 xgboost"),
        "random_forest": (True, None),
        "svm": (True, None),
        "linear": (True, None),
        "lstm": (torch_available, "需要安装 torch"),
        "cnn1d": (torch_available, "需要安装 torch"),
        "mlp": (torch_available, "需要安装 torch"),
    }
    return {
        model: {
            "available": available,
            "unavailable_reason": None if available else reason,
        }
        for model, (available, reason) in availability.items()
    }


def _validate_preferences(
    objective: str,
    search_intensity: str,
    max_models: int,
    max_training_minutes: float | None,
) -> None:
    if objective not in {"balanced", "accuracy", "speed", "explainability"}:
        raise WorkflowError("objective 必须为 balanced、accuracy、speed 或 explainability")
    if search_intensity not in {"fast", "balanced", "thorough"}:
        raise WorkflowError("search_intensity 必须为 fast、balanced 或 thorough")
    if isinstance(max_models, bool) or not isinstance(max_models, int) or not 1 <= max_models <= 3:
        raise WorkflowError("max_models 必须为 1 到 3 的整数")
    if max_training_minutes is not None:
        if (
            isinstance(max_training_minutes, bool)
            or not isinstance(max_training_minutes, (int, float))
            or max_training_minutes <= 0
        ):
            raise WorkflowError("max_training_minutes 必须为正数")


def _model_options(
    rows: int,
    feature_count: int,
    task_type: str,
    has_time: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    recommendation = recommendation_for(rows, feature_count, task_type, has_time)
    recommendation_by_model = {item["model"]: item for item in recommendation["models"]}
    availability = model_availability()
    options: list[dict[str, Any]] = []
    for model in SUPPORTED_MODELS:
        recommended = recommendation_by_model.get(model)
        options.append(
            {
                "model": model,
                "display_name": MODEL_NAMES[model],
                "available": availability[model]["available"],
                "unavailable_reason": availability[model]["unavailable_reason"],
                "recommended_for_data": bool(recommended and recommended["recommended"]),
                "reason": (
                    recommended["reason"]
                    if recommended
                    else "当前数据画像下不是首选，但可在满足约束时作为对照模型"
                ),
                "estimated_cost": MODEL_COST[model],
                "default_params": DEFAULT_PARAMS[model],
            }
        )
    return options, recommendation


def _select_models(
    options: list[dict[str, Any]],
    recommendation: dict[str, Any],
    objective: str,
    max_models: int,
    rows: int,
    task_type: str,
    search_intensity: str,
) -> list[str]:
    available = {item["model"] for item in options if item["available"]}
    ordered_recommendations = [
        item["model"] for item in recommendation["models"] if item["model"] in available
    ]
    if objective == "explainability":
        candidates = ["linear", "random_forest", "xgboost"]
    elif objective == "speed":
        candidates = ["linear", "random_forest", "xgboost"]
    elif task_type == "timeseries" and search_intensity == "thorough" and rows >= 1000:
        candidates = ["lstm", "xgboost", "random_forest"]
    else:
        candidates = ordered_recommendations

    selected: list[str] = []
    for model in candidates:
        if model in available and model not in selected:
            selected.append(model)
            break
    if not selected:
        selected.append("linear")

    # Pair the main nonlinear model with an interpretable baseline when possible.
    if (
        max_models >= 2
        and objective in {"balanced", "explainability"}
        and selected[0] != "linear"
        and "linear" in available
    ):
        selected.append("linear")
    for model in [*candidates, *ordered_recommendations]:
        if len(selected) >= max_models:
            break
        if model not in selected:
            selected.append(model)
    return selected[:max_models]


def _target_diagnostics(dataframe: pd.DataFrame, target: str, task_type: str) -> dict[str, Any]:
    series = dataframe[target].dropna()
    if task_type != "classification" or series.empty:
        return {}
    counts = series.astype(str).value_counts()
    imbalance_ratio = float(counts.max() / counts.min()) if len(counts) > 1 and counts.min() else None
    return {
        "class_count": int(len(counts)),
        "smallest_class_rows": int(counts.min()),
        "largest_class_rows": int(counts.max()),
        "imbalance_ratio": round(imbalance_ratio, 3) if imbalance_ratio is not None else None,
    }


def _data_warnings(
    dataframe: pd.DataFrame,
    features: list[str],
    target: str,
    task_type: str,
) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    questions: list[str] = []
    rows = max(len(dataframe), 1)
    identifier_candidates = [
        column
        for column in features
        if dataframe[column].nunique(dropna=True) / rows >= 0.98
        and (
            not pd.api.types.is_numeric_dtype(dataframe[column])
            or re.search(r"(^|[_\-\s])(id|uuid|key|code|编号|序号)([_\-\s]|$)", column, re.IGNORECASE)
        )
    ]
    if identifier_candidates:
        warnings.append(f"疑似标识符或高基数字段: {identifier_candidates}")
        questions.append("这些高基数字段是否是用户、设备或记录 ID？如是，应考虑分组划分或移除。")
    diagnostics = _target_diagnostics(dataframe, target, task_type)
    if diagnostics.get("imbalance_ratio") and diagnostics["imbalance_ratio"] >= 10:
        warnings.append(f"目标类别明显不平衡，最大/最小类别约 {diagnostics['imbalance_ratio']}:1")
        questions.append("是否更关注少数类别召回率或 Macro-F1，而不是总体准确率？")
    return warnings, questions


def estimate_training_cost(
    models: list[str],
    split_method: str,
    tuning: str,
    n_trials: int,
) -> dict[str, Any]:
    if tuning == "default":
        estimated_fits = len(models) * (6 if split_method == "kfold" else 1)
    elif tuning in {"random", "bayesian"}:
        estimated_fits = len(models) * (max(1, n_trials) * 5 + 1)
    else:
        grid_candidates = {
            "xgboost": 576,
            "random_forest": 144,
            "svm": 16,
            "linear": 1,
        }
        estimated_fits = sum(grid_candidates.get(model, 1) * 5 + 1 for model in models)
    cost_score = max({"low": 1, "medium": 2, "high": 3}[MODEL_COST[model]] for model in models)
    if estimated_fits > 20:
        cost_score += 1
    level = "low" if cost_score <= 1 else "medium" if cost_score == 2 else "high"
    return {
        "level": level,
        "estimated_model_fits": estimated_fits,
        "note": "拟合次数按约 5 折搜索估算；实际耗时取决于数据量、硬件和可选依赖。",
    }


def build_training_plan(
    dataframe: pd.DataFrame,
    features: list[str],
    target: str,
    task_type: str,
    *,
    has_time: bool,
    final_feature_count: int,
    objective: str = "balanced",
    search_intensity: str = "fast",
    max_models: int = 2,
    max_training_minutes: float | None = None,
    explainability_required: bool = False,
) -> dict[str, Any]:
    _validate_preferences(objective, search_intensity, max_models, max_training_minutes)
    if explainability_required:
        objective = "explainability"
    rows = len(dataframe)
    fingerprint = dataframe_fingerprint(dataframe, list(dict.fromkeys(features + [target])))
    options, recommendation = _model_options(rows, final_feature_count, task_type, has_time)
    selected = _select_models(
        options,
        recommendation,
        objective,
        max_models,
        rows,
        task_type,
        search_intensity,
    )

    deep_selected = bool(set(selected) & {"lstm", "cnn1d", "mlp"})
    if task_type == "timeseries" or has_time:
        split_method = "sequential"
    elif rows < 120 and not deep_selected:
        split_method = "kfold"
    else:
        split_method = "random"

    optuna_available = _installed("optuna")
    traditional_only = not deep_selected
    if max_training_minutes is not None and max_training_minutes <= 5:
        tuning, n_trials = "default", 1
    elif search_intensity == "thorough" and traditional_only:
        tuning = "bayesian" if optuna_available else "random"
        n_trials = 30
    elif search_intensity == "balanced" and rows >= 500 and traditional_only:
        tuning, n_trials = "random", 20
    else:
        tuning, n_trials = "default", 1

    ratios = {"train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15}
    diagnostics = _target_diagnostics(dataframe, target, task_type)
    warnings, questions = _data_warnings(dataframe, features, target, task_type)
    model_reasons = [
        next(item["reason"] for item in options if item["model"] == model)
        for model in selected
    ]
    reasons = [
        *model_reasons,
        (
            "检测到时间结构，采用顺序划分以避免未来数据进入训练集"
            if split_method == "sequential"
            else "样本较少，使用 KFold 提高开发集评估稳定性并保留独立测试集"
            if split_method == "kfold"
            else "当前是普通表格任务，采用可分层的随机划分"
        ),
        (
            "首轮使用默认参数，优先建立低成本可靠基线"
            if tuning == "default"
            else f"使用 {tuning} 搜索，在效果和训练成本之间进行权衡"
        ),
    ]
    recommended_plan = {
        "models": selected,
        "split_method": split_method,
        **ratios,
        "tuning": tuning,
        "n_trials": n_trials,
        "model_params": {},
    }
    proposal_material = {
        "recommended_plan": recommended_plan,
        "objective": objective,
        "search_intensity": search_intensity,
        "rows": rows,
        "features": final_feature_count,
        "data_fingerprint": fingerprint,
    }
    proposal_id = hashlib.sha256(
        json.dumps(proposal_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    split_options = [
        {
            "method": "random",
            "available": task_type != "timeseries",
            "reason": "适合普通分类/回归；分类任务会自动尝试分层",
            "constraint": "时序任务禁止使用",
            "estimated_cost": "low",
        },
        {
            "method": "sequential",
            "available": True,
            "reason": "按当前顺序切分，适合时间或流程顺序数据",
            "constraint": "必须确认当前行顺序具有业务含义",
            "estimated_cost": "low",
        },
        {
            "method": "kfold",
            "available": True,
            "compatible_with_recommended_models": not deep_selected,
            "reason": "开发集进行真实交叉验证，同时保留独立测试集",
            "constraint": "当前版本不支持深度学习模型 KFold",
            "estimated_cost": "high",
        },
    ]
    tuning_options = [
        {
            "method": "default",
            "available": True,
            "reason": "快速建立可靠基线",
            "estimated_cost": "low",
        },
        {
            "method": "random",
            "available": True,
            "compatible_with_recommended_models": traditional_only,
            "reason": "有限预算下探索参数空间",
            "constraint": "当前版本仅支持传统模型调参",
            "estimated_cost": "medium",
        },
        {
            "method": "bayesian",
            "available": optuna_available,
            "compatible_with_recommended_models": traditional_only and optuna_available,
            "reason": "用较少试验进行智能搜索",
            "estimated_cost": "medium",
            "unavailable_reason": None if optuna_available else "需要安装 optuna",
        },
        {
            "method": "grid",
            "available": True,
            "compatible_with_recommended_models": traditional_only,
            "reason": "穷举预设参数空间，仅适合空间较小的情况",
            "constraint": "当前版本仅支持传统模型调参",
            "estimated_cost": "high",
        },
    ]
    return {
        "proposal_id": proposal_id,
        "data_fingerprint": fingerprint,
        "recommended_plan": recommended_plan,
        "recommendation_reasons": reasons,
        "confidence": 0.72 if questions else 0.9,
        "estimated_cost": estimate_training_cost(selected, split_method, tuning, n_trials),
        "data_context": {
            "rows": rows,
            "original_feature_count": len(features),
            "final_feature_count": final_feature_count,
            "task_type": task_type,
            "has_time_structure": has_time,
            "target_diagnostics": diagnostics,
        },
        "available_options": {
            "models": options,
            "split_methods": split_options,
            "ratio_presets": [
                {"name": "standard", **ratios, "reason": "默认平衡方案"},
                {
                    "name": "more_training",
                    "train_ratio": 0.8,
                    "val_ratio": 0.1,
                    "test_ratio": 0.1,
                    "reason": "数据充足且希望增加训练样本",
                },
            ],
            "custom_ratios": {
                "available": True,
                "fields": ["train_ratio", "val_ratio", "test_ratio"],
                "constraint": "三个比例必须均大于 0，且总和必须为 1",
            },
            "tuning_methods": tuning_options,
            "manual_model_params": {
                "available": True,
                "by_model": model_parameter_options(task_type),
                "constraint": "只能为已选择的模型传入参数；未提供的参数沿用默认值",
            },
        },
        "warnings": warnings,
        "questions_for_user": questions,
    }
