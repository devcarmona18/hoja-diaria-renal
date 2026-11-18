"""
Asistencia mensual por paciente y cierre de mes para facturación (R12).

REGLA (documentada, ver docs/requerimientos-diciembre.md R12)
-------------------------------------------------------------
Para un paciente y un mes, ``programadas`` son los días DE DIÁLISIS del paciente
(``dias``: LMV = lun-mié-vie, TJS = mar-jue-sáb) del mes que cumplen TODO esto:

  1. la unidad operó ese día (existe alguna sesión con esa fecha);
  2. es anterior a hoy (hoy solo cuenta si ya se marcó su asistencia);
  3. el día es igual o posterior a su primera fila en cualquier hoja (antes no era paciente);
  4. el paciente NO estaba inactivo ni archivado ese día (tabla ``paciente_inactividad``,
     periodos [desde, hasta) que registran R10 «inactivo» y el archivo de R13);
  5. no se marcó H (hospitalizado) ni F (falleció) ese día: son días que no se facturan
     ni cuentan como falta.

Se suman además los días en que ASISTIÓ (A) aunque no fueran de su grupo o
estuviera inactivo (asistió = fue programado), así ``asistidas ≤ programadas`` y el
porcentaje llega a 100 % cuando asistió a todas sus sesiones. Sin ``dias``
asignado, las programadas son las filas de hoja no H/F.
``porcentaje = asistidas / programadas × 100``.

Cierre de mes: guarda ``asistencia_mensual`` (inmutable: el modelo lo impide) bajo un
``cierres_mes``. Reabrir (solo admin, con motivo) deja el cierre anterior como
historial, se audita y permite volver a cerrar.
"""
from __future__ import annotations

import calendar
import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

import models
from services.pacientes import ahora_utc
from services.tiempo import hoy_local

DIAS_SEMANA = {"LMV": (0, 2, 4), "TJS": (1, 3, 5)}   # Python: lunes = 0
RE_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ReglaError(Exception):
    """Error de negocio con código HTTP sugerido."""
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def validar_mes(mes: str) -> str:
    if not RE_MES.match(mes or ""):
        raise ReglaError("El mes debe tener el formato AAAA-MM", 422)
    return mes


def _periodos_inactividad(db: Session) -> dict[int, list[tuple[str, Optional[str]]]]:
    per: dict[int, list] = defaultdict(list)
    for r in db.query(models.PacienteInactividad).all():
        per[r.paciente_id].append((r.desde, r.hasta))
    return per


def _inactivo_en(periodos: list, fecha: str) -> bool:
    return any(desde <= fecha and (hasta is None or fecha < hasta) for desde, hasta in periodos)


def calcular_mes(db: Session, mes: str, hoy: Optional[date] = None) -> list[dict]:
    """Asistencia EN VIVO del mes para cada paciente con filas de hoja en ese mes."""
    validar_mes(mes)
    hoy = hoy or hoy_local()
    anio, m = int(mes[:4]), int(mes[5:])
    dias_mes = [date(anio, m, d) for d in range(1, calendar.monthrange(anio, m)[1] + 1)]

    sesiones = db.query(models.Sesion.id, models.Sesion.fecha).filter(models.Sesion.fecha.startswith(mes)).all()
    operadas = {f for _, f in sesiones}
    fecha_de = dict(sesiones)
    if not sesiones:
        return []

    marcas: dict[int, dict[str, set]] = defaultdict(lambda: defaultdict(set))   # pid -> fecha -> {asistencias}
    for pid, sid, asis in db.query(models.Registro.paciente_id, models.Registro.sesion_id,
                                   models.Registro.asistencia).filter(
            models.Registro.sesion_id.in_(list(fecha_de))).all():
        marcas[pid][fecha_de[sid]].add(asis or "")
    if not marcas:
        return []

    primera = {pid: f for pid, f in db.query(
        models.Registro.paciente_id, _min_fecha()).join(
        models.Sesion, models.Registro.sesion_id == models.Sesion.id).group_by(models.Registro.paciente_id).all()}
    periodos = _periodos_inactividad(db)
    pacientes = {p.id: p for p in db.query(models.Paciente).filter(models.Paciente.id.in_(list(marcas))).all()}

    filas = []
    for pid, p in pacientes.items():
        por_fecha = marcas[pid]
        asistidos = {f for f, s in por_fecha.items() if "A" in s}
        grupo = DIAS_SEMANA.get(p.dias or "")
        prog: set[str] = set(asistidos)
        excl_hf = excl_inact = 0
        if grupo:
            for d in dias_mes:
                f = d.isoformat()
                if d.weekday() not in grupo or f not in operadas or f in asistidos:
                    continue
                if f < primera.get(pid, f):
                    continue
                if d > hoy or (d == hoy and not (por_fecha.get(f, set()) - {""})):
                    continue
                if _inactivo_en(periodos.get(pid, []), f):
                    excl_inact += 1
                    continue
                if por_fecha.get(f, set()) & {"H", "F"}:
                    excl_hf += 1
                    continue
                prog.add(f)
        else:
            for f, s in por_fecha.items():
                if f in asistidos:
                    continue
                if s & {"H", "F"}:
                    excl_hf += 1
                elif not _inactivo_en(periodos.get(pid, []), f):
                    prog.add(f)
        if not prog:
            continue
        a, pr = len(asistidos), len(prog)
        filas.append({
            "paciente_id": pid, "nombre": p.nombre, "cedula": p.cedula, "estacion": p.estacion,
            "cama": p.cama, "turno": p.turno, "medico": p.medico or "", "dias": p.dias,
            "programadas": pr, "asistidas": a, "faltas": pr - a,
            "excluidas": excl_hf + excl_inact,
            "porcentaje": round(a * 100 / pr, 1),
            "archivado": p.archivado_en is not None,
            "inactivo": p.activo is not True and p.archivado_en is None,
        })
    filas.sort(key=lambda r: (r["turno"], r["estacion"], r["cama"]))
    return filas


def _min_fecha():
    from sqlalchemy import func
    return func.min(models.Sesion.fecha)


# ── Cierre de mes ────────────────────────────────────────────────────────────
def cierre_vigente(db: Session, mes: str) -> Optional[models.CierreMes]:
    return (db.query(models.CierreMes)
            .filter(models.CierreMes.mes == mes, models.CierreMes.reabierto_en.is_(None))
            .order_by(models.CierreMes.id.desc()).first())


def _totales(filas: list[dict]) -> dict:
    prog = sum(f["programadas"] for f in filas)
    asis = sum(f["asistidas"] for f in filas)
    return {
        "pacientes_programados": len(filas),
        "pacientes_atendidos": sum(1 for f in filas if f["asistidas"] > 0),
        "sesiones_programadas": prog,
        "sesiones_asistidas": asis,
        "porcentaje": round(asis * 100 / prog, 1) if prog else None,
    }


def _filas_guardadas(db: Session, cierre: models.CierreMes) -> list[dict]:
    filas = []
    q = (db.query(models.AsistenciaMensual, models.Paciente)
         .join(models.Paciente, models.AsistenciaMensual.paciente_id == models.Paciente.id)
         .filter(models.AsistenciaMensual.cierre_id == cierre.id))
    for a, p in q.all():
        filas.append({
            "paciente_id": p.id, "nombre": p.nombre, "cedula": p.cedula, "estacion": p.estacion,
            "cama": p.cama, "turno": p.turno, "medico": p.medico or "", "dias": p.dias,
            "programadas": a.programadas, "asistidas": a.asistidas,
            "faltas": a.programadas - a.asistidas, "excluidas": None,
            "porcentaje": a.porcentaje,
            "archivado": p.archivado_en is not None,
            "inactivo": p.activo is not True and p.archivado_en is None,
        })
    filas.sort(key=lambda r: (r["turno"], r["estacion"], r["cama"]))
    return filas


def resumen_mes(db: Session, mes: str, hoy: Optional[date] = None) -> dict:
    """Mes cerrado -> lo guardado (inmutable). Mes abierto -> cálculo en vivo."""
    validar_mes(mes)
    cierre = cierre_vigente(db, mes)
    filas = _filas_guardadas(db, cierre) if cierre else calcular_mes(db, mes, hoy)
    return {
        "mes": mes,
        "cerrado": cierre is not None,
        "cierre": ({"id": cierre.id, "cerrado_por": cierre.cerrado_por,
                    "cerrado_en": cierre.cerrado_en.isoformat(timespec="seconds") + "Z"} if cierre else None),
        "totales": _totales(filas),
        "pacientes": filas,
    }


def cerrar_mes(db: Session, mes: str, usuario: str, forzar: bool = False,
               hoy: Optional[date] = None) -> models.CierreMes:
    validar_mes(mes)
    hoy = hoy or hoy_local()
    if cierre_vigente(db, mes):
        raise ReglaError(f"El mes {mes} ya está cerrado. Reábralo (admin) para volver a cerrarlo.", 409)
    if mes >= hoy.strftime("%Y-%m") and not forzar:
        raise ReglaError("El mes aún no termina: ciérrelo cuando acabe (o use forzar).", 409)
    filas = calcular_mes(db, mes, hoy)
    if not filas:
        raise ReglaError(f"No hay asistencia para cerrar en {mes}", 400)
    ahora = ahora_utc()
    cierre = models.CierreMes(mes=mes, cerrado_por=usuario, cerrado_en=ahora)
    db.add(cierre)
    db.flush()
    for f in filas:
        db.add(models.AsistenciaMensual(
            cierre_id=cierre.id, mes=mes, paciente_id=f["paciente_id"], programadas=f["programadas"],
            asistidas=f["asistidas"], porcentaje=f["porcentaje"], cerrado_por=usuario, cerrado_en=ahora))
    db.add(models.AuditoriaCierreMes(mes=mes, accion="cerrar", usuario=usuario, creado_en=ahora,
                                     motivo=f"{len(filas)} pacientes"))
    db.commit()
    return cierre


def reabrir_mes(db: Session, mes: str, usuario: str, motivo: str) -> models.CierreMes:
    validar_mes(mes)
    motivo = (motivo or "").strip()
    if len(motivo) < 3:
        raise ReglaError("Indique el motivo de la reapertura", 422)
    cierre = cierre_vigente(db, mes)
    if not cierre:
        raise ReglaError(f"El mes {mes} no está cerrado", 409)
    ahora = ahora_utc()
    cierre.reabierto_por, cierre.reabierto_en, cierre.reapertura_motivo = usuario, ahora, motivo[:300]
    db.add(models.AuditoriaCierreMes(mes=mes, accion="reabrir", usuario=usuario, motivo=motivo[:300],
                                     creado_en=ahora))
    db.commit()
    return cierre


# ── CSV ──────────────────────────────────────────────────────────────────────
def _celda(v) -> str:
    """Evita inyección de fórmulas al abrir el CSV en Excel."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def a_csv(resumen: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["mes", "estado_mes", "paciente", "cedula", "turno", "medico", "programadas",
                "asistidas", "porcentaje", "paciente_archivado"])
    estado = "cerrado" if resumen["cerrado"] else "abierto"
    for f in resumen["pacientes"]:
        w.writerow([resumen["mes"], estado, _celda(f["nombre"]), _celda(f["cedula"]), f["turno"],
                    _celda(f["medico"]), f["programadas"], f["asistidas"], f["porcentaje"],
                    "si" if f["archivado"] else "no"])
    t = resumen["totales"]
    w.writerow([resumen["mes"], estado, "TOTAL", "", "", "", t["sesiones_programadas"],
                t["sesiones_asistidas"], t["porcentaje"], ""])
    return out.getvalue()
