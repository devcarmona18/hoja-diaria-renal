"""
Parser mínimo y robusto de mensajes HL7 v2.x (pensado para ORU^R01).

No depende de librerías externas. Soporta:
  - Separadores definidos por el propio mensaje (MSH-1 y MSH-2).
  - Segmentos separados por <CR> (estándar), y también <LF> o <CR><LF>.
  - Secuencias de escape: \\F\\ \\S\\ \\T\\ \\R\\ \\E\\ \\Xhh..\\ \\.br\\ (y se
    descartan \\H\\ \\N\\ y otras de formato).
  - Repeticiones, componentes y subcomponentes.
  - Varios OBX por mensaje, valores numéricos (NM), numéricos estructurados
    (SN, p. ej. «^130^/^80» para tensión arterial) y texto (ST/TX/FT/CE/CWE).
  - Fechas HL7 (DTM/TS) con precisión parcial y zona horaria opcional.

Convención de índices: igual que en la norma. `segmento.campo(3)` es PID-3.
En MSH, MSH-1 es el separador de campo y MSH-2 los caracteres de codificación.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

__all__ = [
    "ErrorHL7",
    "Separadores",
    "Segmento",
    "Observacion",
    "MensajeHL7",
    "parsear",
    "decodificar_escapes",
    "codificar_escapes",
    "parsear_fecha_hora",
    "parsear_numero",
    "formatear_fecha_hora",
]


class ErrorHL7(ValueError):
    """El texto recibido no es un mensaje HL7 v2 válido o le faltan datos clave."""


@dataclass(frozen=True)
class Separadores:
    """Caracteres delimitadores declarados en MSH-1 / MSH-2."""

    campo: str = "|"
    componente: str = "^"
    repeticion: str = "~"
    escape: str = "\\"
    subcomponente: str = "&"

    @property
    def caracteres_codificacion(self) -> str:
        """Valor de MSH-2 (p. ej. «^~\\&»)."""
        return self.componente + self.repeticion + self.escape + self.subcomponente


_NOMBRE_SEGMENTO = re.compile(r"^[A-Z][A-Z0-9]{2}$")
_ESCAPE_FORMATO = re.compile(r"^(H|N|\.sp\d*|\.in[+-]?\d*|\.ti[+-]?\d*|\.ce|\.fi|\.nf|\.sk\d*|C[0-9A-Fa-f]{4}|M[0-9A-Fa-f]{6}|Z.*)$")


# ── Escapes ──────────────────────────────────────────────────────────────────

def decodificar_escapes(texto: str, sep: Separadores) -> str:
    """Reemplaza las secuencias de escape HL7 por los caracteres que representan."""
    e = sep.escape
    if not e or e not in texto:
        return texto
    salida: list[str] = []
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c != e:
            salida.append(c)
            i += 1
            continue
        fin = texto.find(e, i + 1)
        if fin == -1:  # escape sin cerrar: se conserva literal
            salida.append(texto[i:])
            break
        codigo = texto[i + 1:fin]
        if codigo == "F":
            salida.append(sep.campo)
        elif codigo == "S":
            salida.append(sep.componente)
        elif codigo == "T":
            salida.append(sep.subcomponente)
        elif codigo == "R":
            salida.append(sep.repeticion)
        elif codigo == "E":
            salida.append(sep.escape)
        elif codigo == ".br":
            salida.append("\n")
        elif codigo.startswith("X") and len(codigo) > 1 and len(codigo) % 2 == 1:
            try:
                salida.append(bytes.fromhex(codigo[1:]).decode("latin-1"))
            except ValueError:
                salida.append(texto[i:fin + 1])
        elif _ESCAPE_FORMATO.match(codigo):
            pass  # secuencias de formato/resaltado: se descartan
        else:
            salida.append(texto[i:fin + 1])  # desconocida: literal
        i = fin + 1
    return "".join(salida)


def codificar_escapes(texto: str, sep: Separadores = Separadores()) -> str:
    """Escapa los delimitadores para insertar texto libre dentro de un campo HL7."""
    t = texto.replace(sep.escape, f"{sep.escape}E{sep.escape}")
    t = t.replace(sep.campo, f"{sep.escape}F{sep.escape}")
    t = t.replace(sep.componente, f"{sep.escape}S{sep.escape}")
    t = t.replace(sep.subcomponente, f"{sep.escape}T{sep.escape}")
    t = t.replace(sep.repeticion, f"{sep.escape}R{sep.escape}")
    return t.replace("\r\n", "\n").replace("\r", "\n").replace("\n", f"{sep.escape}.br{sep.escape}")


# ── Tipos de dato ────────────────────────────────────────────────────────────

_FECHA = re.compile(
    r"^(?P<y>\d{4})(?P<m>\d{2})?(?P<d>\d{2})?(?P<H>\d{2})?(?P<M>\d{2})?(?P<S>\d{2})?"
    r"(?:\.(?P<f>\d{1,6}))?(?P<tz>[+-]\d{4})?$"
)


def parsear_fecha_hora(valor: str) -> datetime | None:
    """Convierte un DTM/TS HL7 (YYYY[MM[DD[HH[MM[SS[.S]]]]]][±ZZZZ]) en datetime.

    Devuelve None si está vacío o no es una fecha válida. Si trae zona horaria
    el resultado es «aware»; si no, es «naive» (hora local de la máquina).
    """
    v = (valor or "").strip()
    if not v:
        return None
    m = _FECHA.match(v)
    if not m:
        return None
    try:
        dt = datetime(
            int(m["y"]), int(m["m"] or 1), int(m["d"] or 1),
            int(m["H"] or 0), int(m["M"] or 0), int(m["S"] or 0),
            int((m["f"] or "0").ljust(6, "0")),
        )
    except ValueError:
        return None
    if m["tz"]:
        signo = 1 if m["tz"][0] == "+" else -1
        horas, minutos = int(m["tz"][1:3]), int(m["tz"][3:5])
        dt = dt.replace(tzinfo=timezone(signo * timedelta(hours=horas, minutes=minutos)))
    return dt


def formatear_fecha_hora(dt: datetime) -> str:
    """datetime → DTM HL7 (YYYYMMDDHHMMSS[±ZZZZ])."""
    base = dt.strftime("%Y%m%d%H%M%S")
    if dt.tzinfo is not None:
        base += dt.strftime("%z")
    return base


def parsear_numero(valor: str) -> float | None:
    """Número HL7 (NM). Acepta coma decimal si no hay punto. None si no es numérico."""
    v = (valor or "").strip()
    if not v:
        return None
    if "," in v and "." not in v:
        v = v.replace(",", ".")
    try:
        n = float(v)
    except ValueError:
        return None
    if n != n or n in (float("inf"), float("-inf")):  # NaN / infinito
        return None
    return n


# ── Estructuras ──────────────────────────────────────────────────────────────

@dataclass
class Segmento:
    """Un segmento HL7. `campos[n]` es el campo n en crudo (aún escapado)."""

    nombre: str
    campos: list[str]
    sep: Separadores

    def campo(self, n: int) -> str:
        """Campo n en crudo (sin decodificar escapes). Cadena vacía si no existe."""
        return self.campos[n] if 0 <= n < len(self.campos) else ""

    def repeticiones(self, n: int) -> list[str]:
        """Repeticiones del campo n (en crudo)."""
        crudo = self.campo(n)
        if self.nombre == "MSH" and n in (1, 2):
            return [crudo]
        return crudo.split(self.sep.repeticion) if crudo else []

    def componentes(self, n: int, rep: int = 0) -> list[str]:
        """Componentes (decodificados) de la repetición `rep` del campo n."""
        if self.nombre == "MSH" and n in (1, 2):
            return [self.campo(n)]
        reps = self.repeticiones(n)
        if rep >= len(reps):
            return []
        return [decodificar_escapes(c.split(self.sep.subcomponente)[0], self.sep)
                for c in reps[rep].split(self.sep.componente)]

    def valor(self, n: int, comp: int = 1, sub: int = 1, rep: int = 0) -> str:
        """Valor decodificado de PID-n.comp.sub (índices desde 1, como en la norma)."""
        if self.nombre == "MSH" and n in (1, 2):
            return self.campo(n) if comp == 1 and sub == 1 else ""
        reps = self.repeticiones(n)
        if rep >= len(reps):
            return ""
        comps = reps[rep].split(self.sep.componente)
        if comp - 1 >= len(comps):
            return ""
        subs = comps[comp - 1].split(self.sep.subcomponente)
        if sub - 1 >= len(subs):
            return ""
        return decodificar_escapes(subs[sub - 1], self.sep)

    def texto(self, n: int) -> str:
        """Campo completo decodificado (útil para campos de texto libre)."""
        return decodificar_escapes(self.campo(n), self.sep)


@dataclass
class Observacion:
    """Un OBX ya interpretado."""

    set_id: str
    tipo_valor: str                 # OBX-2: NM, SN, ST, TX, CE, CWE…
    identificador: str              # OBX-3.1
    texto: str                      # OBX-3.2
    sistema: str                    # OBX-3.3 (p. ej. «LN» LOINC o local)
    sub_id: str                     # OBX-4
    valor: str                      # OBX-5 decodificado (repeticiones unidas con el separador «~»)
    valores: list[str]              # OBX-5: cada repetición decodificada por separado
    valor_numerico: float | None    # OBX-5 como número (NM o primer número de SN)
    valor_sn: tuple[str, float | None, str, float | None] | None  # SN: (comparador, n1, separador, n2)
    unidad: str                     # OBX-6.1
    rango_referencia: str           # OBX-7
    banderas: str                   # OBX-8
    estado: str                     # OBX-11 (F=final, P=preliminar, C=corrección…)
    fecha_hora: datetime | None     # OBX-14

    @classmethod
    def desde_segmento(cls, s: Segmento) -> "Observacion":
        tipo = s.valor(2).upper()
        reps = s.repeticiones(5)
        valores = [decodificar_escapes(r, s.sep) for r in reps]
        valor_sn = None
        numerico: float | None = None
        if tipo == "SN":
            c = s.componentes(5)
            c += [""] * (4 - len(c))
            valor_sn = (c[0], parsear_numero(c[1]), c[2], parsear_numero(c[3]))
            numerico = valor_sn[1]
            valores = ["".join(x for x in c if x)]
        elif tipo in ("CE", "CWE", "CNE"):
            # Valor codificado: se guarda el texto (componente 2) si existe, si no el código.
            c = s.componentes(5)
            valores = [(c[1] if len(c) > 1 and c[1] else (c[0] if c else ""))]
        elif tipo == "NM" or tipo == "":
            numerico = parsear_numero(valores[0]) if valores else None
        return cls(
            set_id=s.valor(1),
            tipo_valor=tipo,
            identificador=s.valor(3, 1),
            texto=s.valor(3, 2),
            sistema=s.valor(3, 3),
            sub_id=s.valor(4),
            valor=s.sep.repeticion.join(valores),
            valores=valores,
            valor_numerico=numerico,
            valor_sn=valor_sn,
            unidad=s.valor(6, 1),
            rango_referencia=s.valor(7),
            banderas=s.valor(8),
            estado=s.valor(11),
            fecha_hora=parsear_fecha_hora(s.valor(14)),
        )


@dataclass
class MensajeHL7:
    """Mensaje HL7 v2 parseado."""

    separadores: Separadores
    segmentos: list[Segmento] = field(default_factory=list)

    # ── Acceso genérico ──
    def todos(self, nombre: str) -> list[Segmento]:
        return [s for s in self.segmentos if s.nombre == nombre]

    def primero(self, nombre: str) -> Segmento | None:
        return next((s for s in self.segmentos if s.nombre == nombre), None)

    @property
    def msh(self) -> Segmento:
        return self.segmentos[0]

    # ── Encabezado (MSH) ──
    @property
    def app_emisora(self) -> str:
        return self.msh.valor(3)

    @property
    def instalacion_emisora(self) -> str:
        return self.msh.valor(4)

    @property
    def app_receptora(self) -> str:
        return self.msh.valor(5)

    @property
    def instalacion_receptora(self) -> str:
        return self.msh.valor(6)

    @property
    def fecha_hora(self) -> datetime | None:
        return parsear_fecha_hora(self.msh.valor(7))

    @property
    def tipo(self) -> str:
        return self.msh.valor(9, 1).upper()

    @property
    def evento(self) -> str:
        return self.msh.valor(9, 2).upper()

    @property
    def control_id(self) -> str:
        return self.msh.valor(10).strip()

    @property
    def id_procesamiento(self) -> str:
        return self.msh.valor(11)

    @property
    def version(self) -> str:
        return self.msh.valor(12, 1)

    # ── Paciente (PID) ──
    def id_paciente(self, campo: int = 3, componente: int = 1) -> str:
        """Identificador del paciente según la máquina (por defecto PID-3.1)."""
        pid = self.primero("PID")
        return pid.valor(campo, componente).strip() if pid else ""

    # ── Orden / sesión (OBR) ──
    @property
    def inicio_observacion(self) -> datetime | None:
        """OBR-7: inicio de la sesión de diálisis."""
        obr = self.primero("OBR")
        return parsear_fecha_hora(obr.valor(7)) if obr else None

    @property
    def fin_observacion(self) -> datetime | None:
        """OBR-8: fin de la sesión de diálisis."""
        obr = self.primero("OBR")
        return parsear_fecha_hora(obr.valor(8)) if obr else None

    # ── Observaciones (OBX) ──
    @property
    def observaciones(self) -> list[Observacion]:
        return [Observacion.desde_segmento(s) for s in self.todos("OBX")]

    def validar_oru_r01(self) -> None:
        """Lanza ErrorHL7 si no es un ORU^R01 utilizable (tipo, control, PID, OBX)."""
        if self.tipo != "ORU" or self.evento not in ("R01", ""):
            raise ErrorHL7(f"Tipo de mensaje no soportado: {self.tipo}^{self.evento}")
        if not self.control_id:
            raise ErrorHL7("MSH-10 (id de control) vacío")
        if not self.primero("PID"):
            raise ErrorHL7("Falta el segmento PID")
        if not self.todos("OBX"):
            raise ErrorHL7("El mensaje no trae observaciones OBX")


# ── Entrada principal ────────────────────────────────────────────────────────

def _a_texto(datos: str | bytes) -> str:
    if isinstance(datos, str):
        return datos
    try:
        return datos.decode("utf-8")
    except UnicodeDecodeError:
        return datos.decode("latin-1")  # muchos equipos usan ISO-8859-1


def parsear(datos: str | bytes) -> MensajeHL7:
    """Parsea un mensaje HL7 v2. Lanza ErrorHL7 si la estructura es inválida."""
    texto = _a_texto(datos).strip("\x0b\x1c\r\n \t\x00")
    if not texto.startswith("MSH"):
        raise ErrorHL7("El mensaje debe empezar con el segmento MSH")
    if len(texto) < 8:
        raise ErrorHL7("Segmento MSH incompleto")

    sep_campo = texto[3]
    if sep_campo.isalnum() or sep_campo in "\r\n":
        raise ErrorHL7("Separador de campo (MSH-1) inválido")
    fin_cod = texto.find(sep_campo, 4)
    codif = texto[4:fin_cod] if fin_cod != -1 else texto[4:]
    if not 2 <= len(codif) <= 5 or any(c.isalnum() or c in "\r\n" for c in codif) \
            or len(set(codif[:4] + sep_campo)) != len(codif[:4]) + 1:
        raise ErrorHL7("Caracteres de codificación (MSH-2) inválidos")
    defecto = Separadores()
    sep = Separadores(
        campo=sep_campo,
        componente=codif[0],
        repeticion=codif[1] if len(codif) > 1 else defecto.repeticion,
        escape=codif[2] if len(codif) > 2 else "",
        subcomponente=codif[3] if len(codif) > 3 else defecto.subcomponente,
    )

    lineas = [l for l in re.split(r"\r\n|\r|\n", texto) if l.strip()]
    segmentos: list[Segmento] = []
    for num, linea in enumerate(lineas, start=1):
        nombre = linea[:3]
        if not _NOMBRE_SEGMENTO.match(nombre) or (len(linea) > 3 and linea[3] != sep.campo):
            raise ErrorHL7(f"Segmento inválido en la línea {num}")
        partes = linea.split(sep.campo)
        if nombre == "MSH":
            if num != 1:
                raise ErrorHL7("MSH repetido dentro del mensaje")
            campos = ["MSH", sep.campo] + partes[1:]
        else:
            campos = partes
        segmentos.append(Segmento(nombre=nombre, campos=campos, sep=sep))

    msg = MensajeHL7(separadores=sep, segmentos=segmentos)
    if len(msg.msh.campos) < 10:
        raise ErrorHL7("MSH no trae tipo de mensaje (MSH-9)")
    return msg
