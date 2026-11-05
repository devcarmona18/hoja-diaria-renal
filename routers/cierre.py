from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import models, schemas
from database import get_db

router = APIRouter()


def _calcular_cierre(registros: list[models.Registro], estacion: int) -> schemas.CierreEstacion:
    regs = [r for r in registros if r.paciente and r.paciente.estacion == estacion] if estacion > 0 else registros
    return schemas.CierreEstacion(
        estacion=estacion,
        total=len(regs),
        asistidos=sum(1 for r in regs if r.asistencia == "A"),
        no_asiste=sum(1 for r in regs if r.asistencia == "NA"),
        hospitalizados=sum(1 for r in regs if r.asistencia == "H"),
        fallecidos=sum(1 for r in regs if r.asistencia == "F"),
        sin_marcar=sum(1 for r in regs if not r.asistencia),
        epo_count=sum(1 for r in regs if r.epo and r.asistencia == "A"),
        hierro_count=sum(1 for r in regs if r.hierro and r.asistencia == "A"),
    )


@router.get("/{sesion_id}", response_model=schemas.CierreOut)
def get_cierre(sesion_id: int, db: Session = Depends(get_db)):
    sesion = db.get(models.Sesion, sesion_id)
    if not sesion:
        raise HTTPException(404, "Sesión no encontrada")

    registros = (
        db.query(models.Registro)
        .filter_by(sesion_id=sesion_id)
        .options(joinedload(models.Registro.paciente))
        .all()
    )

    estaciones = [_calcular_cierre(registros, e) for e in (1, 2, 3)]
    totales = _calcular_cierre(registros, 0)
    totales.estacion = 0

    return schemas.CierreOut(sesion=sesion, estaciones=estaciones, totales=totales)


@router.post("/{sesion_id}/cerrar", response_model=schemas.SesionOut)
def cerrar_sesion(sesion_id: int, db: Session = Depends(get_db)):
    sesion = db.get(models.Sesion, sesion_id)
    if not sesion:
        raise HTTPException(404, "Sesión no encontrada")
    if sesion.cerrada:
        raise HTTPException(400, "La sesión ya está cerrada")
    sesion.cerrada = True
    db.commit()
    db.refresh(sesion)
    return sesion


@router.post("/{sesion_id}/reabrir", response_model=schemas.SesionOut)
def reabrir_sesion(sesion_id: int, db: Session = Depends(get_db)):
    sesion = db.get(models.Sesion, sesion_id)
    if not sesion:
        raise HTTPException(404, "Sesión no encontrada")
    sesion.cerrada = False
    db.commit()
    db.refresh(sesion)
    return sesion
