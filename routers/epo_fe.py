"""R14 — Auto-programación mensual de EPO / hierro (reemplaza la antigua «auto-mes»).

Lectura: cualquiera con sesión (demo incluido). Cambios: solo el administrador, y
nunca en un mes cerrado (R12 → 409; el servicio llama a ``exigir_abierto``).
Reglas y algoritmo: docs/epo-hierro.md.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import auth
from database import get_db
from services import epo_fe as srv
from services.asistencia import ReglaError
from services.bloqueo_mes import MesCerrado

router = APIRouter()


class GenerarIn(BaseModel):
    regenerar: bool = False


class TotalesIn(BaseModel):
    epo_jeringas: Optional[int] = Field(None, ge=0, le=60)
    fe_dosis: Optional[int] = Field(None, ge=0, le=26)


class CeldaIn(BaseModel):
    paciente_id: int
    fecha: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    epo: Optional[int] = Field(None, ge=0, le=srv.MAX_EPO_CELDA)
    fe: Optional[int] = Field(None, ge=0, le=1)
    quitar_ajuste: bool = False


class LabIn(BaseModel):
    fechas: Optional[list[str]] = None     # None = regla por defecto


def _ejecutar(db: Session, fn, *args):
    try:
        out = fn(db, *args)
        db.commit()
        return out
    except ReglaError as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    except MesCerrado:
        db.rollback()
        raise          # main.py lo convierte en 409 «El mes está cerrado; reábralo para editar»


@router.get("/{mes}")
def ver_mes(mes: str, db: Session = Depends(get_db)):
    try:
        return srv.grilla(db, mes)
    except ReglaError as e:
        raise HTTPException(e.status, str(e))


@router.get("/{mes}/csv")
def csv_mes(mes: str, db: Session = Depends(get_db)):
    try:
        g = srv.grilla(db, mes)
    except ReglaError as e:
        raise HTTPException(e.status, str(e))
    return Response("﻿" + srv.a_csv(g), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="epo-hierro-{mes}.csv"'})


@router.post("/{mes}/generar")
def generar(mes: str, data: GenerarIn, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.generar, mes, usuario, data.regenerar)


@router.post("/{mes}/recalcular")
def recalcular(mes: str, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.recalcular, mes, usuario)


@router.put("/{mes}/pacientes/{paciente_id}")
def totales(mes: str, paciente_id: int, data: TotalesIn, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.fijar_totales, mes, paciente_id, data.epo_jeringas, data.fe_dosis, usuario)


@router.put("/{mes}/celdas")
def celda(mes: str, data: CeldaIn, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.ajustar_celda, mes, data.paciente_id, data.fecha, data.epo, data.fe,
                     usuario, data.quitar_ajuste)


@router.put("/{mes}/laboratorio")
def laboratorio(mes: str, data: LabIn, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.configurar_lab, mes, data.fechas, usuario)


@router.delete("/{mes}")
def borrar(mes: str, request: Request, db: Session = Depends(get_db)):
    usuario = auth.requerir_admin(request)
    return _ejecutar(db, srv.borrar_mes, mes, usuario)
