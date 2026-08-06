# Práctica de lectura (reading) — diseño

Fecha: 2026-08-06
Estado: aprobado, pendiente de plan de implementación

## Objetivo

Migrar a `app/` la práctica de pronunciación sobre un texto de referencia que existe en el
legacy (raíz del repo), con una diferencia central: el usuario ya no escribe ni guarda su
propio texto. La app le ofrece un texto real obtenido de una fuente externa (Engoo Daily
News), él lo lee en voz alta, y Azure evalúa la pronunciación **contra ese texto**.

La pantalla es la del boceto: dos paneles lado a lado, el izquierdo con el texto de
referencia y el derecho con lo que va diciendo el usuario, que al terminar se convierte en
el review.

## Alcance por fases

### Fase 1 — este entregable

1. Tabla `reading_texts` en el esquema.
2. Plantillas Jinja2 (`base.html` + migración de la página actual).
3. Extracción del JavaScript común a `shared.js`.

No hay scraping, ni endpoints de lectura, ni pantalla nueva en esta fase. El catálogo se
puede poblar a mano por SQL para probar.

### Fase 2 — siguiente

Script de ingesta desde Engoo, job periódico, endpoints `/reading/random` y
`/reading/assess`, pantalla de lectura, y `assess_scripted` en `app/speech`.

### Fuera de alcance (por ahora)

- RAG / búsqueda semántica sobre los textos. Se decidió posponerlo hasta tener la
  arquitectura y datos cargados. Cuando llegue, se resuelve con `pgvector` sobre la misma
  tabla (columna `embedding`), no con BigQuery: el costo de almacenamiento en BigQuery es
  despreciable a esta escala, pero es un almacén analítico, con latencia de ~1 s y sin
  lookups puntuales baratos — herramienta equivocada para servir un texto al azar.
- Fuentes adicionales además de Engoo.
- Limpieza de `conversation_configs` (única tabla sin uso real; se deja como está por
  decisión explícita).

## Decisiones y sus razones

**El catálogo vive en Postgres, poblado por un job periódico; no se scrapea en vivo.**
Scrapear en cada clic haría que cada usuario pague latencia y consuma recursos del sitio
externo para obtener el mismo contenido. Con el catálogo en BD, una caída o un cambio de
HTML en la fuente degrada a "textos algo viejos" en vez de a "feature caída".

**Se guarda el artículo completo e intacto.** El recorte a un extracto legible en ~40-60 s
se calcula al servir, nunca al ingerir. Así, funcionalidades futuras (un plan de mejora
sobre el texto entero, RAG) tienen el dato completo disponible sin re-scrapear.

**El intento de lectura no se persiste.** Ni el audio ni el resultado del assessment se
guardan. Lo único que queda registrado es la contabilidad: el costo en `usage_events` (que
ya existe) y una fila de cuota en `reading_starts`; ninguna de las dos guarda contenido.

**La evaluación usa el modo scripted de Azure.** Mandar el extracto como `reference_text`
habilita `completeness` y el miscue (palabras omitidas, insertadas y mal pronunciadas
contra el texto real), que es exactamente la señal que importa al leer y que el modo
unscripted actual no puede dar.

**Cuota propia, presupuesto compartido.** La lectura no consume las conversaciones del
usuario (son modalidades distintas y sería confuso), pero su costo de Azure sí entra al
mismo presupuesto diario/total y respeta la pausa.

**Jinja2 además de `shared.js`.** Resuelven duplicaciones distintas: Jinja el esqueleto
HTML compartido, `shared.js` la lógica de captura de audio. Con más modalidades previstas,
conviene migrar ahora que hay una sola página que mover.

## Esquema

```sql
CREATE TABLE IF NOT EXISTS reading_texts (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL,
    source_url   TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    level        INTEGER,
    category     TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);
```

Razones de los campos:

- `source_url UNIQUE` es la clave natural: permite `INSERT ... ON CONFLICT DO UPDATE`, y
  con eso el job de ingesta es idempotente.
- `source` existe desde el inicio aunque hoy solo valga `'engoo'`: sumar una segunda
  fuente después no requiere migración.
- `level` es nullable a propósito. "No conozco el nivel" y "nivel 0" son cosas distintas;
  un cero inventado ensuciaría el filtro por rango. El índice evita escanear la tabla
  entera cuando crezca.
- `body` guarda el artículo completo. El extracto se deriva al servir.
- `updated_at` permite ver si el job refrescó un artículo en su última corrida, sin leer
  logs.
- No hay `word_count`: se deriva de `body`, y un campo derivado persistido es un campo que
  puede desincronizarse.

La tabla `reading_starts` (espejo de `conversation_starts`, para la cuota por usuario)
llega en la fase 2, junto con los endpoints que la escriben.

**Atención:** el DDL está hoy duplicado en `app/storage.py` (`_SCHEMA`) y en
`docker/initdb/*.sql`. `reading_texts` debe agregarse a los dos, o divergen. Hay una
tercera copia, informativa, en el docstring de `app/conversation/repository.py:16`.

## Arquitectura (fase 2)

Módulo `app/reading/`, con el scraping aislado para que cambiar de fuente no toque nada más:

| Archivo | Responsabilidad |
|---|---|
| `model.py` | `ReadingText` |
| `sources/engoo.py` | Único lugar que conoce Engoo: `httpx.AsyncClient` + parseo del SSR. Implementa un `Protocol ReadingSource` |
| `repository.py` | `upsert_many()` idempotente y `random(min_level, max_level)` |
| `excerpt.py` | `make_excerpt(body, max_words)`, función pura, corta en límite de oración |
| `ingest.py` | Orquesta fuentes → repositorio. Ejecutable: `python -m app.reading.ingest` |
| `scheduler.py` | Tarea asyncio en el `lifespan`: ingesta al arrancar si la tabla está vacía, luego cada N horas |
| `service.py` | `random_excerpt()` y `assess()` |

En `app/speech/assessment.py` se agrega `assess_scripted(wav_path, reference_text)`,
migrado de `speech.py:27` del legacy.

**Todo el I/O de red es asíncrono** (`httpx.AsyncClient`, endpoints `async def`). El SDK de
Azure es bloqueante, así que sus llamadas van dentro de `asyncio.to_thread` para no
bloquear el event loop.

## Endpoints (fase 2)

`GET /reading/random` → `{reading_id, title, level, source_url, excerpt, word_count}`.
Toma una fila al azar, calcula el extracto al servir, y guarda `reading_id → excerpt` en
memoria con TTL. El cliente no reenvía el `reference_text`: el servidor ya sabe qué texto
entregó, así nadie evalúa contra un texto arbitrario. Consulta el estado de los límites
para avisar temprano, pero no consume cuota.

`POST /reading/assess` (multipart: `reading_id` + `audio` WAV) → scores + palabras. Acá sí
se espera el resultado de Azure: es la respuesta, no un agregado en background. Registra la
cuota y el costo (`usage_events`, `kind="reading_assessment"`).

La cuota se cobra al evaluar, no al pedir el texto, porque evaluar es lo que cuesta dinero.

## Frontend

Se suma `jinja2` como dependencia. `templates/base.html` concentra head, estilos y banner;
`templates/index.html` (migrada desde `app/web/index.html`) y `templates/reading.html`
heredan de ella. Los estáticos pasan a `/static`, lo que implica desarmar el
`app.mount("/", StaticFiles(...))` de `app/cmd/server.py:334`.

`shared.js` concentra lo que hoy vive inline en `index.html` y ambas páginas necesitan:
encode WAV (`floatTo16BitPCM`, `encodeWav`), captura de audio, reconocimiento de voz del
navegador, gestión de `X-User-Id` y el render de palabras coloreadas por accuracy.

La pantalla de lectura tiene tres estados: vacío (botón "Buscar texto random"); listo
(izquierda el texto, derecha la transcripción en vivo del navegador mientras hablás, sin
costo); y review (derecha el resultado de Azure con palabras coloreadas, izquierda las
omisiones e inserciones contra el texto real, arriba los scores).

## Configuración

Nuevas variables, todas declaradas y leídas **solo** en `config.py`, con default:

`READING_MAX_WORDS` (120), `READING_MIN_LEVEL` (4), `READING_MAX_LEVEL` (7),
`READING_INGEST_INTERVAL_HOURS` (24), `READING_INGEST_PAGES` (3),
`READING_HTTP_TIMEOUT_SECONDS` (20), `READING_USER_AGENT`, `USER_READING_QUOTA` (10),
`RATE_LIMIT_READING_PER_MIN`.

`httpx` pasa de `dependency-groups.dev` a dependencia de producción en `pyproject.toml`.

## Errores

Cada fallo degrada sin tumbar el resto: catálogo vacío → 503 con mensaje explícito; fuente
caída o con HTML cambiado → el job loguea y el catálogo anterior sigue sirviendo; Azure
cancelado → 502; sin voz detectada → 422; presupuesto agotado → 429 con motivo tipado,
igual que la conversación hoy.

## Pruebas

Ningún test toca la red. El parser de Engoo se prueba contra un fixture HTML real guardado
en el repo; `make_excerpt` con Hypothesis (ya es dependencia); el repositorio con un doble
en memoria; los endpoints con `TestClient` inyectando servicios falsos, siguiendo el patrón
de `test_app_speech_assessment.py`.

## Riesgo conocido

Engoo es una SPA: con un User-Agent normal devuelve solo el shell de 4 KB. El HTML
renderizado (150 KB, con los enlaces a artículos y el cuerpo completo) aparece únicamente
al declararse Googlebot. Funciona hoy y `robots.txt` no lo prohíbe — el `Disallow:` está
vacío y solo bloquea `/tutors?`, `/app/oauth/` y `/sales` — pero es una dependencia de un
comportamiento no documentado que puede cambiar sin aviso.

Mitigación: vive en un solo archivo detrás de una interfaz, el catálogo persiste en BD, y
una ruptura degrada a "textos viejos" en lugar de a "feature caída".
