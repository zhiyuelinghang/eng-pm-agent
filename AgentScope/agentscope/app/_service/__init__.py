# -*- coding: utf-8 -*-
"""Service layer for the AgentScope app."""
from ._access import (
    AgentView,
    CredentialView,
    KnowledgeBaseView,
    ResourceAccessService,
)
from ._chat import ChatService
from ._credential_models import (
    CredentialModelEntry,
    CredentialModelTestResult,
    ModelDiscoveryError,
    build_credential_model_catalog,
    discover_credential_models,
    supports_model_discovery,
    test_credential_model,
)
from ._embedding import get_embedding_model
from ._index_sweeper import IndexSweeper
from ._index_task_consumer import IndexTaskConsumer
from ._index_worker import IndexWorker
from ._knowledge_base import KnowledgeBaseService
from ._model import get_model
from ._tts_model import get_tts_model
from ._session import SessionService, SessionStatus
from ._session_projection import SessionProjection
from ._projectors import SubagentHitlProjector
from ._toolkit import get_toolkit

__all__ = [
    "AgentView",
    "ChatService",
    "CredentialModelEntry",
    "CredentialModelTestResult",
    "CredentialView",
    "IndexSweeper",
    "IndexTaskConsumer",
    "IndexWorker",
    "KnowledgeBaseService",
    "KnowledgeBaseView",
    "ResourceAccessService",
    "SessionService",
    "SessionStatus",
    "SessionProjection",
    "SubagentHitlProjector",
    "ModelDiscoveryError",
    "build_credential_model_catalog",
    "discover_credential_models",
    "get_embedding_model",
    "get_model",
    "get_tts_model",
    "get_toolkit",
    "supports_model_discovery",
    "test_credential_model",
]
