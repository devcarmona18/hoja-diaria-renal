"""
Firma HMAC-SHA256 entre el puente local y la app.

El puente envía dos cabeceras HTTP:

    X-HL7-Timestamp: <segundos Unix>
    X-HL7-Firma:     sha256=<hex(HMAC_SHA256(secreto, "<timestamp>." + cuerpo))>

La app recalcula la firma con el mismo secreto compartido (HL7_BRIDGE_SECRET)
y rechaza la petición si no coincide o si el sello de tiempo está fuera de la
ventana permitida (protección contra repetición). Además, cada mensaje se
registra por su id de control (MSH-10), así que reenviar el mismo mensaje
dentro de la ventana no crea un segundo borrador (idempotencia).
"""
from __future__ import annotations

import hashlib
import hmac
import time

CABECERA_FIRMA = "X-HL7-Firma"
CABECERA_TIMESTAMP = "X-HL7-Timestamp"
VENTANA_DEFECTO = 300  # segundos

__all__ = ["CABECERA_FIRMA", "CABECERA_TIMESTAMP", "VENTANA_DEFECTO",
           "calcular_firma", "cabeceras_firmadas", "verificar_firma", "ErrorFirma"]


class ErrorFirma(ValueError):
    """Firma ausente, inválida o fuera de la ventana de tiempo."""


def calcular_firma(secreto: str, timestamp: str, cuerpo: bytes) -> str:
    mac = hmac.new(secreto.encode("utf-8"), timestamp.encode("ascii") + b"." + cuerpo, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def cabeceras_firmadas(secreto: str, cuerpo: bytes, ahora: float | None = None) -> dict[str, str]:
    """Cabeceras que el puente adjunta a cada POST."""
    ts = str(int(ahora if ahora is not None else time.time()))
    return {CABECERA_TIMESTAMP: ts, CABECERA_FIRMA: calcular_firma(secreto, ts, cuerpo)}


def verificar_firma(
    secreto: str,
    cuerpo: bytes,
    timestamp: str | None,
    firma: str | None,
    *,
    ventana: int = VENTANA_DEFECTO,
    ahora: float | None = None,
) -> None:
    """Lanza ErrorFirma si la firma no es válida o el sello de tiempo es viejo/futuro."""
    if not secreto:
        raise ErrorFirma("Secreto del puente no configurado")
    if not timestamp or not firma:
        raise ErrorFirma("Faltan las cabeceras de firma")
    try:
        ts = int(timestamp)
    except ValueError as e:
        raise ErrorFirma("Sello de tiempo inválido") from e
    ahora = ahora if ahora is not None else time.time()
    if abs(ahora - ts) > ventana:
        raise ErrorFirma("Sello de tiempo fuera de la ventana permitida")
    esperada = calcular_firma(secreto, str(ts), cuerpo)
    if not hmac.compare_digest(esperada.encode(), firma.strip().encode()):
        raise ErrorFirma("Firma inválida")
