from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, ForeignKey, UniqueConstraint, Index, Text,
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
    # R13: archivo. «Eliminar paciente» = archivar (nunca se borra nada clínico).
    archivado_en      = Column(DateTime)       # UTC; null = no archivado
    archivado_motivo  = Column(String(200))
    # R5/R6 Pedido de insumos
    adicional         = Column(Boolean)  # paciente adicional (null/False = no): sus insumos se piden el día que llega
    citrato           = Column(Boolean)  # CY: sellado/uso habitual de citrato
    heparina_sodica   = Column(Boolean)  # CY: sellado/uso habitual de heparina sódica


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
    # R11: foto JSON de los datos del paciente al cerrar la sesión (cama, peso seco…)
    snapshot                = Column(Text)
    # R6: adicional solo de esta sesión (quien asiste en la fila: paciente o suplente)
    adicional = Column(Boolean)

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


# ── R11–R13 ───────────────────────────────────────────────────────────────────

class Medico(Base):
    """Directorio de médicos tratantes. ``pacientes.medico`` sigue siendo el texto
    libre; se enlaza por nombre (sin distinguir mayúsculas ni espacios)."""
    __tablename__ = "medicos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(120), nullable=False, unique=True)
    iniciales = Column(String(10), nullable=False, default="")
    teams_webhook_url = Column(String(600))      # R13: webhook de Teams (Workflows)


class LabRango(Base):
    """Rangos configurables por analito; sustituyen a los de ``services/labs.py`` (valores por defecto)."""
    __tablename__ = "lab_rangos"

    tipo = Column(String(30), primary_key=True)
    minimo = Column(Float)       # por debajo -> bajo
    maximo = Column(Float)       # por encima -> alto
    muy_alto = Column(Float)     # por encima -> muy alto


class PacienteInactividad(Base):
    """Periodos en que el paciente no contó para la asistencia: [desde, hasta)."""
    __tablename__ = "paciente_inactividad"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False, index=True)
    desde = Column(String(10), nullable=False)     # YYYY-MM-DD
    hasta = Column(String(10))                     # null = sigue inactivo/archivado
    origen = Column(String(12), nullable=False)    # inactivo | archivado
    motivo = Column(String(200))


class CierreMes(Base):
    """Un cierre de mes (facturación). El vigente es el último sin ``reabierto_en``."""
    __tablename__ = "cierres_mes"

    id = Column(Integer, primary_key=True, index=True)
    mes = Column(String(7), nullable=False, index=True)      # YYYY-MM
    cerrado_por = Column(String(80), nullable=False)
    cerrado_en = Column(DateTime, nullable=False)
    reabierto_por = Column(String(80))
    reabierto_en = Column(DateTime)
    reapertura_motivo = Column(String(300))


class AsistenciaMensual(Base):
    """Registro mensual INMUTABLE de asistencia por paciente (base de la facturación)."""
    __tablename__ = "asistencia_mensual"

    id = Column(Integer, primary_key=True, index=True)
    cierre_id = Column(Integer, ForeignKey("cierres_mes.id"), nullable=False, index=True)
    mes = Column(String(7), nullable=False, index=True)
    paciente_id = Column(Integer, ForeignKey("pacientes.id"), nullable=False)
    programadas = Column(Integer, nullable=False)
    asistidas = Column(Integer, nullable=False)
    porcentaje = Column(Float, nullable=False)
    cerrado_por = Column(String(80), nullable=False)
    cerrado_en = Column(DateTime, nullable=False)


class AuditoriaCierreMes(Base):
    __tablename__ = "auditoria_cierre_mes"

    id = Column(Integer, primary_key=True, index=True)
    mes = Column(String(7), nullable=False, index=True)
    accion = Column(String(10), nullable=False)      # cerrar | reabrir
    usuario = Column(String(80), nullable=False)
    motivo = Column(String(300))
    creado_en = Column(DateTime, nullable=False)


class AuditoriaPaciente(Base):
    """R13: bitácora de archivar / restaurar / reactivar pacientes. Sin FK: la
    bitácora sobrevive aunque una prueba o una purga manual borre al paciente."""
    __tablename__ = "auditoria_pacientes"

    id = Column(Integer, primary_key=True, index=True)
    paciente_id = Column(Integer, nullable=False, index=True)
    cedula = Column(String(40))
    accion = Column(String(12), nullable=False)      # archivar | restaurar | reactivar
    usuario = Column(String(80), nullable=False)
    motivo = Column(String(300))
    creado_en = Column(DateTime, nullable=False)


class TeamsEnvio(Base):
    """Bitácora de notificaciones a Teams (evita duplicados del mismo día)."""
    __tablename__ = "teams_envios"

    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(String(10), nullable=False, index=True)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False)
    pacientes = Column(Integer, nullable=False, default=0)
    estado = Column(String(12), nullable=False)       # enviado | error
    http_status = Column(Integer)
    detalle = Column(String(300))
    creado_en = Column(DateTime, nullable=False)


from sqlalchemy import event  # noqa: E402


@event.listens_for(AsistenciaMensual, "before_update")
@event.listens_for(AsistenciaMensual, "before_delete")
def _asistencia_mensual_inmutable(mapper, connection, target):
    """R12: el registro mensual cerrado no se modifica ni se borra (se reabre el cierre y se vuelve a cerrar)."""
    raise ValueError("El registro mensual de asistencia es inmutable")


# ── R5/R6 Pedido de insumos ───────────────────────────────────────────────────

class InsumosConfig(Base):
    """Reglas del pedido de insumos editadas por el administrador (JSON).
    Sin fila = se usan las reglas por defecto de services/insumos_reglas.json."""
    __tablename__ = "insumos_config"

    id             = Column(Integer, primary_key=True)
    clave          = Column(String(40), unique=True, nullable=False)   # "reglas"
    contenido      = Column(Text, nullable=False)                      # JSON
    actualizado_en = Column(DateTime)
    actualizado_por = Column(String(80))


class PedidoInsumos(Base):
    """Foto de un pedido CONFIRMADO/ENVIADO. Las ediciones posteriores de pacientes
    o reglas no lo cambian. Antes de confirmar el pedido se calcula en vivo."""
    __tablename__ = "pedido_insumos"

    id              = Column(Integer, primary_key=True, index=True)
    fecha_pedido    = Column(String(10), nullable=False, unique=True)   # día en que se hace el pedido
    fecha_sesiones  = Column(String(10), nullable=False, index=True)    # día de diálisis que cubre
    estado          = Column(String(20), nullable=False, default="confirmado")
    confirmado_en   = Column(DateTime)
    confirmado_por  = Column(String(80))
    reglas_json     = Column(Text)        # reglas usadas (auditoría)
    resumen_json    = Column(Text)        # avisos/notas del cálculo

    items = relationship("PedidoInsumosItem", back_populates="pedido",
                         cascade="all, delete-orphan", order_by="PedidoInsumosItem.id")


class PedidoInsumosItem(Base):
    """Una línea del pedido: un insumo de un paciente en una sección."""
    __tablename__ = "pedido_insumos_items"

    id              = Column(Integer, primary_key=True, index=True)
    pedido_id       = Column(Integer, ForeignKey("pedido_insumos.id", ondelete="CASCADE"), nullable=False, index=True)
    seccion         = Column(String(20), nullable=False)   # pedido | adicional | devolucion
    fecha_sesion    = Column(String(10))
    paciente_id     = Column(Integer)                      # sin FK: la foto sobrevive al paciente
    paciente_nombre = Column(String(200))
    cedula          = Column(String(40))
    turno           = Column(String(1))
    estacion        = Column(Integer)
    cama            = Column(Integer)
    acceso          = Column(String(80))
    insumo_codigo   = Column(String(60))                   # NULL = paciente sin insumos (solo avisos)
    insumo_nombre   = Column(String(120))
    cantidad        = Column(Integer)
    unidad          = Column(String(30))
    detalle         = Column(String(120))
    alertas         = Column(String(300))                  # avisos del paciente separados por « · »

    pedido = relationship("PedidoInsumos", back_populates="items")
