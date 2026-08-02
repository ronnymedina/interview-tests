"""Rate limiting por IP, en memoria, sin dependencias externas.

Protege el servidor de floods de requests (que no se sature la CPU/BD ni se queme el
presupuesto de Gemini/Azure). Es independiente de la cuota/presupuesto por usuario de
`app/limits/`: aquello acota COSTO por identidad de navegador; esto acota TASA por IP.

Ventana fija por (IP, scope): cada scope tiene su propio tope de requests por ventana.
Estado en memoria del proceso → vale para una sola instancia (el caso del piloto). Si se
escala a varias réplicas, cada una contaría aparte (habría que mover el estado a Redis).
"""

import threading
import time
from collections.abc import Callable

# Cada N hits se barren las entradas cuyo contador ya expiró, para que el dict no crezca
# sin límite ante muchas IPs distintas.
_PRUNE_EVERY = 1000


class IpRateLimiter:
    """Contador de ventana fija por (IP, scope). Thread-safe.

    `limits` mapea scope -> máximo de requests permitidos dentro de `window_seconds`.
    Un scope sin entrada en `limits` no se limita. `now` se inyecta para tests (reloj falso).
    """

    def __init__(
        self,
        limits: dict[str, int],
        window_seconds: int = 60,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = dict(limits)
        self._window = window_seconds
        self._now = now
        self._lock = threading.Lock()
        # (ip, scope) -> (inicio_de_ventana, cuenta)
        self._counters: dict[tuple[str, str], tuple[float, int]] = {}
        self._hits = 0

    def hit(self, ip: str, scope: str) -> int | None:
        """Registra un request. Devuelve None si se permite, o los segundos a esperar si excede.

        Al cruzar la ventana, el contador del par (IP, scope) se reinicia. El valor devuelto
        cuando se bloquea sirve para el header `Retry-After`.
        """
        limit = self._limits.get(scope)
        if limit is None:
            return None

        now = self._now()
        with self._lock:
            self._hits += 1
            if self._hits % _PRUNE_EVERY == 0:
                self._prune(now)

            window_start, count = self._counters.get((ip, scope), (now, 0))
            if now - window_start >= self._window:
                window_start, count = now, 0
            count += 1
            self._counters[(ip, scope)] = (window_start, count)

            if count > limit:
                return max(1, int(self._window - (now - window_start)))
            return None

    def _prune(self, now: float) -> None:
        """Elimina entradas cuya ventana ya expiró (llamado bajo lock)."""
        expired = [
            key for key, (start, _) in self._counters.items() if now - start >= self._window
        ]
        for key in expired:
            del self._counters[key]


def client_ip(request) -> str:
    """IP real del cliente, respetando el proxy de Railway (X-Forwarded-For).

    Detrás de un proxy, `request.client.host` es la IP del proxy; la del cliente viene como
    primer valor de `X-Forwarded-For`. Se usa esa cuando está presente.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
