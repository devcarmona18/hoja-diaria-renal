from pydantic import BaseModel
from typing import Optional


# ── Paciente ──────────────────────────────────────────────────────────────────

class PacienteBase(BaseModel):
    nombre: str
    cedula: str
    estacion: int
    cama: int
    turno: str
    peso_seco: Optional[float] = None
    activo: bool = True
    # Campos clínicos
    acceso: Optional[str] = None
    acceso_cm: Optional[int] = None
    heparina_unidades: Optional[int] = None
    tipo_filtro: Optional[str] = None
    watson: Optional[float] = None
    medico: Optional[str] = None
    # Programación EPO/Fe mensual
    dias: Optional[str] = None
    epo_mensual: Optional[float] = None
    epo_dosis: Optional[float] = None
    hierro_mensual: Optional[int] = None


class PacienteCreate(PacienteBase):
    pass


class PacienteOut(PacienteBase):
    id: int
    model_config = {"from_attributes": True}


# ── Sesión ────────────────────────────────────────────────────────────────────

class SesionOut(BaseModel):
    id: int
    fecha: str
    turno: str
    cerrada: bool
    model_config = {"from_attributes": True}


# ── Registro ──────────────────────────────────────────────────────────────────

class RegistroUpdate(BaseModel):
    asistencia: Optional[str] = None
    peso_entrada: Optional[float] = None
    peso_salida: Optional[float] = None
    epo: Optional[bool] = None
    hierro: Optional[bool] = None
    observaciones: Optional[str] = None
    ktv: Optional[float] = None
    citrato: Optional[bool] = None
    heparina_sodica: Optional[bool] = None
    transitorio_nombre: Optional[str] = None
    transitorio_paciente_id: Optional[int] = None
    transitorio_asistencia: Optional[str] = None


class RegistroOut(BaseModel):
    id: int
    sesion_id: int
    paciente_id: int
    asistencia: Optional[str] = None
    peso_entrada: Optional[float] = None
    peso_salida: Optional[float] = None
    perdida_real: Optional[float] = None
    ganancia_id: Optional[float] = None
    balance_seco: Optional[float] = None
    epo: bool = False
    hierro: bool = False
    observaciones: str = ""
    ktv: Optional[float] = None
    citrato: bool = False
    heparina_sodica: bool = False
    transitorio_nombre: str = ""
    paciente: Optional[PacienteOut] = None
    model_config = {"from_attributes": True}


# ── Cierre ────────────────────────────────────────────────────────────────────

class CierreEstacion(BaseModel):
    estacion: int
    total: int
    asistidos: int
    no_asiste: int
    hospitalizados: int
    fallecidos: int
    sin_marcar: int
    epo_count: int
    hierro_count: int


class CierreOut(BaseModel):
    sesion: SesionOut
    estaciones: list[CierreEstacion]
    totales: CierreEstacion


# ── Programación ──────────────────────────────────────────────────────────────

class ProgramacionItem(BaseModel):
    paciente_id: int
    epo_programado: bool = False
    hierro_programado: bool = False


class ProgramacionBulk(BaseModel):
    fecha: str
    turno: str
    items: list[ProgramacionItem]


class ProgramacionOut(BaseModel):
    id: int
    fecha: str
    turno: str
    paciente_id: int
    epo_programado: bool
    hierro_programado: bool
    paciente: Optional[PacienteOut] = None
    model_config = {"from_attributes": True}


# ── Laboratorio (Fase 2) ──────────────────────────────────────────────────────

class LaboratorioCreate(BaseModel):
    paciente_id: int
    fecha: str
    tipo: str
    valor: float
    unidad: str = ""
    observaciones: str = ""


class LaboratorioOut(LaboratorioCreate):
    id: int
    model_config = {"from_attributes": True}


# ── Auto-programación mensual EPO/Fe ─────────────────────────────────────────

class AutoMesInput(BaseModel):
    anio: int
    mes: int
    turno: str


class AutoMesPacienteResult(BaseModel):
    nombre: str
    cedula: str
    dias: Optional[str]
    sesiones: int
    epo_count: int
    hierro_count: int


class AutoMesResult(BaseModel):
    programados: int
    pacientes: list[AutoMesPacienteResult]


# ── IA Fase 4 ────────────────────────────────────────────────────────────────

class IAConfigInput(BaseModel):
    api_key: str


class IAConsulta(BaseModel):
    paciente_id: int
    pregunta: str
    historial: Optional[list[dict]] = None  # mensajes previos del chat
