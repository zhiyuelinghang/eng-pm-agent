from pathlib import Path

import pytest

from scripts.dobby_agent_tools import _parse_initialization_file


SAMPLES = (
    (
        "原型/工程基本信息/1.工程描述/工程描述.txt",
        "txt",
        "total_lines",
    ),
    (
        "原型/工程基本信息/2.工序划分、计划、里程碑/总进度计划（WBS）.xlsx",
        "xlsx",
        "total_rows",
    ),
    (
        "原型/工程基本信息/3.人员名单 - 副本.xlsx",
        "xlsx",
        "total_rows",
    ),
    (
        "原型/工程基本信息/4.风险源/工程风险清单.xlsx",
        "xlsx",
        "total_rows",
    ),
    (
        "原型/工程基本信息/5.工序质量指标关联表.xlsx",
        "xlsx",
        "total_rows",
    ),
)


@pytest.mark.parametrize(("relative_path", "expected_format", "count_key"), SAMPLES)
def test_project_initialization_samples_can_be_parsed(
    relative_path: str,
    expected_format: str,
    count_key: str,
) -> None:
    path = Path(relative_path)
    result = _parse_initialization_file(
        path.read_bytes(),
        path.suffix.lower(),
        None,
        1,
        10,
    )

    assert result["format"] == expected_format
    assert result[count_key] > 0


def test_wbs_excel_keeps_zero_progress_distinct_from_empty_cells() -> None:
    path = Path(
        "原型/工程基本信息/2.工序划分、计划、里程碑/总进度计划（WBS）.xlsx",
    )
    result = _parse_initialization_file(
        path.read_bytes(),
        path.suffix.lower(),
        None,
        5,
        3,
    )

    header, root_wbs, child_wbs = result["rows"]
    progress_column = header.index("进度 (%)")
    assert root_wbs[progress_column] == 0
    assert child_wbs[progress_column] == 0
