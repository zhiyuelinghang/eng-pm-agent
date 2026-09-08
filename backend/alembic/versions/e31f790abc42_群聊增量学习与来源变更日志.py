"""群聊增量学习与来源变更日志。"""
import re
from alembic import op
from utils.group_learning_schema import GROUP_LEARNING_DDL

revision = 'e31f790abc42'
down_revision = 'd20ef689ab31'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != 'postgresql':
        return
    for statement in GROUP_LEARNING_DDL.split(';'):
        if statement.strip():
            for table in ('memory_records', 'learning_events', 'group_learning_cursors', 'group_learning_batches', 'group_learning_sources'):
                statement = re.sub(rf'\b{table}\b', f'memory.{table}', statement)
            op.execute(statement)
    schema = connection.exec_driver_sql('SELECT current_schema()').scalar_one()
    quoted = connection.dialect.identifier_preparer.quote(schema)
    op.execute('''CREATE TABLE group_learning_source_clocks (
        channel_id bigint PRIMARY KEY, revision bigint NOT NULL DEFAULT 0,
        policy_revision bigint NOT NULL DEFAULT 0, changed_at timestamptz NOT NULL DEFAULT now())''')
    op.execute('''CREATE TABLE group_learning_source_changes (
        channel_id bigint NOT NULL, revision bigint NOT NULL, message_id bigint,
        kind text NOT NULL, audience jsonb NOT NULL DEFAULT '[]'::jsonb,
        project_shared boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(channel_id,revision))''')
    op.execute('CREATE INDEX ix_group_learning_changed_message ON group_learning_source_changes(channel_id,message_id,revision DESC) WHERE message_id IS NOT NULL')
    op.execute(f'''CREATE FUNCTION group_learning_note(cid bigint, mid bigint, change_kind text)
        RETURNS void LANGUAGE plpgsql SET search_path TO {quoted}, public AS $$
        DECLARE seq bigint; shared boolean; recipients jsonb;
        BEGIN
            INSERT INTO group_learning_source_clocks(channel_id) VALUES(cid) ON CONFLICT DO NOTHING;
            UPDATE group_learning_source_clocks SET revision=revision+1,
                policy_revision=policy_revision+CASE WHEN change_kind='policy' THEN 1 ELSE 0 END,
                changed_at=clock_timestamp() WHERE channel_id=cid RETURNING revision INTO seq;
            SELECT coalesce(auto_sync_members,channel_type IN ('project','topic')) AND archived_at IS NULL
                INTO shared FROM chat_channels WHERE id=cid;
            SELECT coalesce(jsonb_agg(p.user_id ORDER BY p.user_id),'[]'::jsonb) INTO recipients
                FROM project_members p JOIN chat_channels c ON c.project_id=p.project_id
                WHERE c.id=cid AND (shared OR EXISTS(SELECT 1 FROM chat_channel_members m
                    WHERE m.channel_id=cid AND m.user_id=p.user_id AND m.left_at IS NULL));
            INSERT INTO group_learning_source_changes(channel_id,revision,message_id,kind,audience,project_shared)
                VALUES(cid,seq,mid,change_kind,recipients,coalesce(shared,false));
        END $$''')
    op.execute(f'''CREATE FUNCTION group_learning_message_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO {quoted}, public AS $$ BEGIN
            IF TG_OP='UPDATE' AND NEW.content IS NOT DISTINCT FROM OLD.content
                AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at
                AND NEW.edited_at IS NOT DISTINCT FROM OLD.edited_at THEN RETURN NEW; END IF;
            IF TG_OP='DELETE' THEN
                PERFORM group_learning_note(OLD.channel_id,OLD.id,'message'); RETURN OLD;
            END IF;
            PERFORM group_learning_note(NEW.channel_id,NEW.id,'message'); RETURN NEW;
        END $$''')
    op.execute('''CREATE TRIGGER group_learning_message AFTER INSERT OR UPDATE OR DELETE ON chat_messages
        FOR EACH ROW EXECUTE FUNCTION group_learning_message_change()''')
    op.execute(f'''CREATE FUNCTION group_learning_policy_change() RETURNS trigger
        LANGUAGE plpgsql SET search_path TO {quoted}, public AS $$ DECLARE cid bigint; pid bigint; BEGIN
            IF TG_TABLE_NAME='chat_channels' THEN
                IF TG_OP='UPDATE' AND NEW.auto_sync_members IS NOT DISTINCT FROM OLD.auto_sync_members
                    AND NEW.channel_type=OLD.channel_type AND NEW.archived_at IS NOT DISTINCT FROM OLD.archived_at
                    AND NEW.membership_revision=OLD.membership_revision THEN RETURN NEW; END IF;
                cid=CASE WHEN TG_OP='DELETE' THEN OLD.id ELSE NEW.id END;
                PERFORM group_learning_note(cid,NULL,'policy');
            ELSIF TG_TABLE_NAME='chat_channel_members' THEN
                IF TG_OP='UPDATE' AND NEW.left_at IS NOT DISTINCT FROM OLD.left_at AND NEW.user_id=OLD.user_id THEN RETURN NEW; END IF;
                cid=CASE WHEN TG_OP='DELETE' THEN OLD.channel_id ELSE NEW.channel_id END;
                PERFORM group_learning_note(cid,NULL,'policy');
            ELSE
                pid=CASE WHEN TG_OP='DELETE' THEN OLD.project_id ELSE NEW.project_id END;
                FOR cid IN SELECT id FROM chat_channels WHERE project_id=pid ORDER BY id LOOP
                    PERFORM group_learning_note(cid,NULL,'policy');
                END LOOP;
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$''')
    for table in ('chat_channels', 'chat_channel_members', 'project_members'):
        op.execute(f'''CREATE TRIGGER group_learning_policy AFTER INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION group_learning_policy_change()''')


def downgrade():
    raise RuntimeError('增量游标与来源证据不可自动删除；回退应用时保留数据。')
