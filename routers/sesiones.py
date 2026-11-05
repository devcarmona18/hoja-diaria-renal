from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import models, schemas
from database import get_db

router = APIRouter()


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
        "citrato": bool(r.citrato),
        "heparina_sodica": bool(r.heparina_sodica),
        "transitorio_nombre": r.transitorio_nombre or "",
        "transitorio_paciente_id": r.transitorio_paciente_id,
        "transitorio_asistencia": r.transitorio_asistencia,
        "transitorio_paciente": {
            "id":                r.transitorio_paciente.id,
            "nombre":            r.transitorio_paciente.nombre,
            "cedula":            r.transitorio_paciente.cedula,
            "estacion":          r.transitorio_paciente.estacion,
            "cama":              r.transitorio_paciente.cama,
            "turno":             r.transitorio_paciente.turno,
            "peso_seco":         r.transitorio_paciente.peso_seco,
            "activo":            r.transitorio_paciente.activo,
            "acceso":            r.transitorio_paciente.acceso,
            "acceso_cm":         r.transitorio_paciente.acceso_cm,
            "heparina_unidades": r.transitorio_paciente.heparina_unidades,
            "tipo_filtro":       r.transitorio_paciente.tipo_filtro,
            "watson":            r.transitorio_paciente.watson,
            "medico":            r.transitorio_paciente.medico,
        } if r.transitorio_paciente else None,
        "paciente": {
            "id": r.paciente.id,
            "nombre": r.paciente.nombre,
            "cedula": r.paciente.cedula,
            "estacion": r.paciente.estacion,
            "cama": r.paciente.cama,
            "turno": r.paciente.turno,
            "peso_seco": r.paciente.peso_seco,
            "activo": r.paciente.activo,
            "acceso": r.paciente.acceso,
            "acceso_cm": r.paciente.acceso_cm,
            "heparina_unidades": r.paciente.heparina_unidades,
            "tipo_filtro": r.paciente.tipo_filtro,
            "watson": r.paciente.watson,
            "medico": r.paciente.medico,
        } if r.paciente else None,
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

    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)

    db.commit()
    db.refresh(r)
    return _build_registro_out(r)


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
    return [_build_registro_out(r) for r in registros]


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

    r = models.Registro(sesion_id=sesion_id, paciente_id=paciente_id)
    db.add(r)
    db.commit()

    r = (
        db.query(models.Registro)
        .options(joinedload(models.Registro.paciente),
                 joinedload(models.Registro.transitorio_paciente))
        .filter_by(id=r.id)
        .first()
    )
    return _build_registro_out(r)


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

    programados = (
        db.query(models.Programacion)
        .filter_by(fecha=fecha, turno=turno)
        .all()
    )

    if programados:
        for prog in programados:
            db.add(models.Registro(
                sesion_id=sesion.id,
                paciente_id=prog.paciente_id,
                epo=prog.epo_programado,
                hierro=prog.hierro_programado,
            ))
    else:
        pacientes = (
            db.query(models.Paciente)
            .filter_by(turno=turno, activo=True)
            .order_by(models.Paciente.estacion, models.Paciente.cama)
            .all()
        )
        for p in pacientes:
            db.add(models.Registro(sesion_id=sesion.id, paciente_id=p.id))

    db.commit()
    db.refresh(sesion)
    return sesion
