from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import models, schemas
from database import get_db

router = APIRouter()


# ── Rutas existentes ──────────────────────────────────────────────────────────

@router.get("/{fecha}/{turno}", response_model=list[schemas.ProgramacionOut])
def get_programacion(fecha: str, turno: str, db: Session = Depends(get_db)):
    return (
        db.query(models.Programacion)
        .filter_by(fecha=fecha, turno=turno)
        .options(joinedload(models.Programacion.paciente))
        .join(models.Paciente)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )


@router.post("", response_model=list[schemas.ProgramacionOut], status_code=201)
def guardar_programacion(data: schemas.ProgramacionBulk, db: Session = Depends(get_db)):
    """Reemplaza la programación de una fecha+turno con la lista enviada."""
    db.query(models.Programacion).filter_by(fecha=data.fecha, turno=data.turno).delete()

    nuevos = []
    for item in data.items:
        if not db.get(models.Paciente, item.paciente_id):
            raise HTTPException(404, f"Paciente {item.paciente_id} no encontrado")
        p = models.Programacion(
            fecha=data.fecha,
            turno=data.turno,
            paciente_id=item.paciente_id,
            epo_programado=item.epo_programado,
            hierro_programado=item.hierro_programado,
        )
        db.add(p)
        nuevos.append(p)

    db.commit()
    for p in nuevos:
        db.refresh(p)

    return (
        db.query(models.Programacion)
        .filter_by(fecha=data.fecha, turno=data.turno)
        .options(joinedload(models.Programacion.paciente))
        .join(models.Paciente)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )


# La antigua «auto-mes» (creaba la lista del día para todo el mes y repartía EPO/Fe
# sin reglas de unidad) se reemplazó por R14: routers/epo_fe.py (/api/epo-fe).
