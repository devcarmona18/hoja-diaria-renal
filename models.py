from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base


class Paciente(Base):
    __tablename__ = "pacientes"

    id                = Column(Integer, primary_key=True, index=True)
    nombre            = Column(String, nullable=False)
    cedula            = Column(String, unique=True, nullable=False)
    estacion          = Column(Integer, nullable=False)   # 1, 2 ó 3
    cama              = Column(Integer, nullable=False)   # 1-16 por estación (display: 1-48)
    turno             = Column(String, nullable=False)    # M, T, N
    peso_seco         = Column(Float)
    activo            = Column(Boolean, default=True)
    # Campos clínicos
    acceso            = Column(String)   # CY | FAV_L | FAV_AR | FAV_ANE | F16 | F17
    acceso_cm         = Column(Integer)  # solo FAV_ANE: cm de cinta de acetato
    heparina_unidades = Column(Integer)  # UI/h (10-20)
    tipo_filtro       = Column(String)   # R-300, R-400, B-18, B-20, etc.
    watson            = Column(Float)    # Volumen distribución Watson (litros)
    medico            = Column(String)   # Nefrólogo tratante
    # Programación EPO/Fe mensual
    dias              = Column(String)   # LMV | TJS (días de la semana)
    epo_mensual       = Column(Float)    # UI totales prescritas al mes
    epo_dosis         = Column(Float)    # UI por aplicación
    hierro_mensual    = Column(Integer)  # Número de aplicaciones de Fe al mes


class Sesion(Base):
    __tablename__ = "sesiones"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String, nullable=False)        # ISO date YYYY-MM-DD
    turno = Column(String, nullable=False)        # M, T, N
    cerrada = Column(Boolean, default=False)

    registros = relationship("Registro", back_populates="sesion", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("fecha", "turno", name="uq_fecha_turno"),)


class Registro(Base):
    __tablename__ = "registros"

    id = Column(Integer, primary_key=True, index=True)
    sesion_id = Column(Integer, ForeignKey("sesiones.id"), nullable=False)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)

    # A=Asiste, NA=No Asiste, H=Hospitalizado, F=Falleció
    asistencia         = Column(String)
    peso_entrada       = Column(Float)
    peso_salida        = Column(Float)
    epo                = Column(Boolean, default=False)
    hierro             = Column(Boolean, default=False)
    observaciones      = Column(String, default="")
    ktv                = Column(Float)             # Kt/V medido en la sesión
    citrato            = Column(Boolean, default=False)  # CY disfuncional: citrato
    heparina_sodica    = Column(Boolean, default=False)  # CY disfuncional: hep. sódica
    transitorio_nombre      = Column(String)
    transitorio_paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=True)
    transitorio_asistencia  = Column(String)

    sesion               = relationship("Sesion", back_populates="registros")
    paciente             = relationship("Paciente", foreign_keys=[paciente_id])
    transitorio_paciente = relationship("Paciente", foreign_keys=[transitorio_paciente_id])

    __table_args__ = (UniqueConstraint("sesion_id", "paciente_id", name="uq_sesion_paciente"),)


class Programacion(Base):
    __tablename__ = "programacion"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String, nullable=False)
    turno = Column(String, nullable=False)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    epo_programado = Column(Boolean, default=False)
    hierro_programado = Column(Boolean, default=False)

    paciente = relationship("Paciente")

    __table_args__ = (UniqueConstraint("fecha", "turno", "paciente_id", name="uq_prog"),)


# ── Fase 2 ────────────────────────────────────────────────────────────────────

class Laboratorio(Base):
    """Resultado de laboratorio individual por paciente y fecha."""
    __tablename__ = "laboratorios"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    fecha = Column(String, nullable=False)       # YYYY-MM-DD
    tipo = Column(String, nullable=False)         # Hb, Hto, Urea, Kt_V, K, …
    valor = Column(Float, nullable=False)
    unidad = Column(String, default="")
    observaciones = Column(String, default="")

    paciente = relationship("Paciente")
