from __future__ import annotations

from auralwarden.transcribers.base import ScriptedTranscriber


DEMO_LINES = [
    ("Speaker 1", "Buenos días. Iniciamos esta transmisión de prueba de AuralWarden."),
    ("Speaker 2", "La nueva licitación se publicará esta semana con sus documentos."),
    ("Speaker 1", "Si alguien solicita ayuda, AuralWarden prepara una alerta local."),
    ("Speaker 3", "El contrato se transcribe con hablantes y marcas de tiempo."),
    ("Speaker 2", "Esta licitación demuestra la detección de una frase configurada."),
    ("Speaker 1", "Cuando exista una coincidencia se preparará un clip local de audio."),
    ("Speaker 3", "El tiempo anterior y posterior será editable desde la aplicación."),
    ("Speaker 2", "La grabación completa del audio será una decisión independiente."),
    ("Speaker 1", "Al cerrar se podrá guardar o descartar esta transcripción temporal."),
]


def create_demo_transcriber() -> ScriptedTranscriber:
    return ScriptedTranscriber(DEMO_LINES.copy())
