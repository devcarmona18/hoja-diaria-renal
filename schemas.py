from pydantic import BaseModel, Field, model_validator
from typing import Literal, Optional


# ── Paciente ──────────────────────────────────────────────────────────────────

class PacienteBase(BaseModel):
    nombre: str
    cedula: str
    estacion: int
    cama: int
    turno: str
    peso_seco: Optional[float] = None
    activo: bool = True
    motivo_inactivo: Optional[str] = None         # R10: hospitalizado | otro
    motivo_inactivo_texto: Optional[str] = None   # R10: texto libre
    # Campos clínicos
    acceso: Optional[str] = None                  # R1: FAV | CY
    acceso_estado: Optional[str] = None           # FAV: limpia | alto_riesgo | aneurismatica
    acceso_calibre: Optional[int] = None          # FAV: 15 | 16 | 17
    acceso_sitio: Optional[str] = None            # CY: yugular | femoral
    acceso_cm: Optional[int] = None
    heparina_unidades: Optional[int] = None
    tipo_filtro: Optional[str] = None
    heparina_ui_kg: Optional[int] = None          # R4: heparina UI/kg, 10-20
    watson: Optional[float] = None
    medico: Optional[str] = None
    # Programación EPO/Fe mensual
    dias: Optional[str] = None
    epo_mensual: Optional[float] = None
    epo_dosis: Optional[float] = None
    hierro_mensual: Optional[int] = None
    # R5/R6 pedido de insumos
    adicional: Optional[bool] = None              # vacío = no
    citrato: Optional[bool] = None                # CY: usa citrato
    heparina_sodica: Optional[bool] = None        # CY: usa heparina sódica


class PacienteCreate(PacienteBase):
    """Entrada de paciente: aquí se validan los catálogos (PacienteOut no, para poder leer datos antiguos)."""
    cedula: str = Field(min_length=1, max_length=40)
    activo: bool = True
    motivo_inactivo: Optional[Literal["hospitalizado", "otro"]] = None
    motivo_inactivo_texto: Optional[str] = Field(None, max_length=200)
    acceso: Optional[Literal["FAV", "CY"]] = None
    acceso_estado: Optional[Literal["limpia", "alto_riesgo", "aneurismatica"]] = None
    acceso_calibre: Optional[Literal[15, 16, 17]] = None
    acceso_sitio: Optional[Literal["yugular", "femoral"]] = None
    heparina_ui_kg: Optional[int] = Field(None, ge=10, le=20)

    @model_validator(mode="after")
    def _coherencia(self):
        # R1: cada tipo de acceso solo conserva sus propios campos
        if self.acceso == "FAV":
            if not self.acceso_estado:
                raise ValueError("La fístula (FAV) requiere estado: limpia, alto_riesgo o aneurismatica")
            self.acceso_sitio = None
            if self.acceso_estado != "aneurismatica":
                self.acceso_cm = None
        elif self.acceso == "CY":
            if not self.acceso_sitio:
                raise ValueError("El catéter (CY) requiere sitio: yugular o femoral")
            self.acceso_estado = None
            self.acceso_calibre = None
            self.acceso_cm = None
        else:
            self.acceso_estado = self.acceso_calibre = self.acceso_sitio = self.acceso_cm = None
        # R5/R6: citrato / heparina sódica solo aplican al catéter (CY)
        if self.acceso != "CY":
            self.citrato = self.heparina_sodica = None
        # R10: el motivo solo aplica a pacientes inactivos
        if self.activo:
            self.motivo_inactivo = None
            self.motivo_inactivo_texto = None
        elif self.motivo_inactivo_texto is not None:
            self.motivo_inactivo_texto = self.motivo_inactivo_texto.strip() or None
        return self


class CambioEstadoPaciente(BaseModel):
    """Cuerpo opcional de PATCH /pacientes/{id}/toggle-activo al DESACTIVAR (R10)."""
    motivo: Optional[Literal["hospitalizado", "otro"]] = None
    motivo_texto: Optional[str] = Field(None, max_length=200)


class PacienteOut(PacienteBase):
    id: int
    model_config = {"from_attributes": True}


# ── Sesión ────────────────────────────────────────────────────────────────────

class SesionOut(BaseModel):
    id: int
    fecha: str
    turno: str
    cerrada: bool
    mes_cerrado: bool = False     # R12: el mes está cerrado -> hoja de solo lectura
    model_config = {"from_attributes": True}


# ── Registro ──────────────────────────────────────────────────────────────────

class RegistroUpdate(BaseModel):
    asistencia: Optional[str] = None
    peso_entrada: Optional[float] = None
    peso_salida: Optional[float] = None
    epo: Optional[bool] = None
    epo_jeringas: Optional[int] = Field(None, ge=0, le=2)   # R14: jeringas de 4.000 UI (máx. 2 = 8.000 UI)
    hierro: Optional[bool] = None
    observaciones: Optional[str] = None
    ktv: Optional[float] = None
    # R3: PA de pie y FC de salida (rangos clínicos plausibles; null = borrar)
    pa_pie_sistolica: Optional[int] = Field(None, ge=50, le=260)
    pa_pie_diastolica: Optional[int] = Field(None, ge=30, le=150)
    fc: Optional[int] = Field(None, ge=30, le=220)
    citrato: Optional[bool] = None
    heparina_sodica: Optional[bool] = None
    transitorio_nombre: Optional[str] = None
    transitorio_paciente_id: Optional[int] = None
    transitorio_asistencia: Optional[str] = None
    adicional: Optional[bool] = None   # R6: adicional solo de esta sesión


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
    epo_jeringas: Optional[int] = None
    hierro: bool = False
    observaciones: str = ""
    ktv: Optional[float] = None
    pa_pie_sistolica: Optional[int] = None
    pa_pie_diastolica: Optional[int] = None
    fc: Optional[int] = None
    citrato: bool = False
    heparina_sodica: bool = False
    adicional: bool = False
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
    epo_jeringas: int = 0          # R14: jeringas de 4.000 UI aplicadas


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


# ── IA Fase 4 ────────────────────────────────────────────────────────────────

class IAConsulta(BaseModel):
    paciente_id: int
    pregunta: str
    historial: Optional[list[dict]] = None  # mensajes previos del chat
