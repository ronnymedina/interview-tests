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

## Notas de seguridad

- La unica variable **sensible** es `AZURE_SPEECH_KEY`. Tratala como una contrasena.
- Si crees que tu key quedo expuesta, rotala en el portal de Azure
  (*Keys and Endpoint* → *Regenerate Key*) y actualiza tu `.env`.
- El resto de variables (region, idioma, ruta de DB, puerto) no son secretas.
