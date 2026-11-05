from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import models, schemas
from database import get_db

router = APIRouter()


@router.get("", response_model=list[schemas.PacienteOut])
def listar_pacientes(
    turno: Optional[str] = Query(None),
    estacion: Optional[int] = Query(None),
    activo: Optional[bool] = Query(None),   # None = todos
    db: Session = Depends(get_db),
):
    q = db.query(models.Paciente)
    if turno:
        q = q.filter(models.Paciente.turno == turno)
    if estacion:
        q = q.filter(models.Paciente.estacion == estacion)
    if activo is not None:
        q = q.filter(models.Paciente.activo == activo)
    return q.order_by(models.Paciente.estacion, models.Paciente.cama).all()


@router.post("", response_model=schemas.PacienteOut, status_code=201)
def crear_paciente(data: schemas.PacienteCreate, db: Session = Depends(get_db)):
    if db.query(models.Paciente).filter_by(cedula=data.cedula).first():
        raise HTTPException(400, "Cédula ya registrada")
    p = models.Paciente(**data.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/{paciente_id}", response_model=schemas.PacienteOut)
def actualizar_paciente(
    paciente_id: int, data: schemas.PacienteCreate, db: Session = Depends(get_db)
):
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{paciente_id}/toggle-activo", response_model=schemas.PacienteOut)
def toggle_activo(paciente_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    p.activo = not p.activo

    if not p.activo:
        # Eliminar registros en sesiones aún abiertas para que no aparezca en la hoja del día
        sesiones_abiertas = db.query(models.Sesion).filter_by(cerrada=False).all()
        for sesion in sesiones_abiertas:
            reg = db.query(models.Registro).filter_by(
                sesion_id=sesion.id, paciente_id=paciente_id
            ).first()
            if reg:
                db.delete(reg)

    db.commit()
    db.refresh(p)
    return p
