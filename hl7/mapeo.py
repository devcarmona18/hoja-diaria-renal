"""
Mapeo configurable: observaciones OBX del AK 98 → campos de la Hoja Diaria.

La tabla vive en `hl7/mapeo_ak98.json` para poder ajustarla sin tocar código.

    ¡ATENCIÓN! Los identificadores OBX-3 incluidos (AK98-PESO-PRE, AK98-KTV…)
    son PROVISIONALES. Deben confirmarse con la especificación de interfaz HL7
    del fabricante del AK 98 antes de cualquier uso real.

Campos de destino soportados (unidades internas):
    peso_entrada (kg), peso_salida (kg), uf_litros (L), ktv,
    ta_sistolica / ta_diastolica (mmHg) — o «tension» como SN «^130^/^80» o «130/80»,
    frecuencia_cardiaca (lpm), duracion_min (min),
    alarmas (lista de textos), observaciones (texto libre).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from .parser import MensajeHL7, Observacion

RUTA_DEFECTO = Path(__file__).with_name("mapeo_ak98.json")

CAMPOS_NUMERICOS = (
    "peso_entrada", "peso_salida", "uf_litros", "ktv",
    "ta_sistolica", "ta_diastolica", "frecuencia_cardiaca", "duracion_min",
)

__all__ = ["RUTA_DEFECTO", "CAMPOS_NUMERICOS", "ResultadoMapeo", "cargar_mapeo",
           "aplicar_mapeo", "determinar_turno"]


@dataclass
class ResultadoMapeo:
    """Valores extraídos de un ORU, listos para crear un borrador."""

    id_paciente: str = ""
    inicio: datetime | None = None
    fin: datetime | None = None
    fecha: str | None = None           # YYYY-MM-DD (hora local de la unidad)
    turno: str | None = None           # M, T, N
    valores: dict[str, Any] = field(default_factory=dict)
    no_mapeados: list[str] = field(default_factory=list)   # identificadores OBX-3 desconocidos
    advertencias: list[str] = field(default_factory=list)


def cargar_mapeo(ruta: str | Path | None = None) -> dict[str, Any]:
    """Lee el JSON de mapeo (por defecto hl7/mapeo_ak98.json)."""
    with open(ruta or RUTA_DEFECTO, encoding="utf-8") as fh:
        datos = json.load(fh)
    if not isinstance(datos.get("observaciones"), dict):
        raise ValueError("El mapeo debe tener un objeto 'observaciones'")
    return datos


def _zona(mapeo: dict[str, Any]) -> timezone:
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", str(mapeo.get("zona_horaria", "-05:00")))
    if not m:
        return timezone(timedelta(hours=-5))
    signo = 1 if m[1] == "+" else -1
    return timezone(signo * timedelta(hours=int(m[2]), minutes=int(m[3])))


def _a_local(dt: datetime, mapeo: dict[str, Any]) -> datetime:
    """Hora local de la unidad, sin tzinfo (las fechas sin zona se asumen locales)."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(_zona(mapeo)).replace(tzinfo=None)


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def determinar_turno(dt: datetime, mapeo: dict[str, Any]) -> tuple[str, str | None]:
    """(fecha ISO, turno) para una hora de inicio de sesión según la tabla de turnos."""
    local = _a_local(dt, mapeo)
    t = local.time().replace(second=0, microsecond=0)
    for r in mapeo.get("turnos", []):
        desde, hasta = _hhmm(r["desde"]), _hhmm(r["hasta"])
        if desde <= hasta:
            if desde <= t <= hasta:
                return local.date().isoformat(), r["turno"]
        else:  # cruza la medianoche
            if t >= desde:
                return local.date().isoformat(), r["turno"]
            if t <= hasta:
                return (local.date() - timedelta(days=1)).isoformat(), r["turno"]
    return local.date().isoformat(), None


def _factor(regla: dict[str, Any], unidad: str) -> float | None:
    unidades: dict[str, float] = regla.get("unidades") or {"": 1}
    if unidad in unidades:
        return float(unidades[unidad])
    for k, v in unidades.items():
        if k.lower() == unidad.lower():
            return float(v)
    return None


_TENSION = re.compile(r"^\s*(\d{2,3}(?:[.,]\d+)?)\s*/\s*(\d{2,3}(?:[.,]\d+)?)\s*$")


def _tension(obx: Observacion) -> tuple[float, float] | None:
    if obx.valor_sn and obx.valor_sn[1] is not None and obx.valor_sn[3] is not None:
        return obx.valor_sn[1], obx.valor_sn[3]
    m = _TENSION.match(obx.valor or "")
    if m:
        return float(m[1].replace(",", ".")), float(m[2].replace(",", "."))
    return None


def aplicar_mapeo(msg: MensajeHL7, mapeo: dict[str, Any]) -> ResultadoMapeo:
    """Extrae del mensaje los valores definidos en el mapeo."""
    pac = mapeo.get("paciente", {})
    res = ResultadoMapeo(id_paciente=msg.id_paciente(int(pac.get("campo", 3)), int(pac.get("componente", 1))))
    reglas: dict[str, dict[str, Any]] = mapeo["observaciones"]
    alarmas: list[str] = []
    notas: list[str] = []

    for obx in msg.observaciones:
        regla = reglas.get(obx.identificador)
        if regla is None:
            if obx.identificador and obx.identificador not in res.no_mapeados:
                res.no_mapeados.append(obx.identificador)
            continue
        if obx.estado.upper() in ("X", "D", "W"):  # no obtenido / borrado / erróneo
            continue
        if obx.estado.upper() == "P":
            res.advertencias.append(f"{obx.identificador}: resultado preliminar")
        destino, tipo = regla["destino"], regla.get("tipo", "numero")

        if tipo == "lista":
            alarmas.extend(v.strip() for v in obx.valores if v.strip())
            continue
        if tipo == "texto":
            if obx.valor.strip():
                notas.append(obx.valor.strip())
            continue

        factor = _factor(regla, obx.unidad)
        if factor is None:
            res.advertencias.append(f"{obx.identificador}: unidad no reconocida «{obx.unidad}»")
            continue
        if tipo == "tension":
            ta = _tension(obx)
            if ta is None:
                res.advertencias.append(f"{obx.identificador}: tensión no interpretable")
                continue
            res.valores["ta_sistolica"] = round(ta[0] * factor, 1)
            res.valores["ta_diastolica"] = round(ta[1] * factor, 1)
            continue
        if obx.valor_numerico is None:
            res.advertencias.append(f"{obx.identificador}: valor no numérico")
            continue
        res.valores[destino] = round(obx.valor_numerico * factor, 3)

    if alarmas:
        res.valores["alarmas"] = alarmas
    if notas:
        res.valores["observaciones"] = " | ".join(notas)

    res.inicio = msg.inicio_observacion
    res.fin = msg.fin_observacion
    if "duracion_min" not in res.valores and res.inicio and res.fin:
        ini, fin = _a_local(res.inicio, mapeo), _a_local(res.fin, mapeo)
        if fin > ini:
            res.valores["duracion_min"] = round((fin - ini).total_seconds() / 60)

    referencia = res.inicio or next((o.fecha_hora for o in msg.observaciones if o.fecha_hora), None) \
        or msg.fecha_hora
    if referencia:
        res.fecha, res.turno = determinar_turno(referencia, mapeo)
    else:
        res.advertencias.append("El mensaje no trae fecha de la sesión")
    return res


def hoy_local(mapeo: dict[str, Any]) -> date:
    """Fecha actual en la zona horaria de la unidad."""
    return datetime.now(_zona(mapeo)).date()
