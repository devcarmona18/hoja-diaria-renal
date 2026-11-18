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

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Query, Session

import config
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
    q = (db.query(models.Paciente).filter(models.Paciente.activo.is_(True))
         .filter(models.Paciente.archivado_en.is_(None)))   # R13: los archivados nunca cuentan
    if turno:
        q = q.filter(models.Paciente.turno == turno)
    if estacion:
        q = q.filter(models.Paciente.estacion == estacion)
    return q.order_by(models.Paciente.estacion, models.Paciente.cama)


def listar_activos(db: Session, turno: Optional[str] = None,
                   estacion: Optional[int] = None) -> list[models.Paciente]:
    return consulta_activos(db, turno, estacion).all()


def ids_activos(db: Session) -> set[int]:
    return {i for (i,) in db.query(models.Paciente.id)
            .filter(models.Paciente.activo.is_(True), models.Paciente.archivado_en.is_(None)).all()}


def esta_activo(p: models.Paciente) -> bool:
    return p.activo is True and p.archivado_en is None


# ── R13: archivo de pacientes ────────────────────────────────────────────────
# «Eliminar paciente» = ARCHIVAR: ``archivado_en`` (UTC) + ``archivado_motivo``.
# Un archivado queda además con ``activo = False``, así todos los helpers de
# arriba (hoja, programación, pedidos) lo excluyen. Durante ``ARCHIVO_DIAS`` aparece
# en la lista «Archivados» y se puede restaurar; después solo desaparece del
# LISTADO: sesiones, laboratorios y asistencia no se borran jamás.

def ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hoy_iso() -> str:
    return ahora_utc().date().isoformat()


def esta_archivado(p: models.Paciente) -> bool:
    return p.archivado_en is not None


def limite_archivo(ahora: Optional[datetime] = None) -> datetime:
    """Instante más antiguo de archivado que todavía se lista / se puede restaurar."""
    return (ahora or ahora_utc()) - timedelta(days=config.ARCHIVO_DIAS)


def en_ventana_archivo(p: models.Paciente, ahora: Optional[datetime] = None) -> bool:
    return p.archivado_en is not None and p.archivado_en >= limite_archivo(ahora)


def consulta_archivados(db: Session, ahora: Optional[datetime] = None) -> Query:
    """Archivados que siguen dentro de la ventana de ``ARCHIVO_DIAS`` (más recientes primero)."""
    return (db.query(models.Paciente)
            .filter(models.Paciente.archivado_en.isnot(None),
                    models.Paciente.archivado_en >= limite_archivo(ahora))
            .order_by(models.Paciente.archivado_en.desc()))


def retirar_de_sesiones_abiertas_sin_datos(db: Session, paciente_id: int) -> None:
    """Quita al paciente de las hojas ABIERTAS solo si su fila está vacía (no se pierden datos clínicos)."""
    for sesion in db.query(models.Sesion).filter_by(cerrada=False).all():
        reg = db.query(models.Registro).filter_by(sesion_id=sesion.id, paciente_id=paciente_id).first()
        if reg and not (reg.asistencia or reg.peso_entrada is not None or reg.peso_salida is not None
                        or reg.ktv is not None or (reg.observaciones or "").strip()):
            db.delete(reg)


def archivar(db: Session, p: models.Paciente, motivo: str, ahora: Optional[datetime] = None) -> None:
    ahora = ahora or ahora_utc()
    p.archivado_en = ahora
    p.archivado_motivo = motivo
    p.activo = False
    p.motivo_inactivo = None
    p.motivo_inactivo_texto = None
    cerrar_inactividad(db, p.id, ahora.date().isoformat(), solo_origen="inactivo")
    abrir_inactividad(db, p.id, ahora.date().isoformat(), "archivado", motivo)
    # fuera de la programación futura y de las hojas abiertas sin datos
    db.query(models.Programacion).filter(
        models.Programacion.paciente_id == p.id,
        models.Programacion.fecha >= ahora.date().isoformat(),
    ).delete(synchronize_session=False)
    # R2/R7: sus cambios de un día pendientes tampoco aplican (al restaurar vuelve a su base)
    db.query(models.AsignacionDia).filter(
        models.AsignacionDia.paciente_id == p.id,
        models.AsignacionDia.fecha >= ahora.date().isoformat(),
    ).delete(synchronize_session=False)
    retirar_de_sesiones_abiertas_sin_datos(db, p.id)


def restaurar(db: Session, p: models.Paciente, ahora: Optional[datetime] = None) -> None:
    ahora = ahora or ahora_utc()
    p.archivado_en = None
    p.archivado_motivo = None
    p.activo = True
    cerrar_inactividad(db, p.id, ahora.date().isoformat(), solo_origen="archivado")


# ── Periodos de inactividad (insumo de la asistencia, R12) ───────────────────
def abrir_inactividad(db: Session, paciente_id: int, desde: str, origen: str,
                      motivo: Optional[str] = None) -> None:
    """Abre un periodo [desde, ∞) si no hay uno abierto del mismo origen."""
    abierto = db.query(models.PacienteInactividad).filter_by(
        paciente_id=paciente_id, hasta=None, origen=origen).first()
    if not abierto:
        db.add(models.PacienteInactividad(paciente_id=paciente_id, desde=desde, origen=origen,
                                          motivo=(motivo or None)))


def cerrar_inactividad(db: Session, paciente_id: int, hasta: str, solo_origen: Optional[str] = None) -> None:
    """Cierra los periodos abiertos en ``hasta`` (ese día el paciente ya cuenta de nuevo)."""
    q = db.query(models.PacienteInactividad).filter_by(paciente_id=paciente_id, hasta=None)
    if solo_origen:
        q = q.filter_by(origen=solo_origen)
    for per in q.all():
        per.hasta = max(hasta, per.desde)   # nunca un periodo negativo


def registrar_cambio_activo(db: Session, p: models.Paciente, estaba_activo: bool) -> None:
    """Llamar tras cambiar ``p.activo`` (R10): abre/cierra el periodo de inactividad de hoy."""
    ahora_activo = p.activo is True
    if estaba_activo and not ahora_activo:
        abrir_inactividad(db, p.id, hoy_iso(), "inactivo", p.motivo_inactivo)
    elif not estaba_activo and ahora_activo:
        cerrar_inactividad(db, p.id, hoy_iso(), solo_origen="inactivo")
