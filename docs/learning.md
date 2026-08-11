# Learning roadmap — LangChain / LangGraph / LangSmith

Topics to learn **by applying them to this project** (`review-ingles`), aimed at a job
working with LangGraph. Every item is self-contained: it can be tackled in a fresh chat.
Tick the checkbox when you finish one.

> How to use this file: in a new chat, paste the item you want to work on and say "let's work
> on this roadmap item". The chat gets the project context below.

---

## Project context (to orient a fresh chat)

An app for practising spoken English. **The migration to `app/` is done**: the legacy code at
the repo root (`main.py`, `conversation.py`, `db.py`, `scoring.py`, `speech.py`, `app.js`,
`index.html`, `style.css`) no longer exists, and `app/cmd/server.py` is the only entrypoint.
Current structure:

- `app/conversation/graph.py` — the LangGraph graph: the `ConversationGraph` class with the
  `ask`/`review` nodes as methods and `compile()`, plus `State`, `FeedbackReport` (free-form
  Markdown feedback + `words` + `phrases`) and `initial_state`.
- `app/conversation/service.py` — `ConversationService` (dependency injection).
- `app/conversation/__init__.py` — the composition root: `build_conversation_graph_service`
  builds the three chat models and the graph, `build_chat_model` translates a
  `provider:model` string into a provider instance, and `api_key_for` resolves which API key
  that provider needs. The only place in the module that reads `settings`.
- `app/conversation/synthesizer.py` — synthesizes the learner's brief (fixed
  `### Puntos` + `### Contexto` format).
- `app/conversation/schemas.py` — input validation with Pydantic (no `if`s).
- `app/conversation/prompts/` — the prompts as `v<N>_<name>.md` files, outside the code;
  loaded with `prompts.load(prompts.TUTOR_SYSTEM)`.
- `app/reading/` — the reading text catalog: ingestion, excerpts and scheduler.
- `app/speech/` — Azure Speech: client, assessment and scoring.
- `app/limits/` — dollar budget and per-user quota.
- `app/storage.py` — Postgres pool (injected connections).
- `app/cmd/server.py` — the FastAPI server.
- `config.py` — the ONLY place environment variables are read.
- `migrations/` — the Postgres schema, as hand-written Alembic migrations.

**Design decisions already made** (do not re-litigate):
- The learner's brief enters as the first `HumanMessage`; the fixed rules go in the
  `SystemMessage`. No artificial "kickoff".
- The final feedback is free-form Markdown + structured `words`/`phrases` (JSON via
  `with_structured_output`).
- The service receives the graph through its constructor (DI); the graph is built once at
  startup.

**Migration status:** complete. `app/cmd/server.py` is the entrypoint, the conversation,
reading and feedback endpoints all live under `app/`, and the legacy root code was deleted
along with its tests.

---

## High priority (the most common interview topics)

### 1. `init_chat_model` — provider-agnostic model
- [x] Done
- **What it is**: instead of instantiating `ChatGoogleGenerativeAI` by hand, use
  `from langchain.chat_models import init_chat_model` to pick the model by string
  (`"google_genai:gemini-2.5-flash"`) or `model_provider`.
- **Where in the project**: `app/conversation/__init__.py` → `build_chat_model`, with the
  supported providers declared in `PROVIDER_API_KEY_FIELDS` (`config.py`).
- **What was done**:
  - Replaced the manual instantiation with `init_chat_model`.
  - Centralized the model/provider string in `config.py`, with a `field_validator` that
    rejects a provider that has no API key field behind it. Each provider brings its own key,
    resolved per model by `api_key_for` — so running the reviewer on a second provider does
    not demand a key nothing uses.
- **Check against the official docs (Context7)**: the `init_chat_model` signature, how to
  pass the API key per provider, and the "configurable" mode (swapping models at runtime).
- **Why (interviews)**: shows you can decouple from the provider; asked about often.

### 2. Persistent checkpointer (SQLite → Postgres)
- [ ] Done
- **What it is**: today the graph uses `InMemorySaver` → each conversation's state lives in
  memory and is lost on restart or across workers. A persistent checkpointer stores the state
  (messages, `thread_id`) in a real database.
- **Careful (common confusion)**: the project's Postgres stores usage, quotas, feedback and
  the reading catalog, NOT the graph state. They are two separate persistences, and the
  checkpointer needs its own.
- **Where in the project**: `app/conversation/graph.py` → `ConversationGraph(..., checkpointer)`;
  injected from `build_conversation_graph_service` in `__init__.py`.
- **What to do**:
  - Intermediate step: `SqliteSaver` (reuses the SQLite you already have).
  - Production: `PostgresSaver` (for multiple workers / autoscaling).
  - Pass the saver to `ConversationGraph` instead of the default `InMemorySaver`.
- **Check against the official docs (Context7)**: the exact import for
  `SqliteSaver`/`PostgresSaver`, setup (context manager, `.setup()` to create tables), sync
  vs async.
- **Why (interviews)**: state persistence is THE serious LangGraph topic.

### 3. LangSmith — observability
- [x] Done (env-based activation + the `review-ingles` project; the datasets/evals "extra" is still pending → item 5)
- **What it is**: automatic traces of every `llm.invoke` and graph run (exact messages sent to
  Gemini, tokens, latency, cost). Turned on by environment variables, no code changes.
- **What to do**:
  - Account on smith.langchain.com → API key.
  - `.env`: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=review-ingles`.
  - Declare the constants in `config.py` (centralized-env convention).
  - Run the server with a real `GEMINI_API_KEY` and look at the traces.
- **Extra to explore inside LangSmith**: **datasets + offline evaluation** (run saved cases
  and measure whether a prompt change improved things). This is what separates someone who
  "builds a chatbot" from someone who operates LLMs seriously.
- **Why (interviews)**: observability and evals are strong differentiators.

---

## Medium priority (going deeper on what you already touched)

### 4. Streaming
- [ ] Done
- **What it is**: emitting tokens/graph updates live (`.stream()` / `astream`) instead of
  waiting for the complete response.
- **Where**: the `ask` node / the endpoints. Needs an endpoint that supports streaming (SSE).
- **Why (interviews)**: real-time chat UX; asked for often.

### 5. Evals with LangSmith (extension of item 3)
- [ ] Done
- **What to do**: create a dataset with sample briefs + answers, and evaluate the quality of
  the feedback or the questions when you change the prompt. LLM-as-judge.
- **Why (interviews)**: measuring instead of "eyeballing it".

### 6. Error handling, retries and cost
- [ ] Done
- **What it is**: retries on LLM failures, token limits, cost control, timeouts.
- **Where**: `service.py` / `graph.py`. Tied to what LangSmith shows you about tokens/cost.

---

## Exploration priority (topics that are new to you)

### 7. Subgraphs and multi-agent patterns
- [ ] Done
- **What it is**: composing several graphs/agents (e.g. one agent that asks and another that
  evaluates), or reusable subgraphs.
- **Applied to this project**: separating the "tutor who converses" from the "evaluator who
  gives feedback" as distinct agents, instead of one graph with `ask`/`review`. Partly there
  already: the `review` node runs with its own system prompt, its own LLM instance and a
  message list built from scratch — but it is still a node of the same graph.
- **Why (interviews)**: "multi-agent" is the buzzword; worth having a demo.

### 8. Human-in-the-loop
- [ ] Done
- **What it is**: pausing the graph for human intervention (approve/edit) and resuming via
  the checkpointer. Requires persistence (item 2).
- **Why (interviews)**: a key pattern in production agents.

---

## Already yours (worth mentioning in an interview, no need to relearn)

- State with reducers (`add_messages`).
- Conditional routing (`conditional_edges`).
- Structured output (`with_structured_output` → `FeedbackReport`).
- Checkpointers and per-`thread_id` persistence (understood in depth; the persistent saver is
  what's missing).
- Guardrails / anti prompt-injection (system prompt taking precedence over the brief).
- Dependency injection and testing with LLM/graph doubles.
- Pydantic validation at the input layer.

---

## Suggested order

1. `init_chat_model` (quick, high impact) → item 1
2. LangSmith (turn it on early, so you can see everything else) → item 3
3. Persistent checkpointer → item 2
4. Evals → item 5
5. Streaming → item 4
6. Multi-agent / human-in-the-loop → items 7 and 8
