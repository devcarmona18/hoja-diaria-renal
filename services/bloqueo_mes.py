"""R12 — Mes cerrado = hojas del mes de solo lectura.

Cuando un mes tiene un cierre vigente (``cierres_mes`` sin ``reabierto_en``), todas
sus hojas diarias quedan bloqueadas: editar registros, agregar pacientes, cerrar o
reabrir un día, crear una hoja nueva, programar EPO/Fe, cambios de un día y
confirmar/anular el pedido de insumos de una fecha de ese mes responden **409**.
Reabrir el mes (admin + motivo, ya auditado) las desbloquea.

Los routers llaman a :func:`exigir_abierto`; ``main.py`` convierte
:class:`MesCerrado` en la respuesta 409.
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy.orm import Session

import models

MENSAJE = "El mes está cerrado; reábralo para editar"


class MesCerrado(Exception):
    def __init__(self, mes: str):
        super().__init__(MENSAJE)
        self.mes = mes


def mes_de(fecha_o_mes: Optional[str]) -> Optional[str]:
    """«YYYY-MM-DD» o «YYYY-MM» -> «YYYY-MM» (None si no tiene esa forma)."""
    if not fecha_o_mes or len(fecha_o_mes) < 7 or fecha_o_mes[4] != "-":
        return None
    return fecha_o_mes[:7]


def meses_cerrados(db: Session, meses: Iterable[str]) -> set[str]:
    meses = {m for m in meses if m}
    if not meses:
        return set()
    filas = (db.query(models.CierreMes.mes)
             .filter(models.CierreMes.mes.in_(meses), models.CierreMes.reabierto_en.is_(None))
             .distinct().all())
    return {m for (m,) in filas}


def mes_cerrado(db: Session, fecha_o_mes: Optional[str]) -> bool:
    mes = mes_de(fecha_o_mes)
    return bool(mes) and mes in meses_cerrados(db, [mes])


def exigir_abierto(db: Session, *fechas_o_meses: Optional[str]) -> None:
    """Lanza :class:`MesCerrado` si alguna fecha (o mes) cae en un mes cerrado."""
    cerrados = meses_cerrados(db, [mes_de(f) for f in fechas_o_meses])
    if cerrados:
        raise MesCerrado(sorted(cerrados)[0])
