from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import models, schemas
from database import get_db
from services.pacientes import consulta_activos, registrar_cambio_activo

router = APIRouter()


@router.get("", response_model=list[schemas.PacienteOut])
def listar_pacientes(
    turno: Optional[str] = Query(None),
    estacion: Optional[int] = Query(None),
    activo: Optional[bool] = Query(None),   # None = todos
    db: Session = Depends(get_db),
):
    if activo is True:
        return consulta_activos(db, turno, estacion).all()
    q = db.query(models.Paciente).filter(models.Paciente.archivado_en.is_(None))   # R13: archivados fuera
    if turno:
        q = q.filter(models.Paciente.turno == turno)
    if estacion:
        q = q.filter(models.Paciente.estacion == estacion)
    if activo is False:
        q = q.filter(models.Paciente.activo.isnot(True))
    return q.order_by(models.Paciente.estacion, models.Paciente.cama).all()


@router.post("", response_model=schemas.PacienteOut, status_code=201)
def crear_paciente(data: schemas.PacienteCreate, db: Session = Depends(get_db)):
    if db.query(models.Paciente).filter_by(cedula=data.cedula).first():
        raise HTTPException(400, "Cédula ya registrada")
    p = models.Paciente(**data.model_dump())
    db.add(p)
    if p.activo is False:   # R12: se crea ya inactivo -> su periodo empieza hoy
        db.flush()
        registrar_cambio_activo(db, p, True)
    db.commit()
    db.refresh(p)
    return p


def _retirar_de_sesiones_abiertas(db: Session, paciente_id: int) -> None:
    """Un paciente inactivo no debe aparecer en las hojas aún abiertas."""
    for sesion in db.query(models.Sesion).filter_by(cerrada=False).all():
        reg = db.query(models.Registro).filter_by(
            sesion_id=sesion.id, paciente_id=paciente_id
        ).first()
        if reg:
            db.delete(reg)


@router.put("/{paciente_id}", response_model=schemas.PacienteOut)
def actualizar_paciente(
    paciente_id: int, data: schemas.PacienteCreate, db: Session = Depends(get_db)
):
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is not None:
        raise HTTPException(409, "El paciente está archivado: restáurelo antes de editarlo")
    estaba_activo = p.activo is True
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    if estaba_activo and not p.activo:
        _retirar_de_sesiones_abiertas(db, paciente_id)
    registrar_cambio_activo(db, p, estaba_activo)   # R12: periodos de inactividad
    db.commit()
    db.refresh(p)
    return p


@router.patch("/{paciente_id}/toggle-activo", response_model=schemas.PacienteOut)
def toggle_activo(
    paciente_id: int,
    data: Optional[schemas.CambioEstadoPaciente] = Body(None),
    db: Session = Depends(get_db),
):
    """Alterna activo/inactivo. Al desactivar acepta {motivo, motivo_texto} (R10); al reactivar los borra."""
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    if p.archivado_en is not None:
        raise HTTPException(409, "El paciente está archivado: restáurelo desde «Archivados»")
    estaba_activo = p.activo is True
    p.activo = not estaba_activo

    if p.activo:
        p.motivo_inactivo = None
        p.motivo_inactivo_texto = None
    else:
        p.motivo_inactivo = data.motivo if data else None
        texto = (data.motivo_texto or "").strip() if data else ""
        p.motivo_inactivo_texto = texto or None
        _retirar_de_sesiones_abiertas(db, paciente_id)
    registrar_cambio_activo(db, p, estaba_activo)   # R12: periodos de inactividad

    db.commit()
    db.refresh(p)
    return p


@router.get("/{paciente_id}/resumen-sesiones")
def resumen_sesiones(
    paciente_id: int,
    dias: int = Query(14, ge=1, le=60, description="Ventana en días hacia atrás"),
    hasta: Optional[str] = Query(None, description="Fecha ISO final de la ventana (por defecto hoy)"),
    db: Session = Depends(get_db),
):
    """R3: sesiones del paciente en los últimos `dias` días (más reciente primero)."""
    p = db.get(models.Paciente, paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")
    try:
        fin = date.fromisoformat(hasta) if hasta else date.today()
    except ValueError:
        raise HTTPException(422, "hasta debe ser una fecha ISO (YYYY-MM-DD)")
    ini = fin - timedelta(days=dias - 1)

    filas = (
        db.query(models.Registro, models.Sesion)
        .join(models.Sesion, models.Registro.sesion_id == models.Sesion.id)
        .filter(models.Registro.paciente_id == paciente_id,
                models.Sesion.fecha >= ini.isoformat(),
                models.Sesion.fecha <= fin.isoformat())
        .order_by(models.Sesion.fecha.desc(), models.Sesion.turno)
        .all()
    )

    sesiones = []
    for r, s in filas:
        perdida = ganancia = None
        if r.peso_entrada is not None and r.peso_salida is not None:
            perdida = round(r.peso_entrada - r.peso_salida, 2)
        if r.peso_entrada is not None and p.peso_seco is not None:
            ganancia = round(r.peso_entrada - p.peso_seco, 2)
        sesiones.append({
            "fecha": s.fecha,
            "turno": s.turno,
            "sesion_id": s.id,
            "registro_id": r.id,
            "asistencia": r.asistencia,
            "peso_entrada": r.peso_entrada,
            "peso_salida": r.peso_salida,
            "peso_seco": p.peso_seco,
            "ganancia": ganancia,
            "perdida": perdida,
            "pa_pie_sistolica": r.pa_pie_sistolica,
            "pa_pie_diastolica": r.pa_pie_diastolica,
            "fc": r.fc,
            "ktv": r.ktv,
            "observaciones": r.observaciones or "",
        })

    return {
        "paciente": {"id": p.id, "nombre": p.nombre, "activo": p.activo is True,
                     "peso_seco": p.peso_seco},
        "desde": ini.isoformat(),
        "hasta": fin.isoformat(),
        "dias": dias,
        "sesiones": sesiones,
    }
