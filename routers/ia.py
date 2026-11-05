"""
Fase 4 — IA: Consulta clínica sobre historial del paciente.
Usa la Claude API (anthropic). Requiere clave en ia_config.json o
variable de entorno ANTHROPIC_API_KEY.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
import models, schemas
from database import get_db
import os, json

router = APIRouter()

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "ia_config.json")

_SYSTEM_PROMPT = """Eres un asistente clínico especializado en nefrología y hemodiálisis.
Recibes el historial resumido de un paciente en diálisis y respondes preguntas del equipo de enfermería o médico.
Responde siempre en español, con lenguaje clínico claro y conciso.
NO diagnostiques ni prescribas. Tus respuestas son de apoyo informativo para el equipo tratante.
Si la información del historial no es suficiente para responder con seguridad, dilo claramente.
Los datos son ficticios para entorno de desarrollo."""


def _get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f).get("anthropic_key")
        except Exception:
            pass
    return None


def _build_context(p: models.Paciente, registros: list, labs: list) -> str:
    """Construye el contexto clínico del paciente para el prompt."""
    acceso_map = {
        "CY": "Catéter yugular", "FAV_L": "FAV limpia",
        "FAV_AR": "FAV alto riesgo", "FAV_ANE": "FAV aneurismática",
        "F16": "Agujas G16", "F17": "Agujas G17",
    }
    lines = [
        "=== PACIENTE ===",
        f"Nombre: {p.nombre}",
        f"Turno: {'Mañana' if p.turno == 'M' else 'Tarde' if p.turno == 'T' else 'Noche'}",
        f"Estación: {p.estacion}  Cama: {p.cama + (p.estacion - 1) * 16}",
        f"Peso seco: {p.peso_seco or '—'} kg",
        f"Acceso vascular: {acceso_map.get(p.acceso or '', p.acceso or '—')}",
        f"Filtro: {p.tipo_filtro or '—'}",
        f"Heparina: {p.heparina_unidades or '—'} UI/h",
        f"Watson V: {p.watson or '—'} L",
        f"Médico: {p.medico or '—'}",
        f"Días diálisis: {p.dias or '—'}",
    ]

    if p.epo_mensual and p.epo_dosis:
        n_dosis = round(p.epo_mensual / p.epo_dosis)
        lines.append(f"EPO: {p.epo_mensual:.0f} UI/mes → {p.epo_dosis:.0f} UI/aplic × {n_dosis} dosis")
    if p.hierro_mensual:
        lines.append(f"Fe i.v.: {p.hierro_mensual} aplic/mes")

    if registros:
        lines.append("\n=== ÚLTIMAS SESIONES (más reciente primero) ===")
        for r in registros[:15]:
            asist = r.asistencia or "Sin marcar"
            ent   = f"{r.peso_entrada:.1f}" if r.peso_entrada else "—"
            sal   = f"{r.peso_salida:.1f}"  if r.peso_salida  else "—"
            perd  = ""
            if r.peso_entrada and r.peso_salida:
                perd = f" Pérd:{r.peso_entrada - r.peso_salida:.2f}kg"
            ktv   = f" KtV:{r.ktv:.2f}" if r.ktv else ""
            meds  = " EPO" if r.epo else ""
            meds += " Fe"  if r.hierro else ""
            cit   = " CIT" if r.citrato else ""
            hs    = " HS"  if r.heparina_sodica else ""
            trans = f" [Trans:{r.transitorio_nombre}]" if r.transitorio_nombre else ""
            fecha = r.sesion.fecha if r.sesion else "?"
            lines.append(f"  {fecha} {asist} E:{ent} S:{sal}{perd}{ktv}{meds}{cit}{hs}{trans}")

    if labs:
        lines.append("\n=== LABORATORIOS (más reciente primero) ===")
        por_tipo: dict[str, list] = {}
        for l in labs:
            por_tipo.setdefault(l.tipo, []).append(l)
        for tipo, lst in por_tipo.items():
            vals = " | ".join(f"{l.fecha}: {l.valor:.1f}" for l in lst[:4])
            lines.append(f"  {tipo}: {vals}")

    return "\n".join(lines)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def ia_status():
    """¿Está la IA configurada?"""
    return {"configured": bool(_get_api_key())}


@router.post("/config")
def ia_guardar_config(data: schemas.IAConfigInput):
    """Guarda la clave API de Anthropic en ia_config.json."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"anthropic_key": data.api_key}, f)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, f"Error al guardar config: {e}")


@router.post("/consulta")
def ia_consulta(data: schemas.IAConsulta, db: Session = Depends(get_db)):
    """
    Consulta IA sobre un paciente.
    Envía el historial como contexto y responde la pregunta.
    """
    api_key = _get_api_key()
    if not api_key:
        raise HTTPException(
            400,
            "IA no configurada. Ingrese su clave de API de Anthropic en la pantalla de IA."
        )

    try:
        import anthropic as _anth
    except ImportError:
        raise HTTPException(
            500,
            "Paquete 'anthropic' no instalado. Ejecute: pip install anthropic"
        )

    p = db.get(models.Paciente, data.paciente_id)
    if not p:
        raise HTTPException(404, "Paciente no encontrado")

    # Historial de sesiones (últimas 20)
    registros = (
        db.query(models.Registro)
        .filter_by(paciente_id=data.paciente_id)
        .options(joinedload(models.Registro.sesion))
        .join(models.Sesion)
        .order_by(models.Sesion.fecha.desc())
        .limit(20)
        .all()
    )

    # Laboratorios (últimos 30)
    labs = (
        db.query(models.Laboratorio)
        .filter_by(paciente_id=data.paciente_id)
        .order_by(models.Laboratorio.fecha.desc())
        .limit(30)
        .all()
    )

    contexto = _build_context(p, registros, labs)

    # Construir mensajes con historial de chat (si viene del frontend)
    messages = []
    for msg in (data.historial or []):
        role = msg.get("role")
        text = msg.get("text", "")
        if role in ("user", "assistant") and text:
            messages.append({"role": role, "content": text})

    # Agregar la pregunta actual
    messages.append({
        "role": "user",
        "content": f"{contexto}\n\nPregunta: {data.pregunta}"
    })

    try:
        client = _anth.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        return {"respuesta": resp.content[0].text}
    except Exception as e:
        raise HTTPException(500, f"Error de la IA: {str(e)}")
