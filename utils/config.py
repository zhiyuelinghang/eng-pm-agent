"""
Dobby Memory Demo — Unified Configuration

All settings read from environment variables with sensible defaults.
Import this module in each demo step to get consistent configuration.
"""

import os
from pathlib import Path

from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    """Read env var with .env file fallback."""
    return os.getenv(key, default)


def _first_env(*keys: str, default: str = "") -> str:
    """Return the first non-empty environment value.

    The upstream module uses short names such as ``DATABASE_URL`` and
    ``DEEPSEEK_API_KEY``.  The engineering platform already has stable
    ``MEMORY_*``/``AI_*`` names, so the adapter accepts both without changing
    the upstream call sites.
    """
    for key in keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default


MEMORY_MODEL_CACHE = Path(
    _first_env(
        "MEMORY_MODEL_CACHE",
        default=str(PROJECT_ROOT / "data" / "huggingface"),
    ),
)
os.environ.setdefault("HF_HOME", str(MEMORY_MODEL_CACHE))
os.environ.setdefault(
    "SENTENCE_TRANSFORMERS_HOME",
    str(MEMORY_MODEL_CACHE / "sentence-transformers"),
)
MEM0_RUNTIME_DIR = Path(
    _first_env(
        "MEM0_DIR",
        default=str(PROJECT_ROOT / "data" / "mem0"),
    ),
)
os.environ.setdefault("MEM0_DIR", str(MEM0_RUNTIME_DIR))
os.environ.setdefault("MEM0_TELEMETRY", "false")


def _postgres_url(raw: str, schema: str) -> str:
    """Normalize SQLAlchemy-style URLs for psycopg and pin search_path."""
    url = make_url(raw)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Dobby 记忆系统必须连接 PostgreSQL")
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema},public"
    return url.set(
        drivername="postgresql",
        query=query,
    ).render_as_string(hide_password=False)


# ---- PostgreSQL ----
DATABASE_SCHEMA = _first_env(
    "MEMORY_DATABASE_SCHEMA",
    default="memory",
)
DATABASE_URL = _postgres_url(
    _first_env(
        "MEMORY_DATABASE_URL",
        "DATABASE_URL",
        default="postgresql://dobby:dobby@localhost:5432/dobby_demo",
    ),
    DATABASE_SCHEMA,
)
MEMORY_TENANT_ID = _first_env(
    "MEMORY_TENANT_ID",
    "AGENTSCOPE_GLOBAL_CONFIG_ID",
    default="projectcopilot",
)
MEM0_COLLECTION = _first_env(
    "MEMORY_COLLECTION_NAME",
    "MEM0_COLLECTION",
    default="dobby_memories",
)

# ---- LLM: DeepSeek V4 ----
DEEPSEEK_API_KEY = _first_env("DEEPSEEK_API_KEY", "AI_API_KEY")
DEEPSEEK_MODEL = _first_env(
    "DEEPSEEK_MODEL",
    "AI_MODEL",
    default="deepseek-chat",
)
DEEPSEEK_CONTEXT_SIZE = int(_env("DEEPSEEK_CONTEXT_SIZE", "131072"))
DEEPSEEK_BASE_URL = _first_env(
    "DEEPSEEK_BASE_URL",
    "AI_BASE_URL",
    default="https://api.deepseek.com/v1",
)

# ---- LLM: DashScope (fallback) ----
DASHSCOPE_API_KEY = _first_env(
    "DASHSCOPE_API_KEY",
    "MEMORY_EMBEDDING_API_KEY",
)

# ---- Embedding ----
EMBEDDING_PROVIDER = _first_env(
    "EMBEDDING_PROVIDER",
    "MEMORY_EMBEDDING_PROVIDER",
    default="local",
)  # local | dashscope | openai
EMBEDDING_MODEL = _first_env(
    "EMBEDDING_MODEL",
    "MEMORY_EMBEDDING_MODEL",
    default="BAAI/bge-large-zh-v1.5",
)
EMBEDDING_DIMS = int(_first_env("MEMORY_EMBEDDING_DIMS", default="1024"))
EMBEDDING_API_KEY = _first_env(
    "MEMORY_EMBEDDING_API_KEY",
    "DASHSCOPE_API_KEY",
)
EMBEDDING_BASE_URL = _first_env(
    "MEMORY_EMBEDDING_BASE_URL",
    default="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# ---- Mem0 ----
# ⚠️  user_id / agent_id MUST NOT contain ':' — mem0ai v2.0.12 SQLite history
#     query breaks on colons, causing LLM extraction to silently return empty.
#     Use underscores or hyphens instead.
MEM0_USER_ID = _env("MEM0_USER_ID", "project_demo")
MEM0_AGENT_ID = _env("MEM0_AGENT_ID", "role_safety")

# ---- WeKnora (Step 2) ----
WEKNORA_BASE_URL = _env("WEKNORA_BASE_URL", "http://localhost:8080/api/v1")
WEKNORA_API_KEY = _env("WEKNORA_API_KEY", "")
WEKNORA_KB_NAME = _env("WEKNORA_KB_NAME", "dobby_engineering_safety")
WEKNORA_ENABLED = _env(
    "WEKNORA_ENABLED",
    "true" if WEKNORA_API_KEY else "false",
).lower() == "true"
WEKNORA_TIMEOUT_CONNECT = float(_env("WEKNORA_TIMEOUT_CONNECT", "5.0"))
WEKNORA_TIMEOUT_READ = float(_env("WEKNORA_TIMEOUT_READ", "30.0"))

# ---- mem0 infer control ----
# When True, mem0 add() calls the LLM to extract structured facts from memory text.
# This improves search recall but adds ~5-15s latency per add() call.
# When False, raw text is stored as-is (fast, lower recall).
MEM0_INFER_ENABLED = _first_env(
    "MEM0_INFER_ENABLED",
    "MEMORY_INFER_ENABLED",
    default="false",
).lower() == "true"
# When True AND MEM0_INFER_ENABLED=True, enrichment runs as a background task
# instead of blocking the chat response. The memory is immediately searchable
# (raw text), and enriched with facts asynchronously.
MEM0_INFER_ASYNC = _env("MEM0_INFER_ASYNC", "true").lower() == "true"

# ---- RRF Fusion (Step 2) ----
RRF_K = 60
FUSION_MEM0_WEIGHT = 0.3
FUSION_KB_WEIGHT = 0.7

# ---- 4源 MMR 融合 ----
# MMR lambda: 0.7 = 偏向相关性, 0.3 = 偏向多样性
FUSION_MMR_LAMBDA = 0.7
# 4源默认权重（归一化前）
FUSION_WEIGHT_MEM0 = 0.20
FUSION_WEIGHT_KB = 0.35
FUSION_WEIGHT_TIMELINE = 0.15
FUSION_WEIGHT_EXPERIENCE = 0.30
FUSION_WEIGHT_GRAPHRAG = 0.25

# ---- LangGraph PostgresSaver (Step 3) ----
LANGGRAPH_CHECKPOINT_DB = _postgres_url(
    _first_env(
        "LANGGRAPH_CHECKPOINT_DB",
        "MEMORY_DATABASE_URL",
        "DATABASE_URL",
        default="postgresql://dobby:dobby@localhost:5432/dobby_demo",
    ),
    DATABASE_SCHEMA,
)
MAX_TOKEN_BUDGET = int(
    _env("MEMORY_MAX_TOKEN_BUDGET", str(DEEPSEEK_CONTEXT_SIZE)),
)
COMPRESSION_TRIGGER_TOKENS = int(
    _env("MEMORY_COMPRESSION_TRIGGER_TOKENS", str(int(MAX_TOKEN_BUDGET * 0.8))),
)
COMPRESSION_KEEP_MESSAGES = 20       # retain last N rounds after compress
COMPRESSION_MODEL = DEEPSEEK_MODEL   # reuse DeepSeek for compression

# ---- Model Router (分角色LLM配置) ----
# 快速模型 — 用于路由、压缩、提取、反思、合并、分舱等后台任务
LLM_FLASH_MODEL = _env("LLM_FLASH_MODEL", DEEPSEEK_MODEL)
# 强力模型 — 用于用户直接看到的回答和最终合成
LLM_PRO_MODEL = _env("LLM_PRO_MODEL", DEEPSEEK_MODEL)

TOKEN_ESTIMATION_CHARS_PER_TOKEN = 2.5  # rough CJK estimation

# ---- L2 Compression Alert ----
COMPRESSION_L2_ALERT_THRESHOLD = int(_env("COMPRESSION_L2_ALERT_THRESHOLD", "10"))
# 进程级累计 reset 次数超过此值触发 WARNING 告警

# ---- Context Window ----
CONTEXT_TRIGGER_RATIO = 0.8
CONTEXT_RESERVE_RATIO = 0.1
TOOL_RESULT_LIMIT = 50000

# ---- Layered Token Budget (§3.3) ----
TOKEN_BUDGET_SYSTEM_PROMPT = 5_000         # ① System Prompt 上限
TOKEN_BUDGET_SUMMARY = 15_000              # ② Summary 上限
TOKEN_BUDGET_LTM_KB_TIMELINE = 30_000      # ③④ LTM+KB+Timeline 合计上限
TOKEN_BUDGET_RUNTIME = 2_000               # ⑤ Runtime Context 上限
TOKEN_BUDGET_RECENT_HISTORY = 10_000       # ⑥ Recent History 上限
TOKEN_BUDGET_OUTPUT_RESERVE = 4_000        # Output Reserve

# ---- Memory ----
MEMORY_TOP_K = int(_first_env("MEMORY_RECALL_TOP_K", default="5"))
MEMORY_THRESHOLD = float(
    _first_env("MEMORY_RECALL_THRESHOLD", default="0.3"),
)
RECENCY_WEIGHT = 0.3
IMPORTANCE_WEIGHT = 0.2
RELEVANCE_WEIGHT = 0.5
RECENCY_HALF_LIFE_DAYS = 30.0

# ---- Decay (Step 4) ----
DECAY_DELETE_THRESHOLD = 0.1       # importance 低于此值触发硬删除
DECAY_MAX_AGE_DAYS = 90            # age 超过此天数才删除
DECAY_ACCESS_STALE_DAYS = 30       # 未访问超过此天数扣 0.1

# ---- P0-1 Ebbinghaus Forgetting Curve ----
# 分类别衰减率（λ值越高衰减越快）
# 来源: YourMemory src/services/decay.py:14-22
#   reflection=0.10(~38d) strategy-like → risk=0.35(~11d) fastest
DECAY_RATE_REFLECTION = 0.10
DECAY_RATE_DECISION    = 0.12
DECAY_RATE_PREFERENCE  = 0.12
DECAY_RATE_FACT        = 0.16
DECAY_RATE_PROCEDURE   = 0.20
DECAY_RATE_ENVIRONMENT = 0.20
DECAY_RATE_RISK        = 0.35
DECAY_RATE_DEFAULT     = 0.16

# 回忆频率加成系数 (每次检索成功增加N%强度)
RECALL_BOOST_FACTOR = 0.2          # 来源: YourMemory src/services/decay.py:39
# 重要性对衰减速度的调节系数
IMPORTANCE_DECAY_MODULATOR = 0.8   # 来源: YourMemory src/services/decay.py:38
# 剪枝阈值 (强度低于此值硬删除)
MEMORY_PRUNE_THRESHOLD = 0.05      # 来源: YourMemory src/jobs/decay_job.py:24
# 检索强化阈值 (相似度超过此值才计入 recall_count)
MEMORY_REINFORCE_THRESHOLD = 0.75  # 来源: YourMemory src/services/retrieve.py:19

# ---- P0-2 Async Compression & Cache Stability ----
# 历史学家触发阈值（原始未压缩消息超过此token数触发后台压缩）
HISTORIAN_TRIGGER_TOKENS = 60_000
# 最多保留的分舱数
COMPARTMENT_COUNT_LIMIT = 50
# 压缩模式: "full"=全量摘要 | "incremental"=递增分舱
COMPRESSION_MODE = "incremental"
# 紧急压缩阈值(token压力≥95%触发快速降级)
EMERGENCY_COMPRESSION_THRESHOLD = 0.95
# 后台压缩开关
COMPRESSION_BACKGROUND = True

# ---- Reflection ----
REFLECTION_IMPORTANCE_THRESHOLD = 150  # Generative Agents paper
REFLECTION_MAX_MEMORIES = 50
REFLECTION_COOLDOWN_HOURS = 24     # 反思冷却时间

# ---- Experience (Codex Phase 1) ----
EXPERIENCE_SIGNAL_THRESHOLD = 0.3  # 最低信号门槛
EXPERIENCE_MIN_CONTENT_LENGTH = 30  # 内容最短长度

# ---- Experience Phase 2 (Step 6) ----
EXPERIENCE_CONSOLIDATION_COOLDOWN_HOURS = 24   # 合并冷却时间（小时）
EXPERIENCE_COARSE_FILTER_THRESHOLD = 0.75      # HNSW 粗筛最低余弦相似度
EXPERIENCE_MERGE_CONFIRM_THRESHOLD = 0.85      # 合并确认阈值（语义级别）
EXPERIENCE_BATCH_DEDUP_THRESHOLD = 0.98        # 批内精确去重阈值（近乎相同）
EXPERIENCE_WIKI_SYNC_ENABLED = True            # 是否同步到 WeKnora wiki
EXPERIENCE_MAX_BODY_LENGTH = 50000             # body_md 最大字符数
EXPERIENCE_MAX_EXTRACTS_PER_RUN = 50           # 单次合并最多处理 extracts 数

# ---- Experience Phase 2: Event-driven consolidation ----
EXPERIENCE_EVENT_DRIVEN_ENABLED = True   # 全局开关：启用事件驱动合并
EXPERIENCE_EVENT_MIN_CLUSTER_SIZE = 5    # 同bucket未合并extract ≥ 此值触发
EXPERIENCE_EVENT_COOLDOWN_MINUTES = 30   # 同bucket冷却时间（分钟）

# ---- Dreamer 夜间维护 (Step 9) ----
DREAMER_ENABLED = _env("DREAMER_ENABLED", "true").lower() == "true"
DREAMER_DEFAULT_MODEL = _env("DREAMER_DEFAULT_MODEL", DEEPSEEK_MODEL)
DREAMER_DEFAULT_TIMEOUT = int(_env("DREAMER_DEFAULT_TIMEOUT", "1200"))
DREAMER_CIRCUIT_BREAKER_MAX_FAILURES = 3
DREAMER_LEASE_TIMEOUT = int(_env("DREAMER_LEASE_TIMEOUT", "3600"))

# verify task
DREAMER_VERIFY_CRON = _env("DREAMER_VERIFY_CRON", "0 3 * * *")
DREAMER_VERIFY_BATCH_SIZE = 50
DREAMER_VERIFY_BROAD_INTERVAL_DAYS = 7

# curate task
DREAMER_CURATE_CRON = _env("DREAMER_CURATE_CRON", "0 4 * * 0")
DREAMER_CURATE_HIGH_SIM = 0.92
DREAMER_CURATE_COARSE_FILTER = 0.75
DREAMER_CURATE_ARCHIVE_IMPORTANCE = 0.3

# classify task
DREAMER_CLASSIFY_CRON = _env("DREAMER_CLASSIFY_CRON", "0 5 * * *")
DREAMER_CLASSIFY_BATCH_SIZE = 100

# decay task
DREAMER_DECAY_CRON = _env("DREAMER_DECAY_CRON", "0 2 * * *")

# ---- GraphRAG (LightRAG embedded) ----
ROOT_DIR = Path(__file__).parent.parent
LIGHTRAG_ENABLED = _env("LIGHTRAG_ENABLED", "false").lower() == "true"
LIGHTRAG_WORKING_DIR = _env(
    "LIGHTRAG_WORKING_DIR",
    str(ROOT_DIR / "data" / "lightrag_cache"),
)
LIGHTRAG_CHUNK_SIZE = 1200
LIGHTRAG_CHUNK_OVERLAP = 100
LIGHTRAG_ENTITY_MAX_GLEANING = 1
LIGHTRAG_ENTITY_EXTRACT_USE_JSON = False
LIGHTRAG_QUERY_MODE = "mix"
LIGHTRAG_QUERY_TOP_K = 10
LIGHTRAG_ENTITY_MAX_TOKENS = 1500
LIGHTRAG_RELATION_MAX_TOKENS = 1500

# ---- Graphiti Phase 3-A (Step 7) ----
NEO4J_URI = _env("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = _env("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = _env("NEO4J_PASSWORD", "password")
GRAPHITI_ENABLED = _env("GRAPHITI_ENABLED", "false").lower() == "true"
GRAPHITI_MAX_EVENTS_PER_RUN = 20             # 单次最多处理事件数
GRAPHITI_EVENT_TIMEOUT_SECONDS = 120         # 单条 add_episode 超时
GRAPHITI_SOURCE_DESCRIPTION = "dobby_agent"  # Graphiti source_description 字段
GRAPHITI_SEARCH_LIMIT = 5                 # 最大搜索结果数
GRAPHITI_SEARCH_TIMEOUT = 10.0            # Neo4j 搜索超时（秒）

# ---- LLM Autonomous Context Scheduling ----
AUTO_HINT_THRESHOLD = float(_env("AUTO_HINT_THRESHOLD", "0.65"))
AUTO_HINT_TIMEOUT = float(_env("AUTO_HINT_TIMEOUT", "0.5"))
AUTO_HINT_MAX_CHARS = int(_env("AUTO_HINT_MAX_CHARS", "120"))
MAX_CONSECUTIVE_MINIMAL = int(_env("MAX_CONSECUTIVE_MINIMAL", "5"))
COMPRESSION_MAX_CONSECUTIVE = int(_env("COMPRESSION_MAX_CONSECUTIVE", "3"))
COMPRESSION_QUALITY_THRESHOLD = float(_env("COMPRESSION_QUALITY_THRESHOLD", "0.3"))
COMPRESSION_MIN_ROUNDS_BETWEEN = int(_env("COMPRESSION_MIN_ROUNDS_BETWEEN", "5"))

# ---- Multi-Agent (Step 5) ----
ROLE_DEFAULT = "dobby_core"          # 默认路由目标
ROLE_AVAILABLE = ["dobby_core", "safety_director", "pm",
                  "compliance_advisor", "inspector", "construction"]
DELEGATE_TIMEOUT_SECONDS = 120       # 子Agent超时
DELEGATE_MAX_ROUNDS = 10             # 子Agent最大推理轮次
# ---- Embed Server ----
EMBED_SERVER_URL = _env("EMBED_SERVER_URL", "http://localhost:9999/v1")
EMBED_SERVER_ENABLED = _env("EMBED_SERVER_ENABLED", "false").lower() == "true"

# ---- LLMLingua-2 Compression (§5.1) ----
COMPRESSION_ENGINE = "llm"           # "llm" | "llmlingua2"
LLMLINGUA2_RATIO = 0.5              # 目标压缩比（保留50% token）
LLMLINGUA2_USE_GPU = False          # 是否用 GPU 加速
LLMLINGUA2_POST_SUMMARIZE = True    # 压缩后是否 LLM 二次摘要

# ── Skill Self-Evolution (§10) ──
SKILL_COMPILE_THRESHOLD = 3                # 触发编译的最低未编译经验数
SKILL_COMPILE_COOLDOWN_HOURS = 6           # 编译冷却时间（小时）
SKILL_MIN_REPEAT_COUNT = 2                 # 最低重复确认次数（写入时 bump）
SKILL_PROMOTION_REF_COUNT = 3              # active 升级所需引用次数
SKILL_DEMOTION_DAYS = 30                   # 降级为 warm 的天数
SKILL_ARCHIVE_DAYS = 90                    # 归档为 cold 的天数
TOKEN_BUDGET_SKILL_INJECTION = 3000        # ①b Skill Injection 层 token 预算
SKILL_REVIEW_REQUIRED_BUCKETS = ["decision"]  # 需要人审的 bucket
SKILL_REVIEW_IMPORTANCE_THRESHOLD = 0.8    # 需要人审的最低 importance


def validate() -> list[str]:
    """Check configuration and return list of issues."""
    issues = []

    if not DEEPSEEK_API_KEY and not DASHSCOPE_API_KEY:
        issues.append(
            "No LLM API key configured. Set DEEPSEEK_API_KEY or DASHSCOPE_API_KEY."
        )

    if EMBEDDING_PROVIDER == "local":
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            issues.append(
                "Local embedding requires: pip install sentence-transformers"
            )
    elif EMBEDDING_PROVIDER in {"dashscope", "openai"} and not EMBEDDING_API_KEY:
        issues.append(
            "API embedding requires MEMORY_EMBEDDING_API_KEY or "
            "DASHSCOPE_API_KEY."
        )

    return issues


def summary() -> str:
    """Print configuration summary."""
    return f"""
Configuration:
  LLM:           DeepSeek {DEEPSEEK_MODEL} ({DEEPSEEK_CONTEXT_SIZE} ctx)
  Embedding:     {EMBEDDING_PROVIDER}:{EMBEDDING_MODEL} ({EMBEDDING_DIMS}d)
  Database:      PostgreSQL/{DATABASE_SCHEMA}
  Mem0 Scope:    user_id={MEM0_USER_ID}, agent_id={MEM0_AGENT_ID}
  WeKnora:       {WEKNORA_BASE_URL} (KB: {WEKNORA_KB_NAME})
  Context:       trigger={CONTEXT_TRIGGER_RATIO}, reserve={CONTEXT_RESERVE_RATIO}
  Memory:        top_k={MEMORY_TOP_K}, threshold={MEMORY_THRESHOLD}
  RRF:           KB_w={FUSION_KB_WEIGHT}, LTM_w={FUSION_MEM0_WEIGHT}, k={RRF_K}
  PostgresSaver: PostgreSQL/{DATABASE_SCHEMA} (compress@{COMPRESSION_TRIGGER_TOKENS}tk)
  Token Budget: system={TOKEN_BUDGET_SYSTEM_PROMPT}, summary={TOKEN_BUDGET_SUMMARY}, LTM+KB={TOKEN_BUDGET_LTM_KB_TIMELINE}, history={TOKEN_BUDGET_RECENT_HISTORY}
  Embed Server: {EMBED_SERVER_URL}
  Reflection:    threshold={REFLECTION_IMPORTANCE_THRESHOLD}
  Event Merge:  cluster_size={EXPERIENCE_EVENT_MIN_CLUSTER_SIZE}, cooldown={EXPERIENCE_EVENT_COOLDOWN_MINUTES}m
  Context Scheduling: auto-hint_threshold={AUTO_HINT_THRESHOLD}, consecutive_minimal={MAX_CONSECUTIVE_MINIMAL}
  Compression Guard: max_consecutive={COMPRESSION_MAX_CONSECUTIVE}, quality_threshold={COMPRESSION_QUALITY_THRESHOLD}
""".strip()
