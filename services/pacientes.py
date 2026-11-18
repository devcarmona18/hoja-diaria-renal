"""
Servicios reutilizables sobre pacientes.

Pacientes ACTIVOS (R10)
-----------------------
Un paciente está *activo* cuando ``Paciente.activo`` es verdadero. Los inactivos
(hospitalizado u otro motivo, ver ``motivo_inactivo``) NO deben contarse en el
pedido de insumos, ni en la programación automática, ni en las hojas nuevas.

Cualquier módulo que necesite "los pacientes que cuentan" debe usar estos
helpers en vez de repetir ``filter(activo == True)``:

    from services.pacientes import consulta_activos, listar_activos, esta_activo

    pacientes = listar_activos(db, turno="M")          # lista ordenada por estación/cama
    q = consulta_activos(db).filter(Paciente.dias == "LMV")   # Query para seguir filtrando
    ids = ids_activos(db)                               # set de ids (para filtrar programaciones)

Catálogos de acceso vascular (R1)
---------------------------------
``ACCESOS``, ``ESTADOS_FAV``, ``CALIBRES_FAV`` y ``SITIOS_CY`` son la única fuente
de verdad; ``etiqueta_acceso`` genera el texto legible usado en la IA y en
cualquier reporte.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Query, Session

import models

# ── Acceso vascular ──────────────────────────────────────────────────────────
ACCESOS = ("FAV", "CY")
ESTADOS_FAV = ("limpia", "alto_riesgo", "aneurismatica")
CALIBRES_FAV = (15, 16, 17)
SITIOS_CY = ("yugular", "femoral")

_ETIQUETA_ESTADO = {
    "limpia": "limpia",
    "alto_riesgo": "alto riesgo",
    "aneurismatica": "aneurismática",
}

# ── Estado del paciente ──────────────────────────────────────────────────────
MOTIVOS_INACTIVO = ("hospitalizado", "otro")


def etiqueta_acceso(p) -> str:
    """Texto legible del acceso vascular. Acepta un Paciente o cualquier objeto con los mismos atributos."""
    acceso = getattr(p, "acceso", None)
    if acceso == "FAV":
        partes = ["FAV"]
        estado = getattr(p, "acceso_estado", None)
        if estado:
            partes.append(_ETIQUETA_ESTADO.get(estado, estado))
        txt = " ".join(partes)
        if estado == "aneurismatica" and getattr(p, "acceso_cm", None):
            txt += f" ({p.acceso_cm} cm)"
        calibre = getattr(p, "acceso_calibre", None)
        if calibre:
            txt += f", aguja calibre {calibre}"
        return txt
    if acceso == "CY":
        sitio = getattr(p, "acceso_sitio", None)
        return f"Catéter (CY) {sitio}" if sitio else "Catéter (CY)"
    return acceso or "—"


# ── Pacientes activos ────────────────────────────────────────────────────────
def consulta_activos(db: Session, turno: Optional[str] = None,
                     estacion: Optional[int] = None) -> Query:
    """Query de pacientes activos, ordenada por estación y cama. Se puede seguir filtrando."""
    q = db.query(models.Paciente).filter(models.Paciente.activo.is_(True))
    if turno:
        q = q.filter(models.Paciente.turno == turno)
    if estacion:
        q = q.filter(models.Paciente.estacion == estacion)
    return q.order_by(models.Paciente.estacion, models.Paciente.cama)


def listar_activos(db: Session, turno: Optional[str] = None,
                   estacion: Optional[int] = None) -> list[models.Paciente]:
    return consulta_activos(db, turno, estacion).all()


def ids_activos(db: Session) -> set[int]:
    return {i for (i,) in db.query(models.Paciente.id).filter(models.Paciente.activo.is_(True)).all()}


def esta_activo(p: models.Paciente) -> bool:
    return p.activo is True
