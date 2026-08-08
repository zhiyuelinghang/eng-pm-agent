from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path
from typing import Any

from .data import write_json
from .errors import DomainError as WorkflowError
from .utils import safe_name


PREDICT_SCRIPT = r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from preprocessing_runtime import load_data, transform_features

BASE = Path(__file__).resolve().parent


def predict(input_path, output_path):
    config = json.loads((BASE / "model_config.json").read_text(encoding="utf-8"))
    artifact = joblib.load(BASE / config["preprocessor_path"])
    frame = load_data(input_path)
    X_frame, kept_index = transform_features(frame, artifact)
    X = X_frame.to_numpy(dtype=float)
    if config.get("scaler_path"):
        X = joblib.load(BASE / config["scaler_path"]).transform(X)
    model_type = config["model_type"]
    if model_type == "xgboost":
        import xgboost as xgb
        model = xgb.XGBClassifier() if config["task_type"] == "classification" else xgb.XGBRegressor()
        model.load_model(BASE / config["model_path"])
        prediction = model.predict(X)
    elif config.get("is_torch"):
        import torch
        with (BASE / config["model_path"]).open("rb") as model_file:
            model = torch.jit.load(model_file)
        model.eval()
        length = config.get("sequence_length")
        if length:
            if len(X) <= length:
                raise ValueError(f"Input rows must exceed sequence length {length}")
            X = np.asarray([X[index:index + length] for index in range(len(X) - length)])
            kept_index = kept_index[length:]
        with torch.no_grad():
            output = model(torch.as_tensor(X, dtype=torch.float32))
            prediction = output.argmax(dim=1).numpy() if config["task_type"] == "classification" else output.reshape(-1).numpy()
    else:
        model = joblib.load(BASE / config["model_path"])
        prediction = model.predict(X)
    if config["task_type"] == "classification" and config.get("target_encoder_path"):
        encoder = joblib.load(BASE / config["target_encoder_path"])
        prediction = encoder.inverse_transform(np.asarray(prediction, dtype=int))
    result = frame.loc[kept_index].copy()
    result["prediction"] = prediction
    result.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Predicted {len(result)} rows -> {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tabular data prediction model inference")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="predictions.csv")
    arguments = parser.parse_args()
    predict(arguments.input, arguments.output)
'''


def _copy(source: str | None, destination: Path) -> str | None:
    if not source:
        return None
    path = Path(source)
    if not path.is_file():
        raise WorkflowError(
            "待导出文件不存在",
            code="INTERNAL_ERROR",
            recoverable=False,
            suggestion="重新训练模型后再导出",
        )
    target = destination / path.name
    shutil.copy2(path, target)
    return target.name


def export_bundle(
    training_results: dict[str, Any],
    evaluation_results: dict[str, Any],
    model_type: str,
    preprocessor_path: str,
    output_dir: str | Path,
    *,
    version: int = 1,
) -> dict[str, Any]:
    model = next((item for item in training_results["models"] if item["model_type"] == model_type), None)
    evaluation = next((item for item in evaluation_results["models"] if item["model_type"] == model_type), None)
    if model is None or evaluation is None:
        raise WorkflowError(f"找不到已训练并评估的模型: {model_type}")
    if version < 1:
        raise WorkflowError("产物版本号必须大于等于 1", code="INVALID_INPUT")
    destination = Path(output_dir) / safe_name(model_type) / f"v{version}"
    destination.mkdir(parents=True, exist_ok=True)
    model_name = _copy(model["model_path"], destination)
    scaler_name = _copy(model.get("scaler_path"), destination)
    preprocessor_name = _copy(preprocessor_path, destination)
    encoder_info = training_results.get("target_encoder")
    encoder_name = _copy(encoder_info.get("path") if encoder_info else None, destination)

    plots_dir = destination / "evaluation_plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_names: list[str] = []
    for plot in evaluation.get("plots", []):
        source = Path(plot)
        if source.is_file():
            target = plots_dir / source.name
            shutil.copy2(source, target)
            plot_names.append(str(Path("evaluation_plots") / source.name))

    config = {
        "model_type": model_type,
        "model_name": model["model_name"],
        "model_path": model_name,
        "scaler_path": scaler_name,
        "preprocessor_path": preprocessor_name,
        "target_encoder_path": encoder_name,
        "target_classes": encoder_info.get("classes") if encoder_info else None,
        "task_type": training_results["task_type"],
        "target": training_results["target"],
        "original_features": training_results.get("original_features", training_results["features"]),
        "features": training_results["features"],
        "model_params": model["params"],
        "split_info": training_results["split_info"],
        "metrics": evaluation["metrics"],
        "is_torch": bool(model.get("is_torch")),
        "sequence_length": model.get("sequence_length"),
    }
    write_json(destination / "model_config.json", config)
    (destination / "predict.py").write_text(textwrap.dedent(PREDICT_SCRIPT), encoding="utf-8")
    runtime_source = Path(__file__).with_name("preprocessing_runtime.py")
    shutil.copy2(runtime_source, destination / "preprocessing_runtime.py")
    metrics_rows = "\n".join(
        f"| {key} | {value} |"
        for key, value in evaluation["metrics"].items()
        if isinstance(value, (str, int, float)) or value is None
    )
    report = f"""# 数据预测模型训练报告

## 模型信息

- 模型：{model['model_name']}
- 任务类型：{training_results['task_type']}
- 目标变量：{training_results['target']}
- 输入特征数：{len(training_results['features'])}
- 训练耗时：{model['duration_seconds']} 秒

## 数据划分

```json
{json.dumps(training_results['split_info'], ensure_ascii=False, indent=2)}
```

## 模型参数

```json
{json.dumps(model['params'], ensure_ascii=False, indent=2)}
```

## 测试集指标

| 指标 | 值 |
|---|---:|
{metrics_rows}

## 推理

```powershell
python predict.py --input new_data.csv --output predictions.csv
```
"""
    (destination / "training_report.md").write_text(report, encoding="utf-8")
    archive_base = destination.parent / f"{safe_name(model_type)}_bundle_v{version}"
    archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=destination)
    return {
        "model_type": model_type,
        "artifact_version": version,
        "export_dir": str(destination),
        "archive_path": archive_path,
        "files": {
            "model": model_name,
            "scaler": scaler_name,
            "preprocessor": preprocessor_name,
            "target_encoder": encoder_name,
            "config": "model_config.json",
            "predict_script": "predict.py",
            "preprocessing_runtime": "preprocessing_runtime.py",
            "report": "training_report.md",
            "plots": plot_names,
        },
    }
