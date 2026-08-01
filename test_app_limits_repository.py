"""Verifica de forma estructural (sin BD viva) el adaptador Postgres y el DDL del esquema.

Los repositorios Postgres de app/ son adaptadores delgados y no se testean unitariamente
(igual que ConversationRepository); acá se comprueba que el adaptador conforma la interfaz
UsageStore y que el esquema incluye las tablas nuevas.
"""

from app.limits import PostgresUsageStore, build_limits_service
from app.limits.repository import UsageStore
from app.limits.service import LimitsService
from app.storage import PostgresStorage


def test_postgres_store_conforms_to_protocol():
    store = PostgresUsageStore(PostgresStorage("postgresql://x/y"))
    assert isinstance(store, UsageStore)


def test_build_limits_service_returns_service():
    service = build_limits_service(PostgresStorage("postgresql://x/y"))
    assert isinstance(service, LimitsService)


def test_storage_schema_includes_new_tables():
    from app.storage import _SCHEMA

    schema_sql = " ".join(_SCHEMA)
    assert "usage_events" in schema_sql
    assert "conversation_starts" in schema_sql
