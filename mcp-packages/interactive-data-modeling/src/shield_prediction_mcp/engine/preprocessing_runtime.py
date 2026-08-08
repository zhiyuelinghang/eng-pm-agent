from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1")


def load_data(filepath: str | Path) -> pd.DataFrame:
    """Load every tabular format accepted by the MCP and exported predictor."""
    path = Path(filepath)
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        separator = "\t" if suffix == ".tsv" else ","
        last_error: Exception | None = None
        for encoding in CSV_ENCODINGS:
            try:
                return pd.read_csv(path, encoding=encoding, sep=separator)
            except (UnicodeDecodeError, pd.errors.ParserError) as exc:
                last_error = exc
        raise ValueError("无法解析数据文件；请检查编码、分隔符和文件结构") from last_error
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    if suffix in {".json", ".jsonl", ".ndjson"}:
        return pd.read_json(path, lines=suffix in {".jsonl", ".ndjson"})
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    raise ValueError(f"不支持的数据格式: {suffix}")


def _apply_denoise(series: pd.Series, config: dict[str, Any]) -> pd.Series:
    method = str(config["method"])
    numeric = pd.to_numeric(series, errors="coerce")
    if method == "moving_average":
        # A trailing window is causal. center=True would expose future rows.
        window = max(1, int(config.get("window", 5)))
        return numeric.rolling(window=window, min_periods=1).mean()
    values = numeric.to_numpy(dtype=float)
    if method == "wavelet":
        import pywt

        if len(values) < 4:
            return numeric
        wavelet = str(config.get("wavelet", "db4"))
        max_level = pywt.dwt_max_level(len(values), pywt.Wavelet(wavelet).dec_len)
        level = min(max(1, int(config.get("level", 3))), max_level) if max_level else 0
        if level == 0:
            return numeric
        coeffs = pywt.wavedec(values, wavelet, level=level)
        sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if len(coeffs[-1]) else 0.0
        threshold = sigma * np.sqrt(2 * np.log(max(len(values), 2)))
        rebuilt = [coeffs[0], *(pywt.threshold(c, threshold, mode="soft") for c in coeffs[1:])]
        return pd.Series(pywt.waverec(rebuilt, wavelet)[: len(values)], index=series.index)
    if method == "savgol":
        from scipy.signal import savgol_filter

        polyorder = max(1, int(config.get("polyorder", 3)))
        window = max(polyorder + 2, int(config.get("window", 11)))
        if window % 2 == 0:
            window += 1
        if len(values) <= polyorder + 1:
            return numeric
        window = min(window, len(values) if len(values) % 2 else len(values) - 1)
        if window <= polyorder:
            return numeric
        return pd.Series(savgol_filter(values, window, polyorder), index=series.index)
    raise ValueError(f"未知降噪方法: {method}")


def transform_features(
    df: pd.DataFrame,
    artifact: dict[str, Any],
    *,
    require_numeric: bool = True,
) -> tuple[pd.DataFrame, pd.Index]:
    """Apply a preprocessor fitted on training data without learning new values."""
    transformed = df.copy()
    original_features = artifact["original_features"]
    missing_columns = [column for column in original_features if column not in transformed.columns]
    if missing_columns:
        raise ValueError(f"新数据缺少特征列: {missing_columns}")

    missing = artifact.get("missing", {})
    methods = missing.get("methods", {})
    fill_values = missing.get("fill_values", {})
    drop_columns = [
        column
        for column, method in methods.items()
        if method == "drop" and column in transformed.columns
    ]
    if drop_columns:
        transformed = transformed.dropna(subset=drop_columns).copy()

    for column, method in methods.items():
        if column not in transformed.columns or not transformed[column].isna().any():
            continue
        fallback = fill_values.get(column)
        if method in {"mean", "median", "mode"}:
            transformed[column] = transformed[column].fillna(fallback)
        elif method == "interpolate":
            numeric = pd.to_numeric(transformed[column], errors="coerce")
            if artifact.get("causal"):
                transformed[column] = numeric.ffill().fillna(fallback)
            else:
                transformed[column] = numeric.interpolate(method="linear").fillna(fallback)
        elif method == "ffill":
            transformed[column] = transformed[column].ffill().fillna(fallback)

    knn_columns = missing.get("knn_columns", [])
    knn_imputer = artifact.get("knn_imputer")
    if knn_columns and knn_imputer is not None:
        transformed[knn_columns] = knn_imputer.transform(transformed[knn_columns])

    denoise = artifact.get("denoise")
    if denoise:
        for column in denoise.get("columns", []):
            transformed[column] = _apply_denoise(transformed[column], denoise)

    for column, config in artifact.get("encoding", {}).items():
        values = transformed[column].astype(str)
        if config["method"] == "label":
            transformed[column] = values.map(config["mapping"]).fillna(-1).astype(float)
        elif config["method"] == "onehot":
            for category, new_column in zip(config["categories"], config["columns"]):
                transformed[new_column] = (values == category).astype(float)
            transformed = transformed.drop(columns=[column])

    final_features = artifact["final_features"]
    result = transformed[final_features]
    if require_numeric:
        result = result.astype(float)
    if require_numeric and result.isna().any().any():
        columns = result.columns[result.isna().any()].tolist()
        raise ValueError(f"预处理后仍存在缺失值: {columns}")
    return result, transformed.index
