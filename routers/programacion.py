from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from datetime import date
import calendar as cal_mod
import models, schemas
from database import get_db

router = APIRouter()


# ── Helpers calendario ────────────────────────────────────────────────────────

_DIAS_WEEKDAY = {"LMV": [0, 2, 4], "TJS": [1, 3, 5]}  # Mon/Wed/Fri or Tue/Thu/Sat


def _fechas_grupo(anio: int, mes: int, dias_grupo: str) -> list[str]:
    """Todas las fechas del mes que corresponden al grupo LMV o TJS."""
    targets = _DIAS_WEEKDAY.get(dias_grupo, [])
    if not targets:
        return []
    num_days = cal_mod.monthrange(anio, mes)[1]
    return [
        date(anio, mes, d).isoformat()
        for d in range(1, num_days + 1)
        if date(anio, mes, d).weekday() in targets
    ]


def _indices_distribuidos(total: int, n: int) -> set[int]:
    """Distribuye n elementos de forma equidistante entre total posiciones."""
    if n <= 0 or total <= 0:
        return set()
    if n >= total:
        return set(range(total))
    step = total / n
    return {int(i * step) for i in range(n)}


# ── Rutas existentes ──────────────────────────────────────────────────────────

@router.get("/{fecha}/{turno}", response_model=list[schemas.ProgramacionOut])
def get_programacion(fecha: str, turno: str, db: Session = Depends(get_db)):
    return (
        db.query(models.Programacion)
        .filter_by(fecha=fecha, turno=turno)
        .options(joinedload(models.Programacion.paciente))
        .join(models.Paciente)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )


@router.post("", response_model=list[schemas.ProgramacionOut], status_code=201)
def guardar_programacion(data: schemas.ProgramacionBulk, db: Session = Depends(get_db)):
    """Reemplaza la programación de una fecha+turno con la lista enviada."""
    db.query(models.Programacion).filter_by(fecha=data.fecha, turno=data.turno).delete()

    nuevos = []
    for item in data.items:
        if not db.get(models.Paciente, item.paciente_id):
            raise HTTPException(404, f"Paciente {item.paciente_id} no encontrado")
        p = models.Programacion(
            fecha=data.fecha,
            turno=data.turno,
            paciente_id=item.paciente_id,
            epo_programado=item.epo_programado,
            hierro_programado=item.hierro_programado,
        )
        db.add(p)
        nuevos.append(p)

    db.commit()
    for p in nuevos:
        db.refresh(p)

    return (
        db.query(models.Programacion)
        .filter_by(fecha=data.fecha, turno=data.turno)
        .options(joinedload(models.Programacion.paciente))
        .join(models.Paciente)
        .order_by(models.Paciente.estacion, models.Paciente.cama)
        .all()
    )


# ── Auto-programación mensual EPO/Fe ─────────────────────────────────────────

@router.post("/auto-mes", response_model=schemas.AutoMesResult, status_code=201)
def auto_programar_mes(data: schemas.AutoMesInput, db: Session = Depends(get_db)):
    """
    Genera la programación EPO/Fe de TODO el mes para el turno indicado.

    Reglas:
    - Solo pacientes activos del turno con `dias` (LMV|TJS) configurado.
    - EPO: distribuye round(epo_mensual/epo_dosis) dosis equidistantes entre
      las sesiones del mes del paciente.
    - Fe: distribuye `hierro_mensual` dosis equidistantes entre esas sesiones.
    - Reemplaza cualquier programación existente para esas fechas+turno.
    """
    if data.turno not in ("M", "T", "N"):
        raise HTTPException(400, "Turno inválido")
    if not (1 <= data.mes <= 12):
        raise HTTPException(400, "Mes inválido")

    pacientes = (
        db.query(models.Paciente)
        .filter_by(turno=data.turno, activo=True)
        .filter(models.Paciente.dias.isnot(None))
        .all()
    )

    if not pacientes:
        raise HTTPException(404, "No hay pacientes con días configurados en este turno")

    # Eliminar programaciones previas del mes para este turno
    num_days = cal_mod.monthrange(data.anio, data.mes)[1]
    fechas_mes = [date(data.anio, data.mes, d).isoformat() for d in range(1, num_days + 1)]
    for fecha in fechas_mes:
        db.query(models.Programacion).filter_by(fecha=fecha, turno=data.turno).delete()

    resumen_pacientes = []
    total_prog = 0

    for p in pacientes:
        fechas_pac = _fechas_grupo(data.anio, data.mes, p.dias)
        n_sesiones = len(fechas_pac)
        if n_sesiones == 0:
            continue

        # Calcular número de dosis EPO
        n_epo = 0
        if p.epo_mensual and p.epo_dosis and p.epo_dosis > 0:
            n_epo = round(p.epo_mensual / p.epo_dosis)

        # Calcular número de dosis Fe
        n_hierro = p.hierro_mensual or 0

        indices_epo    = _indices_distribuidos(n_sesiones, n_epo)
        indices_hierro = _indices_distribuidos(n_sesiones, n_hierro)

        epo_count    = 0
        hierro_count = 0

        for i, fecha in enumerate(fechas_pac):
            aplica_epo    = i in indices_epo
            aplica_hierro = i in indices_hierro
            if aplica_epo:
                epo_count += 1
            if aplica_hierro:
                hierro_count += 1

            prog = models.Programacion(
                fecha=fecha,
                turno=data.turno,
                paciente_id=p.id,
                epo_programado=aplica_epo,
                hierro_programado=aplica_hierro,
            )
            db.add(prog)
            total_prog += 1

        resumen_pacientes.append(schemas.AutoMesPacienteResult(
            nombre=p.nombre,
            cedula=p.cedula,
            dias=p.dias,
            sesiones=n_sesiones,
            epo_count=epo_count,
            hierro_count=hierro_count,
        ))

    db.commit()
    return schemas.AutoMesResult(programados=total_prog, pacientes=resumen_pacientes)


@router.get("/resumen-mes", response_model=schemas.AutoMesResult)
def resumen_mes(anio: int, mes: int, turno: str, db: Session = Depends(get_db)):
    """Preview: cuántas dosis EPO/Fe quedarían por paciente sin modificar la BD."""
    if turno not in ("M", "T", "N"):
        raise HTTPException(400, "Turno inválido")

    pacientes = (
        db.query(models.Paciente)
        .filter_by(turno=turno, activo=True)
        .filter(models.Paciente.dias.isnot(None))
        .all()
    )

    resumen = []
    for p in pacientes:
        fechas_pac = _fechas_grupo(anio, mes, p.dias)
        n_sesiones = len(fechas_pac)
        n_epo = 0
        if p.epo_mensual and p.epo_dosis and p.epo_dosis > 0:
            n_epo = round(p.epo_mensual / p.epo_dosis)
        n_hierro = p.hierro_mensual or 0
        n_epo    = min(n_epo, n_sesiones)
        n_hierro = min(n_hierro, n_sesiones)
        resumen.append(schemas.AutoMesPacienteResult(
            nombre=p.nombre, cedula=p.cedula, dias=p.dias,
            sesiones=n_sesiones, epo_count=n_epo, hierro_count=n_hierro,
        ))

    return schemas.AutoMesResult(programados=0, pacientes=resumen)
