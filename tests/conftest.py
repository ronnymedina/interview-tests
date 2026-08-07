"""Configuracion compartida de los tests."""

import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Limpia el contador del rate limiter entre tests para que no se acumulen los hits de
    la IP compartida del TestClient (evita 429 espurios). Solo actúa si el server ya se
    importó; no lo fuerza para no arrastrar sus dependencias a los tests que no lo usan."""
    import sys

    server = sys.modules.get("app.cmd.server")
    if server is not None:
        server._rate_limiter._counters.clear()
        server._rate_limiter._hits = 0
    yield
