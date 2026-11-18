"""
Integración HL7 con las máquinas AK 98 — «Próximamente».

INACTIVA mientras HL7_ENABLED=false: todos los endpoints de este módulo,
salvo GET /api/hl7/estado, responden 404.

Flujo (solo lectura desde la máquina, nunca hacia ella):

  puente ──POST /mensajes (HMAC)──▶ hl7_mensaje (crudo) ──▶ parser + mapeo
         ──▶ hl7_borrador_sesion (pendiente, con banderas de validación)
  enfermería (admin) ──▶ /borradores/{id}/confirmar ──▶ registro de la hoja del día

Nada de lo recibido se vuelve oficial sin la confirmación de una persona.
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import auth
import config
import models
import schemas
from database import get_db
from services.bloqueo_mes import exigir_abierto
from hl7 import firma, mapeo as hl7_mapeo
from hl7.parser import ErrorHL7, parsear
from models_hl7 import Hl7Auditoria, Hl7BorradorSesion, Hl7Mensaje, Hl7PacienteId, ahora_iso
from routers import sesiones

TAM_MAXIMO = 1024 * 1024
CAMPOS_HOJA = ("peso_entrada", "peso_salida", "ktv")  # columnas de `registros` que se llenan solas


def _habilitado() -> None:
    if not config.HL7_ENABLED:
        raise HTTPException(404, "Not Found")


router = APIRouter()
_activo = APIRouter(dependencies=[Depends(_habilitado)])

_mapeo_cache: dict[str, Any] | None = None


def obtener_mapeo() -> dict[str, Any]:
    global _mapeo_cache
    if _mapeo_cache is None:
        _mapeo_cache = hl7_mapeo.cargar_mapeo(config.HL7_MAPEO_PATH or None)
    return _mapeo_cache


def _usuario(request: Request) -> str:
    return (request.session.get("usuario") if config.AUTH_ENABLED else None) or auth.rol_actual(request) or "?"


def _solo_admin(request: Request) -> str:
    if auth.rol_actual(request) != "admin":
        raise HTTPException(403, "Solo el administrador puede hacer esta acción")
    return _usuario(request)


def _auditar(db: Session, usuario: str, accion: str, *, borrador_id: int | None = None,
             mensaje_id: int | None = None, detalle: dict | None = None) -> None:
    db.add(Hl7Auditoria(usuario=usuario, accion=accion, borrador_id=borrador_id,
                        mensaje_id=mensaje_id, detalle=detalle or {}))


# ── Estado (siempre disponible: lo usa la interfaz) ──────────────────────────

@router.get("/estado")
def estado():
    """{habilitado: bool}. Con false la interfaz solo muestra «Próximamente»."""
    return {"habilitado": bool(config.HL7_ENABLED)}


# ── Validaciones del borrador ────────────────────────────────────────────────

def _bandera(codigo: str, nivel: str, mensaje: str) -> dict[str, str]:
    return {"codigo": codigo, "nivel": nivel, "mensaje": mensaje}


def _buscar_paciente(db: Session, id_externo: str) -> tuple[models.Paciente | None, str | None]:
    if not id_externo:
        return None, None
    v = db.query(Hl7PacienteId).filter_by(id_externo=id_externo).first()
    if v:
        return db.get(models.Paciente, v.paciente_id), "vinculo"
    p = db.query(models.Paciente).filter_by(cedula=id_externo).first()
    return (p, "cedula") if p else (None, None)


def _ultimo_peso_salida(db: Session, paciente_id: int, fecha: str | None) -> tuple[float, str] | None:
    q = (db.query(models.Registro.peso_salida, models.Sesion.fecha)
         .join(models.Sesion, models.Registro.sesion_id == models.Sesion.id)
         .filter(models.Registro.paciente_id == paciente_id, models.Registro.peso_salida.isnot(None)))
    if fecha:
        q = q.filter(models.Sesion.fecha < fecha)
    fila = q.order_by(models.Sesion.fecha.desc()).first()
    return (fila[0], fila[1]) if fila else None


def calcular_banderas(db: Session, res: hl7_mapeo.ResultadoMapeo, paciente: models.Paciente | None,
                      via: str | None, mapeo: dict[str, Any]) -> list[dict[str, str]]:
    b: list[dict[str, str]] = []
    v = res.valores
    umbrales = mapeo.get("umbrales", {})

    if paciente is None:
        b.append(_bandera("paciente_desconocido", "alerta",
                          "El id de paciente de la máquina no está vinculado a ningún paciente"))
    elif via == "cedula":
        b.append(_bandera("vinculado_por_cedula", "info", "Paciente identificado por cédula"))
    if not res.fecha or not res.turno:
        b.append(_bandera("sin_fecha_turno", "alerta", "No se pudo determinar la fecha o el turno de la sesión"))

    for campo, (minimo, maximo) in mapeo.get("rangos", {}).items():
        x = v.get(campo)
        if x is not None and not (minimo <= x <= maximo):
            b.append(_bandera("fuera_de_rango", "alerta", f"{campo} = {x} fuera del rango {minimo}–{maximo}"))

    faltan = [c for c in CAMPOS_HOJA if v.get(c) is None]
    if faltan:
        b.append(_bandera("valores_faltantes", "info", "No llegaron: " + ", ".join(faltan)))

    pe, ps, uf = v.get("peso_entrada"), v.get("peso_salida"), v.get("uf_litros")
    if pe is not None and ps is not None and uf is not None:
        dif = abs((pe - ps) - uf)
        if dif > float(umbrales.get("diferencia_uf_kg", 0.8)):
            b.append(_bandera("uf_inconsistente", "alerta",
                              f"Pérdida de peso ({pe - ps:.1f} kg) no coincide con la UF ({uf:.1f} L)"))
    if pe is not None and ps is not None and ps > pe:
        b.append(_bandera("peso_salida_mayor", "alerta", "El peso de salida es mayor que el de entrada"))

    if paciente is not None:
        if pe is not None:
            previo = _ultimo_peso_salida(db, paciente.id, res.fecha)
            if previo and abs(pe - previo[0]) > float(umbrales.get("salto_peso_kg", 3.5)):
                b.append(_bandera("salto_peso", "alerta",
                                  f"Peso de entrada {pe:.1f} kg vs. salida de la última sesión "
                                  f"{previo[0]:.1f} kg ({previo[1]})"))
        if res.turno and paciente.turno and paciente.turno != res.turno:
            b.append(_bandera("turno_distinto", "info",
                              f"La sesión es del turno {res.turno} y el paciente está asignado al {paciente.turno}"))
        if res.fecha and res.turno:
            s = db.query(models.Sesion).filter_by(fecha=res.fecha, turno=res.turno).first()
            if s and s.cerrada:
                b.append(_bandera("sesion_cerrada", "alerta", "La hoja de ese turno ya está cerrada"))

    if v.get("alarmas"):
        b.append(_bandera("alarmas_maquina", "info", f"{len(v['alarmas'])} alarma(s) durante la sesión"))
    if res.no_mapeados:
        b.append(_bandera("obx_no_mapeados", "info", "Observaciones sin mapeo: " + ", ".join(res.no_mapeados[:10])))
    for a in res.advertencias:
        b.append(_bandera("advertencia", "info", a))
    return b


# ── Ingesta (desde el puente) ────────────────────────────────────────────────

@_activo.post("/mensajes", status_code=201)
async def recibir_mensaje(request: Request, db: Session = Depends(get_db)):
    """Recibe un ORU^R01 firmado por el puente y crea un borrador pendiente."""
    largo = request.headers.get("content-length")
    if largo and largo.isdigit() and int(largo) > TAM_MAXIMO:
        raise HTTPException(413, "Mensaje demasiado grande")
    cuerpo = await request.body()
    if len(cuerpo) > TAM_MAXIMO:
        raise HTTPException(413, "Mensaje demasiado grande")
    try:
        firma.verificar_firma(config.HL7_BRIDGE_SECRET, cuerpo,
                              request.headers.get(firma.CABECERA_TIMESTAMP),
                              request.headers.get(firma.CABECERA_FIRMA),
                              ventana=config.HL7_VENTANA_SEGUNDOS)
    except firma.ErrorFirma as e:
        raise HTTPException(401, f"Firma rechazada: {e}")

    texto = cuerpo.decode("utf-8", errors="replace")
    try:
        msg = parsear(cuerpo)
        control_id = msg.control_id[:64]
        error_parseo: str | None = None
    except ErrorHL7 as e:
        msg, error_parseo = None, str(e)
        control_id = ""
    if not control_id:
        control_id = "SIN-CTRL-" + hashlib.sha256(cuerpo).hexdigest()[:24]

    # Idempotencia: el mismo MSH-10 nunca crea dos borradores.
    existente = db.query(Hl7Mensaje).filter_by(control_id=control_id).first()
    if existente:
        return _respuesta_duplicado(db, existente)

    registro = Hl7Mensaje(control_id=control_id, raw=texto, estado="recibido",
                          maquina=(msg.instalacion_emisora[:64] if msg else None))
    db.add(registro)
    try:
        db.flush()
    except IntegrityError:  # otro proceso lo guardó al mismo tiempo
        db.rollback()
        return _respuesta_duplicado(db, db.query(Hl7Mensaje).filter_by(control_id=control_id).one())

    if msg is not None and error_parseo is None:
        try:
            msg.validar_oru_r01()
        except ErrorHL7 as e:
            error_parseo = str(e)
    if error_parseo:
        registro.estado, registro.error = "error", error_parseo[:500]
        _auditar(db, "puente", "mensaje_error", mensaje_id=registro.id, detalle={"error": error_parseo})
        db.commit()
        return JSONResponse({"estado": "error", "control_id": control_id, "detail": error_parseo}, status_code=422)

    mapeo = obtener_mapeo()
    res = hl7_mapeo.aplicar_mapeo(msg, mapeo)
    paciente, via = _buscar_paciente(db, res.id_paciente)
    borrador = Hl7BorradorSesion(
        mensaje_id=registro.id, paciente_id=paciente.id if paciente else None,
        id_externo=res.id_paciente[:64] or None, maquina=registro.maquina,
        fecha=res.fecha, turno=res.turno,
        inicio=res.inicio.isoformat() if res.inicio else None,
        fin=res.fin.isoformat() if res.fin else None,
        valores=res.valores, banderas=calcular_banderas(db, res, paciente, via, mapeo),
    )
    db.add(borrador)
    registro.estado = "procesado"
    db.flush()
    _auditar(db, "puente", "mensaje_recibido", borrador_id=borrador.id, mensaje_id=registro.id,
             detalle={"maquina": registro.maquina, "banderas": [x["codigo"] for x in borrador.banderas]})
    db.commit()
    return {"estado": "procesado", "control_id": control_id, "borrador_id": borrador.id,
            "banderas": [x["codigo"] for x in borrador.banderas]}


def _respuesta_duplicado(db: Session, m: Hl7Mensaje) -> JSONResponse:
    b = db.query(Hl7BorradorSesion).filter_by(mensaje_id=m.id).first()
    return JSONResponse({"estado": "duplicado", "control_id": m.control_id,
                         "borrador_id": b.id if b else None}, status_code=200)


# ── Bandeja de la máquina ────────────────────────────────────────────────────

def _registro_actual(db: Session, b: Hl7BorradorSesion) -> dict | None:
    if not (b.paciente_id and b.fecha and b.turno):
        return None
    s = db.query(models.Sesion).filter_by(fecha=b.fecha, turno=b.turno).first()
    if not s:
        return None
    r = db.query(models.Registro).filter_by(sesion_id=s.id, paciente_id=b.paciente_id).first()
    return {
        "sesion_id": s.id, "sesion_cerrada": bool(s.cerrada), "registro_id": r.id if r else None,
        "asistencia": r.asistencia if r else None, "peso_entrada": r.peso_entrada if r else None,
        "peso_salida": r.peso_salida if r else None, "ktv": r.ktv if r else None,
    }


def _borrador_out(db: Session, b: Hl7BorradorSesion) -> dict:
    p = b.paciente
    return {
        "id": b.id, "estado": b.estado, "maquina": b.maquina, "id_externo": b.id_externo,
        "fecha": b.fecha, "turno": b.turno, "inicio": b.inicio, "fin": b.fin,
        "valores": b.valores or {}, "banderas": b.banderas or [],
        "creado_en": b.creado_en, "resuelto_por": b.resuelto_por, "resuelto_en": b.resuelto_en,
        "registro_id": b.registro_id, "motivo": b.motivo,
        "control_id": b.mensaje.control_id if b.mensaje else None,
        "paciente": {"id": p.id, "nombre": p.nombre, "cedula": p.cedula, "estacion": p.estacion,
                     "cama": p.cama, "turno": p.turno, "peso_seco": p.peso_seco} if p else None,
        "registro_actual": _registro_actual(db, b) if b.estado == "pendiente" else None,
    }


@_activo.get("/borradores")
def listar_borradores(estado: str = "pendiente", limite: int = 200, db: Session = Depends(get_db)):
    q = db.query(Hl7BorradorSesion)
    if estado != "todos":
        q = q.filter_by(estado=estado)
    filas = q.order_by(Hl7BorradorSesion.id.desc()).limit(max(1, min(limite, 500))).all()
    return [_borrador_out(db, b) for b in filas]


@_activo.get("/borradores/{borrador_id}")
def ver_borrador(borrador_id: int, db: Session = Depends(get_db)):
    b = db.get(Hl7BorradorSesion, borrador_id)
    if not b:
        raise HTTPException(404, "Borrador no encontrado")
    return _borrador_out(db, b)


class ConfirmarInput(BaseModel):
    paciente_id: Optional[int] = None    # obligatorio si el paciente es desconocido
    vincular: bool = True                # recordar id de la máquina → paciente
    fecha: Optional[str] = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    turno: Optional[str] = Field(None, pattern=r"^[MTN]$")
    sobrescribir: bool = False           # reemplazar valores ya escritos a mano


def _texto_observaciones(v: dict[str, Any]) -> str:
    partes = []
    if v.get("ta_sistolica") is not None and v.get("ta_diastolica") is not None:
        partes.append(f"TA {v['ta_sistolica']:g}/{v['ta_diastolica']:g}")
    if v.get("frecuencia_cardiaca") is not None:
        partes.append(f"FC {v['frecuencia_cardiaca']:g}")
    if v.get("duracion_min") is not None:
        partes.append(f"{v['duracion_min']:g} min")
    if v.get("uf_litros") is not None:
        partes.append(f"UF {v['uf_litros']:.2f} L")
    if v.get("alarmas"):
        partes.append("Alarmas: " + ", ".join(v["alarmas"]))
    if v.get("observaciones"):
        partes.append(str(v["observaciones"]))
    return ("AK98: " + " · ".join(partes)) if partes else ""


@_activo.post("/borradores/{borrador_id}/confirmar")
def confirmar_borrador(borrador_id: int, data: ConfirmarInput, request: Request, db: Session = Depends(get_db)):
    """Aplica el borrador al registro de la hoja (paciente/fecha/turno). Solo admin."""
    usuario = _solo_admin(request)
    b = db.get(Hl7BorradorSesion, borrador_id)
    if not b:
        raise HTTPException(404, "Borrador no encontrado")
    if b.estado != "pendiente":
        raise HTTPException(409, f"El borrador ya fue {b.estado}")

    paciente_id = data.paciente_id or b.paciente_id
    if not paciente_id:
        raise HTTPException(422, "Seleccione el paciente al que corresponde la sesión")
    paciente = db.get(models.Paciente, paciente_id)
    if not paciente:
        raise HTTPException(404, "Paciente no encontrado")
    fecha, turno = data.fecha or b.fecha, data.turno or b.turno
    if not fecha or not turno:
        raise HTTPException(422, "Indique la fecha y el turno de la sesión")
    exigir_abierto(db, fecha)   # R12: mes cerrado -> 409

    # Sesión del día con la lógica existente (la crea igual que al abrir la hoja).
    sesion = db.query(models.Sesion).filter_by(fecha=fecha, turno=turno).first()
    if sesion is None:
        sesion = sesiones.get_or_create_sesion(fecha, turno, db)
    if sesion.cerrada:
        raise HTTPException(400, "La sesion esta cerrada y no se puede modificar")
    reg = db.query(models.Registro).filter_by(sesion_id=sesion.id, paciente_id=paciente_id).first()
    if reg is None:
        sesiones.agregar_paciente_a_sesion(sesion.id, paciente_id, db)
        reg = db.query(models.Registro).filter_by(sesion_id=sesion.id, paciente_id=paciente_id).one()

    v = b.valores or {}
    cambios: dict[str, Any] = {}
    conflictos: list[dict[str, Any]] = []
    for campo in CAMPOS_HOJA:
        nuevo, actual = v.get(campo), getattr(reg, campo)
        if nuevo is None:
            continue
        if actual is None or data.sobrescribir:
            if actual != nuevo:
                cambios[campo] = nuevo
        elif abs(actual - nuevo) > 1e-9:
            conflictos.append({"campo": campo, "hoja": actual, "maquina": nuevo})
    if not reg.asistencia:
        cambios["asistencia"] = "A"
    nota = _texto_observaciones(v)
    if nota and nota not in (reg.observaciones or ""):
        cambios["observaciones"] = f"{reg.observaciones} | {nota}" if reg.observaciones else nota

    # Vínculo id de la máquina → paciente (para los próximos mensajes).
    if data.vincular and b.id_externo and (data.paciente_id and data.paciente_id != b.paciente_id):
        v_ex = db.query(Hl7PacienteId).filter_by(id_externo=b.id_externo).first()
        if v_ex:
            v_ex.paciente_id, v_ex.creado_por, v_ex.creado_en = paciente_id, usuario, ahora_iso()
        else:
            db.add(Hl7PacienteId(id_externo=b.id_externo, paciente_id=paciente_id, creado_por=usuario))
        _auditar(db, usuario, "vincular", borrador_id=b.id, detalle={"paciente_id": paciente_id})

    b.estado, b.paciente_id, b.fecha, b.turno = "confirmado", paciente_id, fecha, turno
    b.resuelto_por, b.resuelto_en, b.registro_id = usuario, ahora_iso(), reg.id
    _auditar(db, usuario, "confirmar", borrador_id=b.id, mensaje_id=b.mensaje_id,
             detalle={"registro_id": reg.id, "sesion_id": sesion.id, "aplicados": sorted(cambios),
                      "conflictos": conflictos, "sobrescribir": data.sobrescribir})

    # Misma ruta que la edición manual: respeta el bloqueo de sesión y hace commit.
    registro_out = sesiones.update_registro(reg.id, schemas.RegistroUpdate(**cambios), db)
    return {"borrador": _borrador_out(db, b), "registro": registro_out,
            "aplicados": sorted(cambios), "conflictos": conflictos}


class DescartarInput(BaseModel):
    motivo: str = Field("", max_length=300)


@_activo.post("/borradores/{borrador_id}/descartar")
def descartar_borrador(borrador_id: int, data: DescartarInput, request: Request, db: Session = Depends(get_db)):
    usuario = _solo_admin(request)
    b = db.get(Hl7BorradorSesion, borrador_id)
    if not b:
        raise HTTPException(404, "Borrador no encontrado")
    if b.estado != "pendiente":
        raise HTTPException(409, f"El borrador ya fue {b.estado}")
    b.estado, b.resuelto_por, b.resuelto_en, b.motivo = "descartado", usuario, ahora_iso(), data.motivo or None
    _auditar(db, usuario, "descartar", borrador_id=b.id, mensaje_id=b.mensaje_id, detalle={"motivo": data.motivo})
    db.commit()
    return _borrador_out(db, b)


# ── Vínculos id de máquina → paciente ────────────────────────────────────────

class VinculoInput(BaseModel):
    id_externo: str = Field(..., min_length=1, max_length=64)
    paciente_id: int


@_activo.get("/vinculos")
def listar_vinculos(db: Session = Depends(get_db)):
    return [{"id": x.id, "id_externo": x.id_externo, "paciente_id": x.paciente_id,
             "paciente": x.paciente.nombre if x.paciente else None,
             "creado_en": x.creado_en, "creado_por": x.creado_por}
            for x in db.query(Hl7PacienteId).order_by(Hl7PacienteId.id_externo).all()]


@_activo.post("/vinculos", status_code=201)
def crear_vinculo(data: VinculoInput, request: Request, db: Session = Depends(get_db)):
    usuario = _solo_admin(request)
    if not db.get(models.Paciente, data.paciente_id):
        raise HTTPException(404, "Paciente no encontrado")
    if db.query(Hl7PacienteId).filter_by(id_externo=data.id_externo).first():
        raise HTTPException(409, "Ese id de máquina ya está vinculado")
    x = Hl7PacienteId(id_externo=data.id_externo, paciente_id=data.paciente_id, creado_por=usuario)
    db.add(x)
    db.flush()
    _auditar(db, usuario, "vincular", detalle={"id_externo": data.id_externo, "paciente_id": data.paciente_id})
    db.commit()
    return {"id": x.id, "id_externo": x.id_externo, "paciente_id": x.paciente_id}


@_activo.delete("/vinculos/{vinculo_id}")
def borrar_vinculo(vinculo_id: int, request: Request, db: Session = Depends(get_db)):
    usuario = _solo_admin(request)
    x = db.get(Hl7PacienteId, vinculo_id)
    if not x:
        raise HTTPException(404, "Vínculo no encontrado")
    _auditar(db, usuario, "desvincular", detalle={"id_externo": x.id_externo, "paciente_id": x.paciente_id})
    db.delete(x)
    db.commit()
    return {"ok": True}


@_activo.get("/auditoria")
def ver_auditoria(request: Request, limite: int = 100, db: Session = Depends(get_db)):
    _solo_admin(request)
    filas = db.query(Hl7Auditoria).order_by(Hl7Auditoria.id.desc()).limit(max(1, min(limite, 1000))).all()
    return [{"id": a.id, "momento": a.momento, "usuario": a.usuario, "accion": a.accion,
             "borrador_id": a.borrador_id, "mensaje_id": a.mensaje_id, "detalle": a.detalle} for a in filas]


router.include_router(_activo)
