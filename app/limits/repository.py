"""Persistencia del uso facturable y de los inicios de conversación.

`UsageStore` es el contrato que consume `LimitsService`: lecturas para decidir (costo del día,
costo total, nº de conversaciones del usuario) y escrituras para registrar (evento de uso,
inicio de conversación). Es un `Protocol` para que el servicio dependa de la interfaz y no del
Postgres concreto: en los tests se inyecta un doble en memoria. El adaptador Postgres
(`PostgresUsageStore`) se agrega en la misma capa.
"""

from typing import Protocol, runtime_checkable

from app.storage import PostgresStorage


@runtime_checkable
class UsageStore(Protocol):
    """Contrato de persistencia que necesita LimitsService."""

    def add_conversation_start(self, user_id: str, conversation_id: str) -> None:
        """Registra que un usuario inició una conversación (para la cuota)."""
        ...

    def add_usage_event(
        self,
        user_id: str,
        conversation_id: str,
        provider: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
        audio_seconds: float,
        cost_usd: float,
    ) -> None:
        """Registra una llamada facturable con su costo ya calculado."""
        ...

    def daily_cost_usd(self) -> float:
        """Suma del costo de los eventos de hoy (fecha del servidor)."""
        ...

    def total_cost_usd(self) -> float:
        """Suma del costo de todos los eventos."""
        ...

    def conversation_count(self, user_id: str) -> int:
        """Número de conversaciones iniciadas por ese usuario."""
        ...


class PostgresUsageStore:
    """Adaptador Postgres de UsageStore. Aísla el SQL; recibe el almacenamiento inyectado.

    Sigue el mismo patrón que ConversationRepository: abre una conexión nueva por operación
    vía `storage.connect()` y no crea la tabla (eso lo hace `PostgresStorage.init_schema()` o
    el init del contenedor). `created_at` lo pone Postgres por DEFAULT now().
    """

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    def add_conversation_start(self, user_id: str, conversation_id: str) -> None:
        with self._storage.connect() as conn:
            conn.execute(
                "INSERT INTO conversation_starts (user_id, conversation_id) VALUES (%s, %s)",
                (user_id, conversation_id),
            )

    def add_usage_event(
        self,
        user_id: str,
        conversation_id: str,
        provider: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
        audio_seconds: float,
        cost_usd: float,
    ) -> None:
        with self._storage.connect() as conn:
            conn.execute(
                "INSERT INTO usage_events "
                "(user_id, conversation_id, provider, kind, input_tokens, output_tokens, "
                "audio_seconds, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, conversation_id, provider, kind, input_tokens, output_tokens,
                 audio_seconds, cost_usd),
            )

    def daily_cost_usd(self) -> float:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_events "
                "WHERE created_at::date = CURRENT_DATE"
            ).fetchone()
        assert row is not None  # COALESCE + agregado sin GROUP BY siempre devuelve una fila
        return float(row["total"])

    def total_cost_usd(self) -> float:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_events"
            ).fetchone()
        assert row is not None
        return float(row["total"])

    def conversation_count(self, user_id: str) -> int:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_starts WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        assert row is not None
        return int(row["n"])
