# -*- coding: utf-8 -*-
"""Credential router — CRUD endpoints for API key credentials."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_storage,
)
from ._schema import (
    CreateCredentialRequest,
    CreateCredentialResponse,
    CredentialModelCatalogResponse,
    ListCredentialsResponse,
    ListCredentialSchemasResponse,
    TestCredentialModelRequest,
    UpdateCredentialModelCatalogRequest,
    UpdateCredentialRequest,
)
from .._service import (
    CredentialView,
    CredentialModelTestResult,
    ModelDiscoveryError,
    ResourceAccessService,
    build_credential_embedding_model_catalog,
    build_credential_model_catalog,
    discover_credential_models,
    supports_model_discovery,
    test_credential_embedding_model,
    test_credential_model,
)
from ..storage import StorageBase
from ...credential import (
    CredentialBase,
    CredentialFactory,
    CredentialModelCatalog,
)

credential_router = APIRouter(
    prefix="/credential",
    tags=["credential"],
    responses={404: {"description": "Not found"}},
)


def _model_catalog_response(
    credential: CredentialBase,
) -> CredentialModelCatalogResponse:
    models = build_credential_model_catalog(credential)
    embedding_models = build_credential_embedding_model_catalog(credential)
    return CredentialModelCatalogResponse(
        models=models,
        embedding_models=embedding_models,
        manual_models=credential.model_catalog.manual_models,
        hidden_model_ids=credential.model_catalog.hidden_model_ids,
        hidden_embedding_model_ids=(
            credential.model_catalog.hidden_embedding_model_ids
        ),
        total=(
            sum(model.enabled for model in models)
            + sum(model.enabled for model in embedding_models)
        ),
        discovery_supported=supports_model_discovery(credential),
        last_discovery_at=credential.model_catalog.last_discovery_at,
        last_discovery_error=credential.model_catalog.last_discovery_error,
    )


@credential_router.get(
    "/schemas",
    response_model=ListCredentialSchemasResponse,
    summary="List JSON schemas for all credential types",
)
async def list_credential_schemas() -> ListCredentialSchemasResponse:
    """Return JSON schemas for all registered credential types.

    Used by the frontend to render credential creation forms dynamically.
    """

    return ListCredentialSchemasResponse(
        schemas=CredentialFactory.list_schemas(),
    )


@credential_router.get(
    "/",
    response_model=ListCredentialsResponse,
    summary="List all credentials",
)
async def list_credentials(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListCredentialsResponse:
    """Return all credential records visible to the authenticated user.

    Includes the caller's own credentials plus any credentials shared to
    them through :class:`ResourceAccessPolicyBase`. Shared entries have
    their secret ``data`` payload masked — only the discriminator and
    display name survive in the response — while runtime resolution
    (e.g. the chat model service) still sees the full payload.

    Args:
        user_id (`str`):
            Injected authenticated user ID.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ListCredentialsResponse`:
            All visible credentials paired with editability and
            (for shared entries) redacted data.
    """
    entries = await access.list_resource(user_id, ResourceKind.CREDENTIAL)
    return ListCredentialsResponse(
        credentials=entries,
        total=len(entries),
    )


@credential_router.post(
    "/",
    response_model=CreateCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new credential",
)
async def create_credential(
    body: CreateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> CreateCredentialResponse:
    """Store a new credential.

    Args:
        body (`CreateCredentialRequest`): Credential payload to store.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.

    Returns:
        `CreateCredentialResponse`: The server-assigned credential identifier.
    """
    credential_id = await storage.upsert_credential(
        user_id,
        CredentialFactory.from_dict(body.data),
    )
    return CreateCredentialResponse(credential_id=credential_id)


@credential_router.get(
    "/{credential_id}/models",
    response_model=CredentialModelCatalogResponse,
    summary="List the model catalog for one credential",
)
async def list_credential_models(
    credential_id: str,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialModelCatalogResponse:
    """Return built-in, discovered, and manually configured models."""
    record = await access.resolve_credential(user_id, credential_id)
    credential = CredentialFactory.from_dict(record.data)
    return _model_catalog_response(credential)


@credential_router.post(
    "/{credential_id}/models/test",
    response_model=CredentialModelTestResult,
    summary="Test one model with a minimal real completion",
)
async def test_model(
    credential_id: str,
    body: TestCredentialModelRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialModelTestResult:
    """Test credential, endpoint, and model access without creating a session."""
    record = await access.resolve_credential(user_id, credential_id)
    credential = CredentialFactory.from_dict(record.data)
    if body.model_type == "embedding":
        candidate = next(
            (
                model
                for model in build_credential_embedding_model_catalog(
                    credential,
                )
                if model.name == body.model and model.enabled
            ),
            None,
        )
    else:
        candidate = next(
            (
                model
                for model in build_credential_model_catalog(credential)
                if model.name == body.model and model.enabled
            ),
            None,
        )
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Model '{body.model}' is not enabled for this credential."
            ),
        )
    if body.model_type == "embedding":
        return await test_credential_embedding_model(
            credential,
            body.model,
            candidate.dimensions,
        )
    return await test_credential_model(credential, body.model)


@credential_router.post(
    "/{credential_id}/models/embedding/probe",
    response_model=CredentialModelTestResult,
    summary="Probe an OpenAI-compatible embedding model before saving it",
)
async def probe_embedding_model(
    credential_id: str,
    body: TestCredentialModelRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialModelTestResult:
    """Detect an embedding model's dimensions with one real request."""
    _, record = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    credential = CredentialFactory.from_dict(record.data)
    if credential.get_embedding_model_class() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This credential does not support embedding models.",
        )
    return await test_credential_embedding_model(
        credential,
        body.model,
    )


@credential_router.post(
    "/{credential_id}/models/discover",
    response_model=CredentialModelCatalogResponse,
    summary="Discover models from an OpenAI-compatible service",
)
async def discover_models(
    credential_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialModelCatalogResponse:
    """Refresh the provider-discovered snapshot without touching manual data."""
    owner_id, record = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    credential = CredentialFactory.from_dict(record.data)
    attempted_at = datetime.now(timezone.utc)

    try:
        discovered = await discover_credential_models(credential)
    except ModelDiscoveryError as exc:
        credential.model_catalog.last_discovery_at = attempted_at
        credential.model_catalog.last_discovery_error = str(exc)
        await storage.upsert_credential(owner_id, credential)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    credential.model_catalog.discovered_models = discovered
    credential.model_catalog.last_discovery_at = attempted_at
    credential.model_catalog.last_discovery_error = None
    await storage.upsert_credential(owner_id, credential)
    return _model_catalog_response(credential)


@credential_router.patch(
    "/{credential_id}/models",
    response_model=CredentialModelCatalogResponse,
    summary="Update the manual and hidden models for one credential",
)
async def update_credential_models(
    credential_id: str,
    body: UpdateCredentialModelCatalogRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialModelCatalogResponse:
    """Replace manual entries and model visibility for one credential."""
    owner_id, record = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    credential = CredentialFactory.from_dict(record.data)

    # One effective definition per exact provider model identifier. The last
    # item wins, matching normal form-edit semantics.
    manual_by_name = {
        definition.name: definition
        for definition in body.manual_models
    }
    old_catalog = credential.model_catalog
    credential.model_catalog = CredentialModelCatalog(
        discovered_models=old_catalog.discovered_models,
        manual_models=list(manual_by_name.values()),
        hidden_model_ids=body.hidden_model_ids,
        hidden_embedding_model_ids=body.hidden_embedding_model_ids,
        last_discovery_at=old_catalog.last_discovery_at,
        last_discovery_error=old_catalog.last_discovery_error,
    )
    await storage.upsert_credential(owner_id, credential)
    return _model_catalog_response(credential)


@credential_router.patch(
    "/{credential_id}",
    response_model=CredentialView,
    summary="Update a credential",
)
async def update_credential(
    credential_id: str,
    body: UpdateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialView:
    """Replace the payload of an existing credential.

    Args:
        credential_id (`str`): The credential to update.
        body (`UpdateCredentialRequest`): New credential payload.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor updates the credential.

    Returns:
        `CredentialView`: The updated credential record.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, existing = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )

    credential = CredentialFactory.from_dict(body.data)
    credential.id = credential_id
    if "model_catalog" not in body.data:
        previous = CredentialFactory.from_dict(existing.data)
        credential.model_catalog = previous.model_catalog
    await storage.upsert_credential(owner_id, credential)
    # ``resolve_for_edit`` proved the record existed under ``owner_id``
    # and the upsert above just wrote back to the same key, so the read
    # is a value refresh, not an existence check. If it still comes back
    # empty (e.g. a concurrent delete), surface an explicit server error
    # rather than relying on ``assert`` (which ``-O`` strips).
    updated = await storage.get_credential(owner_id, credential_id)
    if updated is None:
        raise RuntimeError(
            f"Credential {credential_id!r} for owner {owner_id!r} "
            "disappeared immediately after a successful upsert.",
        )
    # Only reachable via ``resolve_for_edit``, so the caller has edit
    # permission by construction.
    return CredentialView.model_validate(
        {**updated.model_dump(), "editable": True},
    )


@credential_router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential",
)
async def delete_credential(
    credential_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> None:
    """Permanently delete a credential.

    Args:
        credential_id (`str`): The credential to delete.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor deletes the credential.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    await storage.delete_credential(owner_id, credential_id)
