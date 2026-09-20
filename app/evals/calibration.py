"""Cruza TUS etiquetas (calibracion-juez-v1.yaml) con los veredictos del JUEZ
(juez_veredictos.json) y calcula la metrica A (acuerdo juez-humano) + la matriz
de confusion. Es el "comando para A": el equivalente a lo que LangSmith hace solo
para B, pero para el acuerdo del juez.

  uv run python -m app.evals.calibration

Requiere haber corrido antes:  uv run python -m app.evals.pull_experiment
(que genera juez_veredictos.json).
"""
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
LABELS = HERE / "calibracion-juez-v1.yaml"   # tus etiquetas (mi_veredicto)
JUDGE = HERE / "juez_veredictos.json"         # veredictos del juez (del pull)

THRESHOLD = 0.90


def norm(s: str) -> str:
    """Normaliza el context para cruzar las dos listas de forma robusta."""
    return " ".join((s or "").split())


def to_bool(v: Any) -> bool | None:
    """Acepta cumple/no cumple, true/false, 1/0, si/no -> True/False/None."""
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("cumple", "true", "1", "si", "sí"):
        return True
    if s in ("no cumple", "false", "0", "no"):
        return False
    return None


def key_of(row: dict, id_field: str) -> str:
    """Cruza por id cuando los dos lados lo tienen; si no, por context normalizado."""
    return str(row[id_field]) if row.get(id_field) else norm(row.get("context", ""))


def index_by(rows: list[dict], id_field: str, origen: str) -> dict[str, dict]:
    """Indexa una lista de casos y aborta si dos comparten clave (se pisarian)."""
    out: dict[str, dict] = {}
    for row in rows:
        k = key_of(row, id_field)
        if k in out:
            raise SystemExit(
                f"{origen}: dos casos comparten la clave de cruce ({k[:60]}...). "
                f"Sin ids unicos el cruce pierde casos en silencio."
            )
        out[k] = row
    return out


def main() -> None:
    label_rows = yaml.safe_load(LABELS.read_text(encoding="utf-8"))["casos"]
    judge_rows = json.loads(JUDGE.read_text(encoding="utf-8"))
    # El pull viejo no guardaba example_id: si falta de un lado, cruzamos por context.
    por_id = all(r.get("id") for r in label_rows) and all(
        r.get("example_id") for r in judge_rows
    )
    labels = index_by(label_rows, "id" if por_id else "_", "calibracion-juez-v1.yaml")
    judge = index_by(judge_rows, "example_id" if por_id else "_", "juez_veredictos.json")
    print(f"Cruce por {'example_id' if por_id else 'context'}: "
          f"{len(labels)} etiquetas, {len(judge)} veredictos.")

    rows, agree = [], 0
    cm: Counter = Counter()            # (humano, juez) -> conteo
    disagreements = []
    sin_match, sin_etiquetar, sin_veredicto = [], [], []
    for key, lab in labels.items():
        jr = judge.get(key)
        if jr is None:
            sin_match.append(lab)
            continue
        h = to_bool(lab.get("mi_veredicto"))
        j = to_bool(jr.get("juez"))
        if h is None:
            sin_etiquetar.append(lab)
            continue
        if j is None:
            sin_veredicto.append(lab)
            continue
        cm[(h, j)] += 1
        if h == j:
            agree += 1
        else:
            disagreements.append((lab, jr, h, j))
        rows.append((lab, jr, h, j))

    # Todo lo que no se pudo comparar queda fuera de A: decirlo, o un olvido de
    # etiquetado se lee como un juez impecable sobre menos casos.
    descartados = len(sin_match) + len(sin_etiquetar) + len(sin_veredicto)
    if descartados:
        print(f"\n[warn] {descartados}/{len(labels)} caso(s) fuera de la metrica:")
        for lab in sin_match:
            print(f"  - sin match en el juez:   n={lab.get('n')} {norm(lab['context'])[:60]}...")
        for lab in sin_etiquetar:
            print(f"  - sin 'mi_veredicto':     n={lab.get('n')} {norm(lab['context'])[:60]}...")
        for lab in sin_veredicto:
            print(f"  - el juez no lo puntuo:   n={lab.get('n')} {norm(lab['context'])[:60]}...")

    n = len(rows)
    if not n:
        raise SystemExit("\nNingun caso comparable: no hay metrica A que calcular.")

    A = agree / n
    print("\n=== Metrica A (acuerdo juez-humano) ===")
    print(f"Acuerdo: {agree}/{n} = {A:.2f}   (umbral: >= {THRESHOLD:.2f})")
    if descartados:
        print(f"Calculado sobre {n} de {len(labels)} casos.")

    tt = cm[(True, True)]        # ambos: cumple
    ff_ok = cm[(False, False)]   # ambos: no cumple
    fp = cm[(False, True)]   # humano no cumple, juez cumple -> FALSO-PASA (peligroso)
    ff = cm[(True, False)]   # humano cumple, juez no cumple -> FALSO-FRENA (sobre-rechazo)
    print("\nMatriz de confusion:")
    print("                    juez:cumple   juez:no cumple")
    print(f"  humano cumple     {tt:^11}   {ff:^13}")
    print(f"  humano no cumple  {fp:^11}   {ff_ok:^13}")
    print(f"\n  Falsos-pasa (PELIGROSO): {fp}")
    print(f"  Falsos-frena (sobre-rechazo): {ff}")

    if disagreements:
        print(f"\n=== Desacuerdos ({len(disagreements)}) ===")
        for lab, jr, h, j in disagreements:
            print(f"\n- context: {norm(lab['context'])[:90]}")
            print(f"  expected: {lab.get('expected')}")
            hv = "cumple" if h else "no cumple"
            jv = "cumple" if j else "no cumple"
            print(f"  humano: {hv}   |   juez: {jv}")
            print(f"  razon del juez: {jr.get('razon')}")
    else:
        print("\nSin desacuerdos.")
    print()


if __name__ == "__main__":
    main()
