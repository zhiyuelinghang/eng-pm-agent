"""Reuse completed MCP results for the exact same material and project state."""
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select

from .initialization_change_models import InitializationChangePreview
from .initialization_changes import _hash


def snapshot_key(plan, client):
    binding_reader = getattr(client, "get_initialization_validation_binding", None)
    binding = binding_reader() if binding_reader else None
    return _hash({
        "contract": "mcp-only-2", "binding": binding,
        "revision": plan["draft_revision"], "baseline": plan["baseline_hash"],
        "payload": plan["effective_payload"], "targets": plan["record_targets"],
        "selected": sorted(plan["selected_keys"]), "resolutions": plan["resolutions"],
        "operation_issues": plan["issues"],
    }), binding


def load_validation_snapshot(db, draft, key):
    saved = db.scalar(select(InitializationChangePreview).where(
        InitializationChangePreview.draft_id == draft.id,
        InitializationChangePreview.project_id == draft.project_id,
        InitializationChangePreview.draft_revision == draft.revision,
        InitializationChangePreview.request["snapshot_key"].as_string() == key,
    ).order_by(InitializationChangePreview.created_at.desc()).limit(1))
    if saved and saved.review.get("validation", {}).get("status") == "completed":
        return deepcopy(saved.review["issues"]), {**saved.review["validation"], "reused": True}
    return None


def save_validation_snapshot(db, draft, plan, key, issues, validation, binding=None):
    if validation.get("status") != "completed":
        return
    # A version switch during the remote call must not cache new rules under
    # the old version's key. The actual MCP verdict still belongs to this review.
    if binding and validation.get("package_id") and any(
        binding.get(name) != validation.get(name) for name in ("package_id", "package_version")
    ):
        return
    db.add(InitializationChangePreview(
        id=str(uuid4()), project_id=draft.project_id, draft_id=draft.id,
        user_id=draft.created_by_user_id, draft_revision=draft.revision,
        baseline_hash=plan["baseline_hash"], request={"snapshot_key": key},
        review={"issues": deepcopy(issues), "validation": {
            **validation, "reused": False, "validated_at": validation.get("validated_at") or datetime.now(UTC).isoformat(),
        }},
    ))
