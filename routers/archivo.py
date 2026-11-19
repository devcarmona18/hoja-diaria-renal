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


class ReactivarIn(BaseModel):
    motivo: Optional[str] = Field(None, max_length=300)


def _item(p: models.Paciente, ahora) -> dict:
    vence = p.archivado_en + timedelta(days=config.ARCHIVO_DIAS)
    return {
        "id": p.id, "nombre": p.nombre, "cedula": p.cedula, "turno": p.turno,
        "medico": p.medico or "", "archivado_en": p.archivado_en.isoformat(timespec="seconds") + "Z",
        "motivo": p.archivado_motivo or "", "vence_listado": vence.isoformat(timespec="seconds") + "Z",
        "dias_restantes": max(0, math.ceil((vence - ahora).total_seconds() / 86400)),
        "en_ventana": srv.en_ventana_archivo(p, ahora),
    }


def item_archivado(p: models.Paciente) -> dict:
    return _item(p, srv.ahora_utc())


@router.get("/archivados")
def listar_archivados(db: Session = Depends(get_db)):
    """Archivados dentro del plazo ``ARCHIVO_DIAS``; pasado el plazo salen de esta lista (no de la base de datos)."""
    ahora = srv.ahora_utc()
    return {"archivo_dias": config.ARCHIVO_DIAS,
            "pacientes": [_item(p, ahora) for p in srv.consulta_archivados(db, ahora).all()]}


@router.get("/archivados/buscar")
def buscar_archivados(cedula: str = "", db: Session = Depends(get_db)):
    """Búsqueda por cédula entre TODOS los archivados, también los que ya salieron de la lista."""
    return {"pacientes": [item_archivado(p) for p in srv.buscar_archivados_por_cedula(db, cedula)]}


@router.post("/{paciente_id}/archivar")
def archivar_paciente(paciente_id: int, data: ArchivarIn, request: Request, db: Session = Depends(get_db)):
    auth.requerir_admin(request)
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is not None:
        raise HTTPException(409, "El paciente ya está archivado")
    srv.archivar(db, p, data.motivo.strip())
    srv.auditar(db, p, "archivar", auth.usuario_actual(request), data.motivo)
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
    srv.auditar(db, p, "restaurar", auth.usuario_actual(request))
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "activo": True}


@router.post("/{paciente_id}/reactivar")
def reactivar_paciente(paciente_id: int, request: Request, data: Optional[ReactivarIn] = None,
                       db: Session = Depends(get_db)):
    """Reactiva un archivado SIN límite de tiempo (p. ej. vuelve a la unidad pasados los
    ``ARCHIVO_DIAS``). Solo admin; queda en ``auditoria_pacientes``."""
    usuario = auth.requerir_admin(request)
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is None:
        raise HTTPException(409, "El paciente no está archivado")
    srv.reactivar(db, p, usuario, data.motivo if data else None)
    db.commit()
    return {"id": p.id, "nombre": p.nombre, "cedula": p.cedula, "turno": p.turno, "activo": True}


@router.get("/{paciente_id}/auditoria")
def auditoria_paciente(paciente_id: int, db: Session = Depends(get_db)):
    filas = (db.query(models.AuditoriaPaciente).filter_by(paciente_id=paciente_id)
             .order_by(models.AuditoriaPaciente.id.desc()).all())
    return [{"accion": a.accion, "usuario": a.usuario, "motivo": a.motivo or "",
             "creado_en": a.creado_en.isoformat(timespec="seconds") + "Z"} for a in filas]
