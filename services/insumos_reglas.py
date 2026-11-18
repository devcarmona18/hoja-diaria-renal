"""
Motor de reglas del pedido de insumos (R5/R6). Funciones PURAS: no tocan la BD.

Las reglas son datos (JSON). Las por defecto viven en ``insumos_reglas.json``
junto a este archivo; el administrador puede reemplazarlas (tabla
``insumos_config``, ver services/insumos.py). Formato:

    {
      "version": 1,
      "insumos":   { "<código>": {"nombre": "...", "unidad": "...", "detalle": "..."} },
      "faltantes": { "<campo>": "mensaje cuando el paciente no tiene ese dato" },
      "reglas": [
        {"insumo": "<código>", "si": {<condiciones>}, "cantidad": <entero | [casos]>}
      ]
    }

* Un código puede llevar marcadores ``{calibre}`` (calibre de aguja de la FAV) o
  ``{filtro}`` (filtro del paciente): ``aguja_fav_{calibre}`` → ``aguja_fav_16``.
  Si el paciente no tiene ese dato NO se adivina: se omite esa línea y se agrega el
  aviso de ``faltantes`` («Calibre faltante»).
* ``cantidad`` es un entero o una lista de casos ``{"si": {...}, "cantidad": n}``;
  gana el primer caso que cumpla (un caso sin ``si`` siempre cumple). Cantidad 0 =
  no se pide.
* Condiciones (todas deben cumplirse): ``acceso`` [FAV, CY], ``sitio`` [yugular,
  femoral], ``estado_fav`` [limpia, …], ``turno`` [M, T, N], ``dia_semana``
  [lunes … sábado], ``citrato`` / ``heparina_sodica`` /
  ``citrato_o_heparina_sodica`` (true/false).
* Si dos reglas dan el mismo insumo, las cantidades se suman.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

RUTA_POR_DEFECTO = Path(__file__).with_name("insumos_reglas.json")

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_DIAS_SIN_TILDE = {"miercoles": "miércoles", "sabado": "sábado"}
MARCADORES = {"calibre", "filtro"}
_RE_MARCADOR = re.compile(r"\{(\w+)\}")
AVISO_SIN_ACCESO = "Acceso vascular faltante"


# ── Esquema de las reglas (validación del JSON) ───────────────────────────────

class Condicion(BaseModel):
    model_config = {"extra": "forbid"}

    acceso: Optional[list[str]] = None
    sitio: Optional[list[str]] = None
    estado_fav: Optional[list[str]] = None
    turno: Optional[list[str]] = None
    dia_semana: Optional[list[str]] = None
    citrato: Optional[bool] = None
    heparina_sodica: Optional[bool] = None
    citrato_o_heparina_sodica: Optional[bool] = None

    @field_validator("dia_semana")
    @classmethod
    def _dias(cls, v):
        if v is None:
            return v
        out = []
        for d in v:
            d2 = _DIAS_SIN_TILDE.get(str(d).strip().lower(), str(d).strip().lower())
            if d2 not in DIAS:
                raise ValueError(f"día inválido: {d!r} (use lunes … sábado)")
            out.append(d2)
        return out


class Caso(BaseModel):
    model_config = {"extra": "forbid"}
    si: Condicion = Field(default_factory=Condicion)
    cantidad: int = Field(ge=0, le=100)


class Regla(BaseModel):
    model_config = {"extra": "forbid"}
    insumo: str = Field(min_length=1, max_length=60)
    si: Condicion = Field(default_factory=Condicion)
    cantidad: Union[int, list[Caso]]
    nota: Optional[str] = None

    @field_validator("cantidad")
    @classmethod
    def _cant(cls, v):
        if isinstance(v, int) and not 0 <= v <= 100:
            raise ValueError("cantidad debe estar entre 0 y 100")
        if isinstance(v, list) and not v:
            raise ValueError("la lista de casos no puede estar vacía")
        return v


class Insumo(BaseModel):
    model_config = {"extra": "forbid"}
    nombre: str = Field(min_length=1, max_length=120)
    unidad: str = Field("unidad", min_length=1, max_length=30)
    detalle: Optional[str] = Field(None, max_length=120)


class Reglas(BaseModel):
    model_config = {"extra": "forbid"}
    version: int = 1
    descripcion: Optional[str] = None
    insumos: dict[str, Insumo]
    faltantes: dict[str, str] = Field(default_factory=dict)
    reglas: list[Regla]

    @model_validator(mode="after")
    def _coherencia(self):
        for codigo, ins in self.insumos.items():
            usados = set(_RE_MARCADOR.findall(codigo)) | set(_RE_MARCADOR.findall(ins.nombre))
            if usados - MARCADORES:
                raise ValueError(f"insumo {codigo!r}: marcador desconocido "
                                 f"{sorted(usados - MARCADORES)} (use {{calibre}} o {{filtro}})")
        for i, r in enumerate(self.reglas, 1):
            if r.insumo not in self.insumos:
                raise ValueError(f"regla {i}: el insumo {r.insumo!r} no está en el catálogo «insumos»")
        return self


def cargar_por_defecto() -> Reglas:
    return Reglas.model_validate(json.loads(RUTA_POR_DEFECTO.read_text(encoding="utf-8")))


def validar(datos: dict) -> Reglas:
    """Valida un dict de reglas (lanza pydantic.ValidationError si no es válido)."""
    return Reglas.model_validate(datos)


# ── Cálculo ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DatosPaciente:
    """Lo que las reglas necesitan saber del paciente en una sesión."""
    acceso: Optional[str]
    calibre: Optional[int] = None
    filtro: Optional[str] = None
    citrato: bool = False
    heparina_sodica: bool = False
    sitio: Optional[str] = None
    estado_fav: Optional[str] = None
    turno: Optional[str] = None


@dataclass
class Linea:
    codigo: str
    nombre: str
    cantidad: int
    unidad: str
    detalle: Optional[str] = None

    def como_dict(self) -> dict:
        return {"codigo": self.codigo, "nombre": self.nombre, "cantidad": self.cantidad,
                "unidad": self.unidad, "detalle": self.detalle}


@dataclass
class Resultado:
    lineas: list[Linea] = field(default_factory=list)
    alertas: list[str] = field(default_factory=list)


def nombre_dia(dia: date) -> str:
    return DIAS[dia.weekday()]


def cumple(cond: Condicion, p: DatosPaciente, dia: date) -> bool:
    """¿El paciente cumple TODAS las condiciones ese día?"""
    def en(lista, valor):
        return lista is None or valor in lista
    especial = bool(p.citrato or p.heparina_sodica)
    return (en(cond.acceso, p.acceso) and en(cond.sitio, p.sitio)
            and en(cond.estado_fav, p.estado_fav) and en(cond.turno, p.turno)
            and en(cond.dia_semana, nombre_dia(dia))
            and (cond.citrato is None or cond.citrato == bool(p.citrato))
            and (cond.heparina_sodica is None or cond.heparina_sodica == bool(p.heparina_sodica))
            and (cond.citrato_o_heparina_sodica is None or cond.citrato_o_heparina_sodica == especial))


def cantidad_de(regla: Regla, p: DatosPaciente, dia: date) -> int:
    if isinstance(regla.cantidad, int):
        return regla.cantidad
    for caso in regla.cantidad:
        if cumple(caso.si, p, dia):
            return caso.cantidad
    return 0


def _valores(p: DatosPaciente) -> dict:
    filtro = (p.filtro or "").strip() or None
    return {"calibre": p.calibre, "filtro": filtro}


def _expandir(texto: str, valores: dict) -> str:
    return _RE_MARCADOR.sub(lambda m: str(valores[m.group(1)]), texto)


def calcular(p: DatosPaciente, dia: date, reglas: Reglas) -> Resultado:
    """Insumos de UN paciente para UNA sesión en `dia`. Orden = orden de las reglas."""
    res = Resultado()
    if not p.acceso:
        res.alertas.append(AVISO_SIN_ACCESO)
        return res
    valores = _valores(p)
    por_codigo: dict[str, Linea] = {}
    for regla in reglas.reglas:
        if not cumple(regla.si, p, dia):
            continue
        n = cantidad_de(regla, p, dia)
        if n <= 0:
            continue
        ins = reglas.insumos[regla.insumo]
        faltan = [m for m in _RE_MARCADOR.findall(regla.insumo + ins.nombre) if valores.get(m) is None]
        if faltan:
            for m in dict.fromkeys(faltan):
                aviso = reglas.faltantes.get(m) or f"{m.capitalize()} faltante"
                if aviso not in res.alertas:
                    res.alertas.append(aviso)
            continue
        codigo = _expandir(regla.insumo, valores)
        if codigo in por_codigo:
            por_codigo[codigo].cantidad += n
            continue
        linea = Linea(codigo=codigo, nombre=_expandir(ins.nombre, valores), cantidad=n,
                      unidad=ins.unidad, detalle=ins.detalle)
        por_codigo[codigo] = linea
        res.lineas.append(linea)
    return res


def sumar(lineas_por_fila) -> list[Linea]:
    """Totales por insumo (orden de primera aparición)."""
    tot: dict[str, Linea] = {}
    for lineas in lineas_por_fila:
        for li in lineas:
            if li.codigo in tot:
                tot[li.codigo].cantidad += li.cantidad
            else:
                tot[li.codigo] = Linea(li.codigo, li.nombre, li.cantidad, li.unidad, li.detalle)
    return list(tot.values())
