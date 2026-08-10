# Revisor separado del tutor — diseño

Fecha: 2026-08-09

## Objetivo

Convertir el nodo `review` en un agente con identidad propia: su propio system prompt, su
propio modelo y temperatura, y un contexto reducido que no arrastra ni el prompt del tutor
ni el material que pegó el alumno.

Hoy `review` hereda `state["messages"]` completo y usa la misma instancia de LLM que el
nodo `ask`. Eso trae tres problemas:

1. **Contaminación de rol.** El prompt del tutor dice literalmente "Do NOT give corrections
   or feedback DURING the conversation" y "Keep turns short, warm, natural". Cuando el
   revisor corre, el modelo lleva N turnos condicionado a ser breve, cálido y a no
   corregir, y se le pide exactamente lo contrario.
2. **Autoevaluación.** Los turnos del tutor entran como `AIMessage`, o sea, como respuestas
   propias del modelo. Un modelo juzgando su propio historial es más indulgente que uno que
   recibe la misma conversación como material ajeno.
3. **Un solo perfil de generación.** El tutor gana con temperatura alta (preguntas variadas
   y naturales); el revisor gana con temperatura baja (evaluación estable y reproducible).
   Con una sola instancia hay que elegir uno.

También prepara el terreno para lo que viene: revisores especializados por foco de
evaluación (`v1_reviewer_past_tense.md`, etc.), seleccionables por nombre de prompt.

## Alcance

Entra:

- Separar la instancia de LLM del nodo `review` de la del nodo `ask`.
- System prompt propio del revisor, en archivo.
- Contexto reducido: transcripción como dato + los `### Puntos` del brief.
- Settings de modelo y temperatura por rol.
- Corregir el wording que trata el `### Contexto` como si fuera un CV.

No entra:

- **El sintetizador.** Conserva la instancia que devuelve `build_llm()` sin argumentos, o
  sea, exactamente el comportamiento de hoy (temperatura por default del proveedor). Que
  corra a temperatura alta cuando su trabajo es copiar el material sin inventar es un
  problema preexistente, no algo que introduzca este cambio.
- **Precios por modelo.** Ver "Limitaciones conocidas".
- **Selección de revisor especializado.** Se crea el slot (`v1_reviewer_general.md`) sin la
  maquinaria de selección.
- **Validación del material que pega el alumno.** Pendiente, sin fecha.

## Decisiones tomadas

### El revisor recibe la transcripción como dato, no como historial

Se descartó reusar `state["messages"]` reemplazando solo el `SystemMessage`. Los turnos del
tutor seguirían entrando como `AIMessage` y el problema 2 quedaría intacto.

La entrada del revisor es:

```
SystemMessage(v1_reviewer_general.md)
HumanMessage(
    "### Points to evaluate\n"
    "<sección ### Puntos del brief>\n\n"
    "### Transcript\n"
    "Tutor: What did you work on last week?\n"
    "Learner: I worked in a API for payments.\n"
    ...
)
```

Sin el prompt del tutor y sin la sección `### Contexto`. El material que pegó el alumno
sirve para elegir de qué conversar, no para juzgar su inglés, y puede ser largo.

### Tres roles, tres instancias de LLM

```
build_llm()                                 → Synthesizer  (sin cambios)
build_llm(CHAT_MODEL, CHAT_TEMPERATURE)     → nodo ask
build_llm(REVIEW_CHAT_MODEL or CHAT_MODEL,
          REVIEW_TEMPERATURE)               → nodo review
```

`build_llm` gana dos parámetros opcionales y llamado sin argumentos se comporta como hoy:

```python
def build_llm(model: str = "", temperature: float | None = None):
    ...
    kwargs = {} if temperature is None else {"temperature": temperature}
    return init_chat_model(model or settings.CHAT_MODEL, api_key=..., **kwargs)
```

`REVIEW_CHAT_MODEL` arranca vacío y cae a `CHAT_MODEL`: el costo por token no cambia hasta
que se decida subir el revisor a un modelo más potente, y eso es una línea en el `.env`.

### El prompt del revisor lleva la regla de precedencia desde el día uno

`v1_reviewer_general.md` absorbe el `_FEEDBACK_INSTRUCTION` actual y le agrega lo que hoy no
tiene: rol propio (evaluador, no tutor) y precedencia explícita — el prompt define el foco de
evaluación y los `### Puntos` del alumno lo refinan, no lo contradicen.

Esa regla no hace falta hoy, pero sí el día que existan revisores especializados: van a
convivir dos canales diciendo qué evaluar (el prompt elegido y el texto libre del alumno) y
tiene que estar definido cuál gana.

### El `### Contexto` no es un CV

Es cualquier contenido que pegue el usuario. El wording actual ("CV, a post, their
experience") aparece en `v1_tutor_system.md` y en la instrucción del sintetizador, y sugiere
que el CV es el caso canónico. Se corrige en ambos y el prompt nuevo nace correcto. Es un
ajuste de redacción; no cambia el comportamiento del sintetizador.

## Componentes

| Archivo | Cambio |
|---|---|
| `config.py` | `CHAT_TEMPERATURE`, `REVIEW_CHAT_MODEL`, `REVIEW_TEMPERATURE` |
| `docs/ENVS.md` | Las tres filas nuevas |
| `prompts/v1_reviewer_general.md` | Nuevo: system prompt del revisor |
| `prompts/v1_tutor_system.md` | Wording del `### Contexto` |
| `prompts/__init__.py` | Constante `REVIEWER_GENERAL` |
| `conversation/graph.py` | `build_graph(tutor_llm, review_llm, ...)`; `review` arma su entrada; muere `_FEEDBACK_INSTRUCTION` |
| `conversation/messages.py` | `render_transcript(messages) -> str` |
| `conversation/synthesizer.py` | `focus_points(brief) -> str`; wording de `_INSTRUCTION` |
| `conversation/service.py` | `build_llm(model, temperature)`; `build_service` arma las tres instancias |
| `limits/cost.py` | `NOTE` sobre el supuesto de un solo modelo |

### `render_transcript(messages)`

Descarta los `SystemMessage` y el primer `HumanMessage` (el brief), y devuelve la
conversación etiquetada:

```
Tutor: What did you work on last week?
Learner: I worked in a API for payments.
```

Vive en `messages.py`, junto a `content_text`, porque opera sobre la lista de mensajes de
LangChain y no sabe nada del dominio.

### `focus_points(brief)`

Devuelve la sección `### Puntos` del brief. Vive en `synthesizer.py` porque es el módulo que
define y documenta ese formato. Es una función pura de lectura: no toca el comportamiento
del sintetizador.

## Manejo de errores

**No hay ruta de degradación nueva.** Los dos modelos usan la misma `GEMINI_API_KEY` y
`REVIEW_CHAT_MODEL` cae a `CHAT_MODEL`, así que los modos de falla son los de hoy: sin clave,
`build_service` levanta `ConversationError` y `server.py` deja el servicio en `None` con 503
en sus endpoints.

`focus_points` cae al brief completo si no encuentra el marcador `### Contexto`. Un brief
malformado degrada a "el revisor ve más contexto del necesario", nunca a "el revisor no sabe
qué evaluar".

`render_transcript` sobre una conversación sin turnos devuelve string vacío. No es un caso
alcanzable por el flujo real (`review` corre recién con `questions_asked >= max_questions`,
y `max_questions >= 1` por el esquema Pydantic), pero el helper no asume.

## Testing

- `render_transcript`: descarta el system y el brief, etiqueta los turnos, tolera una lista
  vacía.
- `focus_points`: extrae la sección; cae al brief completo cuando falta el marcador.
- Nodo `review` con un doble de LLM: los mensajes que recibe **no** contienen el prompt del
  tutor ni el `### Contexto`, y sí contienen la transcripción y los `### Puntos`.
- `build_llm`: pasa `temperature` cuando se le da y la omite cuando no; `REVIEW_CHAT_MODEL`
  vacío cae a `CHAT_MODEL`.
- `prompts.load(prompts.REVIEWER_GENERAL)` carga y conserva su contrato.

Los tests existentes de `build_llm` deben seguir pasando sin tocarlos: es la prueba de que
la firma nueva es compatible hacia atrás.

## Limitaciones conocidas

**El costo estimado asume un solo modelo.** `gemini_cost_usd` aplica un único par
`GEMINI_PRICE_INPUT_PER_1K` / `GEMINI_PRICE_OUTPUT_PER_1K`, y `_gemini_tokens` en
`server.py` suma los tokens de todos los modelos que intervinieron en el turno. Mientras
tutor y revisor compartan modelo, la cuenta es correcta.

Al poner `REVIEW_CHAT_MODEL` en un modelo más caro, el presupuesto **subestima**: los tokens
del revisor se cobran a la tarifa del tutor. Arreglarlo es cambiar el par de precios por un
mapa `modelo → (precio_in, precio_out)` y que `_gemini_tokens` devuelva el desglose en vez
de agregar — `callback.usage_metadata` ya viene indexado por nombre de modelo, así que el
dato está disponible. Queda registrado como `NOTE` en `app/limits/cost.py`.
