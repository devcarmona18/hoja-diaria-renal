from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import models
from database import get_db

router = APIRouter()


def _sesion_a_dict(s: models.Sesion, registros: list) -> dict:
    return {
        "id": s.id,
        "fecha": s.fecha,
        "turno": s.turno,
        "cerrada": s.cerrada,
        "total": len(registros),
        "asistidos": sum(1 for r in registros if r.asistencia == "A"),
        "no_asiste": sum(1 for r in registros if r.asistencia == "NA"),
        "fallecidos": sum(1 for r in registros if r.asistencia == "F"),
        "hospitalizados": sum(1 for r in registros if r.asistencia == "H"),
        "sin_marcar": sum(1 for r in registros if not r.asistencia),
        "epo_count": sum(1 for r in registros if r.epo and r.asistencia == "A"),
        "hierro_count": sum(1 for r in registros if r.hierro and r.asistencia == "A"),
    }


@router.get("")
def listar_historial(
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    turno: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(models.Sesion)
    if anio and mes:
        q = q.filter(models.Sesion.fecha.startswith(f"{anio:04d}-{mes:02d}"))
    elif anio:
        q = q.filter(models.Sesion.fecha.startswith(f"{anio:04d}"))
    if turno:
        q = q.filter(models.Sesion.turno == turno)

    sesiones = q.order_by(models.Sesion.fecha.desc(), models.Sesion.turno).all()

    result = []
    for s in sesiones:
        regs = db.query(models.Registro).filter_by(sesion_id=s.id).all()
        result.append(_sesion_a_dict(s, regs))
    return result


@router.get("/meses")
def listar_meses(db: Session = Depends(get_db)):
    """Retorna lista de 'YYYY-MM' con sesiones registradas, desc."""
    fechas = db.query(models.Sesion.fecha).distinct().all()
    meses = sorted({f[0][:7] for f in fechas}, reverse=True)
    return meses


@router.delete("/mes/{anio}/{mes}")
def limpiar_mes(anio: int, mes: int, db: Session = Depends(get_db)):
    """Elimina todas las sesiones (y registros) de un mes. Pacientes conservados."""
    prefix = f"{anio:04d}-{mes:02d}"
    sesiones = db.query(models.Sesion).filter(models.Sesion.fecha.startswith(prefix)).all()
    if not sesiones:
        raise HTTPException(404, "No hay sesiones para ese mes")

    count = len(sesiones)
    for s in sesiones:
        db.delete(s)
    db.commit()
    return {"eliminadas": count, "mes": prefix}
