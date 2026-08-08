from __future__ import annotations

import json
import math
import os
import warnings
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from .preprocessing_runtime import (
    CSV_ENCODINGS,
    _apply_denoise as _runtime_apply_denoise,
    load_data as _runtime_load_data,
    transform_features as _runtime_transform_features,
)
from .errors import DomainError as WorkflowError
from .utils import safe_name


def load_data(filepath: str | Path) -> pd.DataFrame:
    try:
        dataframe = _runtime_load_data(filepath)
    except ImportError as exc:
        raise WorkflowError(
            "读取该数据格式所需依赖不可用",
            code="DEPENDENCY_UNAVAILABLE",
            recoverable=False,
            suggestion="安装对应数据格式依赖后重试",
        ) from exc
    except OSError as exc:
        raise WorkflowError(
            "数据文件无法读取",
            code="INVALID_INPUT",
            suggestion="检查文件权限和文件完整性后重试",
        ) from exc
    except ValueError as exc:
        message = str(exc)
        public_message = (
            message
            if message.startswith("不支持的数据格式:")
            else "数据文件无法解析；请检查编码、分隔符和文件结构"
        )
        raise WorkflowError(
            public_message,
            code="INVALID_INPUT",
            suggestion="确认文件格式与内容一致后重试",
        ) from exc
    max_rows = max(1, int(os.environ.get("PREDICT_MAX_DATA_ROWS", "1000000")))
    max_columns = max(1, int(os.environ.get("PREDICT_MAX_DATA_COLUMNS", "2000")))
    if len(dataframe) > max_rows:
        raise WorkflowError(
            f"数据行数超出服务器上限 {max_rows}",
            code="RESOURCE_LIMIT",
            suggestion="减少数据行数或由管理员调整 PREDICT_MAX_DATA_ROWS",
        )
    if len(dataframe.columns) > max_columns:
        raise WorkflowError(
            f"数据列数超出服务器上限 {max_columns}",
            code="RESOURCE_LIMIT",
            suggestion="减少字段数量或由管理员调整 PREDICT_MAX_DATA_COLUMNS",
        )
    return dataframe


def write_json(path: str | Path, value: Any) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str)
    return str(destination)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _looks_like_time(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    if not (pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series)):
        return False
    sample = series.dropna().astype(str).head(50)
    if sample.empty:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(sample, errors="coerce")
    return float(parsed.notna().mean()) >= 0.8


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    numeric_stats: dict[str, Any] = {}
    missing: dict[str, Any] = {}
    non_numeric: list[dict[str, Any]] = []
    time_columns: list[str] = []

    for column in df.columns:
        series = df[column]
        info: dict[str, Any] = {
            "name": str(column),
            "dtype": str(series.dtype),
            "non_null_count": int(series.notna().sum()),
            "null_count": int(series.isna().sum()),
            "null_ratio": round(float(series.isna().mean()), 6),
            "unique_count": int(series.nunique(dropna=True)),
            "is_numeric": bool(pd.api.types.is_numeric_dtype(series)),
        }
        if info["null_count"]:
            missing[str(column)] = {
                "count": info["null_count"],
                "ratio": info["null_ratio"],
            }
        if info["is_numeric"]:
            description = series.describe()
            stats = {
                "mean": _finite(description.get("mean")),
                "std": _finite(description.get("std")),
                "min": _finite(description.get("min")),
                "25%": _finite(description.get("25%")),
                "50%": _finite(description.get("50%")),
                "75%": _finite(description.get("75%")),
                "max": _finite(description.get("max")),
            }
            mean = stats["mean"]
            std = stats["std"]
            info["stats"] = stats
            info["cv"] = round(abs(std / mean), 6) if mean not in (None, 0) and std is not None else None
            numeric_stats[str(column)] = stats
        else:
            samples = series.dropna().astype(str).drop_duplicates().head(5).tolist()
            info["sample_values"] = samples
            non_numeric.append(
                {"name": str(column), "unique_count": info["unique_count"], "sample_values": samples}
            )
        if _looks_like_time(series):
            time_columns.append(str(column))
        columns.append(info)

    return {
        "shape": {"rows": int(len(df)), "columns": int(len(df.columns))},
        "columns": columns,
        "missing_summary": missing,
        "numeric_stats": numeric_stats,
        "non_numeric_columns": non_numeric,
        "time_columns": time_columns,
    }


def create_missing_plot(profile: dict[str, Any], output_dir: str | Path) -> str | None:
    missing = profile.get("missing_summary", {})
    if not missing:
        return None
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    columns = list(missing)
    ratios = [float(missing[column]["ratio"]) * 100 for column in columns]
    figure, axis = plt.subplots(figsize=(10, max(4, len(columns) * 0.45)))
    bars = axis.barh(columns, ratios, alpha=0.75)
    axis.set_xlabel("Missing ratio (%)")
    axis.set_title("Missing Values")
    for bar, ratio in zip(bars, ratios):
        axis.text(bar.get_width() + 0.2, bar.get_y() + bar.get_height() / 2, f"{ratio:.1f}%", va="center")
    figure.tight_layout()
    path = Path(output_dir) / "missing_values.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(figure)
    return str(path)


def preprocessing_review(
    df: pd.DataFrame,
    features: list[str],
    target: str,
) -> dict[str, Any]:
    selected = list(dict.fromkeys(features + [target]))
    missing = []
    categorical = []
    noisy = []
    for column in selected:
        series = df[column]
        count = int(series.isna().sum())
        if count:
            if count / max(len(df), 1) > 0.3:
                recommendation = "drop_or_domain_review"
            elif pd.api.types.is_numeric_dtype(series):
                recommendation = "interpolate" if _looks_like_time(df.index.to_series()) else "median"
            else:
                recommendation = "mode"
            missing.append(
                {
                    "column": column,
                    "count": count,
                    "ratio": round(count / max(len(df), 1), 6),
                    "recommendation": recommendation,
                }
            )
        if column in features and not pd.api.types.is_numeric_dtype(series):
            categorical.append(
                {
                    "column": column,
                    "unique_count": int(series.nunique(dropna=True)),
                    "sample_values": series.dropna().astype(str).drop_duplicates().head(5).tolist(),
                    "recommendation": "onehot" if series.nunique(dropna=True) <= 20 else "label",
                }
            )
        if column in features and pd.api.types.is_numeric_dtype(series):
            mean = float(series.mean()) if series.notna().any() else 0.0
            std = float(series.std()) if series.notna().sum() > 1 else 0.0
            cv = abs(std / mean) if mean else None
            if cv is not None and cv > 0.5:
                noisy.append({"column": column, "cv": round(cv, 6)})
    return {"missing": missing, "categorical": categorical, "potentially_noisy": noisy}


def _apply_denoise(series: pd.Series, method: str, config: dict[str, Any]) -> pd.Series:
    try:
        return _runtime_apply_denoise(series, {**config, "method": method})
    except ImportError as exc:
        dependency = "PyWavelets" if method == "wavelet" else "scipy"
        raise WorkflowError(f"{method} 降噪需要安装 {dependency}") from exc
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc


MISSING_METHODS = {"mean", "median", "interpolate", "drop", "knn", "ffill", "mode"}
ENCODING_METHODS = {"label", "onehot", "drop"}
DENOISE_METHODS = {"none", "wavelet", "moving_average", "savgol"}


def validate_preprocessing_config(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    missing_default: str,
    missing_per_column: dict[str, str] | None,
    encoding: dict[str, str] | None,
    denoise: dict[str, Any] | None,
    *,
    causal: bool,
) -> dict[str, Any]:
    if missing_default not in MISSING_METHODS:
        raise WorkflowError(f"未知缺失值处理方式: {missing_default}")
    per_column = {str(key): str(value) for key, value in (missing_per_column or {}).items()}
    unknown_columns = [column for column in per_column if column not in features and column != target]
    if unknown_columns:
        raise WorkflowError(f"缺失值配置包含未选择字段: {unknown_columns}")
    invalid_missing = {column: method for column, method in per_column.items() if method not in MISSING_METHODS}
    if invalid_missing:
        raise WorkflowError(f"无效缺失值策略: {invalid_missing}")

    encoding_config = {str(key): str(value) for key, value in (encoding or {}).items()}
    unknown_encoding = [column for column in encoding_config if column not in features]
    if unknown_encoding:
        raise WorkflowError(f"编码配置包含非输入字段: {unknown_encoding}")
    invalid_encoding = {
        column: method for column, method in encoding_config.items() if method not in ENCODING_METHODS
    }
    if invalid_encoding:
        raise WorkflowError(f"无效编码策略: {invalid_encoding}")
    for column in features:
        if not pd.api.types.is_numeric_dtype(df[column]) and column not in encoding_config:
            raise WorkflowError(f"非数值特征 {column} 必须指定 label、onehot 或 drop")

    denoise_config: dict[str, Any] | None = None
    if denoise and denoise.get("method") not in (None, "none"):
        method = str(denoise["method"])
        if method not in DENOISE_METHODS:
            raise WorkflowError(f"未知降噪方法: {method}")
        columns = [str(column) for column in denoise.get("columns", [])]
        if not columns:
            raise WorkflowError("启用降噪时必须指定 columns")
        invalid_columns = [column for column in columns if column not in features]
        if invalid_columns:
            raise WorkflowError(f"只能对输入特征降噪: {invalid_columns}")
        non_numeric = [column for column in columns if not pd.api.types.is_numeric_dtype(df[column])]
        if non_numeric:
            raise WorkflowError(f"降噪字段必须为数值型: {non_numeric}")
        if causal and method in {"wavelet", "savgol"}:
            raise WorkflowError("时序任务禁止使用会读取未来窗口的 wavelet 或 savgol 降噪")
        if method in {"moving_average", "savgol"}:
            window = denoise.get("window", 5 if method == "moving_average" else 11)
            if isinstance(window, bool) or not isinstance(window, int) or window < 1:
                raise WorkflowError("denoise.window 必须为正整数")
        if method == "savgol":
            polyorder = denoise.get("polyorder", 3)
            if isinstance(polyorder, bool) or not isinstance(polyorder, int) or polyorder < 1:
                raise WorkflowError("denoise.polyorder 必须为正整数")
            if int(denoise.get("window", 11)) <= polyorder:
                raise WorkflowError("savgol 的 window 必须大于 polyorder")
        if method == "wavelet":
            level = denoise.get("level", 3)
            if isinstance(level, bool) or not isinstance(level, int) or level < 1:
                raise WorkflowError("denoise.level 必须为正整数")
        denoise_config = {**denoise, "method": method, "columns": columns}

    if df[target].isna().any() and per_column.get(target, missing_default) != "drop":
        raise WorkflowError("目标变量缺失不能插补；请将该目标字段的缺失值策略设为 drop")
    return {
        "missing_default": missing_default,
        "missing_per_column": per_column,
        "encoding": encoding_config,
        "denoise": denoise_config,
        "causal": bool(causal),
    }


def filter_preprocessing_rows(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    config: dict[str, Any],
) -> tuple[pd.DataFrame, int]:
    per_column = config["missing_per_column"]
    default = config["missing_default"]
    drop_columns = [
        column
        for column in features
        if per_column.get(column, default) == "drop"
    ]
    # Targets are labels, not model inputs. Missing labels are always unusable.
    subset = list(dict.fromkeys(drop_columns + [target]))
    filtered = df.dropna(subset=subset).copy()
    return filtered, int(len(df) - len(filtered))


def fit_preprocessor(
    df: pd.DataFrame,
    features: list[str],
    config: dict[str, Any],
    output_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit imputation and encoding exclusively on the supplied training rows."""
    working = df[features].copy()
    per_column = config["missing_per_column"]
    default = config["missing_default"]
    missing_artifact: dict[str, Any] = {"methods": {}, "fill_values": {}}
    knn_columns: list[str] = []

    for column in features:
        method = per_column.get(column, default)
        series = working[column]
        if method == "drop":
            missing_artifact["methods"][column] = "drop"
            continue
        if method == "knn":
            if not pd.api.types.is_numeric_dtype(series):
                raise WorkflowError(f"KNN 缺失值处理仅支持数值字段: {column}")
            if series.notna().sum() == 0:
                raise WorkflowError(f"字段 {column} 全部为空，无法拟合 KNN")
            knn_columns.append(column)
            missing_artifact["methods"][column] = "knn"
            continue
        if method in {"mean", "median", "interpolate", "ffill"}:
            if not pd.api.types.is_numeric_dtype(series):
                modes = series.mode(dropna=True)
                if modes.empty:
                    raise WorkflowError(f"字段 {column} 全部为空，无法填充")
                method = "mode"
                fallback: Any = modes.iloc[0]
            else:
                fallback = float(series.mean()) if method == "mean" else float(series.median())
        else:
            modes = series.mode(dropna=True)
            if modes.empty:
                raise WorkflowError(f"字段 {column} 全部为空，无法填充")
            method = "mode"
            fallback = modes.iloc[0]
        missing_artifact["methods"][column] = method
        missing_artifact["fill_values"][column] = fallback

    knn_imputer = None
    if knn_columns:
        from sklearn.impute import KNNImputer

        knn_imputer = KNNImputer(n_neighbors=min(5, max(1, len(working) - 1)))
        knn_imputer.fit(working[knn_columns])
        missing_artifact["knn_columns"] = knn_columns

    partial_artifact = {
        "original_features": features,
        "final_features": features,
        "missing": missing_artifact,
        "encoding": {},
        "denoise": config.get("denoise"),
        "causal": config.get("causal", False),
        "knn_imputer": knn_imputer,
    }
    prepared, _ = _runtime_transform_features(working, partial_artifact, require_numeric=False)

    final_features: list[str] = []
    encoding_artifact: dict[str, Any] = {}
    reserved_names = set(features)
    for column in features:
        method = config["encoding"].get(column)
        if pd.api.types.is_numeric_dtype(prepared[column]) and not method:
            final_features.append(column)
            continue
        if method == "drop":
            continue
        values = prepared[column].astype(str)
        categories = sorted(values.dropna().unique().tolist())
        if method == "label":
            mapping = {value: index for index, value in enumerate(categories)}
            encoding_artifact[column] = {"method": "label", "mapping": mapping}
            final_features.append(column)
        elif method == "onehot":
            created: list[str] = []
            for category in categories:
                base_name = f"{column}__{safe_name(category)}"
                new_name = base_name
                suffix = 2
                while new_name in reserved_names:
                    new_name = f"{base_name}_{suffix}"
                    suffix += 1
                reserved_names.add(new_name)
                created.append(new_name)
            encoding_artifact[column] = {
                "method": "onehot",
                "categories": categories,
                "columns": created,
            }
            final_features.extend(created)
        else:
            raise WorkflowError(f"字段 {column} 的编码方式无效: {method}")

    if not final_features:
        raise WorkflowError("预处理后没有可用输入特征")
    artifact = {
        "artifact_version": 2,
        "fitted_scope": "training_partition",
        "original_features": features,
        "final_features": final_features,
        "missing": missing_artifact,
        "encoding": encoding_artifact,
        "denoise": config.get("denoise"),
        "causal": config.get("causal", False),
        "knn_imputer": knn_imputer,
    }
    try:
        transformed, _ = _runtime_transform_features(working, artifact)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc

    if output_dir is not None:
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        artifact_path = destination / "preprocessor.joblib"
        joblib.dump(artifact, artifact_path)
        serializable = {key: value for key, value in artifact.items() if key != "knn_imputer"}
        write_json(destination / "preprocessor.json", serializable)
        artifact["artifact_path"] = str(artifact_path)
    return transformed, artifact


def preprocess_dataframe(
    df: pd.DataFrame,
    features: list[str],
    target: str,
    missing_default: str,
    missing_per_column: dict[str, str] | None,
    encoding: dict[str, str] | None,
    denoise: dict[str, Any] | None,
    output_dir: str | Path,
    *,
    causal: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Create a preview artifact; model training refits it on training rows only."""
    config = validate_preprocessing_config(
        df,
        features,
        target,
        missing_default,
        missing_per_column,
        encoding,
        denoise,
        causal=causal,
    )
    filtered, dropped_rows = filter_preprocessing_rows(df, features, target, config)
    transformed, artifact = fit_preprocessor(filtered, features, config, output_dir)
    processed = transformed.copy()
    processed[target] = filtered.loc[transformed.index, target]
    artifact["target"] = target
    artifact["preview_only"] = True
    artifact["dropped_rows"] = dropped_rows
    artifact["config"] = config
    return processed, artifact


def transform_features(df: pd.DataFrame, artifact: dict[str, Any]) -> tuple[pd.DataFrame, pd.Index]:
    try:
        return _runtime_transform_features(df, artifact)
    except (ImportError, ValueError) as exc:
        raise WorkflowError(str(exc)) from exc
