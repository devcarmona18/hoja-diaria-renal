from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, Index,
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
    # R10: motivo de inactividad (solo cuando activo es falso). Ver services/pacientes.py
    motivo_inactivo       = Column(String)   # hospitalizado | otro
    motivo_inactivo_texto = Column(String)   # texto libre
    # Campos clínicos
    acceso            = Column(String)   # FAV | CY  (R1)
    acceso_estado     = Column(String)   # FAV: limpia | alto_riesgo | aneurismatica
    acceso_calibre    = Column(Integer)  # FAV: calibre de aguja 15 | 16 | 17
    acceso_sitio      = Column(String)   # CY: yugular | femoral
    acceso_cm         = Column(Integer)  # solo FAV aneurismática: cm de cinta de acetato
    heparina_unidades = Column(Integer)  # UI/h (10-20)
    tipo_filtro       = Column(String)   # R-300, R-400, B-18, B-20, etc.
    heparina_ui_kg    = Column(Integer)  # R4: heparina en UI por kg de peso (10-20); heparina_unidades sigue siendo UI/h
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
    # R3: última toma de pie al salir
    pa_pie_sistolica   = Column(Integer)           # mmHg
    pa_pie_diastolica  = Column(Integer)           # mmHg
    fc                 = Column(Integer)           # lpm
    citrato            = Column(Boolean, default=False)  # CY disfuncional: citrato
    heparina_sodica    = Column(Boolean, default=False)  # CY disfuncional: hep. sódica
    transitorio_nombre      = Column(String)
    transitorio_paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=True)
    transitorio_asistencia  = Column(String)
    # Ubicación del paciente EN ESTA SESIÓN (foto al crear el registro). NULL en
    # registros antiguos = se usa la ubicación base del paciente. Así un cambio
    # permanente posterior no altera la hoja de sesiones pasadas.
    estacion = Column(Integer)
    cama     = Column(Integer)

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


class AsignacionDia(Base):
    """Cambio de ubicación de UN día (R7): se aplica sobre la asignación base del
    paciente solo para `fecha`. La ubicación habitual (Paciente.estacion/cama/turno)
    no cambia; el siguiente día de diálisis vuelve a la distribución habitual.

    tipo:
      - mover:       paciente habitual del turno en otra cama/estación ese día.
      - transitorio: paciente que ese día no le tocaba este turno/cama (otro turno,
                     otro grupo de días o paciente nuevo) ocupa una cama libre.
      - reemplazo:   el paciente ocupa la cama de `reemplaza_paciente_id`, que ese
                     día no viene (queda como «H» con suplente en la hoja).
    Un paciente tiene como máximo un cambio por fecha (en cualquier turno).
    `grupo` enlaza los dos cambios de un intercambio para deshacerlos juntos.
    """
    __tablename__ = "asignaciones_dia"

    id                   = Column(Integer, primary_key=True, index=True)
    fecha                = Column(String, nullable=False)    # YYYY-MM-DD
    turno                = Column(String, nullable=False)    # M, T, N
    paciente_id          = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    estacion             = Column(Integer, nullable=False)
    cama                 = Column(Integer, nullable=False)
    tipo                 = Column(String, nullable=False)    # mover | transitorio | reemplazo
    reemplaza_paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=True)
    grupo                = Column(String, nullable=True)
    creado_por           = Column(String)
    creado_en            = Column(DateTime)

    paciente   = relationship("Paciente", foreign_keys=[paciente_id])
    reemplaza  = relationship("Paciente", foreign_keys=[reemplaza_paciente_id])

    __table_args__ = (
        UniqueConstraint("fecha", "paciente_id", name="uq_asig_fecha_paciente"),
        Index("ix_asig_fecha_turno", "fecha", "turno"),
    )


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
