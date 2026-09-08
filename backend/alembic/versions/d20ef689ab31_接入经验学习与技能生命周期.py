"""接入经验学习与技能生命周期。"""
import re
from alembic import op
from utils.learning_schema import LEARNING_DDL

revision = "d20ef689ab31"
down_revision = "c9d81a4e7302"
branch_labels = None
depends_on = None


def upgrade():
    for statement in LEARNING_DDL.split(';'):
        if not statement.strip():
            continue
        for table in ('memory_records','learning_events','learning_jobs','learning_feedback','learning_maintenance'):
            statement = re.sub(rf'\b{table}\b',f'memory.{table}',statement)
        op.execute(statement)


def downgrade():
    raise RuntimeError('学习证据和版本记录不可自动删除；回退应用时保留数据。')
