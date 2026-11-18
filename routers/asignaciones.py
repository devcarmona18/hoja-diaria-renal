"""
Programación del día siguiente con la misma hoja de la página principal (R2) y
cambios de un día vs. permanentes (R7). La lógica vive en `hoja_dia.py`.

  GET    /api/asignaciones/proximo-dia?desde=AAAA-MM-DD
  GET    /api/asignaciones/hoja/{fecha}/{turno}
  GET    /api/asignaciones/buscar?q=…&fecha=…
  POST   /api/asignaciones                  mover / transitorio / reemplazo (o permanente)
  DELETE /api/asignaciones/{id}             deshacer un cambio de un día
  POST   /api/asignaciones/{id}/permanente  convertirlo en ubicación habitual
"""
import unicodedata
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
import hoja_dia as hd
import models
import schemas
from database import get_db

router = APIRouter()


class AsignacionCrear(BaseModel):
    fecha: str
    turno: Literal["M", "T", "N"]
    paciente_id: int
    tipo: Literal["mover", "reemplazo"] = "mover"
    # mover: destino. reemplazo: se toma la cama de `reemplaza_paciente_id`.
    estacion: Optional[int] = Field(None, ge=1, le=3)
    cama: Optional[int] = Field(None, ge=1, le=16)
    reemplaza_paciente_id: Optional[int] = None
    intercambiar: bool = False       # si la cama está ocupada, intercambia las dos camas
    permanente: bool = False         # actualiza la ubicación habitual en vez de solo ese día


# ── Serialización ─────────────────────────────────────────────────────────────

def _pac(p: models.Paciente | None) -> dict | None:
    return schemas.PacienteOut.model_validate(p).model_dump() if p else None


def _asig_out(a: models.AsignacionDia | None) -> dict | None:
    if not a:
        return None
    return {"id": a.id, "tipo": a.tipo, "grupo": a.grupo, "turno": a.turno,
            "estacion": a.estacion, "cama": a.cama,
            "reemplaza_paciente_id": a.reemplaza_paciente_id,
            "creado_por": a.creado_por,
            "creado_en": a.creado_en.isoformat(timespec="minutes") if a.creado_en else None}


def _hoja_out(db: Session, fecha: str, turno: str) -> dict:
    hoja = hd.componer(db, fecha, turno)
    f = hd.parse_fecha(fecha)
    sesion = hd.sesion_de(db, fecha, turno)

    def flags(pid):
        pr = hoja.programacion.get(pid)
        return {"epo": bool(pr.epo_programado) if pr else False,
                "hierro": bool(pr.hierro_programado) if pr else False}

    puestos = []
    for pu in hoja.puestos:
        p = pu.paciente
        a = pu.asignacion
        puestos.append({
            "estacion": pu.estacion, "cama": pu.cama,
            "cama_global": hd.cama_global(pu.estacion, pu.cama),
            "tipo": pu.tipo, "paciente": _pac(p), "asignacion": _asig_out(a),
            "base": {"turno": p.turno, "estacion": p.estacion, "cama": p.cama,
                     "cama_global": hd.cama_global(p.estacion, p.cama)},
            "reemplaza": ({"id": a.reemplaza.id, "nombre": a.reemplaza.nombre}
                          if a and a.reemplaza else None),
            **flags(p.id),
        })
    return {
        "fecha": fecha, "turno": turno,
        "dia_semana": hd.DIA_NOMBRE[f.weekday()], "grupo_dias": hd.grupo_del_dia(f),
        "programado": hoja.programado,
        "sesion": {"id": sesion.id, "cerrada": bool(sesion.cerrada)} if sesion else None,
        "editable": not (sesion and sesion.cerrada),
        "puestos": puestos,
        "desplazados": [{"paciente": _pac(q), "estacion": e, "cama": c,
                         "cama_global": hd.cama_global(e, c),
                         "reemplazado_por": {"id": sup.paciente.id, "nombre": sup.paciente.nombre},
                         "asignacion_id": sup.id}
                        for q, sup, e, c in hoja.desplazados],
        "excluidos": [{"paciente": _pac(p), "motivo": m} for p, m in hoja.excluidos],
        "conflictos": [{"estacion": c["estacion"], "cama": c["cama"],
                        "cama_global": hd.cama_global(c["estacion"], c["cama"]),
                        "pacientes": [{"id": x.paciente.id, "nombre": x.paciente.nombre}
                                      for x in c["pacientes"]]}
                       for c in hoja.conflictos()],
    }


def _usuario(request: Request) -> str:
    if not config.AUTH_ENABLED:
        return "local"
    return request.session.get("usuario") or "admin"


def _validar(fecha: str, turno: str) -> None:
    hd.parse_fecha(fecha)
    if turno not in hd.TURNOS:
        raise hd.Conflicto("Turno inválido (use M, T o N)")


def _ejecutar(db: Session, fn):
    """Corre una operación en una transacción: todo o nada; los conflictos → 409."""
    try:
        res = fn()
        db.commit()
        return res
    except hd.Conflicto as e:
        db.rollback()
        raise HTTPException(409, str(e))
    except Exception:
        db.rollback()
        raise


def _consulta(fn):
    try:
        return fn()
    except hd.Conflicto as e:
        raise HTTPException(400, str(e))


# ── Rutas ─────────────────────────────────────────────────────────────────────

@router.get("/proximo-dia")
def proximo_dia(desde: Optional[str] = Query(None, description="AAAA-MM-DD; por defecto hoy")):
    """Próximo día de diálisis (salta domingos: sábado → lunes)."""
    d = _consulta(lambda: hd.parse_fecha(desde)) if desde else date.today()
    sig = hd.proximo_dia_dialisis(d)
    return {"desde": d.isoformat(), "fecha": sig.isoformat(),
            "dia_semana": hd.DIA_NOMBRE[sig.weekday()], "grupo_dias": hd.grupo_del_dia(sig)}


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


@router.get("/buscar")
def buscar(q: str = Query(..., min_length=1, max_length=60),
           fecha: Optional[str] = None,
           limite: int = Query(20, ge=1, le=50),
           db: Session = Depends(get_db)):
    """Busca pacientes por nombre (sin importar tildes ni mayúsculas) o cédula.

    Con `fecha` indica dónde está cada uno ese día (turno, cama y tipo de cambio).
    """
    texto = _normalizar(q)
    digitos = "".join(ch for ch in q if ch.isdigit())
    # R10: los inactivos aparecen en la búsqueda, marcados («activo»: false), para
    # poder encontrarlos; no se pueden programar (hoja_dia._exigir_activo).
    encontrados = []
    # R13: los archivados no aparecen (se restauran desde «Archivados»).
    for p in (db.query(models.Paciente).filter(models.Paciente.archivado_en.is_(None))
              .order_by(models.Paciente.nombre).all()):
        nombre = _normalizar(p.nombre)
        ced = "".join(ch for ch in (p.cedula or "") if ch.isdigit())
        if all(t in nombre for t in texto.split()) or (digitos and digitos in ced):
            encontrados.append(p)
        if len(encontrados) >= limite:
            break

    ubic = {}
    if fecha:
        def _ubicar():
            for t in hd.TURNOS:
                hoja = hd.componer(db, fecha, t)
                for pu in hoja.puestos:
                    ubic[pu.paciente.id] = {"turno": t, "estacion": pu.estacion, "cama": pu.cama,
                                            "cama_global": hd.cama_global(pu.estacion, pu.cama),
                                            "tipo": pu.tipo}
                for x, sup, e, c in hoja.desplazados:
                    ubic[x.id] = {"turno": t, "estacion": e, "cama": c,
                                  "cama_global": hd.cama_global(e, c), "tipo": "reemplazado",
                                  "reemplazado_por": sup.paciente.nombre}
        _consulta(_ubicar)

    f = hd.parse_fecha(fecha) if fecha else None
    return [{"paciente": _pac(p), "activo": hd.es_activo(p),
             "le_toca": hd.le_toca(p, f) if f else None,
             "en_hoja": ubic.get(p.id)} for p in encontrados]


@router.get("/hoja/{fecha}/{turno}")
def ver_hoja(fecha: str, turno: str, db: Session = Depends(get_db)):
    """Hoja compuesta de ese día: base + cambios de un día, con conflictos detectados."""
    _consulta(lambda: _validar(fecha, turno))
    return _hoja_out(db, fecha, turno)


@router.post("", status_code=201)
def crear_cambio(data: AsignacionCrear, request: Request, db: Session = Depends(get_db)):
    usuario = _usuario(request)

    def op():
        _validar(data.fecha, data.turno)
        if data.tipo == "reemplazo":
            if data.permanente:
                raise hd.Conflicto("Un reemplazo es solo por un día; no puede ser permanente.")
            if not data.reemplaza_paciente_id:
                raise hd.Conflicto("Indique a quién reemplaza (reemplaza_paciente_id).")
            hd.reemplazar(db, data.fecha, data.turno, data.paciente_id,
                          data.reemplaza_paciente_id, usuario)
        else:
            if data.estacion is None or data.cama is None:
                raise hd.Conflicto("Indique estación y cama de destino.")
            ids = hd.mover(db, data.fecha, data.turno, data.paciente_id, data.estacion,
                           data.cama, usuario, intercambiar=data.intercambiar)
            if data.permanente and ids:
                hd.hacer_permanente(db, ids[0])
        return _hoja_out(db, data.fecha, data.turno)

    return _ejecutar(db, op)


@router.delete("/{asignacion_id}")
def deshacer_cambio(asignacion_id: int, db: Session = Depends(get_db)):
    def op():
        fecha, turno = hd.deshacer(db, asignacion_id)
        return _hoja_out(db, fecha, turno)
    return _ejecutar(db, op)


@router.post("/{asignacion_id}/permanente")
def hacer_permanente(asignacion_id: int, db: Session = Depends(get_db)):
    def op():
        fecha, turno = hd.hacer_permanente(db, asignacion_id)
        return _hoja_out(db, fecha, turno)
    return _ejecutar(db, op)
