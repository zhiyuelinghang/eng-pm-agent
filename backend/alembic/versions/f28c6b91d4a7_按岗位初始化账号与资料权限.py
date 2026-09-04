"""按岗位初始化账号与资料权限

Revision ID: f28c6b91d4a7
Revises: a6f4d9c2e810
Create Date: 2026-09-03 15:30:00.000000
"""

from collections.abc import Sequence

from alembic import op


revision: str = "f28c6b91d4a7"
down_revision: str | Sequence[str] | None = "a6f4d9c2e810"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill existing projects with the fixed name-based policy."""

    op.execute(
        """
        UPDATE users AS target
        SET role = CASE
            WHEN LOWER(TRIM(target.username)) = 'admin' THEN 'admin'
            WHEN EXISTS (
                SELECT 1
                FROM project_members AS member
                JOIN project_personnel_assignments AS assignment
                  ON assignment.project_member_id = member.id
                 AND assignment.project_id = member.project_id
                JOIN project_positions AS position
                  ON position.id = assignment.position_id
                 AND position.project_id = assignment.project_id
                WHERE member.user_id = target.id
                  AND TRIM(position.position_name) = '项目经理'
            ) THEN 'admin'
            ELSE 'user'
        END
        """,
    )
    op.execute(
        """
        INSERT INTO engineering_document_sync_states (
            project_id,
            status,
            access_mode,
            revision
        )
        SELECT DISTINCT position.project_id, 'pending', 'restricted', 0
        FROM project_positions AS position
        ON CONFLICT (project_id) DO UPDATE
        SET access_mode = 'restricted'
        """,
    )
    op.execute(
        """
        INSERT INTO engineering_document_permissions (
            project_id,
            node_id,
            subject_type,
            subject_id,
            can_read,
            can_create,
            can_update,
            can_delete,
            can_manage,
            inherit_to_children,
            granted_by_user_id
        )
        SELECT
            node.project_id,
            node.id,
            'position',
            position.id,
            true,
            false,
            false,
            false,
            false,
            true,
            NULL
        FROM engineering_document_nodes AS node
        JOIN project_positions AS position
          ON position.project_id = node.project_id
        WHERE node.node_type = 'knowledge_base'
          AND TRIM(node.name) = 'B_工程知识库'
        ON CONFLICT (project_id, node_id, subject_type, subject_id) DO UPDATE
        SET can_read = true,
            inherit_to_children = true
        """,
    )
    op.execute(
        """
        INSERT INTO engineering_document_permissions (
            project_id,
            node_id,
            subject_type,
            subject_id,
            can_read,
            can_create,
            can_update,
            can_delete,
            can_manage,
            inherit_to_children,
            granted_by_user_id
        )
        SELECT
            node.project_id,
            node.id,
            'position',
            position.id,
            true,
            true,
            true,
            true,
            true,
            true,
            NULL
        FROM engineering_document_nodes AS node
        JOIN project_positions AS position
          ON position.project_id = node.project_id
         AND TRIM(position.position_name) = '项目经理'
        WHERE node.node_type = 'knowledge_base'
        ON CONFLICT (project_id, node_id, subject_type, subject_id) DO UPDATE
        SET can_read = true,
            can_create = true,
            can_update = true,
            can_delete = true,
            can_manage = true,
            inherit_to_children = true
        """,
    )


def downgrade() -> None:
    """Role and grant backfills are intentionally retained on downgrade."""
