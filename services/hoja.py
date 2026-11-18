"""
Hoja completa de un día (R11) y «foto» del paciente al cerrar la sesión.

Al cerrar una sesión se guarda en ``registros.snapshot`` (JSON) lo que puede cambiar
con el tiempo (cama, estación, peso seco, filtro, heparina, dosis de EPO). La cama y la
estación son las de ESE día (``registros.estacion/cama``, que incluyen los cambios de un
día de R2/R7), no la ubicación habitual del paciente. Historial
muestra esa foto, de modo que un día cerrado se ve EXACTAMENTE como quedó aunque el
paciente cambie de cama o de peso seco después. Sesiones cerradas antes de esta
función no tienen foto: se muestran con los datos actuales del paciente.

EPO: ``registros.epo`` es un booleano (una aplicación). Sus UI salen de la dosis por
aplicación del paciente (``epo_dosis``); si falta se asume 1 jeringa = 4.000 UI.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session, joinedload

import models
from hoja_dia import ubicacion_registro
from services.asistencia import ReglaError
from services.pacientes import etiqueta_acceso

JERINGA_UI = 4000
ORDEN_TURNO = {"M": 0, "T": 1, "N": 2}


def foto_paciente(p: models.Paciente, r: Optional[models.Registro] = None) -> dict:
    """Datos del paciente para la hoja. Con ``r``, la ubicación es la de esa sesión."""
    est, cama = ubicacion_registro(r) if r is not None else (p.estacion, p.cama)
    turno = r.sesion.turno if r is not None and r.sesion is not None else p.turno
    return {
        "estacion": est, "cama": cama, "turno": turno, "peso_seco": p.peso_seco,
        "tipo_filtro": p.tipo_filtro, "heparina_ui_kg": p.heparina_ui_kg,
        "heparina_unidades": p.heparina_unidades, "acceso": etiqueta_acceso(p) if p.acceso else "",
        "epo_dosis": p.epo_dosis,
    }


def tomar_snapshot(db: Session, sesion_id: int) -> None:
    for r in (db.query(models.Registro).options(joinedload(models.Registro.paciente))
              .filter_by(sesion_id=sesion_id).all()):
        if r.paciente:
            r.snapshot = json.dumps(foto_paciente(r.paciente, r), ensure_ascii=False)


def borrar_snapshot(db: Session, sesion_id: int) -> None:
    db.query(models.Registro).filter_by(sesion_id=sesion_id).update({models.Registro.snapshot: None})


def _fila(r: models.Registro) -> dict:
    p = r.paciente
    try:
        foto = json.loads(r.snapshot) if r.snapshot else None
    except ValueError:
        foto = None
    d = foto or (foto_paciente(p, r) if p else {})
    seco = d.get("peso_seco")
    perdida = round(r.peso_entrada - r.peso_salida, 2) if r.peso_entrada is not None and r.peso_salida is not None else None
    ganancia = round(r.peso_entrada - seco, 2) if r.peso_entrada is not None and seco is not None else None
    est_vivo, cama_vivo = ubicacion_registro(r)
    est, cama = d.get("estacion") or est_vivo or 0, d.get("cama") or cama_vivo or 0
    trans = r.transitorio_nombre or (r.transitorio_paciente.nombre if r.transitorio_paciente else "")
    return {
        "registro_id": r.id, "paciente_id": r.paciente_id,
        "nombre": p.nombre if p else "", "cedula": p.cedula if p else "",
        "estacion": est, "cama": cama, "cama_display": cama + (est - 1) * 16 if est else cama,
        "turno": d.get("turno") or (p.turno if p else None),
        "asistencia": r.asistencia, "peso_entrada": r.peso_entrada, "peso_salida": r.peso_salida,
        "peso_seco": seco, "perdida": perdida, "ganancia": ganancia,
        "pa_pie_sistolica": r.pa_pie_sistolica, "pa_pie_diastolica": r.pa_pie_diastolica, "fc": r.fc,
        "ktv": r.ktv, "epo": bool(r.epo), "hierro": bool(r.hierro),
        "tipo_filtro": d.get("tipo_filtro"), "heparina_ui_kg": d.get("heparina_ui_kg"),
        "heparina_unidades": d.get("heparina_unidades"),
        "citrato": bool(r.citrato), "heparina_sodica": bool(r.heparina_sodica),
        "acceso": d.get("acceso") or "", "epo_dosis": d.get("epo_dosis"),
        "observaciones": r.observaciones or "", "transitorio": trans,
        "con_foto": bool(foto),
    }


def resumen(filas: list[dict], n_sesiones: int) -> dict:
    asistidos = [f for f in filas if f["asistencia"] == "A"]
    epo = [f for f in asistidos if f["epo"]]
    ui = sum((f["epo_dosis"] or JERINGA_UI) for f in epo)
    return {
        "sesiones": n_sesiones,
        "pacientes": len(filas),
        "asistidos": len(asistidos),
        "no_asiste": sum(1 for f in filas if f["asistencia"] == "NA"),
        "hospitalizados": sum(1 for f in filas if f["asistencia"] == "H"),
        "fallecidos": sum(1 for f in filas if f["asistencia"] == "F"),
        "sin_marcar": sum(1 for f in filas if not f["asistencia"]),
        "epo_aplicaciones": len(epo),
        "epo_ui": int(round(ui)),
        "epo_jeringas": round(ui / JERINGA_UI, 2),
        "epo_dosis_estimada": sum(1 for f in epo if not f["epo_dosis"]),
        "fe_aplicado": sum(1 for f in asistidos if f["hierro"]),
    }


def hoja_completa(db: Session, fecha: str, turno: Optional[str] = None) -> dict:
    if turno and turno not in ORDEN_TURNO:
        raise ReglaError("Turno debe ser M, T o N", 422)
    q = db.query(models.Sesion).filter(models.Sesion.fecha == fecha)
    if turno:
        q = q.filter(models.Sesion.turno == turno)
    sesiones = sorted(q.all(), key=lambda s: ORDEN_TURNO[s.turno])
    if not sesiones:
        raise ReglaError("No hay sesión registrada para esa fecha y turno", 404)
    filas: list[dict] = []
    for s in sesiones:
        regs = (db.query(models.Registro).options(joinedload(models.Registro.paciente),
                                                   joinedload(models.Registro.transitorio_paciente))
                .filter_by(sesion_id=s.id).all())
        for r in regs:
            f = _fila(r)
            f["sesion_turno"] = s.turno
            filas.append(f)
    filas.sort(key=lambda f: (ORDEN_TURNO[f["sesion_turno"]], f["estacion"], f["cama"]))
    return {
        "fecha": fecha, "turno": turno,
        "sesiones": [{"id": s.id, "turno": s.turno, "cerrada": bool(s.cerrada)} for s in sesiones],
        "todas_cerradas": all(s.cerrada for s in sesiones),
        "filas": filas,
        "resumen": resumen(filas, len(sesiones)),
    }
