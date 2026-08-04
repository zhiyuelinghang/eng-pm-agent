"""Regression tests for editing skills in a local workspace."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from agentscope.workspace import LocalWorkspace


class LocalWorkspaceSkillUpdateTest(IsolatedAsyncioTestCase):
    """Skill edits must update both SKILL.md and the local skill index."""

    async def test_update_skill_persists_content_and_agent_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source_dir = Path(temp_dir) / "source-skill"
            source_dir.mkdir()
            (source_dir / "SKILL.md").write_text(
                "---\n"
                "name: original\n"
                "description: Original description\n"
                "---\n\n"
                "Old body\n",
                encoding="utf-8",
            )
            workspace = LocalWorkspace(workdir=str(Path(temp_dir) / "workspace"))
            await workspace.add_skill(str(source_dir))

            await workspace.update_skill(
                "original",
                new_name="renamed",
                description="Updated description",
                markdown="# Updated body\n\nNew instructions.",
            )

            skills = await workspace.list_skills()
            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].name, "renamed")
            self.assertEqual(skills[0].description, "Updated description")
            self.assertEqual(
                skills[0].markdown,
                "# Updated body\n\nNew instructions.",
            )

    async def test_update_skill_rejects_duplicate_name(self) -> None:
        with TemporaryDirectory() as temp_dir:
            workspace = LocalWorkspace(workdir=str(Path(temp_dir) / "workspace"))
            for name in ("first", "second"):
                source_dir = Path(temp_dir) / name
                source_dir.mkdir()
                (source_dir / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: {name} description\n---\n",
                    encoding="utf-8",
                )
                await workspace.add_skill(str(source_dir))

            with self.assertRaisesRegex(ValueError, "already exists"):
                await workspace.update_skill(
                    "first",
                    new_name="second",
                    description="Updated description",
                    markdown="Body",
                )
