from backend.app.project_initialization import (
    ProjectInitializationPayload,
    suggest_unique_username,
    validate_initialization_payload,
)


def _wbs(
    code: str,
    *,
    parent: str | None,
    name: str,
    start: str,
    finish: str,
    predecessors: list[str] | None = None,
) -> dict:
    return {
        "wbs_code": code,
        "parent_wbs_code": parent,
        "predecessor_wbs_codes": predecessors or [],
        "name": name,
        "planned_start_at": start,
        "planned_finish_at": finish,
        "progress_percent": 0,
        "status_text": "打开",
        "priority_text": "中",
        "level": code.count(".") + 1,
    }


def test_numeric_wbs_order_allows_1_1_9_before_1_1_10() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="施工",
                    start="2025-01-01T08:00:00",
                    finish="2025-04-30T17:00:00",
                ),
                _wbs(
                    "1.1.9",
                    parent="1.1",
                    name="2025年春节放假",
                    start="2025-01-21T08:00:00",
                    finish="2025-02-12T17:00:00",
                ),
                _wbs(
                    "1.1.10",
                    parent="1.1",
                    name="节后复工",
                    start="2025-02-13T08:00:00",
                    finish="2025-02-20T17:00:00",
                    predecessors=["1.1.9"],
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert not any("1.1.10 的计划开始早于前任" in item["message"] for item in issues)
    assert not any("同级 WBS 编码顺序" in item["message"] for item in issues)


def test_sibling_start_dates_must_follow_numeric_wbs_order() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="第一项",
                    start="2025-02-01T08:00:00",
                    finish="2025-02-10T17:00:00",
                ),
                _wbs(
                    "1.2",
                    parent="1",
                    name="第二项",
                    start="2025-01-01T08:00:00",
                    finish="2025-01-10T17:00:00",
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["path"] == "wbs.1.2.planned_start_at"
        and "同级 WBS 1.1" in item["message"]
        for item in issues
    )


def test_overlapping_predecessor_dates_are_reported_for_confirmation() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="前任",
                    start="2025-01-01T08:00:00",
                    finish="2025-02-10T17:00:00",
                ),
                _wbs(
                    "1.2",
                    parent="1",
                    name="后续",
                    start="2025-02-01T08:00:00",
                    finish="2025-03-01T17:00:00",
                    predecessors=["1.1"],
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["path"] == "wbs.1.2.planned_start_at"
        and "如属于搭接施工" in item["message"]
        for item in issues
    )


def test_placeholder_wbs_name_is_preserved_but_warned() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "wbs": [
                _wbs(
                    "1",
                    parent=None,
                    name="项目",
                    start="2025-01-01T08:00:00",
                    finish="2025-12-31T17:00:00",
                ),
                _wbs(
                    "1.1",
                    parent="1",
                    name="任务名称",
                    start="2025-01-01T08:00:00",
                    finish="2025-01-02T17:00:00",
                ),
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "warning"
        and item["path"] == "wbs.1.1.name"
        and "疑似占位内容" in item["message"]
        for item in issues
    )


def test_username_suggestion_uses_name_pinyin_and_avoids_collisions() -> None:
    unavailable = {"zhanghuaide", "zhanghuaide2"}

    username = suggest_unique_username(
        "张怀德",
        "310108198611171091",
        unavailable,
    )

    assert username == "zhanghuaide3"


def test_same_person_with_multiple_positions_reuses_one_account() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "personnel": [
                {
                    "serial_no": 1,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-1",
                    "responsibility_description": "负责商务管理",
                },
                {
                    "serial_no": 2,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "劳务员",
                    "certificate_no": "CERT-2",
                    "responsibility_description": "负责劳务管理",
                },
            ],
        },
    )

    issues = validate_initialization_payload(payload)
    personnel_issues = [item for item in issues if item["path"] == "personnel"]

    assert any(
        item["level"] == "warning"
        and "共用同一个平台账号" in item["message"]
        for item in personnel_issues
    )
    assert not any(item["level"] == "error" for item in personnel_issues)


def test_same_person_cannot_repeat_the_same_position() -> None:
    payload = ProjectInitializationPayload.model_validate(
        {
            "personnel": [
                {
                    "serial_no": 1,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-1",
                    "responsibility_description": "负责商务管理",
                },
                {
                    "serial_no": 2,
                    "real_name": "马泽坤",
                    "identity_card_no": "320922199610153614",
                    "position_name": "项目商务副经理",
                    "certificate_no": "CERT-2",
                    "responsibility_description": "负责成本管理",
                },
            ],
        },
    )

    issues = validate_initialization_payload(payload)

    assert any(
        item["level"] == "error"
        and "岗位「项目商务副经理」重复" in item["message"]
        for item in issues
    )
