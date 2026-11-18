"""Utilidades de prueba: datos temporales que se limpian para no alterar los conteos de otras pruebas."""
import contextlib

import models
from database import SessionLocal

_BASE = dict(nombre="Prueba Ficticia, Tmp", estacion=1, cama=1, turno="M", peso_seco=70.0)


def datos_paciente(cedula, **extra):
    return {**_BASE, "cedula": cedula, **extra}


def borrar_paciente(cedula):
    with SessionLocal() as db:
        p = db.query(models.Paciente).filter_by(cedula=cedula).first()
        if p:
            db.query(models.Registro).filter_by(paciente_id=p.id).delete()
            db.query(models.Programacion).filter_by(paciente_id=p.id).delete()
            db.delete(p)
            db.commit()


def borrar_sesion(fecha, turno):
    with SessionLocal() as db:
        s = db.query(models.Sesion).filter_by(fecha=fecha, turno=turno).first()
        if s:
            db.delete(s)
            db.commit()


@contextlib.contextmanager
def paciente_temporal(cliente, cedula, **extra):
    r = cliente.post("/api/pacientes", json=datos_paciente(cedula, **extra))
    try:
        yield r
    finally:
        borrar_paciente(cedula)
