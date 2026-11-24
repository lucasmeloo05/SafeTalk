"""Complete migration functions run inside a rolled-back isolated schema."""
from uuid import uuid4
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from app.database import Base
from conftest import test_engine

def test_full_migration_chain_upgrade_downgrade_upgrade_matches_models():
    schema = "chain_integration_" + uuid4().hex
    scripts = ScriptDirectory("migrations")
    assert scripts.get_heads() == ["e21b7c84a603"]
    steps = list(scripts.walk_revisions())
    with test_engine.connect() as db:
        db.execute(text(f"CREATE SCHEMA {schema}"))
        db.execute(text(f"SET LOCAL search_path TO {schema}"))
        with Operations.context(MigrationContext.configure(db)):
            for step in reversed(steps):
                step.module.upgrade()
            inspector = inspect(db)
            assert set(inspector.get_table_names(schema=schema)) == set(Base.metadata.tables)
            for table in Base.metadata.sorted_tables:
                actual = {column["name"] for column in inspector.get_columns(table.name, schema=schema)}
                assert actual == set(table.columns.keys()), table.name
            for step in steps:
                step.module.downgrade()
            assert inspect(db).get_table_names(schema=schema) == []
            for step in reversed(steps):
                step.module.upgrade()
            assert set(inspect(db).get_table_names(schema=schema)) == set(Base.metadata.tables)
