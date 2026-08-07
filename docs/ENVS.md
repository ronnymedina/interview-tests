# Variables de entorno

Todas las variables se leen en **un unico lugar**: [`config.py`](../config.py). El resto del
codigo importa esas constantes ya tipadas, nunca llama a `os.getenv` por su cuenta.

## Como configurarlas

```bash
cp .env.example .env   # copia la plantilla
# edita .env y pon tus valores reales
```

- El archivo **`.env` esta ignorado por git** (ver `.gitignore`), asi que tus
  credenciales nunca se suben al repositorio.
- `.env.example` **si** se versiona: es la plantilla, sin valores reales.
- En docker-compose el `.env` se inyecta con `env_file`, nunca se hornea en la imagen.
- En el despliegue (Railway u otro) las variables se cargan en el panel del servicio.

La validacion la hace pydantic-settings: con un valor invalido **el servidor no arranca** y
el error dice exactamente que campo esta mal y por que.

## Credenciales

| Variable | Requerida | Default | Descripcion |
|---|---|---|---|
| `AZURE_SPEECH_KEY` | Si (para evaluar) | `""` (vacio) | Key del recurso **Speech** de Azure. Se obtiene en el portal: recurso Speech → *Keys and Endpoint* → **KEY 1**. Sin ella el servidor arranca, pero el primer intento de evaluacion devuelve un error explicativo. **Es un secreto: no lo compartas ni lo subas a git.** |
| `AZURE_SPEECH_REGION` | No | `eastus` | Region del recurso Speech (ej. `eastus`, `brazilsouth`, `westeurope`). Debe coincidir con la region donde creaste el recurso. Elegir la mas cercana reduce la latencia. |
| `GEMINI_API_KEY` | Si (para conversar) | `""` (vacio) | Key del modelo de chat, en <https://aistudio.google.com/apikey>. Sin ella el servidor arranca igual y los endpoints de conversacion responden `503`. **Es un secreto.** |

## Servidor y almacenamiento

| Variable | Default | Descripcion |
|---|---|---|
| `DATABASE_URL` | `postgresql://review:review@localhost:5432/review_ingles` | Cadena de conexion a Postgres que consume psycopg. En docker-compose la inyecta el servicio (`db:5432`); en un despliegue la da el proveedor de la BD. |
| `PORT` | `8000` | Puerto del servidor. En Railway lo inyecta la plataforma en runtime y el `CMD` del Dockerfile lo expande. |
| `SPEECH_LANGUAGE` | `en-US` | Idioma que se evalua. `en-US` es el que tiene soporte mas completo (silabas, prosodia). |
| `CHAT_MODEL` | `google_genai:gemini-2.5-flash` | Modelo del chat en formato `proveedor:modelo` que consume `init_chat_model`. Cambiar de proveedor (p. ej. `openai:gpt-5-nano`) es cambiar esta variable, no el codigo. |

## Presupuesto y cuotas

Dos frenos independientes: el **presupuesto en dolares** (compartido por todas las
modalidades) y la **cuota por usuario** (`X-User-Id`, contadores separados por modalidad).

| Variable | Default | Descripcion |
|---|---|---|
| `DAILY_BUDGET_USD` | `3.0` | Al superarlo la app pausa hasta el dia siguiente; se rehabilita sola al cambiar la fecha. |
| `TOTAL_BUDGET_USD` | `10.0` | Al alcanzarlo la app pausa hasta intervencion manual. |
| `USER_CONVERSATION_QUOTA` | `3` | Conversaciones de por vida por usuario. |
| `USER_READING_QUOTA` | `10` | Lecturas evaluadas por usuario. Contador aparte a proposito: leer no gasta tus conversaciones. El presupuesto en dolares si es compartido. |
| `MAX_ANSWER_SECONDS` | `30` | Duracion maxima del audio de una respuesta. |
| `MAX_QUESTIONS` | `5` | Turnos de una conversacion. |
| `GEMINI_PRICE_INPUT_PER_1K` | `0.0003` | Tarifa por cada 1000 tokens de entrada. Aproximacion del piloto: el costo se ajusta cambiando la env, no el codigo. |
| `GEMINI_PRICE_OUTPUT_PER_1K` | `0.0025` | Idem para los tokens de salida. |
| `AZURE_SPEECH_PRICE_PER_SECOND` | `0.000278` | Azure Pronunciation Assessment se cobra por duracion de audio (~$1/hora). |

## Rate limiting por IP

Proteccion del servidor, independiente de la cuota y del presupuesto: requests por minuto
y por IP.

| Variable | Default | Descripcion |
|---|---|---|
| `RATE_LIMIT_GLOBAL_PER_MIN` | `60` | Tope global para todo el trafico. |
| `RATE_LIMIT_START_PER_MIN` | `10` | `POST /start`: arranca una conversacion (LLM + Azure). |
| `RATE_LIMIT_ANSWER_PER_MIN` | `20` | `POST /answer`: avanza un turno. |
| `RATE_LIMIT_READING_PER_MIN` | `20` | `POST /reading/assess`: subir audio y esperar la evaluacion de Azure. |

## Practica de lectura: ingesta del catalogo (`app/reading`)

El catalogo se puebla con un job periodico, no scrapeando en vivo: asi una caida de la
fuente degrada a "textos algo viejos" en vez de a "feature caida". Ninguna es obligatoria:
con los defaults la ingesta funciona tal cual.

| Variable | Default | Descripcion |
|---|---|---|
| `READING_INGEST_INTERVAL_HOURS` | `24` | Cada cuantas horas repite la ingesta la tarea de fondo del servidor. |
| `READING_INGEST_PAGES` | `3` | Paginas que se recorren por categoria. La ingesta corta antes si una pagina no trae articulos. |
| `READING_MIN_LEVEL` / `READING_MAX_LEVEL` | `4` / `7` | Rango de dificultad. Se aplica como filtro en la URL de la fuente, asi que lo que queda fuera ni se descarga. |
| `READING_INGEST_MAX_ARTICLES` | `60` | Tope de articulos por corrida. Se aplica sobre las categorias ya intercaladas, para que el recorte no sesgue el catalogo a un par de temas. |
| `READING_INGEST_CONCURRENCY` | `5` | Cuantos articulos se bajan a la vez. |
| `READING_HTTP_TIMEOUT_SECONDS` | `20` | Timeout de cada request a la fuente. |
| `READING_USER_AGENT` | Googlebot | Engoo es una SPA: con un User-Agent normal devuelve el shell vacio, y el HTML renderizado aparece solo al declararse Googlebot. Es configurable porque depende de un comportamiento no documentado que puede cambiar. |
| `READING_MAX_WORDS` | `120` | Palabras del extracto que se lee en voz alta (~40-60 s). El articulo se guarda completo; el recorte se calcula al servir, y se vuelve a calcular al evaluar. Cambiarlo cambia el texto de referencia de las lecturas nuevas. |

## Logging estructurado (structlog)

Todos los logs salen con el mismo contrato de campos, listos para Datadog, Loki o Elastic:
`timestamp`, `status`, `message`, `service`, `env`, `version`, `logger.name`,
`logger.thread_name`, `error.kind` / `error.message` / `error.stack` en las excepciones, y
`request_id` en lo que se loguee durante un request HTTP.

| Variable | Default | Descripcion |
|---|---|---|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` o `CRITICAL`. Un valor invalido impide arrancar, con un error que dice cual es. |
| `LOG_FORMAT` | `auto` | `console` (legible, con colores), `json` (una linea por evento) o `auto`: consola si la salida es una terminal, JSON si no. En docker-compose la salida no es un TTY, asi que el contenedor emite JSON sin configurar nada. |
| `DD_SERVICE` / `SERVICE_NAME` | `review-ingles` | Nombre del servicio (unified service tagging). |
| `DD_ENV` / `ENVIRONMENT` | `development` | Entorno. |
| `DD_VERSION` / `SERVICE_VERSION` | `0.1.0` | Version desplegada. Permite comparar el error entre releases. |

Los nombres `DD_*` tienen prioridad porque son los que el agente de Datadog ya inyecta solo
en un despliegue tipico; los alias sin prefijo evitan atar el proyecto a un proveedor.

## LangSmith (observabilidad, opcional)

Estas **no** se declaran como campos en `config.py` a proposito: LangChain las consume
directamente del entorno, y el `load_dotenv()` de `config.py` ya las carga. Se listan aca
para que la configuracion siga teniendo un mapa unico.

| Variable | Descripcion |
|---|---|
| `LANGSMITH_TRACING` | `true` para activar las trazas. |
| `LANGSMITH_ENDPOINT` | `https://api.smith.langchain.com`. |
| `LANGSMITH_API_KEY` | Key de <https://smith.langchain.com>. **Es un secreto.** |
| `LANGSMITH_PROJECT` | Nombre del proyecto donde se agrupan las trazas. |

## Notas de seguridad

- Las variables **sensibles** son `AZURE_SPEECH_KEY`, `GEMINI_API_KEY`, `LANGSMITH_API_KEY`
  y la contrasena dentro de `DATABASE_URL`. Tratalas como contrasenas.
- Si crees que una key quedo expuesta, rotala en el portal del proveedor
  (Azure: *Keys and Endpoint* → *Regenerate Key*) y actualiza tu `.env` y el panel del
  despliegue.
- El resto (region, idioma, puerto, limites) no son secretas.
