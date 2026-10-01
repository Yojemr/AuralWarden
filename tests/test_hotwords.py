from auralwarden.hotwords import HotwordDetector, normalize_text
from auralwarden.models import Hotword


def test_normalization_is_case_and_accent_insensitive() -> None:
    assert normalize_text("  TRANSMISIÓN, pública  ") == "transmision publica"


def test_exact_hotword_detection() -> None:
    detector = HotwordDetector([Hotword("proyecto")])
    matches = detector.find_matches("El proyecto se ejecuta localmente.")
    assert [match.phrase for match in matches] == ["proyecto"]


def test_disabled_hotword_is_ignored() -> None:
    detector = HotwordDetector([Hotword("alerta", enabled=False)])
    assert detector.find_matches("Esta alerta está desactivada.") == []


def test_phrase_can_cross_transcript_boundary() -> None:
    detector = HotwordDetector([Hotword("palabra clave")])

    matches = detector.find_boundary_matches(
        "La siguiente palabra", "clave será importante"
    )

    assert len(matches) == 1
    assert matches[0].phrase == "palabra clave"
    assert matches[0].matched_text == "palabra clave"
    assert matches[0].exact is True


def test_boundary_detection_does_not_repeat_match_inside_one_fragment() -> None:
    detector = HotwordDetector([Hotword("palabra clave")])

    assert detector.find_boundary_matches(
        "Una introducción", "La palabra clave aparece completa"
    ) == []


def test_phrase_can_cross_more_than_two_transcript_fragments() -> None:
    detector = HotwordDetector([Hotword("esta es la palabra clave")])

    matches = detector.find_boundary_matches(
        "inicio esta es la palabra", "clave final"
    )

    assert [match.phrase for match in matches] == ["esta es la palabra clave"]
