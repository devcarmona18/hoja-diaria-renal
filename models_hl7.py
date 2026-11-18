"""
Tablas de la integración HL7 (Próximamente). Son tablas NUEVAS e
independientes: no modifican pacientes, sesiones ni registros.

Crearlas es inocuo aunque HL7_ENABLED=false: quedan vacías.

  hl7_mensaje          mensaje crudo recibido (idempotencia por control_id = MSH-10)
  hl7_paciente_id      vínculo id de paciente de la máquina → Paciente.id
  hl7_borrador_sesion  valores extraídos pendientes de confirmación por enfermería
  hl7_auditoria        quién hizo qué y cuándo (recepción, confirmación, descarte, vínculos)

Las fechas se guardan como texto ISO 8601 en UTC (igual que `fecha` en el
resto del modelo), lo que funciona idéntico en SQLite y PostgreSQL.
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Hl7Mensaje(Base):
    __tablename__ = "hl7_mensaje"

    id          = Column(Integer, primary_key=True)
    recibido_en = Column(String(32), nullable=False, default=ahora_iso)
    control_id  = Column(String(64), nullable=False, unique=True)   # MSH-10
    maquina     = Column(String(64))                               # MSH-4 (instalación emisora)
    estado      = Column(String(20), nullable=False, default="recibido")  # recibido | procesado | error
    error       = Column(String(500))
    raw         = Column(Text, nullable=False)


class Hl7PacienteId(Base):
    __tablename__ = "hl7_paciente_id"

    id          = Column(Integer, primary_key=True)
    id_externo  = Column(String(64), nullable=False, unique=True)   # id del paciente en la máquina (PID-3)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    creado_en   = Column(String(32), nullable=False, default=ahora_iso)
    creado_por  = Column(String(64))

    paciente = relationship("Paciente")


class Hl7BorradorSesion(Base):
    __tablename__ = "hl7_borrador_sesion"

    id           = Column(Integer, primary_key=True)
    mensaje_id   = Column(Integer, ForeignKey("hl7_mensaje.id"), nullable=False, unique=True)
    paciente_id  = Column(Integer, ForeignKey("pacientes.id"), nullable=True)  # None = paciente desconocido
    id_externo   = Column(String(64))
    maquina      = Column(String(64))
    fecha        = Column(String(10))      # YYYY-MM-DD
    turno        = Column(String(1))       # M, T, N
    inicio       = Column(String(32))
    fin          = Column(String(32))
    valores      = Column(JSON, nullable=False, default=dict)   # peso_entrada, ktv, ta_sistolica…
    banderas     = Column(JSON, nullable=False, default=list)   # [{codigo, nivel, mensaje}]
    estado       = Column(String(12), nullable=False, default="pendiente")  # pendiente | confirmado | descartado
    creado_en    = Column(String(32), nullable=False, default=ahora_iso)
    resuelto_por = Column(String(64))
    resuelto_en  = Column(String(32))
    registro_id  = Column(Integer)         # registro de la hoja donde se aplicó (sin FK: los registros pueden borrarse)
    motivo       = Column(String(300))     # motivo del descarte

    paciente = relationship("Paciente")
    mensaje  = relationship("Hl7Mensaje")

    __table_args__ = (Index("ix_hl7_borrador_estado", "estado"),)


class Hl7Auditoria(Base):
    __tablename__ = "hl7_auditoria"

    id          = Column(Integer, primary_key=True)
    momento     = Column(String(32), nullable=False, default=ahora_iso)
    usuario     = Column(String(64))        # «puente» para lo que llega de la máquina
    accion      = Column(String(30), nullable=False)  # mensaje_recibido | confirmar | descartar | vincular…
    borrador_id = Column(Integer)
    mensaje_id  = Column(Integer)
    detalle     = Column(JSON)


TABLAS_HL7 = [Hl7Mensaje.__table__, Hl7PacienteId.__table__, Hl7BorradorSesion.__table__, Hl7Auditoria.__table__]


def crear_tablas(engine) -> None:
    """Crea SOLO las tablas HL7 que falten. No toca ninguna tabla existente."""
    Base.metadata.create_all(bind=engine, tables=TABLAS_HL7, checkfirst=True)
