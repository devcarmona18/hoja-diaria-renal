"""
MLLP (Minimal Lower Layer Protocol): cómo viajan los mensajes HL7 v2 por TCP.

Cada mensaje va enmarcado así:

    <VT=0x0B> mensaje HL7 <FS=0x1C><CR=0x0D>

Y el receptor contesta con un ACK (también enmarcado) cuyo segmento MSA dice:
  - AA: aceptado (Application Accept)
  - AE: error de aplicación (mensaje recibido pero con datos inválidos)
  - AR: rechazado (tipo no soportado, estructura irreconocible…)
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from .parser import MensajeHL7, Separadores, codificar_escapes, formatear_fecha_hora

INICIO = b"\x0b"
FIN = b"\x1c\x0d"
TAM_MAXIMO = 1024 * 1024  # 1 MiB: un ORU de fin de sesión pesa unos pocos KB

CodigoAck = Literal["AA", "AE", "AR"]

__all__ = [
    "INICIO", "FIN", "TAM_MAXIMO", "ErrorMLLP", "enmarcar", "desenmarcar",
    "LectorMLLP", "leer_mensaje", "construir_ack", "control_id_desde_texto",
    "codigo_ack",
]


class ErrorMLLP(ValueError):
    """Trama MLLP inválida o demasiado grande."""


def enmarcar(mensaje: str | bytes, codificacion: str = "utf-8") -> bytes:
    """Envuelve un mensaje HL7 en el marco MLLP."""
    datos = mensaje.encode(codificacion) if isinstance(mensaje, str) else mensaje
    if INICIO in datos or b"\x1c" in datos:
        raise ErrorMLLP("El mensaje contiene bytes de control MLLP")
    return INICIO + datos + FIN


def desenmarcar(trama: bytes) -> bytes:
    """Quita el marco MLLP de una trama completa. Lanza ErrorMLLP si no es válida."""
    inicio = trama.find(INICIO)
    if inicio == -1 or not trama.endswith(FIN):
        raise ErrorMLLP("Trama MLLP sin marco de inicio/fin")
    return trama[inicio + 1:-len(FIN)]


class LectorMLLP:
    """Acumula bytes recibidos por TCP y devuelve los mensajes completos.

    Descarta cualquier basura antes de 0x0B y limita el tamaño de cada mensaje.
    """

    def __init__(self, tam_maximo: int = TAM_MAXIMO) -> None:
        self._buffer = bytearray()
        self._tam_maximo = tam_maximo

    def alimentar(self, datos: bytes) -> list[bytes]:
        self._buffer.extend(datos)
        mensajes: list[bytes] = []
        while True:
            ini = self._buffer.find(INICIO)
            if ini == -1:
                self._buffer.clear()
                break
            if ini > 0:
                del self._buffer[:ini]
            fin = self._buffer.find(FIN, 1)
            if fin == -1:
                if len(self._buffer) > self._tam_maximo:
                    self._buffer.clear()
                    raise ErrorMLLP("Mensaje MLLP excede el tamaño máximo")
                break
            mensajes.append(bytes(self._buffer[1:fin]))
            del self._buffer[:fin + len(FIN)]
        return mensajes


async def leer_mensaje(reader: asyncio.StreamReader, tam_maximo: int = TAM_MAXIMO) -> bytes | None:
    """Lee un mensaje MLLP completo de un stream asyncio. None si se cerró la conexión."""
    try:
        trama = await reader.readuntil(FIN)
    except asyncio.IncompleteReadError:
        return None
    except asyncio.LimitOverrunError as e:
        raise ErrorMLLP("Mensaje MLLP excede el tamaño máximo") from e
    if len(trama) > tam_maximo:
        raise ErrorMLLP("Mensaje MLLP excede el tamaño máximo")
    return desenmarcar(trama)


_CONTROL_RE = re.compile(rb"^MSH(.)")


def control_id_desde_texto(datos: bytes | str) -> str:
    """Extrae MSH-10 a la fuerza (para responder AR aunque el mensaje no parsee)."""
    b = datos.encode("latin-1", "replace") if isinstance(datos, str) else datos
    b = b.lstrip(b"\x0b\r\n ")
    m = _CONTROL_RE.match(b)
    if not m:
        return ""
    sep = m.group(1)
    primera = re.split(rb"\r|\n", b, maxsplit=1)[0]
    partes = primera.split(sep)
    # partes[0]="MSH", partes[1]=MSH-2 … partes[9]=MSH-10
    return partes[9].decode("latin-1", "replace").strip()[:64] if len(partes) > 9 else ""


def construir_ack(
    codigo: CodigoAck,
    original: MensajeHL7 | None = None,
    *,
    control_id_original: str = "",
    texto: str = "",
    app: str = "HOJA-DIARIA",
    instalacion: str = "UNIDAD-RENAL",
    ahora: datetime | None = None,
) -> str:
    """Construye un ACK HL7 v2 (MSH + MSA [+ ERR]) en texto, sin enmarcar."""
    sep = original.separadores if original else Separadores()
    f = sep.campo
    ahora = ahora or datetime.now(timezone.utc)
    ctrl_orig = (original.control_id if original else control_id_original) or ""
    version = (original.version if original else "") or "2.5"
    evento = (original.evento if original else "") or "R01"
    destino_app = original.app_emisora if original else ""
    destino_inst = original.instalacion_emisora if original else ""
    proc = (original.id_procesamiento if original else "") or "P"
    esc = lambda s: codificar_escapes(s, sep)  # noqa: E731

    msh = f.join([
        "MSH", sep.caracteres_codificacion, esc(app), esc(instalacion),
        esc(destino_app), esc(destino_inst), formatear_fecha_hora(ahora), "",
        f"ACK{sep.componente}{evento}{sep.componente}ACK",
        "ACK" + uuid.uuid4().hex[:17].upper(), proc, version,
    ])
    msa = f.join(["MSA", codigo, esc(ctrl_orig), esc(texto[:80])])
    segmentos = [msh, msa]
    if codigo != "AA" and texto:
        severidad = "E"
        cod_err = "207" if codigo == "AE" else "200"
        segmentos.append(f.join(["ERR", "", "", f"{cod_err}{sep.componente}{esc(texto[:80])}", severidad]))
    return "\r".join(segmentos) + "\r"


def codigo_ack(ack: str | bytes) -> str:
    """Devuelve MSA-1 (AA/AE/AR/CA/CE/CR) de un ACK, o "" si no se encuentra."""
    t = ack.decode("utf-8", "replace") if isinstance(ack, bytes) else ack
    t = t.strip("\x0b\x1c\r\n")
    if not t.startswith("MSH") or len(t) < 4:
        return ""
    f = t[3]
    for linea in re.split(r"\r|\n", t):
        if linea.startswith("MSA" + f):
            partes = linea.split(f)
            return partes[1] if len(partes) > 1 else ""
    return ""
