"""Repositorio de configuraciones de conversación (tabla `conversation_configs`).

Aísla el SQL: el resto del código crea, edita, lista y borra configuraciones
llamando métodos tipados, sin escribir sentencias SQL a mano. Recibe el
almacenamiento por inyección de dependencia (constructor), así no sabe dónde
vive la base ni cómo se conecta. NO crea ni migra la tabla; asume que
`conversation_configs` ya existe (eso es un paso posterior).

Solo persiste lo DINÁMICO de cada conversación: el `user_context` del alumno.
Los candados/guardarraíles base son fijos y viven en el código (versionados),
no en esta tabla; se ensamblan con el `user_context` al armar el SystemMessage.

Esquema objetivo de la tabla (referencia, no se ejecuta desde acá; lo crea el
script de init del contenedor Postgres o `PostgresStorage.init_schema()`):

    CREATE TABLE conversation_configs (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        name         TEXT NOT NULL,
        user_context TEXT NOT NULL    -- contexto editable del usuario
    );
"""

from datetime import UTC, datetime
from typing import Any

from app.conversation.model import ConversationConfig
from app.storage import PostgresStorage

# Columnas que devuelve cada SELECT, en el orden en que las lee `_row_to_config`.
_COLUMNS = "id, created_at, updated_at, name, user_context"


def _now() -> str:
    """Timestamp UTC en ISO-8601 con precisión de segundos, como el resto del proyecto."""
    return datetime.now(UTC).isoformat(timespec="seconds")


class ConversationRepository:
    """CRUD de `conversation_configs`. Recibe el almacenamiento por inyección de dependencia."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    @staticmethod
    def _row_to_config(row: dict[str, Any]) -> ConversationConfig:
        return ConversationConfig(
            id=row["id"],
            name=row["name"],
            user_context=row["user_context"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create(self, name: str, user_context: str) -> ConversationConfig:
        """Inserta una configuración nueva y devuelve la fila creada (con id y timestamps)."""
        now = _now()
        with self._storage.connect() as conn:
            row = conn.execute(
                "INSERT INTO conversation_configs (created_at, updated_at, name, user_context) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (now, now, name, user_context),
            ).fetchone()
            # RETURNING id siempre devuelve la fila recién insertada.
            assert row is not None
            config_id = row["id"]
        return ConversationConfig(
            id=config_id,
            name=name,
            user_context=user_context,
            created_at=now,
            updated_at=now,
        )

    def get(self, config_id: int) -> ConversationConfig | None:
        """Devuelve la configuración con ese id, o None si no existe."""
        with self._storage.connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM conversation_configs WHERE id = %s",
                (config_id,),
            ).fetchone()
        return self._row_to_config(row) if row else None

    def list(self) -> list[ConversationConfig]:
        """Devuelve todas las configuraciones, de la más reciente a la más antigua."""
        with self._storage.connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM conversation_configs ORDER BY id DESC"
            ).fetchall()
        return [self._row_to_config(row) for row in rows]

    def update(self, config_id: int, name: str, user_context: str) -> ConversationConfig | None:
        """Actualiza la configuración y refresca `updated_at`.

        Devuelve la fila actualizada, o None si no existía ninguna con ese id.
        """
        now = _now()
        with self._storage.connect() as conn:
            cursor = conn.execute(
                "UPDATE conversation_configs SET name = %s, user_context = %s, updated_at = %s "
                "WHERE id = %s",
                (name, user_context, now, config_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(config_id)

    def delete(self, config_id: int) -> None:
        """Borra la configuración con ese id. No falla si no existe."""
        with self._storage.connect() as conn:
            conn.execute("DELETE FROM conversation_configs WHERE id = %s", (config_id,))
