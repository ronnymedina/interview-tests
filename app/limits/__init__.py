"""Módulo de límites del piloto: costo, cuota por usuario y presupuesto diario/total.

Expone el servicio inyectable y su construcción desde el almacenamiento. La lógica de decisión
vive en service.py; el cálculo de costo en cost.py; la persistencia en repository.py.
"""

from app.limits.model import Decision, DecisionKind
from app.limits.repository import PostgresUsageStore, UsageStore
from app.limits.service import LimitsService
from app.storage import PostgresStorage

__all__ = [
    "Decision",
    "DecisionKind",
    "LimitsService",
    "PostgresUsageStore",
    "UsageStore",
    "build_limits_service",
]


def build_limits_service(storage: PostgresStorage) -> LimitsService:
    """Arma el LimitsService con el adaptador Postgres sobre el almacenamiento compartido.

    A diferencia de speech/conversación, limits NO degrada a None: si Postgres está caído, la
    decisión conservadora (cortar) la toma la Fase 3 al fallar la consulta. Acá solo se compone.
    """
    return LimitsService(PostgresUsageStore(storage))
