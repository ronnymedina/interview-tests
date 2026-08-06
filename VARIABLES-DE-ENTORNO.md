# Variables de entorno

Todas las variables se leen en **un unico lugar**: [`config.py`](config.py). El resto del
codigo importa esas constantes ya tipadas, nunca llama a `os.getenv` por su cuenta.

## Como configurarlas

```bash
cp .env.example .env   # copia la plantilla
# edita .env y pon tus valores reales
```

- El archivo **`.env` esta ignorado por git** (ver `.gitignore`), asi que tus
  credenciales nunca se suben al repositorio.
- `.env.example` **si** se versiona: es la plantilla, sin valores reales.
- Este proyecto corre solo en local, por lo que no hay secretos gestionados por un
  proveedor de nube; basta con tu `.env`.

## Referencia

| Variable | Requerida | Default | Descripcion |
|---|---|---|---|
| `AZURE_SPEECH_KEY` | Si (para evaluar) | `""` (vacio) | Key del recurso **Speech** de Azure. Se obtiene en el portal: recurso Speech → *Keys and Endpoint* → **KEY 1**. Sin ella el servidor arranca, pero el primer intento de evaluacion devuelve un error explicativo. **Es un secreto: no lo compartas ni lo subas a git.** |
| `AZURE_SPEECH_REGION` | No | `eastus` | Region del recurso Speech (ej. `eastus`, `brazilsouth`, `westeurope`). Debe coincidir con la region donde creaste el recurso. Elegir la region mas cercana reduce la latencia. |
| `SPEECH_LANGUAGE` | No | `en-US` | Idioma que se evalua. `en-US` es el que tiene soporte mas completo (silabas, prosodia). |
| `DB_PATH` | No | `attempts.db` | Ruta del archivo SQLite donde se guardan textos e intentos. |
| `PORT` | No | `8000` | Puerto en el que escucha el servidor FastAPI (`http://127.0.0.1:<PORT>`). |

### Logging estructurado (structlog)

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

### Practica de lectura: ingesta del catalogo (`app/reading`)

Ninguna es obligatoria: con los defaults la ingesta funciona tal cual.

| Variable | Default | Descripcion |
|---|---|---|
| `READING_INGEST_INTERVAL_HOURS` | `24` | Cada cuantas horas repite la ingesta la tarea de fondo del servidor. |
| `READING_INGEST_PAGES` | `3` | Paginas que se recorren por categoria. La ingesta corta antes si una pagina no trae articulos. |
| `READING_MIN_LEVEL` / `READING_MAX_LEVEL` | `4` / `7` | Rango de dificultad. Se aplica como filtro en la URL de la fuente, asi que lo que queda fuera ni se descarga. |
| `READING_INGEST_MAX_ARTICLES` | `60` | Tope de articulos por corrida. Se aplica sobre las categorias ya intercaladas, para que el recorte no sesgue el catalogo a un par de temas. |
| `READING_INGEST_CONCURRENCY` | `5` | Cuantos articulos se bajan a la vez. |
| `READING_HTTP_TIMEOUT_SECONDS` | `20` | Timeout de cada request a la fuente. |
| `READING_USER_AGENT` | Googlebot | Engoo es una SPA: con un User-Agent normal devuelve el shell vacio, y el HTML renderizado aparece solo al declararse Googlebot. Es configurable porque depende de un comportamiento no documentado que puede cambiar. |

### Practica de lectura: lo que se lee y cuanto se puede leer

| Variable | Default | Descripcion |
|---|---|---|
| `READING_MAX_WORDS` | `120` | Palabras del extracto que se lee en voz alta (~40-60 s). El articulo se guarda completo; el recorte se calcula al servir, y se vuelve a calcular al evaluar. Cambiarlo cambia el texto de referencia de las lecturas nuevas. |
| `USER_READING_QUOTA` | `10` | Lecturas evaluadas por usuario. Es un contador aparte de `USER_CONVERSATION_QUOTA`: leer no gasta tus conversaciones. El presupuesto en dolares (`DAILY_BUDGET_USD` / `TOTAL_BUDGET_USD`) si es compartido. |
| `RATE_LIMIT_READING_PER_MIN` | `20` | Requests por minuto y por IP a `POST /reading/assess`. |

## Notas de seguridad

- La unica variable **sensible** es `AZURE_SPEECH_KEY`. Tratala como una contrasena.
- Si crees que tu key quedo expuesta, rotala en el portal de Azure
  (*Keys and Endpoint* → *Regenerate Key*) y actualiza tu `.env`.
- El resto de variables (region, idioma, ruta de DB, puerto) no son secretas.
