from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import models, schemas
import hoja_dia
from database import get_db

router = APIRouter()


def _paciente_dict(p):
    """Paciente embebido en el registro: mismos campos que PacienteOut (incluye acceso, ui, estado…)."""
    return schemas.PacienteOut.model_validate(p).model_dump() if p else None


def _build_registro_out(r: models.Registro) -> dict:
    perdida = None
    ganancia = None
    balance = None

    if r.peso_entrada is not None and r.peso_salida is not None:
        perdida = round(r.peso_entrada - r.peso_salida, 2)

    if r.paciente and r.paciente.peso_seco is not None and r.peso_entrada is not None:
        ganancia = round(r.peso_entrada - r.paciente.peso_seco, 2)

    if r.paciente and r.paciente.peso_seco is not None and r.peso_salida is not None:
        balance = round(r.peso_salida - r.paciente.peso_seco, 2)

    return {
        "id": r.id,
        "sesion_id": r.sesion_id,
        "paciente_id": r.paciente_id,
        "asistencia": r.asistencia,
        "peso_entrada": r.peso_entrada,
        "peso_salida": r.peso_salida,
        "perdida_real": perdida,
        "ganancia_id": ganancia,
        "balance_seco": balance,
        "epo": bool(r.epo),
        "hierro": bool(r.hierro),
        "observaciones": r.observaciones or "",
        "ktv": r.ktv,
        "pa_pie_sistolica": r.pa_pie_sistolica,
        "pa_pie_diastolica": r.pa_pie_diastolica,
        "fc": r.fc,
        "citrato": bool(r.citrato),
        "heparina_sodica": bool(r.heparina_sodica),
        "adicional": bool(r.adicional),
        "transitorio_nombre": r.transitorio_nombre or "",
        "transitorio_paciente_id": r.transitorio_paciente_id,
        "transitorio_asistencia": r.transitorio_asistencia,
        "transitorio_paciente": _paciente_dict(r.transitorio_paciente),
        "paciente": _paciente_dict(r.paciente),
    }


# ── Rutas con segmento literal PRIMERO para evitar ambigüedad con /{a}/{b} ──

@router.patch("/registros/{registro_id}")
def update_registro(
    registro_id: int, data: schemas.RegistroUpdate, db: Session = Depends(get_db)
):
    r = (
        db.query(models.Registro)
        .options(joinedload(models.Registro.paciente),
                 joinedload(models.Registro.transitorio_paciente))
        .filter_by(id=registro_id)
        .first()
    )
    if not r:
        raise HTTPException(404, "Registro no encontrado")

    sesion = db.get(models.Sesion, r.sesion_id)
    if sesion.cerrada:
        raise HTTPException(400, "La sesion esta cerrada y no se puede modificar")

    cambios = data.model_dump(exclude_unset=True)

    # R3: la sistólica debe ser mayor que la diastólica (se compara con lo ya guardado)
    sis = cambios.get("pa_pie_sistolica", r.pa_pie_sistolica)
    dia = cambios.get("pa_pie_diastolica", r.pa_pie_diastolica)
    if sis is not None and dia is not None and sis <= dia:
        raise HTTPException(422, "La PA sistólica debe ser mayor que la diastólica")

    for k, v in cambios.items():
        setattr(r, k, v)

    db.commit()
    db.refresh(r)
    return hoja_dia.con_ubicacion(_build_registro_out(r), r)


@router.get("/{sesion_id}/registros")
def get_registros(sesion_id: int, db: Session = Depends(get_db)):
    sesion = db.get(models.Sesion, sesion_id)
    if not sesion:
        raise HTTPException(404, "Sesion no encontrada")

    registros = (
        db.query(models.Registro)
        .filter_by(sesion_id=sesion_id)
        .options(joinedload(models.Registro.paciente),
                 joinedload(models.Registro.transitorio_paciente))
        .join(models.Paciente, models.Registro.paciente_id == models.Paciente.id)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )
    return [hoja_dia.con_ubicacion(_build_registro_out(r), r) for r in registros]


@router.post("/{sesion_id}/paciente/{paciente_id}", status_code=201)
def agregar_paciente_a_sesion(
    sesion_id: int, paciente_id: int, db: Session = Depends(get_db)
):
    """Agrega un paciente a una sesion existente (admision en el dia)."""
    sesion = db.get(models.Sesion, sesion_id)
    if not sesion:
        raise HTTPException(404, "Sesion no encontrada")
    if sesion.cerrada:
        raise HTTPException(400, "La sesion esta cerrada")
    if not db.get(models.Paciente, paciente_id):
        raise HTTPException(404, "Paciente no encontrado")

    existente = db.query(models.Registro).filter_by(
        sesion_id=sesion_id, paciente_id=paciente_id
    ).first()
    if existente:
        raise HTTPException(400, "El paciente ya esta en esta sesion")

    pac = db.get(models.Paciente, paciente_id)
    r = models.Registro(sesion_id=sesion_id, paciente_id=paciente_id,
                        estacion=pac.estacion, cama=pac.cama)
    db.add(r)
    db.commit()

    r = (
        db.query(models.Registro)
        .options(joinedload(models.Registro.paciente),
                 joinedload(models.Registro.transitorio_paciente))
        .filter_by(id=r.id)
        .first()
    )
    return hoja_dia.con_ubicacion(_build_registro_out(r), r)


# ── Ruta parametrica ULTIMA (evita que capture /int/registros) ──────────────

@router.get("/{fecha}/{turno}", response_model=schemas.SesionOut)
def get_or_create_sesion(fecha: str, turno: str, db: Session = Depends(get_db)):
    if turno not in ("M", "T", "N"):
        raise HTTPException(400, "Turno debe ser M, T o N")

    sesion = db.query(models.Sesion).filter_by(fecha=fecha, turno=turno).first()
    if sesion:
        return sesion

    sesion = models.Sesion(fecha=fecha, turno=turno)
    db.add(sesion)
    db.flush()

    # Hoja del día = ubicación base (días LMV/MJS, programación guardada) +
    # cambios de un día de esa fecha (R2/R7). Ver hoja_dia.componer().
    try:
        hoja_dia.crear_registros(db, sesion)
    except hoja_dia.Conflicto as e:
        db.rollback()
        raise HTTPException(400, str(e))

    db.commit()
    db.refresh(sesion)
    return sesion
