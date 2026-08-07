"""Value object de la decisión de admisión de una conversación nueva.

`LimitsService.check_can_start` devuelve un `Decision`. El `kind` distingue los cuatro casos
internos (para log/diagnóstico); `reason` los colapsa a lo que necesita el frontend: los dos
tipos de pausa comparten el banner neutro "paused" y la cuota del usuario es "quota".
"""

import enum
from dataclasses import dataclass


# ruff sugiere enum.StrEnum (UP042), pero no es un cambio cosmético: con `str, Enum`,
# `str(DecisionKind.ALLOW)` da "DecisionKind.ALLOW" y con StrEnum da "allow". Migrar
# requiere revisar cada punto donde el kind se serializa o se loguea; no entra en un
# cambio de linting.
class DecisionKind(str, enum.Enum):  # noqa: UP042
    ALLOW = "allow"
    QUOTA = "quota"
    PAUSED_DAILY = "paused_daily"
    PAUSED_TOTAL = "paused_total"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW

    @property
    def reason(self) -> str | None:
        """Motivo para el frontend: None si se permite, 'quota' o 'paused' si no."""
        if self.kind is DecisionKind.ALLOW:
            return None
        if self.kind is DecisionKind.QUOTA:
            return "quota"
        return "paused"  # PAUSED_DAILY y PAUSED_TOTAL comparten banner neutro
