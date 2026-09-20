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

import yaml

HERE = Path(__file__).resolve().parent
LABELS = HERE / "calibracion-juez-v1.yaml"   # tus etiquetas (mi_veredicto)
JUDGE = HERE / "juez_veredictos.json"         # veredictos del juez (del pull)


def norm(s: str) -> str:
    """Normaliza el context para cruzar las dos listas de forma robusta."""
    return " ".join((s or "").split())


def to_bool(v):
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


def main() -> None:
    labels = {
        norm(c["context"]): c
        for c in yaml.safe_load(LABELS.read_text(encoding="utf-8"))["casos"]
    }
    judge = {
        norm(r["context"]): r
        for r in json.loads(JUDGE.read_text(encoding="utf-8"))
    }

    rows, agree = [], 0
    cm: Counter = Counter()            # (humano, juez) -> conteo
    disagreements = []
    for key, lab in labels.items():
        jr = judge.get(key)
        if jr is None:
            print(f"[warn] sin match en el juez: {key[:60]}...")
            continue
        h = to_bool(lab.get("mi_veredicto"))
        j = to_bool(jr.get("juez"))
        cm[(h, j)] += 1
        if h == j:
            agree += 1
        else:
            disagreements.append((lab, jr, h, j))
        rows.append((lab, jr, h, j))

    n = len(rows)
    A = agree / n if n else 0.0
    print("\n=== Metrica A (acuerdo juez-humano) ===")
    print(f"Acuerdo: {agree}/{n} = {A:.2f}   (umbral: >= 0.90)")

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
            hv = "cumple" if h else ("no cumple" if h is not None else "?")
            jv = "cumple" if j else ("no cumple" if j is not None else "?")
            print(f"  humano: {hv}   |   juez: {jv}")
            print(f"  razon del juez: {jr.get('razon')}")
    else:
        print("\nSin desacuerdos.")
    print()


if __name__ == "__main__":
    main()
