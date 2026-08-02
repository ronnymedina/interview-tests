"""Tests del rate limiter por IP (lógica pura, reloj falso).

Se prueba la ventana fija por (IP, scope): que permita hasta el tope, corte al excederlo,
reinicie al cruzar la ventana, aísle IPs y scopes entre sí, y respete scopes sin límite.
También el parseo de la IP del cliente detrás del proxy (X-Forwarded-For).
"""

from app.ratelimit import IpRateLimiter, client_ip


class FakeClock:
    """Reloj controlable: `advance` mueve el tiempo a voluntad."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _limiter(clock, **limits):
    return IpRateLimiter(limits, window_seconds=60, now=clock)


def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 2})
    assert limiter.hit("1.1.1.1", "global") is None  # 1º permitido
    assert limiter.hit("1.1.1.1", "global") is None  # 2º permitido
    retry = limiter.hit("1.1.1.1", "global")          # 3º excede
    assert retry is not None and retry > 0


def test_window_resets_after_elapsed():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 1})
    assert limiter.hit("1.1.1.1", "global") is None
    assert limiter.hit("1.1.1.1", "global") is not None  # bloqueado dentro de la ventana
    clock.advance(60)                                     # cruza la ventana
    assert limiter.hit("1.1.1.1", "global") is None       # reinició


def test_retry_after_counts_down_within_window():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 1})
    limiter.hit("1.1.1.1", "global")       # consume el único permitido
    clock.advance(20)                       # pasaron 20s de 60
    retry = limiter.hit("1.1.1.1", "global")
    assert retry == 40                      # quedan 40s para reiniciar


def test_ips_are_independent():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 1})
    assert limiter.hit("1.1.1.1", "global") is None
    assert limiter.hit("2.2.2.2", "global") is None  # otra IP no se ve afectada
    assert limiter.hit("1.1.1.1", "global") is not None


def test_scopes_are_independent():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 1, "start": 1})
    assert limiter.hit("1.1.1.1", "global") is None
    assert limiter.hit("1.1.1.1", "start") is None   # scope aparte, su propio contador
    assert limiter.hit("1.1.1.1", "global") is not None


def test_unknown_scope_is_not_limited():
    clock = FakeClock()
    limiter = _limiter(clock, **{"global": 1})
    for _ in range(100):
        assert limiter.hit("1.1.1.1", "sin_limite") is None  # scope sin tope => siempre pasa


def test_client_ip_prefers_forwarded_first_hop():
    class Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}

        class client:
            host = "10.0.0.1"

    assert client_ip(Req()) == "203.0.113.7"


def test_client_ip_falls_back_to_peer():
    class Req:
        headers: dict[str, str] = {}

        class client:
            host = "198.51.100.9"

    assert client_ip(Req()) == "198.51.100.9"


def test_middleware_blocks_when_global_limit_exceeded(monkeypatch):
    """Integración: el middleware corta con 429 + reason 'rate_limited' al pasar el tope.

    Se baja el tope global a 2 y se pega 3 veces a un endpoint barato (el index estático,
    sin BD). El fixture autouse `_reset_rate_limiter` deja el contador limpio al empezar."""
    from fastapi.testclient import TestClient

    from app.cmd import server

    monkeypatch.setitem(server._rate_limiter._limits, "global", 2)
    client = TestClient(server.app)

    assert client.get("/").status_code == 200
    assert client.get("/").status_code == 200
    blocked = client.get("/")
    assert blocked.status_code == 429
    assert blocked.json()["detail"]["reason"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in blocked.headers}
