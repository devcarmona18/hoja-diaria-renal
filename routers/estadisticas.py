from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from collections import defaultdict
import auth
import models
from database import get_db
from services import asistencia as srv_asis

router = APIRouter()


@router.get("/mes/{anio}/{mes}")
def estadisticas_mes(anio: int, mes: int, db: Session = Depends(get_db)):
    """Sesiones A/NA/H/F por paciente en un mes dado."""
    prefix = f"{anio:04d}-{mes:02d}"
    sesion_ids = [
        s.id for s in db.query(models.Sesion)
        .filter(models.Sesion.fecha.startswith(prefix)).all()
    ]
    if not sesion_ids:
        return []

    registros = (
        db.query(models.Registro)
        .filter(models.Registro.sesion_id.in_(sesion_ids))
        .options(joinedload(models.Registro.paciente))
        .all()
    )

    stats = defaultdict(lambda: {"A": 0, "NA": 0, "H": 0, "F": 0, "sin_marcar": 0, "total": 0})
    pac_info: dict = {}

    for r in registros:
        if not r.paciente:
            continue
        pid = r.paciente_id
        pac_info[pid] = {
            "id": r.paciente.id,
            "nombre": r.paciente.nombre,
            "cedula": r.paciente.cedula,
            "estacion": r.paciente.estacion,
            "cama": r.paciente.cama,
            "turno": r.paciente.turno,
            "medico": r.paciente.medico or "",
        }
        stats[pid]["total"] += 1
        if r.asistencia == "A":    stats[pid]["A"] += 1
        elif r.asistencia == "NA": stats[pid]["NA"] += 1
        elif r.asistencia == "H":  stats[pid]["H"] += 1
        elif r.asistencia == "F":  stats[pid]["F"] += 1
        else:                       stats[pid]["sin_marcar"] += 1

    return [
        {**pac_info[pid], **stats[pid]}
        for pid in sorted(pac_info, key=lambda x: (pac_info[x]["estacion"], pac_info[x]["cama"]))
    ]


@router.get("/meses")
def meses_con_sesiones(db: Session = Depends(get_db)):
    fechas = db.query(models.Sesion.fecha).distinct().all()
    return sorted({f[0][:7] for f in fechas}, reverse=True)


@router.get("/paciente/{paciente_id}")
def estadisticas_paciente(
    paciente_id: int,
    mes: Optional[str] = Query(None),  # "YYYY-MM"
    db: Session = Depends(get_db),
):
    p = db.get(models.Paciente, paciente_id)
    if not p:
        return {"error": "Paciente no encontrado"}

    q = db.query(models.Registro).filter_by(paciente_id=paciente_id)
    if mes:
        q = q.join(models.Sesion).filter(models.Sesion.fecha.startswith(mes))
    registros = q.join(models.Sesion).order_by(models.Sesion.fecha).all()

    return {
        "paciente_id": paciente_id,
        "nombre": p.nombre,
        "total": len(registros),
        "asistidos": sum(1 for r in registros if r.asistencia == "A"),
        "no_asiste": sum(1 for r in registros if r.asistencia == "NA"),
        "hospitalizados": sum(1 for r in registros if r.asistencia == "H"),
        "fallecidos": sum(1 for r in registros if r.asistencia == "F"),
        "sin_marcar": sum(1 for r in registros if not r.asistencia),
    }


# ── R12: asistencia mensual (facturación) ────────────────────────────────────
# Regla de cálculo: ver services/asistencia.py (docstring) y docs/requerimientos-diciembre.md.

def _regla(e: srv_asis.ReglaError):
    return HTTPException(e.status, str(e))


@router.get("/asistencia/{anio}/{mes}")
def asistencia_mes(anio: int, mes: int, db: Session = Depends(get_db)):
    """Asistidas / programadas por paciente de CUALQUIER mes. Mes cerrado = registro guardado (inmutable)."""
    try:
        return srv_asis.resumen_mes(db, f"{anio:04d}-{mes:02d}")
    except srv_asis.ReglaError as e:
        raise _regla(e)


@router.get("/asistencia/{anio}/{mes}/csv")
def asistencia_mes_csv(anio: int, mes: int, db: Session = Depends(get_db)):
    try:
        resumen = srv_asis.resumen_mes(db, f"{anio:04d}-{mes:02d}")
    except srv_asis.ReglaError as e:
        raise _regla(e)
    cuerpo = "\ufeff" + srv_asis.a_csv(resumen)      # BOM: Excel abre bien las tildes
    return Response(cuerpo, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="asistencia-{resumen["mes"]}.csv"'})


class CerrarIn(BaseModel):
    forzar: bool = False      # permitir cerrar el mes en curso


class ReabrirIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


@router.post("/asistencia/{anio}/{mes}/cerrar")
def cerrar_mes(anio: int, mes: int, request: Request, data: CerrarIn = Body(default_factory=CerrarIn),
               db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    try:
        srv_asis.cerrar_mes(db, f"{anio:04d}-{mes:02d}", usuario, forzar=data.forzar)
        return srv_asis.resumen_mes(db, f"{anio:04d}-{mes:02d}")
    except srv_asis.ReglaError as e:
        raise _regla(e)


@router.post("/asistencia/{anio}/{mes}/reabrir")
def reabrir_mes(anio: int, mes: int, data: ReabrirIn, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    try:
        srv_asis.reabrir_mes(db, f"{anio:04d}-{mes:02d}", usuario, data.motivo)
        return srv_asis.resumen_mes(db, f"{anio:04d}-{mes:02d}")
    except srv_asis.ReglaError as e:
        raise _regla(e)


@router.get("/asistencia/{anio}/{mes}/auditoria")
def auditoria_mes(anio: int, mes: int, db: Session = Depends(get_db)):
    mes_s = f"{anio:04d}-{mes:02d}"
    filas = (db.query(models.AuditoriaCierreMes).filter_by(mes=mes_s)
             .order_by(models.AuditoriaCierreMes.id.desc()).all())
    return [{"accion": a.accion, "usuario": a.usuario, "motivo": a.motivo or "",
             "fecha": a.creado_en.isoformat(timespec="seconds") + "Z"} for a in filas]
