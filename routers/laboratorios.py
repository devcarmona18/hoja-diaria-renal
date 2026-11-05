from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
import models, schemas
from database import get_db

router = APIRouter()

TIPOS_VALIDOS = {
    "Hb", "Hto", "Urea", "Creatinina", "Kt_V",
    "K", "Na", "Ca", "P", "Albumina",
    "Ferritina", "Sat_Transf", "PTH", "PCR",
}


# ── Literal routes FIRST (before /{paciente_id}) ─────────────────────────────

@router.get("/panel")
def panel_laboratorio(
    tipo: str = Query(..., description="Tipo de laboratorio, ej: Hb"),
    db: Session = Depends(get_db),
):
    """Último valor de `tipo` para cada paciente activo. Usado en Fase 5 (panel clínico)."""
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo inválido. Válidos: {sorted(TIPOS_VALIDOS)}")

    pacientes = (
        db.query(models.Paciente)
        .filter_by(activo=True)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )

    result = []
    for p in pacientes:
        ultimo = (
            db.query(models.Laboratorio)
            .filter_by(paciente_id=p.id, tipo=tipo)
            .order_by(models.Laboratorio.fecha.desc())
            .first()
        )
        result.append({
            "paciente_id": p.id,
            "nombre": p.nombre,
            "estacion": p.estacion,
            "cama": p.cama,
            "turno": p.turno,
            "medico": p.medico or "",
            "valor": ultimo.valor if ultimo else None,
            "fecha": ultimo.fecha if ultimo else None,
        })
    return result


# ── Parametric routes ─────────────────────────────────────────────────────────

@router.get("/{paciente_id}", response_model=list[schemas.LaboratorioOut])
def get_labs(
    paciente_id: int,
    tipo: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    if not db.get(models.Paciente, paciente_id):
        raise HTTPException(404, "Paciente no encontrado")

    q = db.query(models.Laboratorio).filter_by(paciente_id=paciente_id)
    if tipo:
        q = q.filter(models.Laboratorio.tipo == tipo)

    return q.order_by(models.Laboratorio.tipo, models.Laboratorio.fecha).all()


@router.post("", response_model=schemas.LaboratorioOut, status_code=201)
def crear_lab(data: schemas.LaboratorioCreate, db: Session = Depends(get_db)):
    if not db.get(models.Paciente, data.paciente_id):
        raise HTTPException(404, "Paciente no encontrado")
    if data.tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo no valido. Opciones: {sorted(TIPOS_VALIDOS)}")

    lab = models.Laboratorio(**data.model_dump())
    db.add(lab)
    db.commit()
    db.refresh(lab)
    return lab


@router.delete("/{lab_id}", status_code=204)
def eliminar_lab(lab_id: int, db: Session = Depends(get_db)):
    lab = db.get(models.Laboratorio, lab_id)
    if not lab:
        raise HTTPException(404, "Resultado no encontrado")
    db.delete(lab)
    db.commit()
