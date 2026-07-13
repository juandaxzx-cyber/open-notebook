"""Task-boundary marker parsing (PR-E2 part a)."""

from tutor.session.markers import parse_task_marker


def test_no_marker_returns_none_and_original() -> None:
    label, cleaned = parse_task_marker("Sigue con el mismo problema, ¿cuánto da?")
    assert label is None
    assert cleaned == "Sigue con el mismo problema, ¿cuánto da?"


def test_marker_at_start_is_extracted_and_stripped() -> None:
    label, cleaned = parse_task_marker(
        "[[TASK: derivar sin(x^2)]]\nAhora deriva sin(x^2)."
    )
    assert label == "derivar sin(x^2)"
    assert "[[TASK" not in cleaned
    assert cleaned == "Ahora deriva sin(x^2)."


def test_marker_mid_text_is_extracted() -> None:
    label, cleaned = parse_task_marker(
        "Bien pensado. [[TASK: regla de la cadena]] Prueba con cos(3x)."
    )
    assert label == "regla de la cadena"
    assert "[[TASK" not in cleaned
    assert "Bien pensado." in cleaned and "cos(3x)" in cleaned


def test_marker_is_case_and_space_insensitive() -> None:
    label, _ = parse_task_marker("[[ task :  Etiqueta Rara  ]] texto")
    assert label == "Etiqueta Rara"


def test_only_first_marker_counts_extras_stripped() -> None:
    label, cleaned = parse_task_marker("[[TASK: uno]] a [[TASK: dos]] b")
    assert label == "uno"
    assert "[[TASK" not in cleaned


def test_empty_label_treated_as_no_task() -> None:
    label, cleaned = parse_task_marker("[[TASK:  ]] cuerpo")
    assert label is None
    assert "[[TASK" not in cleaned
