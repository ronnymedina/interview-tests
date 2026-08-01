"""Persistencia del uso facturable y de los inicios de conversación.

`UsageStore` es el contrato que consume `LimitsService`: lecturas para decidir (costo del día,
costo total, nº de conversaciones del usuario) y escrituras para registrar (evento de uso,
inicio de conversación). Es un `Protocol` para que el servicio dependa de la interfaz y no del
Postgres concreto: en los tests se inyecta un doble en memoria. El adaptador Postgres
(`PostgresUsageStore`) se agrega en la misma capa.
"""

from typing import Protocol, runtime_checkable


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
