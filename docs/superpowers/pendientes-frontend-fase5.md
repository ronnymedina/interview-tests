# Pendientes del frontend (piloto) — para una task futura

Registrados el 2026-08-02, tras completar la Fase 5. NO implementados todavía; se abordan en otra task.

## 1. El óvalo tutor: forma y color

- **Forma:** hoy es un óvalo (elipse vertical) que "parece un huevo". El usuario lo quiere **más redondo** (tender a círculo), no tan alargado.
- **Color:** el **dorado** (`--gold #b8963f` / gradiente del óvalo) no le gusta. Cambiar el color del óvalo (y probablemente revisar el acento dorado en general).
- Archivo: `app/web/index.html` → CSS `.oval` (gradiente, dimensiones 132×168 → acercar a proporción circular) y tokens `--gold`/`--gold-deep`.

## 2. Paleta de fondo (crema/blanco)

- El blanco/crema actual se siente "plano/pálido" ("paco"). El usuario quiere algo **más claro pero no tan blanco** — no supo describirlo con precisión.
- **PENDIENTE DE INPUT:** el usuario dijo que **traerá un ejemplo / referencia de estilo** (mencionó algo como un "estilo diseño wrapo" — confirmar a qué se refiere: ¿un estilo "warm", una referencia visual concreta, un sitio?). Esperar esa referencia antes de rediseñar la paleta.
- Archivo: `app/web/index.html` → tokens `:root` (`--cream`, `--ivory`).

## 3. Render de Markdown en la pantalla final

- El feedback de Gemini (`final.content_feedback`) viene en **Markdown** (usa headings y bullets), pero el frontend lo pinta como **texto plano** (`$("feedback").textContent = ...` con `.prose { white-space: pre-wrap }`), así que los `#`, `-`, `**` se ven literales y no resaltan.
- **Arreglo:** renderizar el Markdown a HTML (parser ligero, sin dependencias pesadas; o un mini-render de headings/bold/listas) y estilarlo para que se lea bien.
- Archivo: `app/web/index.html` → `showFinal` (la línea del feedback) + CSS `.prose`.

## 4. Palabras clicables sin señal de que se pueden escuchar

- En la pantalla final, las palabras para practicar (pills) **suenan al hacer clic**, pero **no hay indicativo visual** de que son clicables/reproducibles. Si el usuario no lo intenta, no se entera.
- **Arreglo:** agregar una affordance clara — p. ej. un ícono de altavoz 🔊 en cada pill, y/o un texto guía más visible ("Toca una palabra para escucharla" ya existe pero no basta), hover/tooltip, cursor pointer explícito.
- Archivo: `app/web/index.html` → `renderWords` + CSS `.pill`.
