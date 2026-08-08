"""Verifica de forma estructural (sin BD viva) el adaptador Postgres.

Los repositorios Postgres de app/ son adaptadores delgados y no se testean unitariamente;
acá se comprueba que el adaptador conforma la interfaz UsageStore.
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
