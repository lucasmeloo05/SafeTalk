from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import text

from conftest import test_engine


def test_existing_channel_stays_writable_and_upgrade_is_repeatable():
    # The dedicated test connection rolls back even the schema creation.
    schema = "channel_migration_" + uuid4().hex
    scripts = ScriptDirectory("migrations")
    target = scripts.get_revision("b241de8f753a")
    with test_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"SET LOCAL search_path TO {schema}"))
        with Operations.context(MigrationContext.configure(conn)):
            for step in reversed(list(scripts.iterate_revisions(target.down_revision, "base"))):
                step.module.upgrade()
            conn.execute(text("INSERT INTO users (username,email,password_hash,is_active,is_verified) "
                              "VALUES ('fixture','fixture@example.test','unused',true,false)"))
            conn.execute(text("INSERT INTO servers (owner_id,name,is_adult,ai_moderation_enabled,is_discoverable) "
                              "VALUES (1,'demo',false,false,false)"))
            conn.execute(text("INSERT INTO server_channels (server_id,name,channel_type,position) "
                              "VALUES (1,'geral','TEXT',0)"))
            target.module.upgrade()
            assert conn.execute(text("SELECT c.is_read_only,c.is_archived,t.type FROM server_channels c "
                                     "JOIN conversations t ON t.channel_id=c.id")).one() == (False, False, "CHANNEL")
            target.module.downgrade()
            assert conn.scalar(text("SELECT name FROM server_channels")) == "geral"
            target.module.upgrade()
            assert conn.scalar(text("SELECT count(*) FROM conversations WHERE type='CHANNEL'")) == 1
