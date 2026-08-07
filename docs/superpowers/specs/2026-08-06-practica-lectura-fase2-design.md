# Práctica de lectura — fase 2: pantalla, endpoints y evaluación scripted

Fecha: 2026-08-06
Estado: aprobado, pendiente de plan de implementación

Continúa [2026-08-06-practica-lectura-design.md](2026-08-06-practica-lectura-design.md), cuya
fase 1 (tabla `reading_texts`, plantillas Jinja2, `shared.js`) y cuya ingesta desde Engoo ya
están en `main`. Este documento cubre lo que falta para que la práctica de lectura funcione de
punta a punta.

## Objetivo

El usuario abre la práctica de lectura, recibe un texto real del catálogo, lo lee en voz alta
y Azure evalúa su pronunciación **contra ese texto**. La pantalla es la del boceto: dos
paneles lado a lado, el izquierdo con el texto de referencia y el derecho con lo que va
diciendo el usuario, que al terminar se convierte en el review.

## Alcance

Entra: `excerpt.py`, `random()` en el repositorio, `service.py`, `assess_scripted` en
`app/speech`, los endpoints `GET /reading/random` y `POST /reading/assess`, la tabla
`reading_starts`, la pantalla `/reading`, y la configuración nueva.

No entra: el texto se entrega **al azar**. No hay catálogo navegable, ni buscador, ni
paginación, ni filtro por nivel — el usuario recibe un texto y puede pedir otro. También
sigue fuera RAG / búsqueda semántica y cualquier fuente distinta de Engoo.

## Decisiones y sus razones

**El extracto no se guarda en ninguna parte: se recalcula.** El diseño de la fase 1 proponía
una caché en memoria `reading_id → excerpt` con TTL, para que al llegar el audio el servidor
supiera contra qué texto evaluar. Sobra. El cliente recibe el `reading_id` junto con el
extracto y lo devuelve al subir el audio; con ese id el servidor relee la fila y vuelve a
cortar. `make_excerpt(body, max_words)` es determinista, así que el resultado es idéntico al
que se mostró.

Lo que se evita al no cachear: un diccionario en memoria muere en cada redeploy — y el
usuario que estaba grabando recibiría un "sesión vencida" incomprensible —, no se comparte si
algún día hay más de un worker, y obliga a elegir un TTL a ojo.

**El cliente nunca manda el `reference_text`.** Si lo mandara, cualquiera podría evaluar un
audio de "hello" contra un `reference_text` de "hello" y sacar 100. Manda solo el
`reading_id`; el texto lo pone el servidor. Este era el objetivo real de la caché, y se
cumple igual sin ella.

**Ventana de desincronización, aceptada.** Si el job de ingesta actualizara el `body` entre
que el usuario abre la pantalla y sube el audio, evaluaría contra un texto ligeramente
distinto. La ingesta corre cada 24 h y la ventana es de minutos; el peor caso es un score
raro en un intento. No justifica introducir estado.

**La selección al azar no cuenta filas.** `SELECT ... ORDER BY random() LIMIT 1` resuelve en
una consulta. Es un escaneo completo, pero el catálogo son decenas o pocos cientos de filas
(`READING_INGEST_MAX_ARTICLES` = 60 por corrida). Si algún día crece a decenas de miles, se
cambia por `TABLESAMPLE`; hoy sería optimización prematura.

**La cuota se cobra al evaluar, no al pedir el texto.** Evaluar es lo que cuesta dinero.
`GET /reading/random` sí consulta el estado de los límites, pero solo para avisar temprano si
el presupuesto está agotado, sin consumir nada.

**Cuota propia, presupuesto compartido.** `USER_READING_QUOTA` es independiente de
`USER_CONVERSATION_QUOTA`: leer no debe gastarte las conversaciones, son modalidades
distintas y mezclarlas sería confuso. Pero el costo de Azure entra al mismo presupuesto
diario y total, y respeta la pausa, porque el dinero es uno solo.

**La evaluación usa el modo scripted de Azure.** Mandar el extracto como `reference_text`
habilita `completeness` y el miscue (palabras omitidas, insertadas y mal pronunciadas contra
el texto real). Es exactamente la señal que importa al leer, y el modo unscripted que usa
hoy la conversación no puede darla.

## Esquema

```sql
CREATE TABLE IF NOT EXISTS reading_starts (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id    TEXT NOT NULL,
    reading_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS reading_starts_user_idx ON reading_starts (user_id);
```

Espejo de `conversation_starts`: una fila por evaluación, sin contenido — ni el audio ni el
resultado del assessment se persisten. Sirve solo para contar la cuota del usuario, y el
índice por `user_id` es lo que hace barato ese conteo.

No hay FK a `reading_texts`: si un artículo desapareciera del catálogo, borrar el registro de
cuota que ya se cobró sería incorrecto.

El DDL va **a la vez** en `app/storage.py` (`_SCHEMA`) y en un `docker/initdb/05-*.sql`
nuevo, o las dos copias divergen. La tercera copia, informativa, está en el docstring de
`app/conversation/repository.py`.

## Arquitectura

Se completa `app/reading/`:

| Archivo | Responsabilidad |
|---|---|
| `excerpt.py` | `make_excerpt(body, max_words)`. Función pura, sin dependencias, corta en límite de oración |
| `repository.py` | Se le suma `random()` al `Protocol` y al adaptador Postgres |
| `service.py` | `random_excerpt()` y `assess(user_id, reading_id, wav_path)`. Orquesta repositorio + límites + speech |

`make_excerpt` recorre las oraciones del cuerpo acumulando palabras y se detiene antes de
pasar `max_words`; si la primera oración ya excede el límite, corta en la última palabra
completa que quepa. Nunca parte una palabra por la mitad.

**Actualización (pulido posterior):** `make_excerpt` devuelve un prefijo literal del cuerpo en
vez de un texto reconstruido, para conservar los saltos de párrafo del artículo. Sigue siendo
determinista, así que la decisión de no cachear el extracto se mantiene intacta. Ver
[2026-08-06-pulido-lectura-y-voces-design.md](2026-08-06-pulido-lectura-y-voces-design.md).

En `app/speech/assessment.py` se agrega `assess_scripted(wav_path, reference_text)`, migrado
de `speech.py` del legacy. Es la misma llamada que ya existe más
`PronunciationAssessmentConfig(reference_text=...)` y `enable_miscue`.

**Asincronía.** `app/reading` usa `AsyncPostgresStorage`, así que los endpoints de lectura son
`async def` — a diferencia de los de conversación, que son `def` y FastAPI corre en su
threadpool. Dentro de un endpoint `async`, dos cosas bloqueantes deben ir en
`asyncio.to_thread`: las llamadas al SDK de Azure y las llamadas a `LimitsService`, que hoy es
síncrono porque usa `PostgresStorage`. Llamar a `LimitsService` directamente desde el event
loop bloquearía a todos los demás usuarios durante la consulta.

## Endpoints

`GET /reading/random` → `{reading_id, title, level, source_url, excerpt, word_count}`.
Toma una fila al azar y calcula el extracto al servir. Consulta el estado de los límites para
avisar temprano, pero no consume cuota. Catálogo vacío → 503.

`POST /reading/assess` (multipart: `reading_id` + `audio` WAV) → scores, palabras y miscue.
Relee la fila por id, recorta el mismo extracto y lo manda a Azure como `reference_text`. Acá
sí se espera el resultado de Azure: es la respuesta, no un agregado en background. Registra la
cuota en `reading_starts` y el costo en `usage_events` con `kind="reading_assessment"`.

Ambos aplican `RATE_LIMIT_READING_PER_MIN` por IP, con el middleware que ya existe.

## Frontend

`templates/reading.html` hereda de `base.html`, servida en `GET /reading`. En `base.html` se
agrega la navegación entre la conversación (`/`) y la lectura (`/reading`).

Tres estados:

1. **Listo** — izquierda el extracto; derecha vacía con el botón de grabar. Arriba, título,
   badge de nivel y enlace al artículo original. Un botón "Otro texto" pide otro al azar.
2. **Hablando** — la derecha se llena con la transcripción del reconocimiento del navegador,
   en vivo. No toca la red ni cuesta nada.
3. **Review** — la derecha pasa a mostrar el resultado de Azure con las palabras coloreadas
   por accuracy; la izquierda marca sobre el texto real las omisiones y las inserciones;
   arriba la fila de scores, incluido `completeness`, que solo existe en modo scripted.

De `shared.js` se reusan la captura de audio, el encode WAV, el reconocimiento del navegador,
la gestión de `X-User-Id` y el render de palabras coloreadas. Lo propio de esta pantalla —los
dos paneles, el diff contra el texto real— va en un `reading.js` aparte, para no engordar
`shared.js` con lógica que la conversación no usa.

## Configuración

Nuevas, todas declaradas y leídas **solo** en `config.py`, con default:

- `READING_MAX_WORDS` (120) — tamaño del extracto, ~40-60 s de lectura.
- `USER_READING_QUOTA` (10) — evaluaciones por usuario.
- `RATE_LIMIT_READING_PER_MIN` (20) — peticiones por IP, en línea con
  `RATE_LIMIT_ANSWER_PER_MIN`, que cubre una operación equivalente.

Las demás `READING_*` ya existen desde la ingesta.

## Errores

Cada fallo degrada sin tumbar el resto:

| Situación | Respuesta |
|---|---|
| Catálogo vacío | 503, con mensaje explícito de que hay que correr la ingesta |
| `reading_id` inexistente | 404 |
| Azure cancelado | 502 |
| Sin voz detectada en el audio | 422 |
| Cuota o presupuesto agotados | 429 con motivo tipado, igual que la conversación |

## Pruebas

Ningún test toca la red ni levanta una base.

- `make_excerpt` con Hypothesis (ya es dependencia): nunca excede `max_words`, nunca parte una
  palabra, y termina en fin de oración siempre que haya una que quepa.
- `random()` del repositorio contra el doble en memoria que ya usa la ingesta, extendido.
- Los endpoints con `TestClient` inyectando servicios falsos, siguiendo el patrón de
  `test_app_speech_assessment.py`. Incluye el caso que importa: que un `reference_text`
  enviado por el cliente se ignore.
