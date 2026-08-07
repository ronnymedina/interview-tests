"""Servicio de límites: decide la admisión de una conversación y registra el uso.

Compone las lecturas del `UsageStore` con los presupuestos/cuota de `config` para producir una
`Decision`, y ofrece helpers que calculan el costo (vía app/limits/cost) y lo persisten como
evento. Depende de la interfaz `UsageStore`, no del Postgres concreto, así su lógica se prueba
con un doble en memoria. La construcción real (`build_limits_service`) vive en __init__.py.
"""

from app.limits.cost import azure_cost_usd, gemini_cost_usd
from app.limits.model import Decision, DecisionKind
from app.limits.repository import UsageStore
from config import settings


class LimitsService:
    """Aplica cuota por usuario y presupuesto diario/total sobre eventos persistidos."""

    def __init__(self, store: UsageStore) -> None:
        self._store = store

    def check_can_start(self, user_id: str) -> Decision:
        """Decide si `user_id` puede iniciar una conversación.

        Precedencia: tope total → presupuesto diario → cuota del usuario → permitir. El
        presupuesto global protege el costo por encima de la cuota individual.
        """
        if self._store.total_cost_usd() >= settings.TOTAL_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_TOTAL)
        if self._store.daily_cost_usd() >= settings.DAILY_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_DAILY)
        if self._store.conversation_count(user_id) >= settings.USER_CONVERSATION_QUOTA:
            return Decision(DecisionKind.QUOTA)
        return Decision(DecisionKind.ALLOW)

    def check_can_read(self, user_id: str) -> Decision:
        """Decide si `user_id` puede evaluar una lectura.

        Misma precedencia que `check_can_start` (tope total → presupuesto diario → cuota),
        pero contra el contador de lecturas. El presupuesto en dólares es el mismo para las
        dos modalidades porque el dinero es uno solo; la cuota es distinta porque leer y
        conversar son prácticas separadas y gastar una con la otra sería confuso.
        """
        if self._store.total_cost_usd() >= settings.TOTAL_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_TOTAL)
        if self._store.daily_cost_usd() >= settings.DAILY_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_DAILY)
        if self._store.reading_count(user_id) >= settings.USER_READING_QUOTA:
            return Decision(DecisionKind.QUOTA)
        return Decision(DecisionKind.ALLOW)

    def record_conversation_start(self, user_id: str, conversation_id: str) -> None:
        """Registra el inicio de una conversación (cuenta para la cuota del usuario)."""
        self._store.add_conversation_start(user_id, conversation_id)

    def record_reading_start(self, user_id: str, reading_id: int) -> None:
        """Registra una evaluación de lectura (cuenta para la cuota de lectura)."""
        self._store.add_reading_start(user_id, reading_id)

    def record_gemini_usage(
        self,
        user_id: str,
        conversation_id: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calcula y persiste el costo de una llamada a Gemini. Devuelve el costo en USD."""
        cost = gemini_cost_usd(input_tokens, output_tokens)
        self._store.add_usage_event(
            user_id, conversation_id, "gemini", kind,
            input_tokens, output_tokens, 0.0, cost,
        )
        return cost

    def record_azure_usage(
        self,
        user_id: str,
        conversation_id: str,
        audio_seconds: float,
        kind: str = "assessment",
    ) -> float:
        """Calcula y persiste el costo de la evaluación de Azure. Devuelve el costo en USD.

        `kind` distingue la modalidad que gastó ("assessment" en la conversación,
        "reading_assessment" en la lectura), para poder separar costos por modalidad sin
        tener que cruzar `usage_events` contra otra tabla.
        """
        cost = azure_cost_usd(audio_seconds)
        self._store.add_usage_event(
            user_id, conversation_id, "azure", kind,
            0, 0, audio_seconds, cost,
        )
        return cost
