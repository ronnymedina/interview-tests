"""Sintetizador del brief de sesión.

Toma lo que el alumno configuró (texto libre: qué quiere practicar, su CV, un post, etc.)
y lo reescribe SIEMPRE al mismo molde de dos secciones, que luego entra como primer
`HumanMessage` de la conversación (ver `graph.initial_state`):

    ### Puntos que quiero estudiar y sobre los que debo recibir feedback
    - ...

    ### Contexto
    ...

Que el formato sea fijo permite que el tutor sepa dónde está el foco y que el paso de
feedback evalúe justamente los `### Puntos`, sin listas hardcodeadas en el grafo.
"""

from langchain_core.messages import HumanMessage

from .messages import content_text

# Meta-instrucción para el LLM sintetizador. Conserva todo el detalle (no resume) y fuerza
# EXACTAMENTE las dos secciones del brief.
_INSTRUCTION = (
    "You are a prompt engineer for a spoken English practice app. Take the learner's raw input "
    "and rewrite it into a session brief with EXACTLY these two Markdown sections and nothing "
    "else:\n\n"
    "### Puntos que quiero estudiar y sobre los que debo recibir feedback\n"
    "- (one bullet per English aspect the learner wants to work on; keep them in Spanish)\n\n"
    "### Contexto\n"
    "(the material to ground the conversation: CV, a post, their experience. PRESERVE EVERY "
    "concrete detail — never shorten or summarize away, never invent facts not in the input.)\n\n"
    "Output only the brief, with no preamble, no title and no quotes. Learner's input:\n\n"
)


class Synthesizer:
    """Convierte texto libre del alumno en un brief con formato fijo, usando un LLM.

    Recibe el LLM por inyección de dependencia, así es fácil de testear con un doble.
    """

    def __init__(self, llm) -> None:
        self._llm = llm

    def synthesize(self, context: str) -> str:
        """Devuelve el brief sintetizado (### Puntos + ### Contexto) a partir del contexto libre.

        No valida el contexto: eso lo hace el esquema Pydantic del endpoint antes de llegar acá.
        """
        return content_text(self._llm.invoke([HumanMessage(_INSTRUCTION + context)]))
