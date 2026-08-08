from __future__ import annotations

from typing import Any


def _candidate(
    value: Any,
    label: str,
    reason: str,
    **metadata: Any,
) -> dict[str, Any]:
    return {"value": value, "label": label, "reason": reason, **metadata}


def profile_decision_options(profile: dict[str, Any]) -> dict[str, Any]:
    columns = profile.get("columns", [])
    targets = []
    features = []
    for column in columns:
        name = str(column["name"])
        dtype = str(column.get("dtype", "unknown"))
        missing = float(column.get("null_ratio", 0.0))
        reason = f"类型为 {dtype}，缺失率 {missing:.1%}"
        targets.append(_candidate(name, name, reason))
        features.append(_candidate(name, name, reason))
    time_candidates = [
        _candidate(None, "不使用时间字段", "普通分类或回归任务不需要时间顺序")
    ]
    time_candidates.extend(
        _candidate(column, column, "数据画像识别为可能的时间或顺序字段")
        for column in profile.get("time_columns", [])
    )
    return {
        "target": {"type": "single_select", "candidates": targets},
        "features": {"type": "multi_select", "candidates": features},
        "task_type": {
            "type": "single_select",
            "candidates": [
                _candidate("auto", "自动判断", "根据目标字段和时间字段自动识别任务"),
                _candidate("regression", "回归", "预测连续数值"),
                _candidate("classification", "分类", "预测离散类别"),
                _candidate("timeseries", "时序", "按时间顺序预测并启用因果约束"),
            ],
        },
        "time_column": {"type": "single_select", "candidates": time_candidates},
    }


def _method_candidates(items: list[dict[str, Any]], *, key: str = "method") -> list[dict[str, Any]]:
    result = []
    for item in items:
        value = item.get(key)
        label = str(item.get("display_name") or item.get("name") or value)
        reason = str(item.get("reason") or item.get("best_for") or item.get("constraint") or "可选配置")
        metadata = {k: v for k, v in item.items() if k not in {key, "display_name", "name", "reason"}}
        result.append(_candidate(value, label, reason, **metadata))
    return result


def pipeline_decision_options(result: dict[str, Any]) -> dict[str, Any]:
    available = result["available_options"]
    preprocessing = available["preprocessing"]
    ratios = available.get("ratio_presets", [])
    return {
        "missing_method": {
            "type": "single_select",
            "candidates": _method_candidates(preprocessing["missing_methods"]),
        },
        "encoding_method": {
            "type": "single_select",
            "candidates": _method_candidates(preprocessing["encoding_methods"]),
        },
        "denoise_method": {
            "type": "single_select",
            "candidates": _method_candidates(preprocessing["denoise_methods"]),
        },
        "models": {
            "type": "multi_select",
            "candidates": _method_candidates(available["models"], key="model"),
        },
        "split_method": {
            "type": "single_select",
            "candidates": _method_candidates(available["split_methods"]),
        },
        "ratio_preset": {
            "type": "single_select",
            "candidates": _method_candidates(ratios, key="name"),
        },
        "custom_ratios": {
            "type": "free_text",
            "candidates": [
                _candidate(
                    "train_ratio,val_ratio,test_ratio",
                    "自定义训练/验证/测试比例",
                    str(available["custom_ratios"].get("constraint", "三个比例之和必须为 1")),
                )
            ],
        },
        "tuning": {
            "type": "single_select",
            "candidates": _method_candidates(available["tuning_methods"]),
        },
        "model_params": {
            "type": "free_text",
            "candidates": [
                _candidate(
                    available["manual_model_params"].get("by_model", {}),
                    "手动模型参数",
                    str(available["manual_model_params"].get("constraint", "按模型填写参数")),
                )
            ],
        },
        "pipeline_confirmation": {
            "type": "confirm",
            "candidates": [
                _candidate("accept", "接受推荐并开始训练", "使用推荐的完整流水线"),
                _candidate("modify", "修改后开始训练", "在同一次回复中覆盖任意配置"),
                _candidate("pause", "暂不训练", "保留方案，稍后继续"),
            ],
        },
    }
