from pathlib import Path
from typing import Any

from scripts import provision_initialization_agents


def _write_skill(root: Path, name: str) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        (
            "---\n"
            f"name: {name}\n"
            f"description: 测试技能 {name}\n"
            "---\n\n"
            "# 测试\n"
        ),
        encoding="utf-8",
    )


def test_skill_sync_uses_one_unique_workspace_per_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_skill(tmp_path, "read-initialization-attachments")
    _write_skill(tmp_path, "extract-project-basics")
    monkeypatch.setattr(
        provision_initialization_agents,
        "SKILL_SOURCE_ROOT",
        tmp_path,
    )
    calls: list[dict[str, Any]] = []

    def fake_request(
        client: object,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        del client
        calls.append(
            {
                "method": method,
                "path": path,
                **kwargs,
            },
        )
        if method == "POST" and path == "/sessions/":
            return {"session_id": f"session-{kwargs['json']['agent_id']}"}
        if method == "GET" and path == "/workspace/skill":
            return []
        return {}

    monkeypatch.setattr(
        provision_initialization_agents,
        "_request",
        fake_request,
    )

    for agent_id in ("agent-a", "agent-b"):
        provision_initialization_agents._sync_agent_skills(
            object(),
            token="token",
            agent_id=agent_id,
            skill_names=(
                "read-initialization-attachments",
                "extract-project-basics",
            ),
        )

    session_calls = [
        call
        for call in calls
        if call["method"] == "POST" and call["path"] == "/sessions/"
    ]
    assert [
        call["json"]["workspace_id"]
        for call in session_calls
    ] == [
        "dobby-managed-agent-skills-agent-a",
        "dobby-managed-agent-skills-agent-b",
    ]


def test_skill_sync_removes_only_managed_skill_copies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_skill(tmp_path, "read-initialization-attachments")
    monkeypatch.setattr(
        provision_initialization_agents,
        "SKILL_SOURCE_ROOT",
        tmp_path,
    )
    calls: list[tuple[str, str]] = []

    def fake_request(
        client: object,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        del client, kwargs
        calls.append((method, path))
        if method == "POST" and path == "/sessions/":
            return {"session_id": "session-a"}
        if method == "GET" and path == "/workspace/skill":
            return [
                {"name": "read-initialization-attachments (1)"},
                {"name": "管理员手工技能"},
            ]
        return {}

    monkeypatch.setattr(
        provision_initialization_agents,
        "_request",
        fake_request,
    )

    provision_initialization_agents._sync_agent_skills(
        object(),
        token="token",
        agent_id="agent-a",
        skill_names=("read-initialization-attachments",),
    )

    deleted = [
        path
        for method, path in calls
        if method == "DELETE"
    ]
    assert deleted == [
        "/workspace/skill/read-initialization-attachments%20%281%29",
    ]
    assert all("管理员手工技能" not in path for path in deleted)
