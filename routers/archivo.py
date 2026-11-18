"""R13 — Archivo de pacientes («Eliminar paciente» = archivar). Nada clínico se borra."""
import math
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import auth
import config
import models
from database import get_db
from services import pacientes as srv

router = APIRouter()


class ArchivarIn(BaseModel):
    motivo: str = Field(min_length=2, max_length=200)


def _item(p: models.Paciente, ahora) -> dict:
    vence = p.archivado_en + timedelta(days=config.ARCHIVO_DIAS)
    return {
        "id": p.id, "nombre": p.nombre, "cedula": p.cedula, "turno": p.turno,
        "medico": p.medico or "", "archivado_en": p.archivado_en.isoformat(timespec="seconds") + "Z",
        "motivo": p.archivado_motivo or "", "vence_listado": vence.isoformat(timespec="seconds") + "Z",
        "dias_restantes": max(0, math.ceil((vence - ahora).total_seconds() / 86400)),
    }


@router.get("/archivados")
def listar_archivados(db: Session = Depends(get_db)):
    """Archivados dentro del plazo ``ARCHIVO_DIAS``; pasado el plazo salen de esta lista (no de la base de datos)."""
    ahora = srv.ahora_utc()
    return {"archivo_dias": config.ARCHIVO_DIAS,
            "pacientes": [_item(p, ahora) for p in srv.consulta_archivados(db, ahora).all()]}


@router.post("/{paciente_id}/archivar")
def archivar_paciente(paciente_id: int, data: ArchivarIn, request: Request, db: Session = Depends(get_db)):
    auth.requerir_admin(request)
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is not None:
        raise HTTPException(409, "El paciente ya está archivado")
    srv.archivar(db, p, data.motivo.strip())
    db.commit()
    return _item(p, srv.ahora_utc())


@router.post("/{paciente_id}/restaurar")
def restaurar_paciente(paciente_id: int, request: Request, db: Session = Depends(get_db)):
    auth.requerir_admin(request)
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is None:
        raise HTTPException(409, "El paciente no está archivado")
    if not srv.en_ventana_archivo(p):
        raise HTTPException(409, f"Pasaron más de {config.ARCHIVO_DIAS} días desde el archivo: ya no se puede restaurar desde la lista")
    srv.restaurar(db, p)
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "activo": True}
