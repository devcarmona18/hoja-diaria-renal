"""
Notificaciones de laboratorio a Microsoft Teams (R13). APAGADO por defecto.

* ``TEAMS_ENABLED=false`` (por defecto): ``enviar_notificaciones`` no realiza NINGUNA
  llamada HTTP saliente. La vista previa del reporte sí funciona (no envía nada).
* Un webhook (Workflows de Teams) por médico, en ``medicos.teams_webhook_url``.
* El reporte agrupa por médico a sus pacientes ACTIVOS con algún resultado fuera
  de rango (última toma de cada analito) e identifica a los pacientes SOLO por
  iniciales: ni nombres, ni cédulas.
* Se envía los días del mes de ``TEAMS_DIAS`` (por defecto 1 y 15); el trabajo de
  GitHub Actions corre a diario y este módulo decide si hoy toca. Un médico no
  recibe dos veces el mismo día (bitácora ``teams_envios``), salvo ``forzar``.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

import config
import models
from services import labs as srv_labs
from services.medicos import asegurar_medicos, iniciales_paciente, normalizar, webhook_valido
from services.pacientes import ahora_utc, consulta_activos
from services.tiempo import hoy_local

log = logging.getLogger("uvicorn.error")
MAX_PACIENTES_TARJETA = 60


def dias_de_envio() -> list[int]:
    out = []
    for t in (config.TEAMS_DIAS or "").split(","):
        t = t.strip()
        if t.isdigit() and 1 <= int(t) <= 31:
            out.append(int(t))
    return sorted(set(out))


def es_dia_de_envio(hoy: Optional[date] = None) -> bool:
    return (hoy or hoy_local()).day in dias_de_envio()


def construir_reportes(db: Session, medico_id: Optional[int] = None) -> list[dict]:
    """Un reporte por médico con pacientes activos con resultados anormales (solo iniciales)."""
    medicos = asegurar_medicos(db)
    rangos = srv_labs.rangos(db)
    pacientes = [p for p in consulta_activos(db).all() if normalizar(p.medico)]
    ultimos = srv_labs.ultimos_valores(db, {p.id for p in pacientes})
    por_medico: dict[str, list] = {}
    for p in pacientes:
        hallazgos = []
        for tipo, rango in rangos.items():
            lab = ultimos.get((p.id, tipo))
            if not lab:
                continue
            est = srv_labs.estado(lab.valor, rango)
            if est in ("bajo", "alto", "muy_alto"):
                hallazgos.append({"tipo": tipo, "etiqueta": rango["etiqueta"], "valor": lab.valor,
                                  "unidad": rango["unidad"], "estado": est, "fecha": lab.fecha})
        if hallazgos:
            por_medico.setdefault(normalizar(p.medico), []).append(
                {"iniciales": iniciales_paciente(p.nombre), "hallazgos": hallazgos})
    reportes = []
    for clave, pacs in por_medico.items():
        m = medicos.get(clave)
        if not m or (medico_id and m.id != medico_id):
            continue
        pacs.sort(key=lambda x: x["iniciales"])
        reportes.append({"medico_id": m.id, "medico": m.nombre, "medico_iniciales": m.iniciales,
                         "tiene_webhook": webhook_valido(m.teams_webhook_url),
                         "total_pacientes": len(pacs), "pacientes": pacs})
    reportes.sort(key=lambda r: r["medico"])
    return reportes


def _linea(h: dict) -> str:
    u = f" {h['unidad']}" if h["unidad"] else ""
    return f"{h['etiqueta']} {h['valor']:g}{u} ({srv_labs.ESTADO_ETIQUETA[h['estado']].lower()}, {h['fecha']})"


def construir_payload(reporte: dict, hoy: Optional[date] = None) -> dict:
    """Mensaje con Tarjeta Adaptable (formato de los Workflows de Teams). Solo iniciales de pacientes."""
    hoy = hoy or hoy_local()
    cuerpo = [
        {"type": "TextBlock", "weight": "Bolder", "size": "Medium", "wrap": True,
         "text": f"Laboratorios fuera de rango · {hoy.strftime('%d/%m/%Y')}"},
        {"type": "TextBlock", "wrap": True, "isSubtle": True,
         "text": f"Dr(a). {reporte['medico_iniciales'] or reporte['medico']} · "
                 f"{reporte['total_pacientes']} paciente(s) con resultados fuera de rango "
                 "(última toma de cada examen). Pacientes identificados por iniciales."},
    ]
    for pac in reporte["pacientes"][:MAX_PACIENTES_TARJETA]:
        cuerpo.append({"type": "TextBlock", "wrap": True, "spacing": "Small",
                       "text": f"**{pac['iniciales']}**: " + "; ".join(_linea(h) for h in pac["hallazgos"])})
    if len(reporte["pacientes"]) > MAX_PACIENTES_TARJETA:
        cuerpo.append({"type": "TextBlock", "wrap": True,
                       "text": f"… y {len(reporte['pacientes']) - MAX_PACIENTES_TARJETA} más en la aplicación."})
    return {"type": "message", "attachments": [{
        "contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
        "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard", "version": "1.4", "body": cuerpo}}]}


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # un webhook legítimo no redirige: no seguimos nada
        return None


def _post_json(url: str, payload: dict, timeout: float) -> int:
    """ÚNICO punto de salida HTTP del módulo (las pruebas lo sustituyen)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(_SinRedireccion)
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def enviar_notificaciones(db: Session, forzar: bool = False, medico_id: Optional[int] = None,
                          hoy: Optional[date] = None) -> dict:
    hoy = hoy or hoy_local()
    base = {"enabled": config.TEAMS_ENABLED, "dias_envio": dias_de_envio(), "enviados": [], "omitidos": []}
    if not config.TEAMS_ENABLED:
        return {**base, "mensaje": "Notificaciones de Teams desactivadas (TEAMS_ENABLED=false): no se envió nada."}
    base["programado_hoy"] = es_dia_de_envio(hoy)
    if not forzar and not base["programado_hoy"]:
        return {**base, "mensaje": "Hoy no es día de envío."}

    for rep in construir_reportes(db, medico_id):
        m = db.get(models.Medico, rep["medico_id"])
        item = {"medico": m.nombre, "pacientes": rep["total_pacientes"]}
        if not webhook_valido(m.teams_webhook_url):
            base["omitidos"].append({**item, "motivo": "sin webhook válido"})
            continue
        if not forzar and db.query(models.TeamsEnvio).filter_by(
                fecha=hoy.isoformat(), medico_id=m.id, estado="enviado").first():
            base["omitidos"].append({**item, "motivo": "ya enviado hoy"})
            continue
        estado, status, detalle = "error", None, ""
        try:
            status = _post_json(m.teams_webhook_url, construir_payload(rep, hoy), config.TEAMS_TIMEOUT)
            estado = "enviado" if 200 <= status < 300 else "error"
            detalle = "" if estado == "enviado" else f"HTTP {status}"
        except Exception as e:   # red caída, DNS, timeout…
            detalle = type(e).__name__
            log.warning("Teams: fallo al enviar a médico %s: %s", m.id, detalle)
        db.add(models.TeamsEnvio(fecha=hoy.isoformat(), medico_id=m.id, pacientes=rep["total_pacientes"],
                                 estado=estado, http_status=status, detalle=detalle, creado_en=ahora_utc()))
        db.commit()
        (base["enviados"] if estado == "enviado" else base["omitidos"]).append(
            {**item, **({"http_status": status} if status else {}), **({"motivo": detalle} if estado != "enviado" else {})})
    return base
