"""
Pedido de insumos (R5/R6). La lógica vive en services/insumos.py (BD) y
services/insumos_reglas.py (reglas puras).

  GET    /api/insumos/pedido?fecha=&turno=&estacion=      pedido del día (vivo o confirmado)
  GET    /api/insumos/pedido.csv?fecha=&turno=&estacion=  mismo pedido en CSV
  POST   /api/insumos/pedido/confirmar  {fecha}           guarda la foto (Confirmado/Enviado)
  DELETE /api/insumos/pedido/{fecha}                      anula la confirmación (vuelve a borrador)
  GET    /api/insumos/pedidos                             pedidos confirmados (más recientes primero)
  GET    /api/insumos/reglas                              reglas activas (personalizadas o por defecto)
  PUT    /api/insumos/reglas                              reemplaza las reglas (JSON validado)
  DELETE /api/insumos/reglas                              vuelve a las reglas por defecto

El adicional solo de una sesión se marca en la hoja con
PATCH /api/sesiones/registros/{id} {"adicional": true}.

Escrituras: el middleware de auth ya rechaza al rol demo (solo lectura).
"""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

import config
import hoja_dia as hd
import models
from database import get_db
from services import insumos as svc
from services import insumos_reglas as ir

router = APIRouter()


class ConfirmarInput(BaseModel):
    fecha: str
    fecha_sesiones: Optional[str] = None


def _usuario(request: Request) -> str:
    if not config.AUTH_ENABLED:
        return "local"
    return request.session.get("usuario") or "admin"


def _datos(db: Session, fecha: Optional[str], fecha_sesiones: Optional[str],
           turno: Optional[str], estacion: Optional[int]) -> dict:
    try:
        res = svc.ver(db, fecha or date.today().isoformat(), fecha_sesiones)
    except (svc.ErrorPedido, hd.Conflicto) as e:
        raise HTTPException(400, str(e))
    return svc.serializar(res, turno, estacion)


Turno = Optional[Literal["M", "T", "N"]]


@router.get("/pedido")
def ver_pedido(fecha: Optional[str] = Query(None, description="Fecha del pedido AAAA-MM-DD (por defecto hoy)"),
               fecha_sesiones: Optional[str] = Query(None, description="Por defecto el próximo día de diálisis"),
               turno: Turno = None,
               estacion: Optional[int] = Query(None, ge=1, le=3),
               db: Session = Depends(get_db)):
    return _datos(db, fecha, fecha_sesiones, turno, estacion)


@router.get("/pedido.csv")
def pedido_csv(fecha: Optional[str] = None, fecha_sesiones: Optional[str] = None,
               turno: Turno = None, estacion: Optional[int] = Query(None, ge=1, le=3),
               db: Session = Depends(get_db)):
    datos = _datos(db, fecha, fecha_sesiones, turno, estacion)
    nombre = f"pedido-insumos-{datos['fecha_pedido']}"
    if turno:
        nombre += f"-{turno}"
    if estacion:
        nombre += f"-est{estacion}"
    return Response(svc.a_csv(datos), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'})


@router.post("/pedido/confirmar", status_code=201)
def confirmar(data: ConfirmarInput, request: Request, db: Session = Depends(get_db)):
    try:
        svc.confirmar(db, data.fecha, _usuario(request), data.fecha_sesiones)
        db.commit()
    except svc.ErrorPedido as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except hd.Conflicto as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return _datos(db, data.fecha, None, None, None)


@router.delete("/pedido/{fecha}")
def anular(fecha: str, db: Session = Depends(get_db)):
    try:
        svc.anular(db, fecha)
        db.commit()
    except svc.ErrorPedido as e:
        db.rollback()
        raise HTTPException(404, str(e))
    return {"ok": True}


@router.get("/pedidos")
def listar_pedidos(limite: int = Query(30, ge=1, le=200), db: Session = Depends(get_db)):
    filas = (db.query(models.PedidoInsumos).order_by(models.PedidoInsumos.fecha_pedido.desc())
             .limit(limite).all())
    return [{"id": p.id, "fecha_pedido": p.fecha_pedido, "fecha_sesiones": p.fecha_sesiones,
             "estado": p.estado, "confirmado_por": p.confirmado_por,
             "confirmado_en": p.confirmado_en.isoformat(timespec="minutes") if p.confirmado_en else None,
             "items": len(p.items)} for p in filas]


# ── Reglas ────────────────────────────────────────────────────────────────────

def _reglas_out(db: Session) -> dict:
    fila = svc.reglas_guardadas(db)
    reglas = svc.reglas_activas(db)
    return {"origen": "personalizadas" if fila else "predeterminadas",
            "actualizado_en": fila.actualizado_en.isoformat(timespec="minutes") if fila and fila.actualizado_en else None,
            "actualizado_por": fila.actualizado_por if fila else None,
            "reglas": reglas.model_dump(exclude_none=True)}


@router.get("/reglas")
def ver_reglas(db: Session = Depends(get_db)):
    return _reglas_out(db)


@router.put("/reglas")
def guardar_reglas(request: Request, datos: dict = Body(...), db: Session = Depends(get_db)):
    try:
        svc.guardar_reglas(db, datos, _usuario(request))
    except ValidationError as e:
        errores = [f"{'.'.join(str(x) for x in err['loc']) or 'reglas'}: {err['msg']}" for err in e.errors()]
        raise HTTPException(422, "Reglas inválidas: " + " | ".join(errores[:5]))
    db.commit()
    return _reglas_out(db)


@router.delete("/reglas")
def restaurar_reglas(db: Session = Depends(get_db)):
    svc.restaurar_reglas(db)
    db.commit()
    return _reglas_out(db)


@router.get("/reglas/por-defecto")
def reglas_por_defecto():
    return ir.cargar_por_defecto().model_dump(exclude_none=True)

