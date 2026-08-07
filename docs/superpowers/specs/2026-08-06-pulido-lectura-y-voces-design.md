# Pulido de la práctica de lectura, voces compartidas y filtro por nivel — diseño

Fecha: 2026-08-06
Estado: aprobado, pendiente de plan de implementación

Continúa [2026-08-06-practica-lectura-fase2-design.md](2026-08-06-practica-lectura-fase2-design.md),
ya implementada. Recoge lo que apareció al usar la pantalla por primera vez.

## Objetivo

Cinco cosas, de las cuales dos son defectos reales y tres son mejoras:

1. El 🔊 de cada palabra no funciona en la pantalla de lectura (defecto).
2. El texto de referencia pierde los saltos de párrafo del artículo original (defecto).
3. El selector de voz pasa de un `<select>` a tres botones, con solo las tres voces de Google.
4. Desaparecen las menciones al proveedor de evaluación en el texto que ve el usuario.
5. El usuario puede pedir un texto de nivel máximo N, en vez de aceptar cualquiera.

## Fuera de alcance

El rediseño de la navegación entre modalidades (hoy poco visible) queda para después: es una
decisión de estilo visual que merece verse antes de elegirse.

## 1. El 🔊 de las palabras, y `Tts` compartido

**El síntoma:** en `app/web/static/reading.js` el callback de pronunciación está vacío:

```javascript
renderWord(word, () => {})
```

**Por qué está vacío:** el objeto `Tts` (*text to speech*: la función del navegador que lee un
texto en voz alta) está escrito dentro de `index.html`, la página de la conversación. La
página de lectura no lo ve, así que no había nada que poner ahí.

**Por qué no basta con moverlo a `shared.js`:** `Tts` lee la voz y el ritmo del DOM de la
conversación.

```javascript
const v = this.voices[Number($("voice").value)] || null;
u.rate = Number($("rate").value);
```

En la pantalla de lectura esos elementos no existen: `$("voice")` devuelve `null` y la línea
falla. Además contradice la regla que `shared.js` declara en su cabecera desde la fase 1:
*"acá NO se referencian ids del DOM propios de una página"*.

### La solución: un módulo de preferencias

Se crea `app/web/static/prefs.js`, **el único lugar que sabe dónde viven las preferencias del
usuario**. Hoy las guarda en `localStorage`; si mañana pasan a la base de datos detrás de un
endpoint, solo cambia ese archivo — ni `Tts`, ni la conversación, ni la lectura se enteran.

```javascript
const Prefs = {
  voiceName() { return localStorage.getItem("pilot_voice") || "Google US English"; },
  setVoiceName(name) { localStorage.setItem("pilot_voice", name); },
  rate() { return Number(localStorage.getItem("pilot_rate") || 0.95); },
  setRate(value) { localStorage.setItem("pilot_rate", String(value)); },
  maxLevel() { return Number(localStorage.getItem("pilot_max_level") || 7); },
  setMaxLevel(level) { localStorage.setItem("pilot_max_level", String(level)); },
};
```

`Tts` se muda a `shared.js` y pide los valores a `Prefs`, con lo que deja de depender del DOM
y de conocer ningún almacenamiento concreto. Los controles de cada página solo *escriben* en
`Prefs`. Con eso, `renderWord(word, (t) => Tts.speak(t))` funciona en las dos pantallas.

**`pilot_voice` cambia de formato.** Hoy guarda un número: la *posición* de la voz en la lista
del navegador. Si cambia el orden de las voces instaladas, ese número apunta a otra voz. Pasa
a guardar el **nombre** (`"Google US English"`), que es estable y además significa algo si
algún día viaja a un endpoint. Un valor viejo (numérico) no coincide con ningún nombre, así
que cae al default sin romper nada.

En `base.html` los scripts cargan en orden: `prefs.js`, `shared.js`, y el de cada página.

## 2. Los párrafos del texto de referencia

**El síntoma:** el panel muestra un bloque de texto corrido, sin separación entre párrafos.

**La causa:** `make_excerpt` parte el cuerpo en oraciones y las vuelve a unir con un espacio:

```python
excerpt = f"{excerpt} {sentence}".strip() if excerpt else sentence
```

Los artículos de Engoo traen saltos de párrafo (entre 10 y 24 por cuerpo en el catálogo
actual) y ese `join` los borra todos.

**El arreglo:** en vez de reconstruir el texto, cortarlo. Se calcula en qué posición del cuerpo
original hay que cortar y se devuelve ese prefijo. El texto sale intacto, con sus saltos de
línea y sus espacios.

Sigue siendo una función pura y determinista, que es lo que sostiene el diseño sin caché de la
fase 2: el servidor recalcula el extracto al evaluar y obtiene exactamente el mismo texto.

`reading.js` pinta un `<p>` por párrafo, y lo mismo al repintar el panel con las omisiones
tachadas: la vista de review conserva los párrafos en lugar de aplanarlos.

## 3. El selector de voz: tres botones

Desaparecen el `<select id="voice">` y su `<label>`. En su lugar, tres botones tipo píldora:

| Botón | Voz |
|---|---|
| 🇺🇸 US | `Google US English` |
| 🇬🇧 UK F | `Google UK English Female` |
| 🇬🇧 UK M | `Google UK English Male` |

El activo se marca con la clase `.on`, que ya existe en `app.css`. El slider de ritmo se queda
igual, escribiendo ahora en `Prefs.setRate()`.

**Solo Chrome.** Esas tres voces solo existen en Chrome, y esta versión no intenta disimularlo:
no hay fallback ni botones deshabilitados. El aviso azul que ya existe pasa de recomendación a
requisito: *"Esta versión funciona solo en Google Chrome en computadora: las voces y el dictado
por voz dependen de él."*

El título del panel del texto de referencia gana además un botón **🔊 Escuchar**, que lee el
extracto con la voz elegida. Mientras suena pasa a **⏹ Detener**. Se corta solo al pedir otro
texto o al empezar a grabar: no tiene sentido que la voz siga leyendo con el micrófono abierto.

## 4. El panel del texto de referencia

- **El título entra al panel.** Hoy es el `<h1>` de la página, lejos del texto al que
  pertenece. Pasa a estar dentro del panel izquierdo, en negrita, encima del texto. El `<h1>`
  vuelve a ser fijo: "Lectura en voz alta".
- **La meta se pega al título.** Debajo, en pequeño y gris: el badge de nivel y el enlace
  *Artículo original ↗*. Hoy el enlace cuelga a media frase del subtítulo, lejos de lo que
  describe.
- **Sin menciones al proveedor.** *"Al terminar, Azure te dice qué palabras fallaste"* pasa a
  *"Al terminar te decimos qué palabras fallaste"*, y en `index.html` *"su score de Azure"* pasa
  a *"su score"*. Son los dos únicos textos visibles que nombran al proveedor; no hay ninguno
  que mencione a Gemini. Las demás apariciones de "Azure" son comentarios de código, que se
  quedan: explican de dónde salen los datos a quien programa y no las ve ningún usuario.

## 5. Filtro por nivel máximo

El catálogo se puebla con niveles 4 a 7. Quien está en un 4 o 5 no quiere que le toque un 7.

**El control:** junto a "Otro texto", un selector *"Nivel máximo"* con 4, 5, 6 y 7. Es un
**tope**, no un nivel exacto: pedir 5 puede devolver un 4 o un 5. Un nivel exacto agotaría el
catálogo antes y no resuelve nada mejor — el problema es que se vaya por arriba, no que varíe.
La elección se guarda en `Prefs`, así que sobrevive a recargar.

**Por dentro:** `GET /reading/random?max_level=5`. El repositorio pasa de `random()` a
`random(max_level: int | None = None)`, que añade `WHERE level <= %s` cuando venga. El índice
`reading_texts_level_idx` de la fase 1 es exactamente el que sirve para esto.

**Los textos sin nivel quedan fuera cuando se filtra.** `level` es nullable a propósito ("no sé
el nivel" ≠ "nivel 0"). Si pides "5 o menos", un texto de nivel desconocido podría ser un 8, así
que no entra. Sin filtro entran todos, como hoy.

**Si no hay ninguno, 503 con el motivo.** *"No hay textos de nivel N o menos en el catálogo.
Prueba subiendo el nivel máximo."* Devolver un texto de nivel más alto sería ignorar lo que el
usuario pidió, que es justamente lo que venimos a arreglar.

**Validación:** `max_level` es un entero de 1 a 10; fuera de rango o no numérico da 422, que
FastAPI produce solo con anotar el tipo y las cotas.

## Pruebas

`make_excerpt` es lo único con test automatizado. Tiene ocho (cinco casos concretos y tres
propiedades con Hypothesis) y gana dos propiedades más:

- **El extracto es un prefijo literal del cuerpo** (salvo el `strip` de los extremos). Es la
  garantía de que no se pierde ni un espacio ni un salto de línea.
- **Si hay un salto de párrafo dentro del recorte, el extracto lo conserva.**

Las ocho existentes siguen valiendo, en particular la de determinismo, de la que depende que no
haga falta caché del extracto.

Además: el repositorio en memoria gana el filtro por nivel y sus casos (respeta el tope, excluye
los de nivel desconocido, sin filtro devuelve cualquiera); el servicio, que propaga el
parámetro; y el endpoint, que un `max_level` inválido da 422 y que sin parámetro se comporta
como hoy.

El frontend no tiene infraestructura de test en este proyecto, así que se verifica a mano en
Chrome: los tres botones de voz cambian la voz y la elección sobrevive al recargar; el 🔊 de una
palabra suena en lectura; Escuchar lee el texto y Detener lo corta; los párrafos se ven
separados antes y después de evaluar; y el selector de nivel no devuelve textos por encima del
tope.
