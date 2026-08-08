from __future__ import annotations

from typing import Any


PUBLIC_ARTIFACT_FIELDS = (
    "artifact_id",
    "kind",
    "model_type",
    "version",
    "created_at",
)


def public_artifact_metadata(
    artifact: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Return an allowlisted artifact view with no storage details.

    Internal artifact dictionaries intentionally contain filesystem paths for
    server-side retrieval and cleanup. Public channels must never serialize
    those dictionaries by exclusion because new path-like fields could bypass
    a blacklist.
    """

    public = {
        key: artifact[key]
        for key in PUBLIC_ARTIFACT_FIELDS
        if key in artifact and artifact[key] is not None
    }
    artifact_id = public.get("artifact_id")
    if session_id and artifact_id:
        public["resource_ref"] = (
            f"predict://session/{session_id}/artifact/{artifact_id}"
        )
    return public
