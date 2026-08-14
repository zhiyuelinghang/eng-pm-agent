"""Dreamer Tasks 注册表"""

DREAMER_TASK_REGISTRY: dict[str, type] = {}

try:
    from .decay_v2 import DecayV2Task
    DREAMER_TASK_REGISTRY["decay"] = DecayV2Task
except ImportError:
    pass

try:
    from .verify import VerifyTask
    DREAMER_TASK_REGISTRY["verify"] = VerifyTask
except ImportError:
    pass

try:
    from .curate import CurateTask
    DREAMER_TASK_REGISTRY["curate"] = CurateTask
except ImportError:
    pass

try:
    from .classify import ClassifyTask
    DREAMER_TASK_REGISTRY["classify"] = ClassifyTask
except ImportError:
    pass
