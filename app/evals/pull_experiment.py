"""Trae una corrida terminada DIRECTO de LangSmith: los briefs congelados Y los
veredictos reales del juez. NO re-corre el sintetizador y NO re-puntúa el juez;
lee lo que ya quedó guardado en el experimento. Un comando, reusable.

  uv run python -m app.evals.pull_experiment [nombre_experimento]

'nombre_experimento' es el 'session_name' que imprime run_langsmith_eval al
terminar (p. ej. synthesizer-v2-2026-08-21-xxxxxxxx). Por defecto usa el baseline v1.
"""
import json
import sys
from pathlib import Path

from langsmith import Client

import config  # noqa: F401  -> load_dotenv: LANGSMITH_API_KEY, etc.

DEFAULT_EXP = "synthesizer-v1-2026-08-20-71606909"
OUT = Path(__file__).resolve().parent / "juez_veredictos.json"


def main() -> None:
    exp = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXP
    client = Client()
    rows, passes = [], 0
    for run in client.list_runs(project_name=exp, is_root=True):
        context = (run.inputs or {}).get("context")
        brief = (run.outputs or {}).get("brief")
        score, comment = None, None
        for fb in client.list_feedback(run_ids=[run.id]):
            if fb.key == "safety":          # la clave del evaluador del juez
                score, comment = fb.score, fb.comment
                break
        if score == 1:
            passes += 1
        rows.append({
            "context": context,
            "brief": brief,
            "juez": "cumple" if score == 1 else ("no cumple" if score == 0 else None),
            "juez_score": score,
            "razon": comment,
        })
    n = len(rows)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Pull de '{exp}': {n} casos | juez 'cumple' {passes}/{n} "
          f"(avg {passes/n:.2f} -> deberia dar 0.53)")
    print(f"Escrito: {OUT}")


if __name__ == "__main__":
    main()
