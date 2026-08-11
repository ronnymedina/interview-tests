# Environment variables

Every variable is read in **one single place**: [`config.py`](../config.py). The rest of the
code imports those already-typed constants and never calls `os.getenv` on its own — a stray
`os.getenv` is an architecture bug, not a shortcut.

Validation is done by pydantic-settings: with an invalid value **the server does not
start**, and the error names exactly which field is wrong and why.

## How to configure them

```bash
cp .env.example .env   # copy the template
# edit .env and put your real values in
```

- **`.env` is git-ignored** (see `.gitignore`), so your credentials never reach the repo.
- `.env.example` **is** versioned: it is the template, without real values.
- In docker-compose the `.env` is injected with `env_file`; it is never baked into the image.
- On a deployment (Railway or other) the variables are set in the service panel.

### Reading the tables

- **Required** — `Yes` means the server does not work without it. `Yes (for X)` means only
  feature X breaks: the server starts anyway and that feature answers with an error. `No`
  means the default is fine for both local and production use.
- **Accepted values** — what the field validates. Anything outside that range stops startup.
- **In production** — `same` means the default is also the right value in production.

## Credentials

All secrets. Never commit them; set them in the deployment panel.

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `GEMINI_API_KEY` | Yes (to converse) | `""` (empty) | An API key string | Chat model key, from <https://aistudio.google.com/apikey>. Only demanded when `CHAT_MODEL` or `REVIEW_CHAT_MODEL` point at `google_genai`. Without it the server starts and the conversation endpoints answer `503`. |
| `AZURE_SPEECH_KEY` | Yes (to assess) | `""` (empty) | An API key string | Key of the Azure **Speech** resource: portal → Speech resource → *Keys and Endpoint* → **KEY 1**. Without it the server starts, but the first assessment attempt returns an explanatory error. |
| `AZURE_SPEECH_REGION` | No | `eastus` | Any Azure region slug (`eastus`, `brazilsouth`, `westeurope`, …) | Must match the region where the resource was created. The closest one cuts latency. Not a secret. |

**In production:** all three must be set in the panel. Rotating a leaked key (Azure: *Keys
and Endpoint* → *Regenerate Key*) requires updating both your `.env` and the panel.

## Server and storage

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `DATABASE_URL` | Yes | `postgresql://review:review@localhost:5432/review_ingles` | A psycopg connection string | In docker-compose the service injects it (`db:5432`); on a deployment the database provider gives it. Contains a password — treat it as a secret. |
| `PORT` | No | `8000` | `1`–`65535` | Server port. On Railway the platform injects it at runtime and the Dockerfile `CMD` expands it. **In production: leave it to the platform.** |
| `SPEECH_LANGUAGE` | No | `en-US` | A BCP-47 tag Azure supports | The language being assessed. `en-US` has the most complete support (syllables, prosody). In production: same. |

## Conversation model

The `provider:model` format is what `init_chat_model` consumes. **Only the providers listed
in `PROVIDER_API_KEY_FIELDS` (`config.py`) are accepted** — today just `google_genai` —
because each one needs its own API key field. An unknown prefix, or a string without a
`provider:` part, stops startup with an explicit message instead of building a client that
401s on the first request. Adding a provider is two lines of `config.py`: a key field and a
map entry.

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `CHAT_MODEL` | No | `google_genai:gemini-2.5-flash` | `google_genai:<model>` | Model for the tutor and the synthesizer. |
| `CHAT_TEMPERATURE` | No | `1.0` | Float in the provider's range (Gemini: `0.0`–`2.0`) | Tutor temperature. High on purpose: varied, natural questions instead of the same mould every turn. |
| `REVIEW_CHAT_MODEL` | No | `""` (empty) | `google_genai:<model>`, or empty | Reviewer model. Empty = use `CHAT_MODEL`, so by default cost per token does not change. **In production, raising this to a stronger model is the one lever that improves feedback quality** — but see the pricing caveat below. |
| `REVIEW_TEMPERATURE` | No | `0.2` | Float in the provider's range | Reviewer temperature. Low on purpose: evaluation has to be stable and reproducible, not creative. |

## Budget and quotas

Two independent brakes: the **dollar budget** (shared across all modes) and the **per-user
quota** (`X-User-Id`, separate counters per mode).

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `DAILY_BUDGET_USD` | No | `3.0` | Float > 0 | Once exceeded the app pauses until the next day; it re-enables itself when the date changes. |
| `TOTAL_BUDGET_USD` | No | `10.0` | Float > 0 | Once reached the app pauses until manual intervention. |
| `USER_CONVERSATION_QUOTA` | No | `3` | Integer ≥ 0 | Lifetime conversations per user. |
| `USER_READING_QUOTA` | No | `10` | Integer ≥ 0 | Assessed readings per user. A separate counter on purpose: reading must not spend your conversations. The dollar budget *is* shared. |
| `MAX_ANSWER_SECONDS` | No | `30` | Integer > 0 | Maximum audio duration for one answer. |
| `MAX_QUESTIONS` | No | `5` | Integer > 0 | Turns in a conversation. |
| `GEMINI_PRICE_INPUT_PER_1K` | No | `0.0003` | Float ≥ 0 | Price per 1000 input tokens. |
| `GEMINI_PRICE_OUTPUT_PER_1K` | No | `0.0025` | Float ≥ 0 | Same for output tokens. |
| `AZURE_SPEECH_PRICE_PER_SECOND` | No | `0.000278` | Float ≥ 0 | Azure Pronunciation Assessment bills by audio duration (~$1/hour). |

**In production:** the prices are pilot approximations, tuned by env rather than by code.
They apply to **every model equally**, so if `REVIEW_CHAT_MODEL` points at a pricier model
the recorded spend is underestimated and the budget brake trips later than it should. Set
the budgets before opening access — they are the spend brake, see [deploy.md](deploy.md).

## Rate limiting per IP

Server protection, independent of quota and budget: requests per minute, per IP.

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `RATE_LIMIT_GLOBAL_PER_MIN` | No | `60` | Integer > 0 | Global cap for all traffic. |
| `RATE_LIMIT_START_PER_MIN` | No | `10` | Integer > 0 | `POST /start`: begins a conversation (LLM + Azure). |
| `RATE_LIMIT_ANSWER_PER_MIN` | No | `20` | Integer > 0 | `POST /answer`: advances one turn. |
| `RATE_LIMIT_READING_PER_MIN` | No | `20` | Integer > 0 | `POST /reading/assess`: uploads audio and waits for Azure's assessment. |

**In production:** the defaults assume a pilot with few users. A public deployment behind a
CDN or proxy needs these raised, since many users may share an egress IP.

## Reading practice: catalog ingestion (`app/reading`)

The catalog is populated by a periodic job rather than scraped live, so a source outage
degrades to "somewhat old texts" instead of "feature down". **None of these are required**:
ingestion works as-is with the defaults.

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `READING_INGEST_INTERVAL_HOURS` | No | `24` | Integer > 0 | How often the server's background task repeats the ingestion. |
| `READING_INGEST_PAGES` | No | `3` | Integer > 0 | Pages walked per category. Ingestion stops early if a page brings no articles. |
| `READING_MIN_LEVEL` / `READING_MAX_LEVEL` | No | `4` / `7` | Integers within the source's scale | Difficulty range. Applied as a filter in the source URL, so anything outside is never downloaded. |
| `READING_INGEST_MAX_ARTICLES` | No | `60` | Integer > 0 | Cap per run. Applied over the already-interleaved categories, so trimming does not bias the catalog toward a couple of topics. |
| `READING_INGEST_CONCURRENCY` | No | `5` | Integer > 0 | How many articles download at once. |
| `READING_HTTP_TIMEOUT_SECONDS` | No | `20` | Integer > 0 | Timeout for each request to the source. |
| `READING_USER_AGENT` | No | Googlebot | Any User-Agent string | Engoo is an SPA: with a normal User-Agent it returns an empty shell, and the rendered HTML only appears when declaring Googlebot. Configurable because it depends on undocumented behavior that may change. |
| `READING_MAX_WORDS` | No | `120` | Integer > 0 | Words in the excerpt read aloud (~40–60 s). The article is stored whole; the excerpt is computed when serving and recomputed when assessing. **Changing it changes the reference text of new readings.** |

## Structured logging (structlog)

Every log carries the same field contract, ready for Datadog, Loki or Elastic: `timestamp`,
`status`, `message`, `service`, `env`, `version`, `logger.name`, `logger.thread_name`,
`error.kind` / `error.message` / `error.stack` on exceptions, and `request_id` for anything
logged during an HTTP request.

| Variable | Required | Default | Accepted values | Description |
|---|---|---|---|---|
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | An invalid value stops startup with an error naming it. In production: `INFO`. |
| `LOG_FORMAT` | No | `auto` | `console`, `json`, `auto` | `console` is readable and colored, `json` is one line per event, `auto` picks console for a TTY and JSON otherwise. In docker-compose the output is not a TTY, so the container emits JSON with no configuration. In production: `auto` already resolves to `json`. |
| `DD_SERVICE` / `SERVICE_NAME` | No | `review-ingles` | Any string | Service name (unified service tagging). |
| `DD_ENV` / `ENVIRONMENT` | No | `development` | Any string | Environment. **In production: set it to `production`** — it is the tag that separates your dashboards. |
| `DD_VERSION` / `SERVICE_VERSION` | No | `0.1.0` | Any string | Deployed version. Makes it possible to compare an error across releases. |

The `DD_*` names take precedence because a typical deployment already has the Datadog agent
injecting them; the unprefixed aliases keep the project from being tied to one vendor.

## LangSmith (observability, optional)

These are deliberately **not** declared as fields in `config.py`: LangChain consumes them
straight from the environment, and `config.py`'s `load_dotenv()` already loads them. They
are listed here so the configuration still has a single map.

| Variable | Required | Accepted values | Description |
|---|---|---|---|
| `LANGSMITH_TRACING` | No | `true` / `false` | `true` turns tracing on. |
| `LANGSMITH_ENDPOINT` | No | A URL | `https://api.smith.langchain.com`. |
| `LANGSMITH_API_KEY` | No | An API key string | Key from <https://smith.langchain.com>. **A secret.** |
| `LANGSMITH_PROJECT` | No | Any string | Project name the traces are grouped under. |

## Security notes

- The **sensitive** variables are `GEMINI_API_KEY`, `AZURE_SPEECH_KEY`, `LANGSMITH_API_KEY`
  and the password inside `DATABASE_URL`. Treat them as passwords.
- If you believe a key leaked, rotate it in the provider's portal and update both your
  `.env` and the deployment panel.
- The rest (region, language, port, limits) are not secret.
