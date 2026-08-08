from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """Canonical persisted workflow states.

    Values intentionally retain the v1 lowercase representation so existing
    session files remain readable; public envelopes expose uppercase names.
    """

    CREATED = "created"
    PROFILED = "profiled"
    VARIABLES_CONFIRMED = "variables_confirmed"
    PREPROCESSING_REVIEWED = "preprocessing_reviewed"
    PREPROCESSED = "preprocessed"
    MODELS_RECOMMENDED = "models_recommended"
    MODELS_SELECTED = "models_selected"
    TRAINING_CONFIGURED = "training_configured"
    PIPELINE_PROPOSED = "pipeline_proposed"
    TRAINED = "trained"
    EVALUATED = "evaluated"
    EXPORTED = "exported"


LEGACY_STAGES = tuple(state.value for state in WorkflowState)


_FORWARD_TRANSITIONS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.CREATED: {WorkflowState.PROFILED},
    WorkflowState.PROFILED: {WorkflowState.VARIABLES_CONFIRMED},
    WorkflowState.VARIABLES_CONFIRMED: {
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.PIPELINE_PROPOSED,
    },
    WorkflowState.PREPROCESSING_REVIEWED: {WorkflowState.PREPROCESSED},
    WorkflowState.PREPROCESSED: {WorkflowState.MODELS_RECOMMENDED},
    WorkflowState.MODELS_RECOMMENDED: {
        WorkflowState.MODELS_SELECTED,
        WorkflowState.TRAINING_CONFIGURED,
    },
    WorkflowState.MODELS_SELECTED: {WorkflowState.TRAINING_CONFIGURED},
    WorkflowState.TRAINING_CONFIGURED: {WorkflowState.TRAINED},
    WorkflowState.PIPELINE_PROPOSED: {WorkflowState.TRAINED},
    WorkflowState.TRAINED: {WorkflowState.EVALUATED},
    WorkflowState.EVALUATED: {WorkflowState.EXPORTED},
    WorkflowState.EXPORTED: set(),
}

# All user-visible rewinds are declared here as real state transitions.  The
# storage layer and rewind tool both consult this single source of truth.
_REWIND_TARGETS: dict[WorkflowState, set[WorkflowState]] = {
    WorkflowState.VARIABLES_CONFIRMED: {WorkflowState.PROFILED},
    WorkflowState.PREPROCESSING_REVIEWED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
    },
    WorkflowState.PREPROCESSED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
    },
    WorkflowState.MODELS_RECOMMENDED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
    },
    WorkflowState.MODELS_SELECTED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.MODELS_RECOMMENDED,
    },
    WorkflowState.TRAINING_CONFIGURED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.MODELS_RECOMMENDED,
        WorkflowState.MODELS_SELECTED,
    },
    WorkflowState.PIPELINE_PROPOSED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
    },
    WorkflowState.TRAINED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.MODELS_RECOMMENDED,
        WorkflowState.MODELS_SELECTED,
        WorkflowState.TRAINING_CONFIGURED,
        WorkflowState.PIPELINE_PROPOSED,
    },
    WorkflowState.EVALUATED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.MODELS_RECOMMENDED,
        WorkflowState.MODELS_SELECTED,
        WorkflowState.TRAINING_CONFIGURED,
        WorkflowState.PIPELINE_PROPOSED,
        WorkflowState.TRAINED,
    },
    WorkflowState.EXPORTED: {
        WorkflowState.PROFILED,
        WorkflowState.VARIABLES_CONFIRMED,
        WorkflowState.PREPROCESSING_REVIEWED,
        WorkflowState.MODELS_RECOMMENDED,
        WorkflowState.MODELS_SELECTED,
        WorkflowState.TRAINING_CONFIGURED,
        WorkflowState.PIPELINE_PROPOSED,
        WorkflowState.TRAINED,
    },
}

ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    state: frozenset({state} | targets | _REWIND_TARGETS.get(state, set()))
    for state, targets in _FORWARD_TRANSITIONS.items()
}


def coerce_state(value: str | WorkflowState) -> WorkflowState:
    if isinstance(value, WorkflowState):
        return value
    return WorkflowState(value.lower())


def public_state_name(stage: str | WorkflowState | None) -> str | None:
    if stage is None:
        return None
    return coerce_state(stage).name


def transition_allowed(
    current: str | WorkflowState,
    target: str | WorkflowState,
) -> bool:
    try:
        current_state = coerce_state(current)
        target_state = coerce_state(target)
    except ValueError:
        return False
    return target_state in ALLOWED_TRANSITIONS.get(current_state, frozenset())


def is_rewind_transition(
    current: str | WorkflowState,
    target: str | WorkflowState,
) -> bool:
    current_state = coerce_state(current)
    target_state = coerce_state(target)
    return target_state in _REWIND_TARGETS.get(current_state, set())
