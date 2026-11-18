"""Utilidades de prueba R11-R13: pacientes/sesiones temporales y limpieza completa (incluye tablas nuevas)."""
import contextlib

import models
from database import SessionLocal


def borrar_paciente_total(cedula):
    with SessionLocal() as db:
        p = db.query(models.Paciente).filter_by(cedula=cedula).first()
        if not p:
            return
        pid = p.id
        db.query(models.Registro).filter_by(paciente_id=pid).delete()
        db.query(models.Registro).filter_by(transitorio_paciente_id=pid).update({"transitorio_paciente_id": None})
        db.query(models.Programacion).filter_by(paciente_id=pid).delete()
        db.query(models.Laboratorio).filter_by(paciente_id=pid).delete()
        db.query(models.PacienteInactividad).filter_by(paciente_id=pid).delete()
        db.query(models.AsignacionDia).filter(   # R2/R7: cambios de un día (suyos o como reemplazado)
            (models.AsignacionDia.paciente_id == pid)
            | (models.AsignacionDia.reemplaza_paciente_id == pid)).delete(synchronize_session=False)
        db.query(models.AsistenciaMensual).filter_by(paciente_id=pid).delete()   # delete masivo: sin evento ORM
        db.delete(p)
        db.commit()


def borrar_mes(mes):
    """Quita sesiones, cierres y auditoría de un mes de prueba."""
    with SessionLocal() as db:
        for s in db.query(models.Sesion).filter(models.Sesion.fecha.startswith(mes)).all():
            db.delete(s)
        db.query(models.AsistenciaMensual).filter_by(mes=mes).delete()
        db.query(models.CierreMes).filter_by(mes=mes).delete()
        db.query(models.AuditoriaCierreMes).filter_by(mes=mes).delete()
        db.commit()


def crear_paciente(cliente, cedula, **extra):
    base = dict(nombre="Zapata Ficticio, Prueba", cedula=cedula, estacion=3, cama=16, turno="N",
                peso_seco=70.0, dias="LMV")
    r = cliente.post("/api/pacientes", json={**base, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def registro_de(cliente, fecha, turno, paciente_id):
    ses = cliente.get(f"/api/sesiones/{fecha}/{turno}").json()
    regs = cliente.get(f"/api/sesiones/{ses['id']}/registros").json()
    return ses, next(r for r in regs if r["paciente_id"] == paciente_id)


def marcar(cliente, fecha, turno, paciente_id, **campos):
    ses, reg = registro_de(cliente, fecha, turno, paciente_id)
    r = cliente.patch(f"/api/sesiones/registros/{reg['id']}", json=campos)
    assert r.status_code == 200, r.text
    return ses, r.json()


@contextlib.contextmanager
def paciente_y_mes(cliente, cedula, mes, **extra):
    try:
        yield crear_paciente(cliente, cedula, **extra)
    finally:
        borrar_mes(mes)
        borrar_paciente_total(cedula)
