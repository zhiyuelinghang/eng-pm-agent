# tests/conftest.py
#
# test_unfixed_diffs.py 是脚本风格 E2E 测试（顶层直调 11 个 test 函数 + sys.exit 汇总），
# 由 `python tests/test_unfixed_diffs.py` 直接运行（README「差异修复验证 66 AC」）。
# pytest 导入该模块时会执行顶层代码并触发 SystemExit → INTERNALERROR，
# 故从 pytest 收集器中排除；其余脚本风格测试（test_p0_1_* / test_p0_2_* 等）
# 顶层执行块有 `if __name__ == "__main__"` 保护，可正常收集。

collect_ignore = ["test_unfixed_diffs.py"]
