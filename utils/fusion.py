"""
5-Source Adaptive RRF + MMR Fusion + Context Assembler.

Fuses Mem0 memory, WeKnora knowledge base, Graphiti timeline,
Experience Store, and GraphRAG search results into a diversity-aware
ranked list, then assembles the multi-layer context for LLM injection.

Key design decisions (from 长期短期记忆机制核心设计方案.md §5.3):
- Default 5-source weights: mem0=0.20, kb=0.35, timeline=0.15, experience=0.30, graphrag=0.25
- RRF k = 60 (standard constant)
- MMR lambda = 0.7 (bias toward relevance)
- MMR top_k = 6 (final candidates after dedup)
- <system-reminder> trusted channel for injection (Claude Code paradigm)
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from . import config as _cfg
from .skill_registry import SkillRegistry


@dataclass
class SearchResult:
    """Unified search result from any source."""
    source: str           # "mem0" | "weknora"
    content: str
    score: float
    metadata: dict = field(default_factory=dict)

    def summary(self) -> str:
        """One-line summary for logging."""
        snippet = self.content[:80].replace("\n", " ")
        return f"[{self.source} s={self.score:.3f}] {snippet}..."


# ============================================================
# 5源结构化辅助函数（用于融合，非工具输出）
# ============================================================


async def _search_experiences_structured(
    query: str,
    project_id: str,
    limit: int = 5,
) -> list[dict]:
    """查询 experiences 表并返回结构化 dict 列表。

    不同于 _execute_search_experiences()（返回格式化字符串给工具输出），
    此函数返回原始结构化数据供 MemoryFusion.fuse() 排序。

    Args:
        query: 搜索查询（当前版本使用 project_id 全量拉取 + RRF 排序）
        project_id: 项目标识
        limit: 返回上限

    Returns:
        [{"content": str, "score": float, "source_type": str, "experience_id": int, "version": int}, ...]
    """
    try:
        conn = psycopg.Connection.connect(
            _cfg.DATABASE_URL, autocommit=True, prepare_threshold=0,
        )
        with conn:
            cur = conn.execute(
                """SELECT id, body_md, bucket, version, importance
                   FROM experiences WHERE project_id = %s
                   ORDER BY importance DESC, updated_at DESC
                   LIMIT %s""",
                (project_id, limit * 2),  # 多取一些供RRF排序
            )
            rows = cur.fetchall()

        return [
            {
                "content": (r[1] or "")[:500],
                "score": float(r[4]) if r[4] is not None else 0.5,
                "source_type": r[2] or "procedure",
                "experience_id": r[0],
                "version": r[3],
            }
            for r in rows
        ]
    except Exception:
        return []


def _graphiti_to_items(data: dict) -> list[dict]:
    """将 graphiti_search() 返回的 dict 转换为可融合的条目列表。

    graphiti_search() 返回：
        {"timeline": [{type, body, time}, ...],
         "active_risks": [str, ...],
         "source": "pg_only" | "pg+neo4j",
         "neo4j_available": bool}

    Args:
        data: graphiti_search() 的返回 dict

    Returns:
        [{"content": str, "source_type": "timeline"|"active_risk", ...}, ...]
    """
    tag_map = {
        "risk_created": "\U0001f534 风险出现",
        "risk_resolved": "\U0001f7e2 风险关闭",
        "task_completed": "\u2705 任务完成",
        "state_changed": "\U0001f535 状态变更",
    }
    items: list[dict] = []

    for evt in data.get("timeline", []):
        event_type = evt.get("type", "")
        tag = tag_map.get(event_type, f"\u2753 {event_type}")
        time_str = evt.get("time", "")[:10]
        items.append({
            "content": f"[{time_str}] {tag} \u2014 {evt.get('body', '')}",
            "source_type": "timeline",
            "event_type": event_type,
            "time": evt.get("time", ""),
        })

    for risk in data.get("active_risks", []):
        items.append({
            "content": f"\u26a0\ufe0f {risk}",
            "source_type": "active_risk",
        })

    return items


# ============================================================
# MemoryFusion: RRF merging of Mem0 + WeKnora results
# ============================================================

class MemoryFusion:
    """5-source adaptive RRF + MMR fusion of memory, knowledge, timeline, experience, and graphrag."""

    def __init__(
        self,
        default_weights: dict | None = None,
        rrf_k: int = 60,
        mmr_lambda: float | None = None,
    ):
        self.default_weights = default_weights or {
            "mem0": _cfg.FUSION_WEIGHT_MEM0,
            "kb": _cfg.FUSION_WEIGHT_KB,
            "timeline": _cfg.FUSION_WEIGHT_TIMELINE,
            "experience": _cfg.FUSION_WEIGHT_EXPERIENCE,
            "graphrag": _cfg.FUSION_WEIGHT_GRAPHRAG,
        }
        self.rrf_k = rrf_k
        self.mmr_lambda = mmr_lambda if mmr_lambda is not None else _cfg.FUSION_MMR_LAMBDA

    def fuse(
        self,
        mem0_results: list[str],
        kb_results: list[dict],
        timeline_items: list[dict] | None = None,
        experience_results: list[dict] | None = None,
        graphrag_results: list[dict] | None = None,
        query: str = "",
        mem0_meta: list[dict] | None = None,  # 新增: 与 mem0_results 平行的 created_at 元数据
    ) -> list[SearchResult]:
        """5源自适应RRF + MMR去重融合。

        Args:
            mem0_results: Mem0 搜索返回的 list[str]
            kb_results: WeKnora hybrid_search 返回的 list[dict]
            timeline_items: _graphiti_to_items() 返回的 list[dict]（可选）
            experience_results: _search_experiences_structured() 返回的 list[dict]（可选）
            graphrag_results: GraphRAG 搜索返回的 list[dict]（可选）
            query: 原始用户查询（用于关键词权重自适应）
            mem0_meta: 与 mem0_results 平行的元数据列表, 每项可含
                       {"created_at": "ISO时间戳"} 供时间聚类排序（可选, 向后兼容）

        Returns:
            去重后的 top-6 SearchResult 列表
        """
        # ── 1. 统一格式化为 (source_name, SearchResult) 对 ──
        all_items: list[tuple[str, SearchResult]] = []

        # Mem0
        for i, text in enumerate(mem0_results or []):
            meta: dict = {}
            if mem0_meta is not None and i < len(mem0_meta) and isinstance(mem0_meta[i], dict):
                meta = {"created_at": mem0_meta[i].get("created_at")}
            all_items.append(("mem0", SearchResult(
                source="mem0",
                content=str(text) if not isinstance(text, str) else text,
                score=float(i + 1),
                metadata=meta,
            )))

        # WeKnora
        for i, item in enumerate(kb_results or []):
            content = (
                item.get("content")
                or item.get("chunk_content")
                or item.get("text")
                or str(item)
            )
            all_items.append(("kb", SearchResult(
                source="weknora",
                content=content,
                score=float(i + 1),
                metadata={
                    "knowledge_id": item.get("knowledge_id", ""),
                    "document_id": item.get("document_id", ""),
                    "title": item.get("title", ""),
                    "score_raw": item.get("score", 0),
                },
            )))

        # Graphiti Timeline
        for i, item in enumerate(timeline_items or []):
            all_items.append(("timeline", SearchResult(
                source="graphiti",
                content=item.get("content", ""),
                score=float(i + 1),
                metadata={
                    "event_type": item.get("event_type", ""),
                    "time": item.get("time", ""),
                    "source_type": item.get("source_type", ""),
                },
            )))

        # Experience Store
        for i, item in enumerate(experience_results or []):
            all_items.append(("experience", SearchResult(
                source="experience",
                content=item.get("content", ""),
                score=float(item.get("score", float(i + 1))),
                metadata={
                    "source_type": item.get("source_type", ""),
                    "experience_id": item.get("experience_id", ""),
                    "version": item.get("version", ""),
                },
            )))

        # GraphRAG
        for i, item in enumerate(graphrag_results or []):
            all_items.append(("graphrag", SearchResult(
                source="graphrag",
                content=item.get("formatted", item.get("content", "")),
                score=float(i + 1),
                metadata={
                    "entities": item.get("entities", []),
                    "relations": item.get("relations", []),
                    "source_chunks": item.get("chunks", []),
                },
            )))

        if not all_items:
            return []

        # ── 2. 自适应权重 ──
        weights = self._adapt_weights(query)

        # ── 3. RRF 评分 ──
        ranked_by_source: dict[str, list[int]] = {}
        for idx, (source, _) in enumerate(all_items):
            ranked_by_source.setdefault(source, []).append(idx)

        scores: dict[int, float] = {}
        for source, indices in ranked_by_source.items():
            w = weights.get(source, 0.20)
            for rank, idx in enumerate(indices, 1):
                scores[idx] = w / (self.rrf_k + rank)

        # ── 4. 按 RRF 分数排序 ──
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        candidates: list[SearchResult] = []
        for idx, score in ranked:
            item = all_items[idx][1]
            item.score = round(score, 6)
            candidates.append(item)

        # ── 4b. 时间聚类排序 (对标 arxiv 2606.01435 max(timestamp)) ──
        candidates = self._temporal_cluster_sort(candidates)

        # ── 5. MMR 去重 ──
        return self._mmr_select(candidates, top_k=6)

    # ── 私有辅助方法 ──

    def _adapt_weights(self, query: str) -> dict:
        """关键词感知的自适应权重调整（零LLM调用）。

        检测查询中的时间/规范/经验/记忆线索，
        给对应的源加权 0.10，从其他源均摊。
        无信号时使用默认均衡权重。

        Returns:
            归一化后的权重 dict {"mem0": float, "kb": float, ...}
        """
        w = dict(self.default_weights)

        if not query:
            return w

        if any(kw in query for kw in [
            "今天", "最近", "之前", "上次", "什么时候",
            "进度", "周报", "时间线", "发生了什么",
        ]):
            w = self._boost(w, "timeline", 0.10)

        if any(kw in query for kw in [
            "规范", "标准", "要求", "GB", "条款", "规定", "合规", "安全规程",
        ]):
            w = self._boost(w, "kb", 0.10)

        if any(kw in query for kw in [
            "经验", "教训", "踩坑", "之前怎么", "处理过",
            "类似", "上次遇到", "怎么做",
        ]):
            w = self._boost(w, "experience", 0.10)

        if any(kw in query for kw in [
            "记录", "讨论", "之前说", "决定", "结论", "上次讨论", "回忆",
        ]):
            w = self._boost(w, "mem0", 0.10)

        if any(kw in query for kw in [
            "关联", "涉及", "跨文档", "所有相关", "综合",
            "关联条款", "引用关系",
        ]):
            w = self._boost(w, "graphrag", 0.10)

        # 归一化
        total = sum(w.values())
        if total > 0:
            w = {k: v / total for k, v in w.items()}

        return w

    @staticmethod
    def _boost(weights: dict, key: str, delta: float) -> dict:
        """提升某个源权重 delta，从其他源均摊。保持最低 0.05，单源上限 0.60。"""
        w = dict(weights)
        others = [k for k in w if k != key]
        if not others:
            w[key] += delta
            return w
        steal_each = delta / len(others)
        for k in others:
            w[k] = max(0.05, w[k] - steal_each)
        w[key] = min(0.60, w[key] + delta)
        return w

    def _temporal_cluster_sort(
        self,
        candidates: list[SearchResult],
        threshold: float = 0.15,
    ) -> list[SearchResult]:
        """同主题簇内按 created_at 降序排列。

        对标 arxiv 2606.01435 的确定性 max(timestamp):
        同主题变体 (3-gram Jaccard >= threshold) 聚为一簇, 簇内最新排最前.
        无 created_at 的项默认 "0000-01-01" 排簇尾. 跨簇保持 RRF 分排序.
        """
        if len(candidates) <= 1:
            return candidates
        clusters = self._cluster_by_topic(candidates, threshold)
        result: list[SearchResult] = []
        for cluster in clusters:
            cluster.sort(
                key=lambda r: r.metadata.get("created_at") or "0000-01-01T00:00:00",
                reverse=True,
            )
            result.extend(cluster)
        return result

    def _cluster_by_topic(
        self,
        candidates: list[SearchResult],
        threshold: float = 0.15,
    ) -> list[list[SearchResult]]:
        """单链聚类: 3-gram Jaccard >= threshold 视为同主题.

        阈值 0.15 来自实测校准 (基准适配器: 同主题变体 0.16-0.22, 噪声 0.07-0.10).
        """
        n = len(candidates)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(n):
            for j in range(i + 1, n):
                if self._text_similarity(candidates[i].content, candidates[j].content) >= threshold:
                    union(i, j)

        clusters_map: dict[int, list[SearchResult]] = {}
        for i, c in enumerate(candidates):
            clusters_map.setdefault(find(i), []).append(c)
        return sorted(
            clusters_map.values(),
            key=lambda cl: max(r.score for r in cl),
            reverse=True,
        )

    @staticmethod
    def _mmr_similarity(a: SearchResult, b: SearchResult) -> float:
        """内容相似度 + 时间折扣.

        异日变体 (created_at 不同) 不是重复 — 保留 (×0.02 折扣);
        同日或未知时间走原 jaccard.
        # 运行时加权 RRF ≈0.003 比适配器未加权 ≈0.016 小 5-15x; ×0.05 会在运行时尺度把异日变体推出 0 以下
        """
        sim = MemoryFusion._text_similarity(a.content, b.content)
        ta = a.metadata.get("created_at")
        tb = b.metadata.get("created_at")
        if ta and tb and ta != tb:
            sim *= 0.02
        return sim

    def _mmr_select(
        self, candidates: list[SearchResult], top_k: int = 6
    ) -> list[SearchResult]:
        """MMR 贪心选择：平衡相关性和多样性。

        MMR = λ × relevance_score - (1-λ) × max_similarity_to_selected

        参考：m3-memory MMR implementation。
        """
        if len(candidates) <= 1:
            return candidates

        selected = [candidates[0]]
        remaining = candidates[1:]

        while len(selected) < top_k and remaining:
            best_idx = 0
            best_mmr = -float("inf")
            best_sim = 0.0
            for idx, c in enumerate(remaining):
                relevance = c.score
                max_sim = max(
                    self._mmr_similarity(c, s)
                    for s in selected
                )
                mmr = self.mmr_lambda * relevance - (1 - self.mmr_lambda) * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = idx
                    best_sim = max_sim
            # 仅对同日/未知日期项生效 (异日变体经 ×0.02 折扣后 ≤0.02, 永远不会 break)
            if best_mmr <= 0 and best_sim >= 0.5:
                break
            selected.append(remaining.pop(best_idx))

        return selected

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """字符级 3-gram Jaccard 相似度。

        比 content[:60].lower() 前缀匹配更鲁棒：
        - 对词序变化不敏感
        - 对轻微 rewording 容忍度更高
        - 零外部依赖，O(n) 复杂度（n = min(len, 100)）
        """
        def triples(s: str) -> set[str]:
            s = s[:100].lower()
            return {s[i:i + 3] for i in range(len(s) - 2)}

        ta, tb = triples(a), triples(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)


# ============================================================
# ContextAssembler: 7-layer context assembly
# ============================================================

class ContextAssembler:
    """
    Assembles the 7-layer context window for each LLM call.

    Order (from 长期短期记忆机制核心设计方案.md §3.2):
      ① System Prompt    (2-5K tokens)  — role persona
      ② Summary           (5-15K tokens) — compressed history
      ③ LTM Injection     (10-20K tokens) — Mem0 results
      ④ KB Injection      (10-20K tokens) — WeKnora results
      ⑤ Runtime Context    (1-2K tokens)  — time/project/role
      ⑥ Recent History    (5-10K tokens)  — last N messages
      ⑦ User Message       (variable)     — current input
    """

    @staticmethod
    def format_system_reminder(
        fused: list[SearchResult],
        mem0_raw: list[str] | None = None,
        kb_raw: list[dict] | None = None,
    ) -> str:
        """Format 5-source search results as <system-reminder> block."""
        lines = ["<system-reminder>"]
        lines.append("以下是从长期记忆、知识库、项目时间线和经验库中检索到的相关信息：")

        # ── 长期记忆 ──
        mem_items = [r for r in fused if r.source == "mem0"]
        lines.append("")
        lines.append("【长期记忆 — 项目历史】")
        if mem_items:
            for i, item in enumerate(mem_items, 1):
                timestamp = item.metadata.get("created_at", "")
                ts_str = f"[{timestamp[:10]}] " if timestamp else ""
                lines.append(f"  {i}. {ts_str}{item.content}")
        else:
            lines.append("  暂无相关记录（首次对话或该项目尚未存储记忆）。")

        # ── 知识库 ──
        kb_items = [r for r in fused if r.source == "weknora"]
        if kb_items:
            lines.append("")
            lines.append("【知识库 — 规范标准】")
            for i, item in enumerate(kb_items, 1):
                title = item.metadata.get("title", "")
                title_str = f"（{title}）" if title else ""
                lines.append(f"  {i}. {item.content}{title_str}")

        # ── 时间线 ──
        tl_items = [r for r in fused if r.source == "graphiti"]
        if tl_items:
            lines.append("")
            lines.append("【项目时间线 — 最近事件】")
            for i, item in enumerate(tl_items, 1):
                lines.append(f"  {i}. {item.content}")

        # ── 经验库 ──
        exp_items = [r for r in fused if r.source == "experience"]
        if exp_items:
            lines.append("")
            lines.append("【经验库 — 历史教训】")
            for i, item in enumerate(exp_items, 1):
                src_type = item.metadata.get("source_type", "")
                type_str = f"[{src_type}] " if src_type else ""
                lines.append(f"  {i}. {type_str}{item.content}")

        # ── 知识图谱 ──
        graph_items = [r for r in fused if r.source == "graphrag"]
        if graph_items:
            lines.append("")
            lines.append("【知识图谱 — 实体关联】")
            for i, item in enumerate(graph_items, 1):
                lines.append(f"  {i}. {item.content}")

        lines.append("</system-reminder>")
        return "\n".join(lines)

    def assemble(
        self,
        *,
        system_prompt: str,
        summary: str = "",
        ltm_results: list[str] | None = None,
        kb_results: list[dict] | None = None,
        fused_results: list[SearchResult] | None = None,
        recent_history: list | None = None,
        user_message: str,
        project_id: str = "",
        role_id: str = "",
        current_time: str = "",
        skill_text: str = "",
    ) -> list[dict]:
        """
        Assemble full context into OpenAI-compatible messages list.

        Returns a list of message dicts ready to send to the LLM.
        """
        if current_time == "":
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        messages: list[dict] = []

        # ── ① System Prompt ──
        # Inject runtime info into system prompt
        runtime_header = ""
        if project_id or role_id or current_time:
            runtime_header = (
                f"\n\n<runtime_context>"
                f"\n  当前时间: {current_time}"
                f"\n  项目: {project_id}"
                f"\n  角色: {role_id}"
                f"\n</runtime_context>"
            )
        messages.append({
            "role": "system",
            "content": system_prompt + runtime_header,
        })

        # ── Layer ①b: Skill Injection (§10) ──
        # skill_text is pre-computed by the async caller and passed in;
        # this method is sync and must not call asyncio.run().
        if skill_text:
            messages.append({
                "role": "system",
                "content": skill_text,
            })

        # ── ② Summary ──
        if summary:
            messages.append({
                "role": "system",
                "content": f"<summary>\n{summary}\n</summary>",
            })

        # ── ③④ LTM + KB Injection (fused via <system-reminder>) ──
        if fused_results:
            reminder = self.format_system_reminder(fused_results, ltm_results, kb_results)
            messages.append({
                "role": "system",
                "content": reminder,
            })

        # ── ⑤ Runtime Context (already in system prompt header) ──

        # ── ⑥ Recent History ──
        if recent_history:
            for msg in recent_history:
                if hasattr(msg, "role") and hasattr(msg, "content"):
                    messages.append({"role": msg.role, "content": msg.content})
                elif isinstance(msg, dict):
                    messages.append(msg)

        # ── ⑦ User Message ──
        messages.append({"role": "user", "content": user_message})

        return messages

    def assemble_prompt_only(
        self,
        *,
        system_prompt: str,
        summary: str = "",
        fused_results: list[SearchResult] | None = None,
        user_message: str,
        project_id: str = "",
        role_id: str = "",
        current_time: str = "",
        skill_text: str = "",
    ) -> str:
        """
        Assemble context into a single string prompt (for simple LLM calls).

        Useful when the model API doesn't support system/user message separation.
        """
        messages = self.assemble(
            system_prompt=system_prompt,
            summary=summary,
            fused_results=fused_results,
            user_message=user_message,
            project_id=project_id,
            role_id=role_id,
            current_time=current_time,
            skill_text=skill_text,
        )
        parts = []
        for m in messages:
            role = m["role"]
            content = m["content"]
            if role == "system":
                parts.append(content)
            elif role == "user":
                parts.append(f"\n\n---\n用户: {content}")
            elif role == "assistant":
                parts.append(f"\n助手: {content}")
        return "\n".join(parts)
