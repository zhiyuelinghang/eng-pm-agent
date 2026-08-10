#!/usr/bin/env python3
"""
运行时移植测试 — fusion.py 时间聚类排序 + 时间感知 MMR.

Run: python test_runtime_port.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # dobby-memory/
from utils.fusion import MemoryFusion


class TR:
    def __init__(self):
        self.r = []
    def add(self, name, passed, detail=""):
        self.r.append((name, passed, detail))
        print(f"  {'PASS' if passed else 'FAIL'} {name}" + (f": {detail}" if detail else ""))
    def summary(self):
        p = sum(1 for _, x, _ in self.r if x)
        print(f"\n{'='*60}\nResults: {p}/{len(self.r)} passed {'ALL PASS' if p == len(self.r) else 'FAILURES'}\n{'='*60}")
        return p == len(self.r)


# ── 时间聚类排序: 同主题异日变体按 created_at 降序 ──
def t01_temporal_cluster_sort(r: TR):
    mf = MemoryFusion()
    # 三个同主题异日变体 (Jaccard 0.16-0.22 ≥ 0.15 聚类阈值, 实测校准),
    # 输入顺序为"旧→新" (RRF rank 使 March 15 排最前,
    # 只有时间聚类排序能把 April 5 提到第一)
    results = mf.fuse(
        [
            "[s1] [A]: The Q1 release deadline is March 15.",
            "[s2] [A]: Deadline pushed to March 30 due to scope changes.",
            "[s3] [A]: Final deadline set to April 5 after QA review.",
        ],
        [],  # kb_results
        mem0_meta=[
            {"created_at": "2024-01-10T00:00:00"},
            {"created_at": "2024-02-01T00:00:00"},
            {"created_at": "2024-02-20T00:00:00"},
        ],
    )
    contents = [s.content for s in results]
    r.add("3 deadline variants present", len(results) == 3, f"got {len(results)}")
    r.add("April 5 first (newest)", "April 5" in contents[0], f"first={contents[0][:40]}")
    return True


# ── 时间感知 MMR: 异日变体保留, 同日重复去重 ──
def t02_temporal_mmr(r: TR):
    mf = MemoryFusion()
    results = mf.fuse(
        [
            "[s1] [A]: The Q1 release deadline is March 15.",
            "[s1] [A]: The Q1 release deadline is March 15.",   # 同日重复
            "[s3] [A]: Final deadline set to April 5 after QA review.",  # 异日变体
        ],
        [],
        mem0_meta=[
            {"created_at": "2024-01-10T00:00:00"},
            {"created_at": "2024-01-10T00:00:00"},
            {"created_at": "2024-02-20T00:00:00"},
        ],
    )
    contents = [s.content for s in results]
    mar_count = sum(1 for c in contents if "March 15" in c)
    apr_count = sum(1 for c in contents if "April 5" in c)
    r.add("same-date duplicate deduped (<=1)", mar_count <= 1, f"count={mar_count}")
    r.add("different-date variant kept", apr_count >= 1, f"count={apr_count}")
    return True


# ── 向后兼容: 无 mem0_meta 时行为不变 ──
def t03_backward_compat(r: TR):
    mf = MemoryFusion()
    results = mf.fuse(["hello world memory"], [], query="hello")
    r.add("no mem0_meta still works", len(results) >= 1, f"got {len(results)}")
    return True


# ── 实体图懒加载 (不依赖真实 mem0: 直接测 EntityGraph 扩散) ──
def t04_entity_diffusion(r: TR):
    from utils.entity_graph import EntityExtractor, EntityGraph

    g = EntityGraph()
    ext = EntityExtractor()
    mem1 = "Alice is the new project manager for the Phoenix initiative."
    mem2 = "The Phoenix initiative office is on the 3rd floor, room 302."
    mem3 = "All PMs have admin access to the build server."
    g.add_memory("mem1", mem1, ext.extract(mem1), created_at="2024-01-10T00:00:00")
    g.add_memory("mem2", mem2, ext.extract(mem2), created_at="2024-01-11T00:00:00")
    g.add_memory("mem3", mem3, ext.extract(mem3), created_at="2024-01-12T00:00:00")

    act = g.spreading_activation(["Alice"], max_depth=2)
    r.add("mem1 activated (direct)", act.get("mem1", 0) >= 0.9, f"act={act.get('mem1', 0):.2f}")
    r.add("mem2 activated (2-hop via Phoenix)", act.get("mem2", 0) >= 0.4, f"act={act.get('mem2', 0):.2f}")
    r.add("mem3 absent (no link)", "mem3" not in act, f"keys={sorted(act)}")
    # 扩散出的记忆可取回文本+时间
    r.add("get_content from diffusion", g.get_content("mem2") == mem2)
    r.add("get_created_at from diffusion", g.get_created_at("mem2") == "2024-01-11T00:00:00")
    return True


# ── assemble_context 传递 mem0_meta: 验证元数据构造逻辑 ──
def t05_mem0_meta_construction(r: TR):
    # 模拟 assemble_context 中的 mem0_strs / mem0_meta 构造
    # 输入顺序为"旧→新", 时间聚类排序必须把 April 5 提到第一
    mem0_results = [
        {"id": "m2", "memory": "[s1] [A]: The Q1 release deadline is March 15.", "created_at": "2024-01-10T00:00:00"},
        {"id": "m1", "memory": "[s3] [A]: Final deadline set to April 5 after QA review.", "created_at": "2024-02-20T00:00:00"},
        "plain string result",  # 非 dict 兼容
    ]
    mem0_strs = [
        r.get("memory", str(r)) if isinstance(r, dict) else str(r)
        for r in mem0_results
    ]
    mem0_meta = [
        {"created_at": r.get("created_at")} if isinstance(r, dict) else {}
        for r in mem0_results
    ]
    mf = MemoryFusion()
    fused = mf.fuse(mem0_strs, [], mem0_meta=mem0_meta)
    contents = [s.content for s in fused]
    r.add("all 3 results fused", len(fused) == 3, f"got {len(fused)}")
    r.add("April 5 first (time sort)", "April 5" in contents[0], f"first={contents[0][:30]}")
    return True


# ── MemoryManager 实体图接线: mock mem0 验证懒加载/扩散/降级 ──
def t06_memorymanager_wiring(r: TR):
    from unittest.mock import MagicMock, patch
    from utils.memory_manager import MemoryManager
    from utils.entity_graph import EntityGraph

    # 1. 懒加载: mock get_all 返回带实体的记忆
    mock_mem0 = MagicMock()
    mock_mem0.get_all.return_value = {"results": [
        {"id": "m1", "memory": "Alice is the new project manager for the Phoenix initiative.",
         "created_at": "2024-01-10T00:00:00"},
        {"id": "m2", "memory": "The Phoenix initiative office is on the 3rd floor, room 302.",
         "created_at": "2024-01-11T00:00:00"},
    ]}
    mm = MemoryManager(project_id="proj1", role_id="dobby_core")
    with patch("utils.memory_manager.get_mem0", return_value=mock_mem0):
        graph = asyncio.run(mm._get_entity_graph("proj1", "dobby_core"))
    r.add("lazy build returns graph", graph is not None and isinstance(graph, EntityGraph))
    r.add("graph has 2 memories",
          graph.get_content("m1") is not None and graph.get_content("m2") is not None)

    # 2. TTL 复用: 第二次调用不再 get_all
    mock_mem0.reset_mock()
    with patch("utils.memory_manager.get_mem0", return_value=mock_mem0):
        graph2 = asyncio.run(mm._get_entity_graph("proj1", "dobby_core"))
    r.add("TTL reuse (no second get_all)", mock_mem0.get_all.call_count == 0,
          f"calls={mock_mem0.get_all.call_count}")

    # 3. 扩散: 查询含 Alice 的实体
    with patch("utils.memory_manager.get_mem0", return_value=mock_mem0):
        results = asyncio.run(mm._search_memory("Where is Alice's office?", "proj1", "dobby_core"))
    ids = {str(x.get("id")) for x in results}
    r.add("diffusion reaches mem2 (Phoenix hop)", "m2" in ids, f"ids={ids}")
    diffused = [x for x in results if str(x.get("id")) == "m2"]
    r.add("diffused item carries created_at",
          diffused and diffused[0].get("created_at") == "2024-01-11T00:00:00",
          f"created_at={diffused[0].get('created_at') if diffused else None}")

    # 4. 降级: get_all 抛异常 → None, 原路径不受影响
    mock_broken = MagicMock()
    mock_broken.get_all.side_effect = RuntimeError("mem0 down")
    mm2 = MemoryManager(project_id="proj1", role_id="dobby_core")
    with patch("utils.memory_manager.get_mem0", return_value=mock_broken):
        g = asyncio.run(mm2._get_entity_graph("proj1", "dobby_core"))
    r.add("graceful degradation (None on mem0 down)", g is None)

    # 5. 默认 project_id="" 回退: 图按 MEM0_USER_ID 构建
    mock_mem0.reset_mock()
    mm3 = MemoryManager(project_id="", role_id="dobby_core")
    from utils import config as _cfg
    with patch("utils.memory_manager.get_mem0", return_value=mock_mem0):
        asyncio.run(mm3._get_entity_graph("", "dobby_core"))
    call_filters = mock_mem0.get_all.call_args.kwargs.get("filters", {})
    r.add("empty project_id falls back to MEM0_USER_ID",
          call_filters.get("user_id") == _cfg.MEM0_USER_ID,
          f"user_id={call_filters.get('user_id')}")

    # 6. remember() 增量: mock add 返回 v2 dict 形状
    mock_mem0.reset_mock()
    mock_mem0.add.return_value = {"results": [
        {"id": "m3", "memory": "Contract type is the most predictive feature (SHAP 0.42).",
         "created_at": "2024-02-01T00:00:00"},
    ]}
    mm4 = MemoryManager(project_id="proj1", role_id="dobby_core")
    with patch("utils.memory_manager.get_mem0", return_value=mock_mem0):
        mm4._entity_graph = EntityGraph()  # 图已加载
        asyncio.run(mm4.remember("Contract type is the most predictive feature (SHAP 0.42)."))
    r.add("remember incremental adds to graph",
          mm4._entity_graph.get_content("m3") is not None
          and "contract type" in (mm4._entity_graph.get_content("m3") or "").lower())
    return True


def main():
    t = TR()
    t01_temporal_cluster_sort(t)
    t02_temporal_mmr(t)
    t03_backward_compat(t)
    t04_entity_diffusion(t)
    t05_mem0_meta_construction(t)
    t06_memorymanager_wiring(t)
    return t.summary()


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
