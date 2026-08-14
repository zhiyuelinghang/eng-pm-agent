"""
Entity graph for multi-hop memory retrieval.

对标:
- agentmemory V4 graph.py EntityRelationExtractor + MemoryGraph.spreading_activation()
- 扩散激活: decay=0.5, min_activation=0.05 (agentmemory V4 精确默认值)
- 实体提取: 正则模式对标 _PROPER_RE + 中文虚词分段/长片段窗口扩展
"""

from __future__ import annotations

import re
from collections import defaultdict


class EntityExtractor:
    """Zero-dependency entity extraction for Chinese and English text.

    对标 agentmemory V4 EntityRelationExtractor._extract_regex().
    _PROPER_RE = r'\\b[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)+\\b'
    我们放宽为单大写词也提取 (Alice, Phoenix, PM, XGBoost, AUC).
    """

    # 对标 agentmemory V4 _PROPER_RE, 但允许单大写词
    _EN_PROPER = re.compile(r'\b[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*\b')
    # 中文连续片段 ≥2 字
    _ZH_WORD = re.compile(r'[\u4e00-\u9fff]{2,}')
    # 数字位置模式: 3楼, 302室, 5号
    _NUM_LOC = re.compile(r'\d+[楼室层号栋位]\d*[室号]?')
    # 规范编号: JGJ 120-2012, GB 50016 (至少2位数字, 避免 "AUC 0.89" 误报为 "AUC 0")
    _STANDARD = re.compile(r'[A-Z]{2,}\s+\d{2,}[-\d]*')
    # 拼音/缩写实体: PM, API, JWT, XGBoost, AUC
    _ACRONYM = re.compile(r'\b[A-Z]{2,}[a-z]*\b')

    # 中文连接词/虚词 — 把长连续片段切分为有意义的分段
    _ZH_SPLIT_WORDS = (
        '根据', '采用', '进行', '需要', '以及',
        '的', '了', '是', '在', '与', '和', '及', '为', '按',
    )
    # 位置/时态助词 — 只从分段末尾剥离, 避免切断复合词 ("地下连续墙" 中的 "下")
    _ZH_TRAIL = ('等', '时', '后', '中', '上', '下')
    _ZH_SPLIT_RE = re.compile('|'.join(map(re.escape, _ZH_SPLIT_WORDS)))

    @classmethod
    def _zh_pieces(cls, run: str) -> list[str]:
        """切分一段中文: 在连接词处断开, 剥离句末助词, 丢弃 <2 字碎片."""
        pieces: list[str] = []
        for part in cls._ZH_SPLIT_RE.split(run):
            while part and part[-1] in cls._ZH_TRAIL:
                part = part[:-1]
            if len(part) >= 2:
                pieces.append(part)
        return pieces

    @classmethod
    def extract(cls, text: str) -> list[str]:
        """Extract entities from text. Returns deduplicated list."""
        entities: list[str] = []

        # 英文专有名词 (对标 agentmemory V4 _PROPER_RE)
        for m in cls._EN_PROPER.finditer(text):
            token = m.group().strip()
            # 去掉开头的停用词: "The Phoenix" → "Phoenix"
            # (否则 "The X" 与 "X" 会成为不同的实体键, 破坏 co-occurrence 检索)
            words = token.split()
            while words and words[0].lower() in _STOP_WORDS:
                words = words[1:]
            if not words:
                # 整个 run 都是停用词 ("The", "March") — 不是实体
                continue
            token = " ".join(words)
            # 过滤常见停用词
            if token.lower() not in _STOP_WORDS and len(token) >= 2:
                entities.append(token)

        # 中文: 虚词分段 + 长片段 4-gram 窗口
        zh_runs = [(m.start(), m.end(), m.group())
                   for m in cls._ZH_WORD.finditer(text)]
        num_locs = [(m.start(), m.end(), m.group())
                    for m in cls._NUM_LOC.finditer(text)]
        runs: list[tuple[int, list[str]]] = []
        for zs, _ze, run in zh_runs:
            # 数字位置已吃掉单位字: "3号" 匹配 [0,2), 汉字片段 "号基坑…" 从 1 开始,
            # 即从数字位置匹配内部开始 — 去掉开头的单位字
            if run[0] in _UNIT_CHARS and any(ns <= zs < ne for ns, ne, _ in num_locs):
                run = run[1:]
                zs += 1
            runs.append((zs, cls._zh_pieces(run)))
        for _zs, pieces in runs:
            for piece in pieces:
                n = len(piece)
                if n <= 8:
                    entities.append(piece)
                else:
                    # 长片段 (n > 8): 输出滑动 4-gram 窗口
                    for i in range(n - 3):
                        entities.append(piece[i:i + 4])
                if n >= 5:
                    # 子实体窗口: 保留 5 字术语, 如 "地下连续墙支护" → "地下连续墙"
                    entities.append(piece[:5])
                    entities.append(piece[-5:])

        # 数字位置
        for _ns, _ne, nt in num_locs:
            entities.append(nt)

        # 数字+单位与紧随的中文分段合并: "3号" + "基坑" → "3号基坑"
        for _ns, ne, nt in num_locs:
            for zs, pieces in runs:
                if zs == ne and pieces:
                    entities.append(nt + pieces[0])
                    break

        # 规范编号
        for m in cls._STANDARD.finditer(text):
            entities.append(m.group())

        # 缩写
        for m in cls._ACRONYM.finditer(text):
            token = m.group()
            if len(token) >= 2:
                entities.append(token)

        # 去重保持顺序
        seen: set[str] = set()
        result: list[str] = []
        for e in entities:
            key = e.lower()
            if key not in seen:
                seen.add(key)
                result.append(e)
        return result


class EntityGraph:
    """Entity→Memory inverted index with BFS spreading activation.

    对标 agentmemory V4 MemoryGraph.spreading_activation():
    - 数据结构: _entity_to_mems (entity→memory_id), _mem_to_entities (memory_id→entity)
    - co-occurrence edges: 同一记忆中的实体互相连接
    - BFS 扩散: depth 0→1→2, 每跳 decay=0.5

    agentmemory V4 的 _entity_index 是 entity→entity_node_id, 我们用 entity→{mem_id}
    """

    def __init__(self) -> None:
        self._entity_to_mems: dict[str, set[str]] = defaultdict(set)
        self._mem_to_entities: dict[str, set[str]] = defaultdict(set)
        # co-occurrence edges: entity → co-occurring entities
        self._cooccurrence: dict[str, set[str]] = defaultdict(set)
        # 记忆文本与创建时间 (对标 agentmemory V4 MemoryNode.content)
        self._contents: dict[str, str] = {}
        self._mem_times: dict[str, str] = {}

    def add_memory(
        self,
        mem_id: str,
        content: str,
        entities: list[str],
        created_at: str | None = None,
    ) -> None:
        """Index a memory by its entities. Build co-occurrence edges.

        Args:
            mem_id: 记忆唯一ID
            content: 记忆文本 (存储供扩散后取回)
            entities: 提取的实体列表
            created_at: ISO 时间戳 (可选, 供时间聚类排序)
        """
        entity_keys = [e.lower() for e in entities]
        self._mem_to_entities[mem_id] = set(entity_keys)
        for key in entity_keys:
            self._entity_to_mems[key].add(mem_id)
        # co-occurrence: 同一记忆中的所有实体互相连接
        for i, e1 in enumerate(entity_keys):
            for e2 in entity_keys[i + 1:]:
                self._cooccurrence[e1].add(e2)
                self._cooccurrence[e2].add(e1)
        self._contents[mem_id] = content
        if created_at is not None:
            self._mem_times[mem_id] = created_at

    def get_content(self, mem_id: str) -> str | None:
        """按记忆ID取回内容文本 (对标 agentmemory V4 MemoryNode.content)."""
        return self._contents.get(mem_id)

    def get_created_at(self, mem_id: str) -> str | None:
        """按记忆ID取回创建时间 (供时间排序)."""
        return self._mem_times.get(mem_id)

    def spreading_activation(
        self,
        seed_entities: list[str],
        max_depth: int = 2,
        decay: float = 0.5,
        min_activation: float = 0.05,
    ) -> dict[str, float]:
        """BFS from seed entities. Returns {mem_id: activation_score}.

        精确对标 agentmemory V4 MemoryGraph.spreading_activation():
        - decay=0.5 (相同)
        - min_activation=0.05 (相同)
        - max_depth=2 (agentmemory V4 默认 3, engram 场景更浅)
        - 跳数跟踪避免重复访问 (agentmemory V4 的 visited_depth)
        """
        mem_scores: dict[str, float] = {}
        visited_depth: dict[str, int] = {}

        # Seed: activation=1.0
        frontier: list[tuple[str, float, str]] = []  # (key, act, type)
        for seed in seed_entities:
            key = seed.lower()
            if key not in visited_depth:
                visited_depth[key] = 0
                frontier.append((key, 1.0, 'entity'))

        for depth in range(max_depth + 1):
            next_frontier: list[tuple[str, float, str]] = []
            for node_key, act, node_type in frontier:
                if act < min_activation:
                    continue
                if node_type == 'entity':
                    # entity → 直接关联的记忆 (activation = act * 1.0)
                    for mem_id in self._entity_to_mems.get(node_key, set()):
                        mem_scores[mem_id] = max(mem_scores.get(mem_id, 0.0), act)
                        if depth < max_depth:
                            # memory → 记忆中的其他实体 (下一跳)
                            for co_entity in self._mem_to_entities.get(mem_id, set()):
                                if co_entity == node_key:
                                    continue
                                prop = act * decay
                                if prop >= min_activation:
                                    prev = visited_depth.get(co_entity, max_depth + 1)
                                    if depth + 1 < prev:
                                        visited_depth[co_entity] = depth + 1
                                        next_frontier.append((co_entity, prop, 'entity'))
            frontier = next_frontier

        return mem_scores

    def stats(self) -> dict:
        """Graph stats for diagnostics."""
        return {
            "total_entities": len(self._entity_to_mems),
            "total_memories": len(self._mem_to_entities),
            "avg_mems_per_entity": (
                sum(len(v) for v in self._entity_to_mems.values()) / max(len(self._entity_to_mems), 1)
            ),
        }


# 数字位置单位字 — 也出现在汉字区间, 需在分段前剥离
_UNIT_CHARS = '楼室层号栋位'

# 英文停用词 — 对标 agentmemory V4 过滤常见非实体词
_STOP_WORDS: set[str] = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'can', 'could', 'should', 'may', 'might', 'shall', 'must',
    'this', 'that', 'these', 'those', 'it', 'its', 'he', 'she',
    'they', 'we', 'you', 'i', 'me', 'my', 'our', 'your', 'his',
    'her', 'their', 'not', 'no', 'nor', 'or', 'and', 'but', 'if',
    'then', 'else', 'when', 'where', 'why', 'how', 'what', 'which',
    'who', 'whom', 'all', 'each', 'every', 'both', 'few', 'more',
    'most', 'other', 'some', 'such', 'only', 'own', 'same', 'so',
    'than', 'too', 'very', 'just', 'about', 'above', 'after',
    'again', 'against', 'between', 'into', 'through', 'during',
    'before', 'under', 'over', 'up', 'down', 'in', 'out', 'on',
    'off', 'at', 'by', 'for', 'with', 'from', 'to', 'of',
    'ok', 'okay', 'yes', 'no', 'thanks', 'thank', 'got',
    'hi', 'hello', 'hey', 'bye', 'good', 'bad', 'great',
    'sure', 'like', 'know', 'think', 'see', 'want', 'need',
    'going', 'come', 'get', 'make', 'use', 'also', 'well',
    'really', 'still', 'much', 'many', 'lot', 'bit',
    'one', 'two', 'three', 'first', 'second', 'last', 'next',
    # 月份/星期名 — 避免日期句 ("... deadline is March 15.") 提取出假实体
    'january', 'february', 'march', 'april', 'june', 'july',
    'august', 'september', 'october', 'november', 'december',
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday',
    'saturday', 'sunday',
}
