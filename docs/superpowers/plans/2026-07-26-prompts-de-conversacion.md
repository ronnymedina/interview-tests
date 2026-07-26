# Prompts de conversación Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generar el escenario (system prompt) de una conversación con un LLM a partir de un contexto libre (escrito o dictado), y persistir esos prompts con nombre para reutilizarlos.

**Architecture:** Se agrega una tabla `conversation_prompts` con CRUD en `db.py`; la generación con Gemini vive en `conversation.py` (único punto que habla con el LLM); `main.py` expone endpoints bajo `/conversation`; el frontend gana una pantalla "Prompt de conversación" para generar/gestionar, y la vista "Conversación" pasa de un textarea libre a un selector de prompts guardados.

**Tech Stack:** Python 3, FastAPI, SQLite (`sqlite3`), LangChain + `langchain_google_genai` (Gemini), JS vanilla (Web Speech API), pytest, `uv`.

## Global Constraints

- Variables de entorno: solo se leen en `config.py`; ningún otro módulo hace `os.getenv`. Esta feature **no agrega variables**: reutiliza `GEMINI_API_KEY` y `GEMINI_MODEL` ya definidas.
- `conversation.py` es el **único** módulo que importa/usa LangGraph y Gemini. La generación del prompt vive ahí.
- El prompt guardado contiene **solo** `name` + `system_prompt`; el contexto crudo es transitorio.
- Sin persistir turno-a-turno, sin leer archivos, sin enganchar la tabla `texts`.
- En la vista Conversación **no** hay tipeo ad-hoc: se elige un prompt guardado (patrón Textos↔Practicar).
- Mensajes de validación al usuario en español (estilo `_clean_text`).
- Tests con BD temporal vía la fixture `temp_db`/`client` de `conftest.py`. Correr con `uv run pytest`.

---

### Task 1: Tabla y CRUD de `conversation_prompts` (`db.py`)

**Files:**
- Modify: `db.py` (agregar la tabla al `SCHEMA` y las 5 funciones CRUD)
- Test: `test_db.py`

**Interfaces:**
- Produces:
  - `db.create_conversation_prompt(name: str, system_prompt: str) -> int`
  - `db.get_conversation_prompt(prompt_id: int) -> dict | None`
  - `db.list_conversation_prompts() -> list[dict]`  (orden `id DESC`)
  - `db.update_conversation_prompt(prompt_id: int, name: str, system_prompt: str) -> None`
  - `db.delete_conversation_prompt(prompt_id: int) -> None`
  - Cada dict: `{id, created_at, updated_at, name, system_prompt}`.

- [ ] **Step 1: Write the failing test**

En `test_db.py`, agregar al final:

```python
def test_conversation_prompt_crud(temp_db):
    assert db.list_conversation_prompts() == []

    pid = db.create_conversation_prompt("Entrevista", "Ask about work.")
    assert isinstance(pid, int) and pid > 0

    got = db.get_conversation_prompt(pid)
    assert got["name"] == "Entrevista"
    assert got["system_prompt"] == "Ask about work."
    assert got["created_at"] and got["updated_at"]

    db.update_conversation_prompt(pid, "Entrevista v2", "Ask about backend work.")
    got = db.get_conversation_prompt(pid)
    assert got["name"] == "Entrevista v2"
    assert got["system_prompt"] == "Ask about backend work."

    db.delete_conversation_prompt(pid)
    assert db.get_conversation_prompt(pid) is None
    assert db.list_conversation_prompts() == []


def test_conversation_prompts_ordered_id_desc(temp_db):
    first = db.create_conversation_prompt("Uno", "A")
    second = db.create_conversation_prompt("Dos", "B")
    ids = [p["id"] for p in db.list_conversation_prompts()]
    assert ids == [second, first]
```

`test_db.py` ya importa `db`. Verificarlo; si no, agregar `import db` arriba.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest test_db.py::test_conversation_prompt_crud -v`
Expected: FAIL con `AttributeError: module 'db' has no attribute 'create_conversation_prompt'`.

- [ ] **Step 3: Agregar la tabla al SCHEMA**

En `db.py`, dentro de la constante `SCHEMA`, agregar al final (antes del cierre `"""`):

```sql

-- Prompts de conversacion reutilizables: escenario (system_prompt) con nombre, generado
-- con el LLM o escrito a mano, para elegirlo al iniciar una conversacion.
CREATE TABLE IF NOT EXISTS conversation_prompts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    name          TEXT NOT NULL,
    system_prompt TEXT NOT NULL
);
```

- [ ] **Step 4: Implementar el CRUD**

En `db.py`, agregar al final del archivo:

```python
# --- prompts de conversacion -------------------------------------------------


def create_conversation_prompt(name: str, system_prompt: str) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO conversation_prompts (created_at, updated_at, name, system_prompt) "
            "VALUES (?, ?, ?, ?)",
            (now, now, name, system_prompt),
        )
        return cursor.lastrowid or 0


def get_conversation_prompt(prompt_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, created_at, updated_at, name, system_prompt "
            "FROM conversation_prompts WHERE id = ?",
            (prompt_id,),
        ).fetchone()
        return dict(row) if row else None


def list_conversation_prompts() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, updated_at, name, system_prompt "
            "FROM conversation_prompts ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def update_conversation_prompt(prompt_id: int, name: str, system_prompt: str) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        conn.execute(
            "UPDATE conversation_prompts SET name = ?, system_prompt = ?, updated_at = ? "
            "WHERE id = ?",
            (name, system_prompt, now, prompt_id),
        )


def delete_conversation_prompt(prompt_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM conversation_prompts WHERE id = ?", (prompt_id,))
```

`datetime`, `timezone` y `_connect` ya están importados/definidos en `db.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest test_db.py -v`
Expected: PASS (los tests nuevos y los existentes).

- [ ] **Step 6: Commit**

```bash
git add db.py test_db.py
git commit -m "feat: tabla y CRUD de conversation_prompts"
```

---

### Task 2: Generación del escenario con el LLM (`conversation.py`)

**Files:**
- Modify: `conversation.py` (refactor `_get_llm`, nueva `_GENERATE_INSTRUCTION` y `generate_system_prompt`)
- Modify: `test_conversation.py` (test nuevo + reset de `_llm` en el test de 500)
- Test: `test_conversation.py`

**Interfaces:**
- Consumes: `_content_text` (ya existe), `ConversationError` (ya existe), `HumanMessage` (ya importado).
- Produces: `conversation.generate_system_prompt(context: str, llm=None) -> str`.

- [ ] **Step 1: Write the failing test**

En `test_conversation.py`, agregar al final:

```python
def test_generate_system_prompt_returns_scenario():
    llm = FakeLLM(["Ask the learner about their backend experience."])
    result = conversation.generate_system_prompt("Practicar entrevista backend", llm=llm)
    assert result == "Ask the learner about their backend experience."


def test_generate_system_prompt_empty_context_raises_400():
    with pytest.raises(conversation.ConversationError) as error:
        conversation.generate_system_prompt("   ", llm=FakeLLM([]))
    assert error.value.status == 400


def test_generate_system_prompt_flattens_block_content():
    llm = BlockContentLLM(["Scenario as blocks"])
    result = conversation.generate_system_prompt("algo de contexto", llm=llm)
    assert result == "Scenario as blocks"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest test_conversation.py::test_generate_system_prompt_returns_scenario -v`
Expected: FAIL con `AttributeError: module 'conversation' has no attribute 'generate_system_prompt'`.

- [ ] **Step 3: Refactor a `_get_llm()` perezoso**

En `conversation.py`, reemplazar el bloque actual:

```python
# Grafo real (Gemini), construido una sola vez. Los tests usan build_graph con un doble.
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        if not config.GEMINI_API_KEY:
            raise ConversationError(
                "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
                "y pon tu clave de Gemini.",
                status=500,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL, google_api_key=config.GEMINI_API_KEY
        )
        _graph = build_graph(llm)
    return _graph
```

por:

```python
# Cliente Gemini y grafo reales, construidos una sola vez. Los tests inyectan dobles
# (llm=/graph=), asi que estos accesores no se ejecutan en los tests.
_llm = None
_graph = None


def _get_llm():
    global _llm
    if _llm is None:
        if not config.GEMINI_API_KEY:
            raise ConversationError(
                "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
                "y pon tu clave de Gemini.",
                status=500,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        _llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL, google_api_key=config.GEMINI_API_KEY
        )
    return _llm


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph(_get_llm())
    return _graph
```

- [ ] **Step 4: Agregar la meta-instrucción y `generate_system_prompt`**

En `conversation.py`, junto a las otras instrucciones (después de `_FEEDBACK_INSTRUCTION`), agregar:

```python
# Meta-instruccion para generar el escenario a partir del contexto libre del alumno.
# Devuelve texto plano (no salida estructurada): el escenario que luego envuelve _ASK_INSTRUCTION.
_GENERATE_INSTRUCTION = (
    "You are a prompt engineer for a spoken English practice app. Turn the learner's context "
    "below into a concise scenario (2-5 sentences) for a spoken English practice partner: "
    "describe what the partner should ask about and evaluate. Write it in English, addressed "
    "in the second person to the practice partner. Output ONLY the scenario text, with no "
    "preamble, no title and no quotes. Context:\n\n"
)
```

Y agregar la función (después de `answer`, al final del archivo):

```python
def generate_system_prompt(context: str, llm=None) -> str:
    """Expande un contexto libre del alumno a un escenario en ingles usando el LLM.

    Es una llamada simple (sin grafo). El escenario resultante es lo mismo que hoy se
    escribe a mano en el campo "escenario": al iniciar la conversacion lo envuelve
    _ASK_INSTRUCTION. `llm=` es inyectable para los tests.
    """
    context = context.strip()
    if not context:
        raise ConversationError("El contexto esta vacio.", status=400)
    llm = llm or _get_llm()
    return _content_text(llm.invoke([HumanMessage(_GENERATE_INSTRUCTION + context)]))
```

- [ ] **Step 5: Ajustar el test de "sin API key" para resetear `_llm`**

En `test_conversation.py`, en `test_start_without_api_key_raises_500`, agregar el reset de `_llm` junto al de `_graph`:

```python
def test_start_without_api_key_raises_500(monkeypatch):
    """Sin GEMINI_API_KEY, _get_graph() debe fallar con 500 al construir el grafo real."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(conversation, "_llm", None)
    monkeypatch.setattr(conversation, "_graph", None)

    with pytest.raises(conversation.ConversationError) as error:
        conversation.start("Roleplay", 2)

    assert error.value.status == 500
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest test_conversation.py -v`
Expected: PASS (nuevos y existentes, incluido `test_start_without_api_key_raises_500`).

- [ ] **Step 7: Commit**

```bash
git add conversation.py test_conversation.py
git commit -m "feat: generate_system_prompt en conversation.py (LLM comparte cliente con el grafo)"
```

---

### Task 3: Endpoints de generación y CRUD (`main.py`)

**Files:**
- Modify: `main.py` (modelos Pydantic + 5 endpoints)
- Test: `test_api.py`

**Interfaces:**
- Consumes: `conversation.generate_system_prompt`, `db.*_conversation_prompt(s)` de Tasks 1-2.
- Produces (HTTP):
  - `POST /conversation/prompt/generate` body `{context}` → `{system_prompt}` (400 si vacío)
  - `GET /conversation/prompts` → `list[dict]`
  - `POST /conversation/prompts` body `{name, system_prompt}` → dict (400 si vacío)
  - `PUT /conversation/prompts/{prompt_id}` body `{name, system_prompt}` → dict (404 / 400)
  - `DELETE /conversation/prompts/{prompt_id}` → `{ok: true}` (404 si no existe)

- [ ] **Step 1: Write the failing test**

En `test_api.py`, agregar al final (el archivo ya importa `conversation` y `db`):

```python
def test_create_and_list_conversation_prompt(client):
    resp = client.post(
        "/conversation/prompts",
        json={"name": "Entrevista", "system_prompt": "Ask about work."},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Entrevista"

    listed = client.get("/conversation/prompts").json()
    assert len(listed) == 1
    assert listed[0]["system_prompt"] == "Ask about work."


def test_create_conversation_prompt_empty_name_rejected(client):
    resp = client.post("/conversation/prompts", json={"name": "  ", "system_prompt": "x"})
    assert resp.status_code == 400


def test_create_conversation_prompt_empty_prompt_rejected(client):
    resp = client.post("/conversation/prompts", json={"name": "n", "system_prompt": "  "})
    assert resp.status_code == 400


def test_update_conversation_prompt(client):
    pid = client.post(
        "/conversation/prompts", json={"name": "Viejo", "system_prompt": "Old."}
    ).json()["id"]
    resp = client.put(
        f"/conversation/prompts/{pid}", json={"name": "Nuevo", "system_prompt": "New."}
    )
    assert resp.status_code == 200
    assert db.get_conversation_prompt(pid)["name"] == "Nuevo"


def test_update_missing_conversation_prompt_returns_404(client):
    resp = client.put("/conversation/prompts/999", json={"name": "n", "system_prompt": "s"})
    assert resp.status_code == 404


def test_delete_conversation_prompt(client):
    pid = client.post(
        "/conversation/prompts", json={"name": "Uno", "system_prompt": "s"}
    ).json()["id"]
    assert client.delete(f"/conversation/prompts/{pid}").status_code == 200
    assert client.get("/conversation/prompts").json() == []


def test_delete_missing_conversation_prompt_returns_404(client):
    assert client.delete("/conversation/prompts/999").status_code == 404


def test_conversation_prompt_generate(client, monkeypatch):
    monkeypatch.setattr(
        conversation, "generate_system_prompt", lambda context: f"Scenario for: {context}"
    )
    resp = client.post("/conversation/prompt/generate", json={"context": "backend interview"})
    assert resp.status_code == 200
    assert resp.json() == {"system_prompt": "Scenario for: backend interview"}


def test_conversation_prompt_generate_empty_context_rejected(client):
    resp = client.post("/conversation/prompt/generate", json={"context": "   "})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest test_api.py::test_create_and_list_conversation_prompt -v`
Expected: FAIL con status 404 (endpoint inexistente) en vez de 200.

- [ ] **Step 3: Agregar los modelos Pydantic**

En `main.py`, junto a los otros modelos (después de `ConversationStartIn`), agregar:

```python
class ConversationPromptGenerateIn(BaseModel):
    context: str


class ConversationPromptIn(BaseModel):
    name: str
    system_prompt: str


def _clean_conversation_prompt(payload: ConversationPromptIn) -> tuple[str, str]:
    """Valida y normaliza un prompt de conversacion. Lanza 400 con mensaje en espanol."""
    name = payload.name.strip()
    system_prompt = payload.system_prompt.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre esta vacio.")
    if not system_prompt:
        raise HTTPException(status_code=400, detail="El escenario esta vacio.")
    return name, system_prompt
```

- [ ] **Step 4: Agregar los endpoints**

En `main.py`, después del endpoint `conversation_start` (antes de `conversation_answer`), agregar:

```python
@app.post("/conversation/prompt/generate")
def conversation_prompt_generate(payload: ConversationPromptGenerateIn) -> dict:
    context = payload.context.strip()
    if not context:
        raise HTTPException(status_code=400, detail="El contexto esta vacio.")
    try:
        system_prompt = conversation.generate_system_prompt(context)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    return {"system_prompt": system_prompt}


@app.get("/conversation/prompts")
def list_conversation_prompts() -> list[dict]:
    return db.list_conversation_prompts()


@app.post("/conversation/prompts")
def create_conversation_prompt(payload: ConversationPromptIn) -> dict:
    name, system_prompt = _clean_conversation_prompt(payload)
    prompt_id = db.create_conversation_prompt(name, system_prompt)
    return db.get_conversation_prompt(prompt_id)


@app.put("/conversation/prompts/{prompt_id}")
def update_conversation_prompt(prompt_id: int, payload: ConversationPromptIn) -> dict:
    if db.get_conversation_prompt(prompt_id) is None:
        raise HTTPException(status_code=404, detail="El prompt no existe.")
    name, system_prompt = _clean_conversation_prompt(payload)
    db.update_conversation_prompt(prompt_id, name, system_prompt)
    return db.get_conversation_prompt(prompt_id)


@app.delete("/conversation/prompts/{prompt_id}")
def delete_conversation_prompt(prompt_id: int) -> dict:
    if db.get_conversation_prompt(prompt_id) is None:
        raise HTTPException(status_code=404, detail="El prompt no existe.")
    db.delete_conversation_prompt(prompt_id)
    return {"ok": True}
```

Nota: los nombres de estas funciones-ruta conviven con `db.list_conversation_prompts` etc. sin colisión porque se invocan con el prefijo `db.`. Las rutas `/conversation/prompt/generate` y `/conversation/prompts` no chocan con `/conversation/{conversation_id}/answer` (distinto último segmento / número de segmentos).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest test_api.py -v`
Expected: PASS (nuevos y existentes).

- [ ] **Step 6: Full backend suite**

Run: `uv run pytest -q`
Expected: toda la suite en verde.

- [ ] **Step 7: Commit**

```bash
git add main.py test_api.py
git commit -m "feat: endpoints /conversation/prompt(s) (generar + CRUD)"
```

---

### Task 4: Pantalla "Prompt de conversación" (frontend: generar/gestionar)

**Files:**
- Modify: `index.html` (botón de menú + `section#view-conv-prompts`)
- Modify: `app.js` (els + carga + generar + dictado + guardar/editar/borrar + wiring)
- Modify: `style.css` (ancho de textareas/inputs de la vista nueva)

**Interfaces:**
- Consumes (HTTP): endpoints de Task 3.
- Produces (JS, usados por Task 5): `conversationPromptsData` (array cacheado) y
  `loadConversationPrompts()` (que además llamará a `renderConversationPromptSelect()` de Task 5).

- [ ] **Step 1: Agregar el botón de menú y la sección en `index.html`**

En `index.html`, en el `<nav class="menu">`, agregar después del botón de Textos:

```html
        <button type="button" data-view="conv-prompts">Prompt de conversacion</button>
```

Y agregar la sección nueva después de `</section>` de `#view-texts` (antes de `#view-words`):

```html
      <!-- Vista: prompts de conversacion (generar y gestionar) -->
      <section id="view-conv-prompts" class="view hidden">
        <h2>Prompt de conversacion</h2>
        <p class="hint">
          Escribe o dicta un contexto (tu intencion, tu CV, un tema), genera un escenario en
          ingles con el asistente, editalo y guardalo con un nombre para reutilizarlo en tus
          conversaciones.
        </p>

        <input type="hidden" id="cp-id" />

        <label for="cp-context">Contexto / intencion</label>
        <textarea id="cp-context" rows="4"
          placeholder="Practicar una entrevista para un puesto backend; evalua mi vocabulario tecnico. (Puedes pegar tu CV)"></textarea>
        <div class="controls">
          <button id="cp-dictate" type="button" class="secondary">🎤 Dictar</button>
          <button id="cp-generate" type="button">✨ Generar escenario</button>
          <span id="cp-status" class="status"></span>
        </div>

        <label for="cp-prompt">Escenario (editable)</label>
        <textarea id="cp-prompt" rows="5"
          placeholder="El escenario en ingles aparecera aqui; puedes editarlo antes de guardar."></textarea>

        <label for="cp-name">Nombre del prompt</label>
        <input id="cp-name" type="text" maxlength="200" />

        <div class="controls">
          <button id="cp-save" type="button">Guardar prompt</button>
          <button id="cp-cancel" type="button" class="secondary">Limpiar</button>
          <span id="cp-error" class="error hidden"></span>
        </div>

        <table id="conv-prompts">
          <thead>
            <tr>
              <th>Nombre</th>
              <th>Escenario</th>
              <th></th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
      </section>
```

- [ ] **Step 2: Registrar los elementos en `app.js`**

En `app.js`, dentro del objeto `els = { ... }`, agregar (antes del cierre `}`):

```javascript
  cpId: document.getElementById("cp-id"),
  cpContext: document.getElementById("cp-context"),
  cpDictate: document.getElementById("cp-dictate"),
  cpGenerate: document.getElementById("cp-generate"),
  cpStatus: document.getElementById("cp-status"),
  cpPrompt: document.getElementById("cp-prompt"),
  cpName: document.getElementById("cp-name"),
  cpSave: document.getElementById("cp-save"),
  cpCancel: document.getElementById("cp-cancel"),
  cpError: document.getElementById("cp-error"),
  convPrompts: document.querySelector("#conv-prompts tbody"),
```

- [ ] **Step 3: Agregar la lógica de la pantalla en `app.js`**

En `app.js`, después del bloque `// --- conversacion -----` (o al final, antes de `// --- arranque ---`), agregar:

```javascript
// --- prompts de conversacion (generar / gestionar) ---------------------------

let conversationPromptsData = []; // ultimos prompts cargados, para el select y la tabla

async function loadConversationPrompts() {
  const response = await fetch("/conversation/prompts");
  if (!response.ok) return;
  conversationPromptsData = await response.json();
  renderConversationPromptsTable();
  // Definido en la vista Conversacion (Task 5). El guard evita romper el arranque
  // mientras esa tarea todavia no existe.
  if (typeof renderConversationPromptSelect === "function") renderConversationPromptSelect();
}

function renderConversationPromptsTable() {
  els.convPrompts.innerHTML = "";
  if (conversationPromptsData.length === 0) {
    els.convPrompts.innerHTML = `<tr><td colspan="3" class="empty">Sin prompts todavia.</td></tr>`;
    return;
  }
  for (const prompt of conversationPromptsData) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="truncate">${escapeHtml(prompt.name)}</td>
      <td class="truncate">${escapeHtml(prompt.system_prompt)}</td>
    `;
    const actions = document.createElement("td");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary small";
    edit.textContent = "Editar";
    edit.addEventListener("click", () => editConversationPrompt(prompt));
    const del = document.createElement("button");
    del.type = "button";
    del.className = "secondary small";
    del.textContent = "Borrar";
    del.addEventListener("click", () => deleteConversationPrompt(prompt));
    actions.append(edit, del);
    row.appendChild(actions);
    els.convPrompts.appendChild(row);
  }
}

function showCpError(message) {
  els.cpError.textContent = message;
  els.cpError.classList.remove("hidden");
}

function editConversationPrompt(prompt) {
  els.cpError.classList.add("hidden");
  els.cpId.value = prompt.id;
  els.cpPrompt.value = prompt.system_prompt;
  els.cpName.value = prompt.name;
  els.cpContext.value = "";
  els.cpName.focus();
}

function clearConversationPromptForm() {
  els.cpError.classList.add("hidden");
  els.cpId.value = "";
  els.cpContext.value = "";
  els.cpPrompt.value = "";
  els.cpName.value = "";
}

async function generateConversationPrompt() {
  els.cpError.classList.add("hidden");
  const context = els.cpContext.value.trim();
  if (!context) {
    showCpError("Escribe o dicta un contexto primero.");
    return;
  }
  els.cpGenerate.disabled = true;
  els.cpStatus.textContent = "Generando...";
  let response;
  try {
    response = await fetch("/conversation/prompt/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context }),
    });
  } catch (err) {
    els.cpGenerate.disabled = false;
    els.cpStatus.textContent = "";
    showCpError("No se pudo contactar al servidor: " + err.message);
    return;
  }
  els.cpGenerate.disabled = false;
  els.cpStatus.textContent = "";
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showCpError(formatDetail(body.detail) || `El servidor respondio ${response.status}.`);
    return;
  }
  els.cpPrompt.value = (await response.json()).system_prompt;
}

async function saveConversationPrompt() {
  els.cpError.classList.add("hidden");
  const name = els.cpName.value.trim();
  const systemPrompt = els.cpPrompt.value.trim();
  if (!name) return showCpError("Ponle un nombre al prompt.");
  if (!systemPrompt) return showCpError("El escenario esta vacio.");

  const id = els.cpId.value;
  const url = id ? `/conversation/prompts/${id}` : "/conversation/prompts";
  const method = id ? "PUT" : "POST";
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, system_prompt: systemPrompt }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showCpError(formatDetail(body.detail) || "No se pudo guardar.");
    return;
  }
  clearConversationPromptForm();
  await loadConversationPrompts();
}

async function deleteConversationPrompt(prompt) {
  if (!confirm(`Borrar el prompt "${prompt.name}"?`)) return;
  const response = await fetch(`/conversation/prompts/${prompt.id}`, { method: "DELETE" });
  if (!response.ok) return;
  if (els.cpId.value === String(prompt.id)) clearConversationPromptForm();
  await loadConversationPrompts();
}

// Dictado por voz del cuadro de contexto (Web Speech API del navegador; gratis, sin backend).
// Se usa es-ES porque el contexto se dicta normalmente en espanol. Reusa el mismo objeto
// SpeechRecognition que ya detecta la conversacion.
let promptRecognition = null;
let promptDictating = false;

function togglePromptDictation() {
  if (!SpeechRecognition) return;
  if (promptDictating) {
    promptRecognition.stop();
    return;
  }
  promptRecognition = new SpeechRecognition();
  promptRecognition.lang = "es-ES";
  promptRecognition.continuous = true;
  promptRecognition.interimResults = false;
  promptRecognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        const text = event.results[i][0].transcript.trim();
        els.cpContext.value = (els.cpContext.value + " " + text).trim();
      }
    }
  };
  const stop = () => {
    promptDictating = false;
    els.cpDictate.textContent = "🎤 Dictar";
    els.cpStatus.textContent = "";
  };
  promptRecognition.onend = stop;
  promptRecognition.onerror = stop;
  promptRecognition.start();
  promptDictating = true;
  els.cpDictate.textContent = "⏹ Parar";
  els.cpStatus.textContent = "Escuchando...";
}
```

- [ ] **Step 4: Cablear eventos y carga inicial en `app.js`**

En `app.js`, en la sección `// --- arranque ---` (junto a los otros `addEventListener` y las llamadas `loadTexts()` etc.), agregar:

```javascript
// Pantalla de prompts de conversacion.
els.cpGenerate.addEventListener("click", generateConversationPrompt);
els.cpSave.addEventListener("click", saveConversationPrompt);
els.cpCancel.addEventListener("click", clearConversationPromptForm);
els.cpDictate.addEventListener("click", togglePromptDictation);
if (!SpeechRecognition) {
  els.cpDictate.disabled = true;
  els.cpDictate.title = "Tu navegador no soporta dictado por voz.";
}
loadConversationPrompts();
```

- [ ] **Step 5: Agregar el ancho de los campos en `style.css`**

En `style.css`, junto a la regla `#conv-setup textarea, ...`, agregar:

```css
#view-conv-prompts textarea,
#view-conv-prompts input[type="text"] {
  width: 100%;
  box-sizing: border-box;
}
```

- [ ] **Step 6: Verificar sintaxis del JS**

Run: `node --check app.js`
Expected: sin salida (sin errores de sintaxis).

- [ ] **Step 7: Commit**

```bash
git add index.html app.js style.css
git commit -m "feat: pantalla Prompt de conversacion (generar, dictar, gestionar)"
```

---

### Task 5: Vista "Conversación" con selector de prompts (frontend)

**Files:**
- Modify: `index.html` (reemplazar textarea por selector + aviso "no hay prompts")
- Modify: `app.js` (els, `renderConversationPromptSelect`, `startConversation`, enlace del aviso)

**Interfaces:**
- Consumes: `conversationPromptsData` y `loadConversationPrompts()` de Task 4; `switchView` (ya existe).
- Produces (JS): `renderConversationPromptSelect()` (llamado desde `loadConversationPrompts`).

- [ ] **Step 1: Reemplazar el textarea por el selector en `index.html`**

En `index.html`, dentro de `#conv-setup`, reemplazar:

```html
          <label for="conv-prompt">Escenario (system prompt)</label>
          <textarea id="conv-prompt" rows="4"
            placeholder="Hazme preguntas en ingles sobre mi experiencia de trabajo, en pasado."></textarea>
```

por:

```html
          <div id="conv-no-prompts" class="hint hidden">
            No tienes prompts guardados. Crealos en la pestana
            <button type="button" class="link" data-goto="conv-prompts">Prompt de conversacion</button>.
          </div>
          <label for="conv-prompt-select">Prompt de conversacion</label>
          <select id="conv-prompt-select"></select>
```

- [ ] **Step 2: Actualizar `els` en `app.js`**

En `app.js`, en el objeto `els`, **quitar** la línea:

```javascript
  convPrompt: document.getElementById("conv-prompt"),
```

y **agregar**:

```javascript
  convPromptSelect: document.getElementById("conv-prompt-select"),
  convNoPrompts: document.getElementById("conv-no-prompts"),
```

- [ ] **Step 3: Agregar `renderConversationPromptSelect` en `app.js`**

En `app.js`, en la sección de conversación (cerca de `startConversation`), agregar:

```javascript
// Puebla el selector de prompts de la vista Conversacion con los prompts guardados,
// conservando la seleccion si sigue existiendo. Sin prompts: muestra el aviso y
// deshabilita "Empezar" (mismo patron que el selector de textos en Practicar).
function renderConversationPromptSelect() {
  const previous = els.convPromptSelect.value;
  els.convNoPrompts.classList.toggle("hidden", conversationPromptsData.length > 0);
  els.convPromptSelect.classList.toggle("hidden", conversationPromptsData.length === 0);

  els.convPromptSelect.innerHTML = "";
  for (const prompt of conversationPromptsData) {
    const option = document.createElement("option");
    option.value = prompt.id;
    option.textContent = prompt.name;
    els.convPromptSelect.appendChild(option);
  }
  if (conversationPromptsData.some((p) => String(p.id) === previous)) {
    els.convPromptSelect.value = previous;
  }
  els.convStart.disabled = conversationPromptsData.length === 0;
}
```

- [ ] **Step 4: Actualizar `startConversation` en `app.js`**

Reemplazar el arranque de `startConversation` que lee el textarea:

```javascript
async function startConversation() {
  els.convSetupError.classList.add("hidden");
  const systemPrompt = els.convPrompt.value.trim();
  const maxQuestions = Number(els.convQuestions.value);
  if (!systemPrompt) {
    els.convSetupError.textContent = "Escribe un escenario.";
    els.convSetupError.classList.remove("hidden");
    return;
  }
```

por (leyendo el prompt seleccionado de los datos cargados):

```javascript
async function startConversation() {
  els.convSetupError.classList.add("hidden");
  const selected = conversationPromptsData.find(
    (p) => String(p.id) === els.convPromptSelect.value
  );
  if (!selected) {
    els.convSetupError.textContent = "Elige un prompt de conversacion.";
    els.convSetupError.classList.remove("hidden");
    return;
  }
  const systemPrompt = selected.system_prompt;
  const maxQuestions = Number(els.convQuestions.value);
```

El resto de `startConversation` (validación de `maxQuestions`, el `fetch` a `/conversation/start` con `{ system_prompt: systemPrompt, max_questions: maxQuestions }`, y el manejo de respuesta) **no cambia**.

- [ ] **Step 5: Enlazar el aviso "no hay prompts" a su pestaña**

En `app.js`, en la sección `// --- arranque ---` (junto al handler equivalente de `els.noTexts`), agregar:

```javascript
// Enlace del aviso "no tienes prompts" que lleva a la pestana Prompt de conversacion.
els.convNoPrompts.addEventListener("click", (event) => {
  if (event.target.closest("button[data-goto]")) switchView("conv-prompts");
});
```

- [ ] **Step 6: Verificar sintaxis del JS**

Run: `node --check app.js`
Expected: sin salida (sin errores). En particular, ninguna referencia sobrante a `els.convPrompt`.

Run: `grep -n "els.convPrompt\b" app.js`
Expected: sin resultados (solo debe quedar `els.convPromptSelect`).

- [ ] **Step 7: Commit**

```bash
git add index.html app.js
git commit -m "feat: vista Conversacion usa selector de prompts guardados"
```

---

### Task 6: Verificación de integración e walkthrough manual

**Files:** ninguno (verificación).

- [ ] **Step 1: Suite completa verde**

Run: `uv run pytest -q`
Expected: toda la suite en verde.

- [ ] **Step 2: Chequeo de la generación real con Gemini**

Con `GEMINI_API_KEY` en `.env`, levantar el server (`uv run python main.py`) y en otra terminal:

Run:
```bash
curl -s -X POST localhost:8000/conversation/prompt/generate \
  -H "Content-Type: application/json" \
  -d '{"context":"Practicar una entrevista para un puesto backend; evalua mi vocabulario tecnico"}'
```
Expected: JSON `{"system_prompt": "..."}` con un escenario en inglés, sin preámbulo ni comillas.

- [ ] **Step 3: Walkthrough en Chrome**

Con `GEMINI_API_KEY` (y `AZURE_SPEECH_KEY` para el modo azure), en `http://localhost:8000`:

1. Pestaña **Prompt de conversacion**: escribir un contexto y/o **Dictar** por voz → el texto aparece en el cuadro.
2. **✨ Generar escenario** → aparece un escenario en inglés en el textarea editable; editarlo.
3. Poner nombre → **Guardar prompt** → aparece en la tabla. Probar **Editar** y **Borrar**.
4. Pestaña **Conversacion** con la base sin prompts: se ve el aviso "No tienes prompts…" y **Empezar** deshabilitado; el enlace lleva a la pestaña de prompts.
5. Con un prompt guardado: el selector lo muestra; elegirlo + Nº de preguntas + Fuente → **Empezar** → la conversación arranca con ese escenario y el flujo de voz/scoring/feedback funciona igual que antes.
6. Pestañas **Practicar, Textos, Banco de palabras, Historial** siguen intactas.

- [ ] **Step 4: Commit final (si hubo ajustes del walkthrough)**

```bash
git add -A
git commit -m "chore: ajustes del walkthrough de prompts de conversacion"
```
