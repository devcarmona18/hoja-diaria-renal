"""R13 — Panel clínico por estado, comparativa, rangos, médicos y notificaciones de Teams."""
import secrets
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import auth
import config
import models
from database import get_db
from routers.laboratorios import TIPOS_VALIDOS
from services import labs as srv
from services import teams
from services.medicos import (asegurar_medicos, enmascarar, iniciales_paciente, normalizar,
                              webhook_valido)
from services.pacientes import ahora_utc, consulta_activos

router = APIRouter()
ESTADOS_FILTRO = set(srv.ESTADOS) | {"sin_dato", "sin_rango"}


# ── Rangos configurables ─────────────────────────────────────────────────────
class RangoIn(BaseModel):
    minimo: Optional[float] = Field(None, ge=0)
    maximo: Optional[float] = Field(None, ge=0)
    muy_alto: Optional[float] = Field(None, ge=0)


@router.get("/rangos")
def listar_rangos(db: Session = Depends(get_db)):
    return list(srv.rangos(db).values())


@router.put("/rangos/{tipo}")
def guardar_rango(tipo: str, data: RangoIn, request: Request, db: Session = Depends(get_db)):
    auth.requerir_admin(request)
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(404, "Tipo de laboratorio desconocido")
    err = srv.validar_rango(data.minimo, data.maximo, data.muy_alto)
    if err:
        raise HTTPException(422, err)
    r = db.get(models.LabRango, tipo) or models.LabRango(tipo=tipo)
    r.minimo, r.maximo, r.muy_alto = data.minimo, data.maximo, data.muy_alto
    db.add(r)
    db.commit()
    return srv.rangos(db)[tipo]


@router.delete("/rangos/{tipo}")
def restablecer_rango(tipo: str, request: Request, db: Session = Depends(get_db)):
    """Vuelve a los valores por defecto."""
    auth.requerir_admin(request)
    r = db.get(models.LabRango, tipo)
    if r:
        db.delete(r)
        db.commit()
    if tipo not in srv.DEFECTOS:
        raise HTTPException(404, "Tipo de laboratorio desconocido")
    return srv.rangos(db)[tipo]


# ── Panel filtrable por estado ───────────────────────────────────────────────
@router.get("/panel")
def panel(
    tipo: str = Query(..., description="Analito, p. ej. Hb"),
    estado: Optional[str] = Query(None, description="bajo,normal,alto,muy_alto,sin_dato (separados por coma)"),
    medico: Optional[str] = Query(None),
    turno: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Último valor de ``tipo`` de cada paciente ACTIVO, con su estado, última muestra y médico tratante."""
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, f"Tipo inválido. Válidos: {sorted(TIPOS_VALIDOS)}")
    filtro = {e.strip() for e in estado.split(",") if e.strip()} if estado else set()
    if filtro - ESTADOS_FILTRO:
        raise HTTPException(422, f"Estado inválido. Válidos: {sorted(ESTADOS_FILTRO)}")
    rango = srv.rangos(db)[tipo]
    pacientes = consulta_activos(db, turno=turno).all()
    ultimos = srv.ultimos_valores(db, {p.id for p in pacientes}, tipo)
    clave_medico = normalizar(medico) if medico else None

    filas, conteo = [], defaultdict(int)
    for p in pacientes:
        if clave_medico is not None and normalizar(p.medico) != clave_medico:
            continue
        lab = ultimos.get((p.id, tipo))
        est = srv.estado(lab.valor if lab else None, rango)
        conteo[est] += 1
        if filtro and est not in filtro:
            continue
        filas.append({
            "paciente_id": p.id, "nombre": p.nombre, "iniciales": iniciales_paciente(p.nombre),
            "estacion": p.estacion, "cama": p.cama, "turno": p.turno, "medico": p.medico or "",
            "valor": lab.valor if lab else None, "unidad": rango["unidad"],
            "estado": est, "estado_etiqueta": srv.ESTADO_ETIQUETA[est],
            "fecha": lab.fecha if lab else None,
        })
    return {"tipo": tipo, "rango": rango, "total": sum(conteo.values()), "conteo": dict(conteo),
            "medicos": sorted({p.medico.strip() for p in pacientes if (p.medico or "").strip()}),
            "pacientes": filas}


# ── Comparativa por paciente ─────────────────────────────────────────────────
@router.get("/comparativa/{paciente_id}")
def comparativa(paciente_id: int, tipo: str = Query(...), db: Session = Depends(get_db)):
    """Tomas y promedio por mes de un analito (también para pacientes archivados)."""
    if tipo not in TIPOS_VALIDOS:
        raise HTTPException(400, "Tipo inválido")
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    rango = srv.rangos(db)[tipo]
    labs = (db.query(models.Laboratorio).filter_by(paciente_id=paciente_id, tipo=tipo)
            .order_by(models.Laboratorio.fecha, models.Laboratorio.id).all())
    tomas = [{"fecha": l.fecha, "valor": l.valor, "estado": srv.estado(l.valor, rango)} for l in labs]
    por_mes: dict[str, list[float]] = defaultdict(list)
    for t in tomas:
        por_mes[t["fecha"][:7]].append(t["valor"])
    meses, previo = [], None
    for mes in sorted(por_mes):
        prom = round(sum(por_mes[mes]) / len(por_mes[mes]), 2)
        meses.append({"mes": mes, "promedio": prom, "tomas": len(por_mes[mes]),
                      "estado": srv.estado(prom, rango),
                      "variacion": round(prom - previo, 2) if previo is not None else None})
        previo = prom
    return {"paciente_id": paciente_id, "nombre": p.nombre, "tipo": tipo, "rango": rango,
            "tomas": tomas, "meses": meses}


# ── Médicos y webhooks ───────────────────────────────────────────────────────
class MedicoIn(BaseModel):
    iniciales: Optional[str] = Field(None, max_length=10)
    teams_webhook_url: Optional[str] = Field(None, max_length=600)   # "" = quitar


def _medico_out(m: models.Medico) -> dict:
    return {"id": m.id, "nombre": m.nombre, "iniciales": m.iniciales,
            "tiene_webhook": bool(m.teams_webhook_url), "webhook_valido": webhook_valido(m.teams_webhook_url),
            "webhook_enmascarado": enmascarar(m.teams_webhook_url)}


@router.get("/medicos")
def listar_medicos(db: Session = Depends(get_db)):
    asegurar_medicos(db)
    db.commit()
    return [_medico_out(m) for m in db.query(models.Medico).order_by(models.Medico.nombre).all()]


@router.put("/medicos/{medico_id}")
def actualizar_medico(medico_id: int, data: MedicoIn, request: Request, db: Session = Depends(get_db)):
    auth.requerir_admin(request)
    m = db.get(models.Medico, medico_id)
    if not m:
        raise HTTPException(404, "Médico no encontrado")
    cambios = data.model_dump(exclude_unset=True)
    if "iniciales" in cambios:
        m.iniciales = (cambios["iniciales"] or "").strip().upper()
    if "teams_webhook_url" in cambios:
        url = (cambios["teams_webhook_url"] or "").strip()
        if url and not webhook_valido(url):
            raise HTTPException(422, "El webhook debe ser https y de un dominio de Microsoft permitido")
        m.teams_webhook_url = url or None
    db.commit()
    return _medico_out(m)


# ── Notificaciones de Teams ──────────────────────────────────────────────────
class EnviarIn(BaseModel):
    forzar: bool = False                  # ignora «hoy es día de envío» y «ya enviado hoy»
    medico_id: Optional[int] = None


def _token_valido(request: Request) -> bool:
    esperado = config.TEAMS_JOB_TOKEN
    if not esperado:
        return False
    cab = request.headers.get("authorization", "")
    dado = cab[7:].strip() if cab.lower().startswith("bearer ") else request.headers.get("x-job-token", "")
    return bool(dado) and secrets.compare_digest(dado.encode(), esperado.encode())


@router.get("/notificaciones/estado")
def estado_notificaciones(db: Session = Depends(get_db)):
    ultimos = (db.query(models.TeamsEnvio).order_by(models.TeamsEnvio.id.desc()).limit(10).all())
    return {"enabled": config.TEAMS_ENABLED, "dias_envio": teams.dias_de_envio(),
            "hoy_es_dia_de_envio": teams.es_dia_de_envio(), "token_configurado": bool(config.TEAMS_JOB_TOKEN),
            "ultimos_envios": [{"fecha": e.fecha, "medico_id": e.medico_id, "pacientes": e.pacientes,
                                "estado": e.estado, "detalle": e.detalle or ""} for e in ultimos]}


@router.get("/notificaciones/vista-previa")
def vista_previa(request: Request, medico_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    """Reporte por médico y mensaje que se enviaría. NO envía nada, funcione o no Teams."""
    auth.requerir_admin(request)
    reportes = teams.construir_reportes(db, medico_id)
    db.commit()
    return {"enabled": config.TEAMS_ENABLED,
            "reportes": [{**r, "payload": teams.construir_payload(r)} for r in reportes]}


@router.post("/notificaciones/enviar")
def enviar_notificaciones(request: Request, data: Optional[EnviarIn] = Body(None), db: Session = Depends(get_db)):
    """Envía el reporte a Teams. Autoriza el admin con sesión o el token ``TEAMS_JOB_TOKEN`` (trabajo programado).
    Con TEAMS_ENABLED=false responde 200 sin hacer ninguna llamada de red."""
    if not _token_valido(request):
        auth.requerir_admin(request)
    data = data or EnviarIn()
    res = teams.enviar_notificaciones(db, forzar=data.forzar, medico_id=data.medico_id)
    db.commit()
    return res
