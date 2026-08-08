from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..engine.data import (
    create_missing_plot,
    load_data,
    preprocess_dataframe,
    preprocessing_review,
    profile_dataframe,
    write_json,
)
from ..engine.evaluation import evaluate_training_results
from ..engine.exporting import export_bundle
from ..engine.modeling import (
    SUPPORTED_MODELS,
    infer_task_type,
    recommendation_for,
    train_selected_models,
)
from ..engine.planning import (
    build_preprocessing_plan,
    build_training_plan,
    dataframe_fingerprint,
    estimate_training_cost,
    model_availability,
)
from ..session.store import SessionStore, WorkflowError, public_state, utc_now
from ..validation.configuration import validate_preprocessing_config, validate_training_configuration


def _sort_by_time(dataframe: pd.DataFrame, time_column: str | None) -> pd.DataFrame:
    if not time_column:
        return dataframe
    series = dataframe[time_column]
    if pd.api.types.is_numeric_dtype(series):
        order = pd.to_numeric(series, errors="coerce")
    else:
        order = pd.to_datetime(series, errors="coerce")
    if order.isna().any():
        raise WorkflowError(f"时间字段 {time_column} 包含无法解析的值")
    return (
        dataframe.assign(__mcp_order=order)
        .sort_values("__mcp_order", kind="stable")
        .drop(columns="__mcp_order")
        .reset_index(drop=True)
    )


class InteractiveDataModelingService:
    def __init__(self, root: str | Path | None = None) -> None:
        self.store = SessionStore(root)

    def import_data(
        self,
        file_name: str,
        content_base64: str,
        media_type: str | None = None,
    ) -> dict[str, Any]:
        return self.store.import_data(file_name, content_base64, media_type)

    def create_session(
        self,
        data_path: str | None = None,
        output_dir: str | None = None,
        data_ref: str | None = None,
    ) -> dict[str, Any]:
        if data_ref and data_path:
            raise WorkflowError("data_ref 和 data_path 只能提供一个")
        snapshot_source = bool(data_ref)
        resolved_path = self.store.resolve_data_ref(data_ref) if data_ref else data_path
        if not resolved_path:
            raise WorkflowError("必须提供平台 data_ref 或本地 data_path")
        state = self.store.create(
            str(resolved_path),
            output_dir,
            snapshot_source=snapshot_source,
        )
        return {
            "session_id": state["session_id"],
            "stage": state["stage"],
            "message": "会话已创建。下一步调用 profile_data 获取数据概览。",
            "next_tool": "profile_data",
        }

    def profile_data(self, session_id: str) -> dict[str, Any]:
        state = self.store.load(session_id)
        self.store.require_stage(state, "created", "profiled")
        dataframe = load_data(state["data_path"])
        profile = profile_dataframe(dataframe)
        missing_plot = create_missing_plot(profile, Path(state["session_dir"]) / "profile_plots")
        if missing_plot:
            profile["missing_plot"] = missing_plot
        profile_path = Path(state["session_dir"]) / "profile.json"
        write_json(profile_path, profile)
        self.store.advance(state, "profiled", profile_path=str(profile_path), profile=profile)
        return {
            "session_id": session_id,
            "stage": "profiled",
            "profile": profile,
            "intervention_required": True,
            "message": "数据概览完成。必须确认目标变量和输入特征后才能继续。",
            "next_tool": "confirm_variables",
            "choices": {
                "target": dataframe.columns.astype(str).tolist(),
                "feature_mode": ["all_numeric", "manual"],
            },
        }

    def confirm_variables(
        self,
        session_id: str,
        target: str,
        features: list[str] | None = None,
        feature_mode: str = "manual",
        task_type: str = "auto",
        time_column: str | None = None,
    ) -> dict[str, Any]:
        state = self.store.load(session_id)
        self.store.require_stage(state, "profiled", "variables_confirmed")
        dataframe = load_data(state["data_path"])
        columns = dataframe.columns.astype(str).tolist()
        dataframe.columns = columns
        if target not in columns:
            raise WorkflowError(f"目标变量不存在: {target}")
        if feature_mode == "all_numeric":
            selected = [
                column
                for column in columns
                if column != target and pd.api.types.is_numeric_dtype(dataframe[column])
            ]
        elif feature_mode == "manual":
            selected = list(dict.fromkeys(features or []))
        else:
            raise WorkflowError("feature_mode 必须为 all_numeric 或 manual")
        if target in selected:
            raise WorkflowError("目标变量不能同时作为输入特征")
        missing = [column for column in selected if column not in columns]
        if missing:
            raise WorkflowError(f"输入特征不存在: {missing}")
        if not selected:
            raise WorkflowError("至少选择一个输入特征")
        if time_column and time_column not in columns:
            raise WorkflowError(f"时间或顺序字段不存在: {time_column}")
        resolved_task = infer_task_type(dataframe[target], task_type, has_time=bool(time_column))
        variables = {
            "target": target,
            "features": selected,
            "feature_mode": feature_mode,
            "task_type": resolved_task,
            "time_column": time_column,
        }
        self.store.advance(state, "variables_confirmed", variables=variables)
        return {
            "session_id": session_id,
            "stage": "variables_confirmed",
            "confirmed": variables,
            "intervention_required": False,
            "message": "输入/输出变量已确认。下一步由 Agent 一次生成完整流水线推荐方案。",
            "next_tool": "propose_pipeline_plan",
        }

    def propose_pipeline_plan(
        self,
        session_id: str,
        objective: str = "balanced",
        search_intensity: str = "fast",
        max_models: int = 2,
        max_training_minutes: float | None = None,
        explainability_required: bool = False,
    ) -> dict[str, Any]:
        """Build one user-facing proposal for preprocessing, models and training."""
        state = self.store.load(session_id)
        self.store.require_stage(state, "variables_confirmed", "pipeline_proposed")
        variables = state["variables"]
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        dataframe = _sort_by_time(dataframe, variables.get("time_column"))
        causal = variables["task_type"] == "timeseries" or bool(variables.get("time_column"))

        review = preprocessing_review(dataframe, variables["features"], variables["target"])
        preprocessing_plan = build_preprocessing_plan(
            dataframe,
            variables["features"],
            variables["target"],
            variables["task_type"],
            review,
            has_time=bool(variables.get("time_column")),
        )
        recommended_preprocessing = preprocessing_plan["recommended_config"]
        validated_preprocessing = validate_preprocessing_config(
            dataframe,
            variables["features"],
            variables["target"],
            recommended_preprocessing["missing_default"],
            recommended_preprocessing["missing_per_column"],
            recommended_preprocessing["encoding"],
            recommended_preprocessing["denoise"],
            causal=causal,
        )
        _, preview_artifact = preprocess_dataframe(
            dataframe,
            variables["features"],
            variables["target"],
            validated_preprocessing["missing_default"],
            validated_preprocessing["missing_per_column"],
            validated_preprocessing["encoding"],
            validated_preprocessing["denoise"],
            Path(state["session_dir"]) / "pipeline_plan_preview",
            causal=causal,
        )

        training_proposal = build_training_plan(
            dataframe,
            variables["features"],
            variables["target"],
            variables["task_type"],
            has_time=bool(variables.get("time_column")),
            final_feature_count=len(preview_artifact["final_features"]),
            objective=objective,
            search_intensity=search_intensity,
            max_models=max_models,
            max_training_minutes=max_training_minutes,
            explainability_required=explainability_required,
        )
        recommended_training = {
            key: value
            for key, value in training_proposal["recommended_plan"].items()
            if key != "models"
        }
        recommended_plan = {
            "preprocessing": validated_preprocessing,
            "models": training_proposal["recommended_plan"]["models"],
            "training": recommended_training,
        }
        proposal_material = {
            "data_fingerprint": training_proposal["data_fingerprint"],
            "recommended_plan": recommended_plan,
            "objective": objective,
            "search_intensity": search_intensity,
        }
        proposal_id = hashlib.sha256(
            json.dumps(proposal_material, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        proposal = {
            "proposal_id": proposal_id,
            "data_fingerprint": training_proposal["data_fingerprint"],
            "recommended_plan": recommended_plan,
            "recommendation_reasons": {
                "preprocessing": preprocessing_plan["recommendation_reasons"],
                "models_and_training": training_proposal["recommendation_reasons"],
            },
            "confidence": training_proposal["confidence"],
            "estimated_cost": training_proposal["estimated_cost"],
            "data_context": {
                **training_proposal["data_context"],
                "preview_final_features": preview_artifact["final_features"],
            },
            "available_options": {
                "preprocessing": preprocessing_plan["available_options"],
                "models": training_proposal["available_options"]["models"],
                "split_methods": training_proposal["available_options"]["split_methods"],
                "ratio_presets": training_proposal["available_options"]["ratio_presets"],
                "custom_ratios": training_proposal["available_options"]["custom_ratios"],
                "tuning_methods": training_proposal["available_options"]["tuning_methods"],
                "manual_model_params": training_proposal["available_options"]["manual_model_params"],
            },
            "warnings": [
                *preprocessing_plan["warnings"],
                *training_proposal["warnings"],
            ],
            "attention_items": training_proposal["questions_for_user"],
        }
        review_path = Path(state["session_dir"]) / "preprocessing_review.json"
        proposal_path = Path(state["session_dir"]) / "pipeline_plan_proposal.json"
        write_json(review_path, review)
        write_json(proposal_path, proposal)
        self.store.advance(
            state,
            "pipeline_proposed",
            preprocessing_review=review,
            preprocessing_review_path=str(review_path),
            pipeline_plan_proposal=proposal,
            pipeline_plan_proposal_path=str(proposal_path),
        )
        return {
            "session_id": session_id,
            "stage": "pipeline_proposed",
            **proposal,
            "intervention_required": True,
            "confirmation_scope": "complete_pipeline_and_start_training",
            "message": (
                "完整流水线推荐和所有备选数据已生成；由 Agent 根据结构化 options 呈现并收集一次确认。"
            ),
            "next_tool": "confirm_pipeline_plan",
        }

    def confirm_pipeline_plan(
        self,
        session_id: str,
        proposal_id: str,
        missing_default: str | None = None,
        missing_per_column: dict[str, str] | None = None,
        encoding: dict[str, str] | None = None,
        denoise: dict[str, Any] | None = None,
        models: list[str] | None = None,
        split_method: str | None = None,
        tuning: str | None = None,
        train_ratio: float | None = None,
        val_ratio: float | None = None,
        test_ratio: float | None = None,
        n_trials: int | None = None,
        model_params: dict[str, dict[str, Any]] | None = None,
        user_adjustment_note: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Validate the user's single decision, then preprocess and train immediately."""
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户已确认完整方案并同意开始训练")
        state = self.store.load(session_id)
        self.store.require_stage(state, "pipeline_proposed")
        proposal = state.get("pipeline_plan_proposal")
        if not proposal:
            raise WorkflowError("当前会话没有完整流水线方案，请先调用 propose_pipeline_plan")
        if proposal_id != proposal["proposal_id"]:
            raise WorkflowError("proposal_id 已过期，请重新获取完整流水线方案")

        variables = state["variables"]
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        dataframe = _sort_by_time(dataframe, variables.get("time_column"))
        current_fingerprint = dataframe_fingerprint(
            dataframe,
            list(dict.fromkeys(variables["features"] + [variables["target"]])),
        )
        if current_fingerprint != proposal["data_fingerprint"]:
            raise WorkflowError("原始数据在方案生成后发生变化，请重新执行 propose_pipeline_plan")

        recommended = proposal["recommended_plan"]
        recommended_preprocessing = recommended["preprocessing"]
        merged_missing = {
            **recommended_preprocessing["missing_per_column"],
            **(missing_per_column or {}),
        }
        merged_encoding = {
            **recommended_preprocessing["encoding"],
            **(encoding or {}),
        }
        causal = variables["task_type"] == "timeseries" or bool(variables.get("time_column"))
        preprocessing_config = validate_preprocessing_config(
            dataframe,
            variables["features"],
            variables["target"],
            missing_default or recommended_preprocessing["missing_default"],
            merged_missing,
            merged_encoding,
            denoise if denoise is not None else recommended_preprocessing["denoise"],
            causal=causal,
        )
        _, preview_artifact = preprocess_dataframe(
            dataframe,
            variables["features"],
            variables["target"],
            preprocessing_config["missing_default"],
            preprocessing_config["missing_per_column"],
            preprocessing_config["encoding"],
            preprocessing_config["denoise"],
            Path(state["session_dir"]) / "confirmed_pipeline_preview",
            causal=causal,
        )

        selected = list(dict.fromkeys(models if models is not None else recommended["models"]))
        invalid = [model for model in selected if model not in SUPPORTED_MODELS]
        if invalid:
            raise WorkflowError(f"不支持的模型: {invalid}")
        if not selected:
            raise WorkflowError("至少选择一个模型")
        availability = model_availability()
        unavailable = {
            model: availability[model]["unavailable_reason"]
            for model in selected
            if not availability[model]["available"]
        }
        if unavailable:
            raise WorkflowError(f"所选模型当前不可用: {unavailable}")

        recommended_training = recommended["training"]
        resolved_training = {
            "split_method": (
                split_method if split_method is not None else recommended_training["split_method"]
            ),
            "tuning": tuning if tuning is not None else recommended_training["tuning"],
            "train_ratio": (
                train_ratio if train_ratio is not None else recommended_training["train_ratio"]
            ),
            "val_ratio": val_ratio if val_ratio is not None else recommended_training["val_ratio"],
            "test_ratio": (
                test_ratio if test_ratio is not None else recommended_training["test_ratio"]
            ),
            "n_trials": n_trials if n_trials is not None else recommended_training["n_trials"],
            "model_params": (
                model_params if model_params is not None else recommended_training["model_params"]
            ),
        }
        normalized_params = validate_training_configuration(
            selected,
            variables["task_type"],
            resolved_training["split_method"],
            resolved_training["tuning"],
            resolved_training["train_ratio"],
            resolved_training["val_ratio"],
            resolved_training["test_ratio"],
            resolved_training["n_trials"],
            resolved_training["model_params"],
        )
        training_config = {**resolved_training, "model_params": normalized_params}
        final_plan = {
            "preprocessing": preprocessing_config,
            "models": selected,
            "training": training_config,
        }
        changed_fields = {
            section: {
                "recommended": recommended[section],
                "selected": final_plan[section],
            }
            for section in ("preprocessing", "models", "training")
            if recommended[section] != final_plan[section]
        }
        plan_record = {
            "proposal_id": proposal_id,
            "source": "user_modified" if changed_fields else "recommended",
            "final_plan": final_plan,
            "changes_from_recommendation": changed_fields,
            "user_adjustment_note": user_adjustment_note,
            "confirmed_at": utc_now(),
            "confirmation_scope": "complete_pipeline_and_start_training",
        }

        training_dir = Path(state["artifacts_dir"]) / "training"
        results = train_selected_models(
            dataframe,
            variables["features"],
            variables["target"],
            variables["task_type"],
            selected,
            training_config,
            training_dir,
            preprocessing_config=preprocessing_config,
        )
        config_path = Path(state["session_dir"]) / "training_config.json"
        plan_path = Path(state["session_dir"]) / "confirmed_pipeline_plan.json"
        results_path = training_dir / "training_results.json"
        write_json(config_path, training_config)
        write_json(plan_path, plan_record)
        self.store.advance(
            state,
            "trained",
            preprocessing_config=preprocessing_config,
            preprocessing_summary={
                "preview_only": True,
                "original_features": variables["features"],
                "final_features": preview_artifact["final_features"],
                "task_type": variables["task_type"],
            },
            selected_models=selected,
            training_config=training_config,
            training_config_path=str(config_path),
            confirmed_pipeline_plan=plan_record,
            confirmed_pipeline_plan_path=str(plan_path),
            training_results=results,
            training_results_path=str(results_path),
            preprocessor_path=results["preprocessor_path"],
            final_features=results["features"],
        )
        model_preview = [
            {
                "model": result["model_name"],
                "duration_seconds": result["duration_seconds"],
                "params": result["params"],
                "model_path": result["model_path"],
            }
            for result in results["models"]
        ]
        return {
            "session_id": session_id,
            "stage": "trained",
            "final_plan": final_plan,
            "changes_from_recommendation": changed_fields,
            "models": model_preview,
            "split_info": results["split_info"],
            "intervention_required": True,
            "message": "完整方案已按用户的一次确认执行，训练完成。用户确认后可进行测试集评估。",
            "next_tool": "evaluate_models",
        }

    def inspect_preprocessing(self, session_id: str) -> dict[str, Any]:
        state = self.store.load(session_id)
        self.store.require_stage(state, "variables_confirmed", "preprocessing_reviewed")
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        variables = state["variables"]
        review = preprocessing_review(dataframe, variables["features"], variables["target"])
        review_path = Path(state["session_dir"]) / "preprocessing_review.json"
        write_json(review_path, review)
        self.store.advance(
            state,
            "preprocessing_reviewed",
            preprocessing_review=review,
            preprocessing_review_path=str(review_path),
        )
        return {
            "session_id": session_id,
            "stage": "preprocessing_reviewed",
            "review": review,
            "intervention_required": True,
            "message": "请明确选择缺失值、非数值字段和降噪处理方式。禁止自动处理。",
            "next_tool": "apply_preprocessing",
            "choices": {
                "missing_default": ["mean", "median", "interpolate", "drop", "knn", "ffill", "mode"],
                "encoding": ["label", "onehot", "drop"],
                "denoise_method": ["none", "wavelet", "moving_average", "savgol"],
            },
        }

    def apply_preprocessing(
        self,
        session_id: str,
        missing_default: str,
        missing_per_column: dict[str, str] | None = None,
        encoding: dict[str, str] | None = None,
        denoise: dict[str, Any] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户已确认预处理决策")
        state = self.store.load(session_id)
        self.store.require_stage(state, "preprocessing_reviewed", "preprocessed")
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        variables = state["variables"]
        time_column = variables.get("time_column")
        dataframe = _sort_by_time(dataframe, time_column)
        processed, artifact = preprocess_dataframe(
            dataframe,
            variables["features"],
            variables["target"],
            missing_default,
            missing_per_column,
            encoding,
            denoise,
            Path(state["session_dir"]) / "preprocessing",
            causal=variables["task_type"] == "timeseries" or bool(time_column),
        )
        processed_path = Path(state["session_dir"]) / "preprocessed_data.csv"
        processed.to_csv(processed_path, index=False, encoding="utf-8-sig")
        summary = {
            "original_shape": [int(len(dataframe)), int(len(dataframe.columns))],
            "processed_shape": [int(len(processed)), int(len(processed.columns))],
            "target": variables["target"],
            "original_features": variables["features"],
            "final_features": artifact["final_features"],
            "task_type": variables["task_type"],
            "missing": artifact["missing"],
            "encoding": artifact["encoding"],
            "denoise": artifact["denoise"],
            "preview_only": True,
            "dropped_rows": artifact["dropped_rows"],
        }
        self.store.advance(
            state,
            "preprocessed",
            preprocessed_data_path=str(processed_path),
            preview_preprocessor_path=artifact["artifact_path"],
            preprocessing_config=artifact["config"],
            preprocessing_summary=summary,
            final_features=artifact["final_features"],
        )
        return {
            "session_id": session_id,
            "stage": "preprocessed",
            "summary": summary,
            "processed_data_path": str(processed_path),
            "intervention_required": True,
            "message": "预处理完成。下一步由 Agent 生成完整训练计划、备选方案和成本说明。",
            "next_tool": "propose_training_plan",
        }

    def _create_training_plan(
        self,
        session_id: str,
        objective: str,
        search_intensity: str,
        max_models: int,
        max_training_minutes: float | None,
        explainability_required: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self.store.load(session_id)
        self.store.require_stage(state, "preprocessed", "models_recommended")
        variables = state["variables"]
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        dataframe = _sort_by_time(dataframe, variables.get("time_column"))
        recommendation = recommendation_for(
            rows=len(dataframe),
            feature_count=len(state["final_features"]),
            task_type=variables["task_type"],
            has_time=bool(variables.get("time_column")),
        )
        proposal = build_training_plan(
            dataframe,
            variables["features"],
            variables["target"],
            variables["task_type"],
            has_time=bool(variables.get("time_column")),
            final_feature_count=len(state["final_features"]),
            objective=objective,
            search_intensity=search_intensity,
            max_models=max_models,
            max_training_minutes=max_training_minutes,
            explainability_required=explainability_required,
        )
        recommendation_path = Path(state["session_dir"]) / "model_recommendations.json"
        proposal_path = Path(state["session_dir"]) / "training_plan_proposal.json"
        write_json(recommendation_path, recommendation)
        write_json(proposal_path, proposal)
        self.store.advance(
            state,
            "models_recommended",
            recommendations=recommendation,
            recommendations_path=str(recommendation_path),
            training_plan_proposal=proposal,
            training_plan_proposal_path=str(proposal_path),
        )
        return recommendation, proposal

    def propose_training_plan(
        self,
        session_id: str,
        objective: str = "balanced",
        search_intensity: str = "fast",
        max_models: int = 2,
        max_training_minutes: float | None = None,
        explainability_required: bool = False,
    ) -> dict[str, Any]:
        _, proposal = self._create_training_plan(
            session_id,
            objective,
            search_intensity,
            max_models,
            max_training_minutes,
            explainability_required,
        )
        return {
            "session_id": session_id,
            "stage": "models_recommended",
            **proposal,
            "intervention_required": True,
            "message": (
                "请向用户同时展示推荐方案、推荐理由、预计成本和所有可用备选项。"
                "用户可以直接接受，也可以修改任意部分；在用户明确选择前不得配置或训练。"
            ),
            "next_tool": "configure_training_plan",
        }

    # Internal compatibility methods for historical sessions and direct Python
    # callers. They are intentionally not registered as MCP tools.
    def recommend_models(self, session_id: str) -> dict[str, Any]:
        recommendation, proposal = self._create_training_plan(
            session_id,
            "balanced",
            "fast",
            2,
            None,
            False,
        )
        return {
            "session_id": session_id,
            "stage": "models_recommended",
            "recommendations": recommendation,
            "training_plan_proposal": proposal,
            "intervention_required": True,
            "message": "兼容模式：模型推荐已生成。新客户端应优先展示完整训练计划和备选方案。",
            "next_tool": "select_models",
        }

    def select_models(self, session_id: str, models: list[str], confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户已确认模型选择")
        state = self.store.load(session_id)
        self.store.require_stage(state, "models_recommended", "models_selected")
        selected = list(dict.fromkeys(models))
        invalid = [model for model in selected if model not in SUPPORTED_MODELS]
        if invalid:
            raise WorkflowError(f"不支持的模型: {invalid}")
        if not selected:
            raise WorkflowError("至少选择一个模型")
        self.store.advance(state, "models_selected", selected_models=selected)
        return {
            "session_id": session_id,
            "stage": "models_selected",
            "selected_models": selected,
            "intervention_required": True,
            "message": "模型已选择。下一步确认数据划分和超参数设置。",
            "next_tool": "configure_training",
            "choices": {
                "split_method": ["random", "sequential", "kfold"],
                "tuning": ["default", "grid", "random", "bayesian"],
            },
        }

    def configure_training(
        self,
        session_id: str,
        split_method: str,
        tuning: str = "default",
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
        n_trials: int = 30,
        model_params: dict[str, dict[str, Any]] | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户已确认训练配置")
        state = self.store.load(session_id)
        self.store.require_stage(state, "models_selected", "training_configured")
        normalized_params = validate_training_configuration(
            state["selected_models"],
            state["variables"]["task_type"],
            split_method,
            tuning,
            train_ratio,
            val_ratio,
            test_ratio,
            n_trials,
            model_params,
        )
        training_config = {
            "split_method": split_method,
            "tuning": tuning,
            "train_ratio": train_ratio,
            "val_ratio": val_ratio,
            "test_ratio": test_ratio,
            "n_trials": n_trials,
            "model_params": normalized_params,
        }
        config_path = Path(state["session_dir"]) / "training_config.json"
        write_json(config_path, training_config)
        self.store.advance(
            state,
            "training_configured",
            training_config=training_config,
            training_config_path=str(config_path),
        )
        return {
            "session_id": session_id,
            "stage": "training_configured",
            "training_config": training_config,
            "selected_models": state["selected_models"],
            "intervention_required": True,
            "message": "训练设置已确认。调用 train_models 才会开始训练。",
            "next_tool": "train_models",
        }

    def configure_training_plan(
        self,
        session_id: str,
        proposal_id: str | None = None,
        models: list[str] | None = None,
        split_method: str | None = None,
        tuning: str | None = None,
        train_ratio: float | None = None,
        val_ratio: float | None = None,
        test_ratio: float | None = None,
        n_trials: int | None = None,
        model_params: dict[str, dict[str, Any]] | None = None,
        user_adjustment_note: str | None = None,
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户已确认推荐方案或明确提出修改")
        state = self.store.load(session_id)
        self.store.require_stage(state, "models_recommended", "training_configured")
        proposal = state.get("training_plan_proposal")
        if not proposal:
            raise WorkflowError("当前会话没有训练计划，请先调用 propose_training_plan")
        if proposal_id is not None and proposal_id != proposal["proposal_id"]:
            raise WorkflowError("proposal_id 已过期，请重新获取训练计划后再确认")
        variables = state["variables"]
        current_dataframe = load_data(state["data_path"])
        current_dataframe.columns = current_dataframe.columns.astype(str)
        current_dataframe = _sort_by_time(current_dataframe, variables.get("time_column"))
        current_fingerprint = dataframe_fingerprint(
            current_dataframe,
            list(dict.fromkeys(variables["features"] + [variables["target"]])),
        )
        if current_fingerprint != proposal["data_fingerprint"]:
            raise WorkflowError("原始数据在计划生成后发生变化，请重新执行 propose_training_plan")

        recommended = proposal["recommended_plan"]
        selected = list(dict.fromkeys(models if models is not None else recommended["models"]))
        invalid = [model for model in selected if model not in SUPPORTED_MODELS]
        if invalid:
            raise WorkflowError(f"不支持的模型: {invalid}")
        if not selected:
            raise WorkflowError("至少选择一个模型")
        availability = model_availability()
        unavailable = {
            model: availability[model]["unavailable_reason"]
            for model in selected
            if not availability[model]["available"]
        }
        if unavailable:
            raise WorkflowError(f"所选模型当前不可用: {unavailable}")

        resolved = {
            "split_method": split_method if split_method is not None else recommended["split_method"],
            "tuning": tuning if tuning is not None else recommended["tuning"],
            "train_ratio": train_ratio if train_ratio is not None else recommended["train_ratio"],
            "val_ratio": val_ratio if val_ratio is not None else recommended["val_ratio"],
            "test_ratio": test_ratio if test_ratio is not None else recommended["test_ratio"],
            "n_trials": n_trials if n_trials is not None else recommended["n_trials"],
            "model_params": model_params if model_params is not None else recommended["model_params"],
        }
        normalized_params = validate_training_configuration(
            selected,
            state["variables"]["task_type"],
            resolved["split_method"],
            resolved["tuning"],
            resolved["train_ratio"],
            resolved["val_ratio"],
            resolved["test_ratio"],
            resolved["n_trials"],
            resolved["model_params"],
        )
        training_config = {**resolved, "model_params": normalized_params}
        final_plan = {"models": selected, **training_config}
        changed_fields = {
            key: {"recommended": recommended.get(key), "selected": value}
            for key, value in final_plan.items()
            if recommended.get(key) != value
        }
        plan_record = {
            "proposal_id": proposal["proposal_id"],
            "source": "user_modified" if changed_fields else "recommended",
            "final_plan": final_plan,
            "changes_from_recommendation": changed_fields,
            "user_adjustment_note": user_adjustment_note,
            "confirmed_at": utc_now(),
        }
        config_path = Path(state["session_dir"]) / "training_config.json"
        plan_path = Path(state["session_dir"]) / "confirmed_training_plan.json"
        write_json(config_path, training_config)
        write_json(plan_path, plan_record)
        self.store.advance(
            state,
            "training_configured",
            selected_models=selected,
            training_config=training_config,
            training_config_path=str(config_path),
            confirmed_training_plan=plan_record,
            confirmed_training_plan_path=str(plan_path),
        )
        return {
            "session_id": session_id,
            "stage": "training_configured",
            "final_plan": final_plan,
            "changes_from_recommendation": changed_fields,
            "estimated_cost": estimate_training_cost(
                selected,
                training_config["split_method"],
                training_config["tuning"],
                training_config["n_trials"],
            ),
            "intervention_required": True,
            "confirmation_required": "start_training",
            "message": (
                "最终训练配置已锁定。请向用户完整展示模型、划分、比例、调参和参数，"
                "并再次询问是否开始训练；未获得明确确认不得调用 train_models。"
            ),
            "next_tool": "train_models",
        }

    def train_models(self, session_id: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true 才能执行训练")
        state = self.store.load(session_id)
        self.store.require_stage(state, "training_configured")
        variables = state["variables"]
        dataframe = load_data(state["data_path"])
        dataframe.columns = dataframe.columns.astype(str)
        dataframe = _sort_by_time(dataframe, variables.get("time_column"))
        confirmed_plan = state.get("confirmed_training_plan")
        if confirmed_plan and state.get("training_plan_proposal"):
            current_fingerprint = dataframe_fingerprint(
                dataframe,
                list(dict.fromkeys(variables["features"] + [variables["target"]])),
            )
            if current_fingerprint != state["training_plan_proposal"]["data_fingerprint"]:
                raise WorkflowError("原始数据在训练计划确认后发生变化，请重新生成并确认训练计划")
        training_dir = Path(state["artifacts_dir"]) / "training"
        results = train_selected_models(
            dataframe,
            variables["features"],
            variables["target"],
            variables["task_type"],
            state["selected_models"],
            state["training_config"],
            training_dir,
            preprocessing_config=state["preprocessing_config"],
        )
        results_path = training_dir / "training_results.json"
        self.store.advance(
            state,
            "trained",
            training_results=results,
            training_results_path=str(results_path),
            preprocessor_path=results["preprocessor_path"],
            final_features=results["features"],
        )
        preview = [
            {
                "model": result["model_name"],
                "duration_seconds": result["duration_seconds"],
                "params": result["params"],
                "model_path": result["model_path"],
            }
            for result in results["models"]
        ]
        return {
            "session_id": session_id,
            "stage": "trained",
            "models": preview,
            "split_info": results["split_info"],
            "intervention_required": True,
            "message": "训练完成。用户确认后调用 evaluate_models；也可返回调整参数或更换模型。",
            "next_tool": "evaluate_models",
        }

    def evaluate_models(self, session_id: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true 才能执行测试集评估")
        state = self.store.load(session_id)
        self.store.require_stage(state, "trained", "evaluated")
        evaluation_dir = Path(state["artifacts_dir"]) / "evaluation"
        results = evaluate_training_results(state["training_results"], evaluation_dir)
        results_path = evaluation_dir / "evaluation_results.json"
        self.store.advance(
            state,
            "evaluated",
            evaluation_results=results,
            evaluation_results_path=str(results_path),
        )
        return {
            "session_id": session_id,
            "stage": "evaluated",
            "evaluation": results,
            "intervention_required": True,
            "message": "评估完成。满意后选择模型调用 export_model；不满意可调用 rewind_session。",
            "next_tool": "export_model",
        }

    def export_model(self, session_id: str, model_type: str, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise WorkflowError("必须将 confirm 设为 true，表示用户满意并同意导出")
        state = self.store.load(session_id)
        self.store.require_stage(state, "evaluated", "exported")
        export_dir = Path(state["artifacts_dir"]) / "exports"
        versions = dict(state.get("artifact_versions", {}))
        version = int(versions.get(model_type, 0)) + 1
        result = export_bundle(
            state["training_results"],
            state["evaluation_results"],
            model_type,
            state["preprocessor_path"],
            export_dir,
            version=version,
        )
        versions[model_type] = version
        exports = list(state.get("exports", []))
        exports.append(result)
        artifacts = dict(state.get("artifacts", {}))
        artifact_id = f"{model_type}_v{version}"
        artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "kind": "model_bundle",
            "model_type": model_type,
            "version": version,
            "created_at": utc_now(),
            "archive_path": result.get("archive_path"),
        }
        self.store.advance(
            state,
            "exported",
            exports=exports,
            artifacts=artifacts,
            artifact_versions=versions,
        )
        return {
            "session_id": session_id,
            "stage": "exported",
            "export": result,
            "artifact_ref": f"predict://session/{session_id}/artifact/{artifact_id}",
            "message": "模型、预处理器、配置、独立推理脚本、训练报告和图表已导出。",
        }

    def rewind_session(self, session_id: str, target_stage: str, reason: str = "user_revision") -> dict[str, Any]:
        state = self.store.load(session_id)
        allowed = {
            "profiled": [
                "variables",
                "preprocessing_review",
                "preprocessing_review_path",
                "preprocessing_summary",
                "preprocessed_data_path",
                "preview_preprocessor_path",
                "preprocessing_config",
                "preprocessor_path",
                "final_features",
                "recommendations",
                "recommendations_path",
                "pipeline_plan_proposal",
                "pipeline_plan_proposal_path",
                "training_plan_proposal",
                "training_plan_proposal_path",
                "confirmed_pipeline_plan",
                "confirmed_pipeline_plan_path",
                "confirmed_training_plan",
                "confirmed_training_plan_path",
                "selected_models",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "variables_confirmed": [
                "preprocessing_review",
                "preprocessing_review_path",
                "preprocessing_summary",
                "preprocessed_data_path",
                "preview_preprocessor_path",
                "preprocessing_config",
                "preprocessor_path",
                "final_features",
                "recommendations",
                "recommendations_path",
                "pipeline_plan_proposal",
                "pipeline_plan_proposal_path",
                "training_plan_proposal",
                "training_plan_proposal_path",
                "confirmed_pipeline_plan",
                "confirmed_pipeline_plan_path",
                "confirmed_training_plan",
                "confirmed_training_plan_path",
                "selected_models",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "preprocessing_reviewed": [
                "preprocessing_summary",
                "preprocessed_data_path",
                "preview_preprocessor_path",
                "preprocessing_config",
                "preprocessor_path",
                "final_features",
                "recommendations",
                "recommendations_path",
                "training_plan_proposal",
                "training_plan_proposal_path",
                "confirmed_training_plan",
                "confirmed_training_plan_path",
                "selected_models",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "models_recommended": [
                "confirmed_training_plan",
                "confirmed_training_plan_path",
                "selected_models",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "models_selected": [
                "confirmed_training_plan",
                "confirmed_training_plan_path",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "training_configured": [
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "pipeline_proposed": [
                "preprocessing_config",
                "preprocessor_path",
                "final_features",
                "confirmed_pipeline_plan",
                "confirmed_pipeline_plan_path",
                "selected_models",
                "training_config",
                "training_config_path",
                "training_results",
                "training_results_path",
                "evaluation_results",
                "evaluation_results_path",
                "exports",
            ],
            "trained": ["evaluation_results", "evaluation_results_path", "exports"],
        }
        if target_stage not in allowed:
            raise WorkflowError(f"不允许回退到阶段: {target_stage}")
        current_index = list(self.store_stage_order()).index(state["stage"])
        target_index = list(self.store_stage_order()).index(target_stage)
        if target_index >= current_index:
            raise WorkflowError("rewind_session 只能回退到更早阶段")
        self.store.rewind(
            state,
            target_stage,
            remove_keys=allowed[target_stage],
            reason=reason,
        )
        return {
            "session_id": session_id,
            "stage": target_stage,
            "message": f"已回退到 {target_stage}，可重新执行该阶段之后的操作。",
        }

    @staticmethod
    def store_stage_order() -> tuple[str, ...]:
        from ..session.store import STAGES  # legacy state-file order

        return STAGES

    def get_session_state(self, session_id: str) -> dict[str, Any]:
        # Python API compatibility for existing local callers. Public MCP tools
        # use predict_get_status, which applies the restricted public view.
        state = self.store.load(session_id)
        return {key: value for key, value in state.items() if key != "history"}

    def list_sessions(self) -> list[dict[str, Any]]:
        return self.store.list_sessions()

    def workflow_description(self) -> str:
        return json.dumps(
            {
                "recommended_workflow": [
                    "predict_create_session",
                    "predict_profile_data",
                    "predict_confirm_variables",
                    "predict_propose_pipeline_plan",
                    "predict_confirm_pipeline_plan",
                    "predict_get_job_status",
                    "predict_evaluate_models",
                    "predict_export_model",
                ],
                "interaction": {
                    "single_confirmation": (
                        "一次展示预处理、模型、划分和调参的推荐方案、理由、成本、风险及全部备选项；"
                        "用户可接受或在同一次回复中修改，确认后直接训练。"
                    ),
                    "display_contract": "Agent 根据标准 options 呈现全部候选及 reason，并等待用户确认。",
                },
                "removed_legacy_tools": [
                    "inspect_preprocessing",
                    "apply_preprocessing",
                    "propose_training_plan",
                    "configure_training_plan",
                    "train_models",
                    "recommend_models",
                    "select_models",
                    "configure_training",
                ],
                "principle": (
                    "Agent 必须一次给出完整推荐和全部可选项，最终选择权属于用户；"
                    "长任务返回 job_id 并通过 predict_get_job_status 查询。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )


# 保留旧类名，确保现有脚本和 Agent 配置无需修改即可继续使用。
ShieldPredictionService = InteractiveDataModelingService
