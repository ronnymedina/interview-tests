"""Judge-human agreement: the crossing between hand labels and judge verdicts.

Metric A is only trustworthy if every case it drops says so out loud. A label that never
matched a verdict, a case left unlabelled, or two cases sharing a crossing key all used to
shrink the denominator in silence, which reads as a flawless judge over fewer cases. These
tests pin the loud behaviour, plus the confusion matrix the calibration is read from.
"""

import json

import pytest
import yaml

from app.evals import calibration


def a_label(n, veredicto, example_id=None, context=None, expected="safe"):
    return {
        "n": n,
        "id": example_id or f"id-{n}",
        "expected": expected,
        "context": context or f"context of case {n}",
        "mi_veredicto": veredicto,
    }


def a_verdict(n, juez, example_id=None, context=None, razon="because"):
    return {
        "example_id": example_id or f"id-{n}",
        "context": context or f"context of case {n}",
        "brief": f"brief of case {n}",
        "juez": juez,
        "razon": razon,
    }


@pytest.fixture
def run(tmp_path, monkeypatch, capsys):
    """Point the module at temporary files and return its stdout."""
    def _run(labels, verdicts):
        labels_file = tmp_path / "labels.yaml"
        judge_file = tmp_path / "judge.json"
        labels_file.write_text(yaml.safe_dump({"casos": labels}, allow_unicode=True))
        judge_file.write_text(json.dumps(verdicts, ensure_ascii=False))
        monkeypatch.setattr(calibration, "LABELS", labels_file)
        monkeypatch.setattr(calibration, "JUDGE", judge_file)
        calibration.main()
        return capsys.readouterr().out
    return _run


@pytest.mark.parametrize("raw, expected", [
    ("cumple", True), ("no cumple", False),
    (True, True), (False, False),
    ("1", True), ("0", False),
    ("si", True), ("sí", True), ("no", False),
    ("  CUMPLE  ", True),
    (None, None), ("", None), ("cumlpe", None),
])
def test_reads_the_hand_label_in_every_accepted_spelling(raw, expected):
    """A typo must land on None (unlabelled), never silently on one of the verdicts."""
    assert calibration.to_bool(raw) is expected


def test_agreement_and_the_confusion_matrix(run):
    """Both directions of disagreement are counted apart: false-pass is the dangerous one."""
    labels = [a_label(1, "cumple"), a_label(2, "no cumple"),
              a_label(3, "no cumple"), a_label(4, "cumple")]
    verdicts = [a_verdict(1, "cumple"), a_verdict(2, "no cumple"),
                a_verdict(3, "cumple"), a_verdict(4, "no cumple")]

    out = run(labels, verdicts)

    assert "Acuerdo: 2/4 = 0.50" in out
    assert "Falsos-pasa (PELIGROSO): 1" in out      # humano no cumple, juez cumple
    assert "Falsos-frena (sobre-rechazo): 1" in out  # humano cumple, juez no cumple
    assert "Desacuerdos (2)" in out


def test_crosses_by_example_id_when_both_sides_have_it(run):
    """The id wins over the context, so rewording a case does not break the crossing."""
    labels = [a_label(1, "cumple", context="the context as it was labelled")]
    verdicts = [a_verdict(1, "cumple", context="the context with different spacing")]

    out = run(labels, verdicts)

    assert "Cruce por example_id" in out
    assert "Acuerdo: 1/1 = 1.00" in out


def test_falls_back_to_the_context_when_an_id_is_missing(run):
    """Verdicts pulled before example_id was stored must still cross."""
    labels = [a_label(1, "cumple", context="same   context\nspaced  oddly")]
    verdicts = [{**a_verdict(1, "cumple", context="same context spaced oddly"),
                 "example_id": None}]

    out = run(labels, verdicts)

    assert "Cruce por context" in out
    assert "Acuerdo: 1/1 = 1.00" in out


def test_a_case_with_no_verdict_to_match_is_reported_not_dropped(run):
    """It leaves the metric, and the metric says over how many cases it was computed."""
    labels = [a_label(1, "cumple"), a_label(2, "cumple")]
    verdicts = [a_verdict(1, "cumple")]

    out = run(labels, verdicts)

    assert "1/2 caso(s) fuera de la metrica" in out
    assert "sin match en el juez:   n=2" in out
    assert "Acuerdo: 1/1 = 1.00" in out
    assert "Calculado sobre 1 de 2 casos" in out


def test_an_unlabelled_case_is_reported_instead_of_counting_as_disagreement(run):
    """Forgetting a label must not look like the judge got it wrong."""
    labels = [a_label(1, "cumple"), a_label(2, None)]
    verdicts = [a_verdict(1, "cumple"), a_verdict(2, "no cumple")]

    out = run(labels, verdicts)

    assert "sin 'mi_veredicto':     n=2" in out
    assert "Sin desacuerdos" in out
    assert "Acuerdo: 1/1 = 1.00" in out


def test_a_case_the_judge_never_scored_is_reported(run):
    """A run with no 'safety' feedback arrives as None and is not a disagreement either."""
    labels = [a_label(1, "cumple"), a_label(2, "cumple")]
    verdicts = [a_verdict(1, "cumple"), a_verdict(2, None)]

    out = run(labels, verdicts)

    assert "el juez no lo puntuo:   n=2" in out
    assert "Sin desacuerdos" in out


def test_two_cases_sharing_a_crossing_key_abort(run):
    """Without unique keys one case overwrites the other and leaves the metric unnoticed."""
    labels = [a_label(1, "cumple", example_id="dup"), a_label(2, "cumple", example_id="dup")]
    verdicts = [a_verdict(1, "cumple", example_id="dup")]

    with pytest.raises(SystemExit, match="comparten la clave de cruce"):
        run(labels, verdicts)


def test_no_comparable_case_is_an_error_not_an_agreement_of_zero(run):
    """0/0 would print as 0.00 and read like a broken judge rather than a broken crossing."""
    labels = [a_label(1, "cumple")]
    verdicts = [a_verdict(2, "cumple")]

    with pytest.raises(SystemExit, match="Ningun caso comparable"):
        run(labels, verdicts)
