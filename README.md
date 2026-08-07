# review-ingles

Practica de ingles hablado con evaluacion automatica de pronunciacion. Dos modalidades:

- **`/` — conversacion**: un tutor (LLM) te hace preguntas, vos respondes hablando y al
  final recibis un feedback escrito y el score de pronunciacion.
- **`/reading` — lectura en voz alta**: la app te da un texto real, lo lees, y Azure Speech
  (Pronunciation Assessment) evalua tu pronunciacion **contra ese texto**, palabra por
  palabra y fonema por fonema.

> Funciona solo en **Google Chrome** de escritorio: las voces del tutor y el dictado por
> voz dependen de la Web Speech API de ese navegador.

## Estructura

Todo el codigo vive en [`app/`](app/); en la raiz solo quedan configuracion y tests.

| Ruta | Que hace |
|---|---|
| `app/cmd/server.py` | Servidor FastAPI: rutas, middlewares (request id, rate limit) y wiring de dependencias |
| `app/conversation/` | Grafo LangGraph del tutor, prompts, repositorio y servicio |
| `app/reading/` | Catalogo de textos: ingesta, extractos, scheduler y servicio |
| `app/speech/` | Azure Speech: cliente, evaluacion (con y sin texto de referencia) y scoring |
| `app/limits/` | Presupuesto en dolares y cuota por usuario |
| `app/feedback/` | Feedback del piloto |
| `app/web/` | Plantillas Jinja2 y assets estaticos |
| `app/storage.py`, `app/logconfig.py`, `app/ratelimit.py` | Pool de Postgres, structlog y rate limiter |
| `config.py` | **Unico** lugar del proyecto que lee variables de entorno |
| `docs/` | Toda la documentacion ([variables de entorno](docs/ENVS.md), planes y specs) |

## Puesta en marcha

### 1. Credenciales

- **Azure Speech** (evaluacion de pronunciacion). Gratis con el tier `F0` (5 h de audio al
  mes). En el [portal de Azure](https://portal.azure.com) → *Create a resource* → **Speech**
  → tier **Free F0**, eligiendo la region mas cercana para bajar la latencia. Despues, en
  el recurso → **Keys and Endpoint**, copia **KEY 1** y la **Region**.
- **Gemini** (el tutor). Key en <https://aistudio.google.com/apikey>.

Ambas son secretos: viven solo en tu `.env`, que esta en `.gitignore`.

### 2. Configurar

```bash
cp .env.example .env   # y pon tus valores
```

El detalle de cada variable esta en [docs/ENVS.md](docs/ENVS.md).

### 3. Correr

**Con docker-compose** (levanta Postgres + la app con hot reload; es la forma recomendada):

```bash
docker compose up --build
```

**En local** (necesitas un Postgres corriendo y `DATABASE_URL` apuntando a el):

```bash
uv sync
uv run uvicorn app.cmd.server:app --reload
```

Abri <http://127.0.0.1:8000>.

### 4. Poblar el catalogo de lectura

El catalogo se puebla solo desde Engoo Daily News con un job periodico: el servidor corre
la ingesta al arrancar si la tabla esta vacia, y despues cada `READING_INGEST_INTERVAL_HOURS`.
Si `/reading` responde **503**, el catalogo esta vacio; podes forzarla:

```bash
uv run python -m app.reading.ingest
```

El texto que se lee es un **extracto** del articulo (`READING_MAX_WORDS`, 120 por defecto),
recortado en limite de oracion. El articulo se guarda completo; el recorte se calcula al
servir y se vuelve a calcular al evaluar a partir del id del texto. Por eso el navegador
nunca manda el texto de referencia: lo pone el servidor.

El selector **Nivel maximo** de la pantalla es un tope, no un nivel exacto: pedir 5 puede
darte un 4 o un 5. Si no hay ningun texto que cumpla, la app lo dice en vez de darte uno
mas dificil.

## Tests

```bash
uv run pytest
```

Tambien corren dentro del build de Docker, en un stage dedicado:

```bash
docker build --target test .   # falla el build si rompen los tests
```

## Deploy

El [`Dockerfile`](Dockerfile) es multistage: `base` → `development` → `test` → `production`.
La imagen de produccion es minima (solo el venv de prod, `app/` y `config.py`), corre como
usuario **non-root** (`appuser`, uid 10001) y no lleva `uv` ni dependencias de desarrollo.
El `.env` **nunca** se hornea en la imagen: las variables se inyectan en runtime.

```bash
docker build --target production -t review-ingles:prod .
```

El `CMD` usa `sh -c "exec uvicorn ... --port ${PORT:-8000}"`: expande el `PORT` que el
proveedor inyecta en runtime (Railway lo hace; sin eso no puede rutear el trafico al
contenedor) y, gracias al `exec`, uvicorn queda como PID 1 y recibe el `SIGTERM` para
apagarse ordenadamente.

Para desplegar:

1. Aprovisiona un **Postgres** y aplica los scripts de [`docker/initdb/`](docker/initdb/) en
   orden — en compose se ejecutan solos al crear el volumen, pero en un Postgres gestionado
   hay que correrlos a mano una vez.
2. Carga las variables de entorno en el panel del servicio. Como minimo:
   `DATABASE_URL`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `GEMINI_API_KEY`. Revisa
   tambien `DAILY_BUDGET_USD` / `TOTAL_BUDGET_USD` y las cuotas por usuario antes de abrir
   el acceso: son el freno de gasto. Ver [docs/ENVS.md](docs/ENVS.md).
3. Despliega el `Dockerfile` con `--target production`.

> El servidor **no tiene autenticacion**. La identidad es un `X-User-Id` que manda el
> navegador, util para separar cuotas, no para proteger nada. Antes de exponerlo en
> internet, ten presente que el control de gasto son el presupuesto y el rate limit por IP.

## Como funciona el Pronunciation Assessment de Azure

Referencia oficial:
[How to use pronunciation assessment (Python)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment?pivots=programming-language-python).

### Los scores

| Score | Que mide |
|---|---|
| **Accuracy** | Que tan parecidos son tus fonemas a los de un nativo. Se agrega desde el nivel de fonema a silaba, palabra y texto completo. |
| **Fluency** | Que tan naturales son tus pausas (silencios) entre palabras. |
| **Completeness** | Proporcion de palabras pronunciadas respecto al texto de referencia. Solo aplica cuando hay texto de referencia (lectura). |
| **Prosody** | Naturalidad del habla: acento, entonacion, velocidad y ritmo. Solo disponible en `en-US` y SDK ≥ 1.35. |
| **Pronunciation** (`PronScore`) | Score global, ponderado a partir de los anteriores. |

**Formula del score global** (ordenando los sub-scores de menor a mayor, `s0`..`s3`):

- Con prosodia: `PronScore = 0.4*s0 + 0.2*s1 + 0.2*s2 + 0.2*s3`
- Sin prosodia: `PronScore = 0.6*s0 + 0.2*s1 + 0.2*s2`

El peor score pesa mas. Es exactamente lo que replica el agregado en `app/speech/`.

### Configuracion que usa este proyecto

Fijada en `app/speech/azure_client.py`:

- `PronunciationAssessmentGradingSystem.HundredMark` — scores de 0 a 100.
- `PronunciationAssessmentGranularity.Phoneme` — score por fonema, silaba, palabra y texto.
- `enable_prosody_assessment()` — activa el score de prosodia (solo `en-US`).
- `phoneme_alphabet = "IPA"` — fonemas en alfabeto IPA (los que pinta la pagina).

### `ErrorType` por palabra

Azure marca cada palabra con: `None`, `Omission`, `Insertion`, `Mispronunciation`,
`UnexpectedBreak`, `MissingBreak` o `Monotone`. Una palabra es `Mispronunciation` cuando su
`AccuracyScore` esta por debajo de 60.

### Modo continuo y miscue

Se usa **reconocimiento continuo** (sin el limite de ~30 s del modo `recognize_once`). En
modo continuo **`EnableMiscue` no esta soportado**: Azure no marca por si mismo `Omission`
ni `Insertion`. Para obtener esas etiquetas hay que **comparar lo reconocido contra el texto
de referencia**, que es justo lo que hace `app/speech/assessment.py` con `difflib`, siguiendo
el [sample oficial en Python](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/scenarios/python/console/language-learning/pronunciation_assessment.py)
(`pronunciation_assessment_continuous_from_file`).
