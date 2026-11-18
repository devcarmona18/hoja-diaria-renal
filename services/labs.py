"""
Estado de los resultados de laboratorio (R13).

Estados: ``bajo`` < mínimo · ``normal`` · ``alto`` > máximo · ``muy_alto`` > umbral «muy alto».
Los valores por defecto reproducen los rangos de referencia que ya usaba la interfaz
(``LAB_CONFIG`` en laboratorios.js); el umbral «muy alto» es nuevo. Todo se puede
cambiar desde la tabla ``lab_rangos`` (PUT /api/labs/rangos/{tipo}, solo admin).
Un analito sin ningún límite devuelve ``sin_rango``.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

import models

ESTADOS = ("bajo", "normal", "alto", "muy_alto")
ESTADO_ETIQUETA = {"bajo": "Bajo", "normal": "Normal", "alto": "Alto", "muy_alto": "Muy alto",
                   "sin_rango": "Sin rango", "sin_dato": "Sin dato"}

# tipo -> (etiqueta, unidad, mínimo, máximo, muy_alto)
DEFECTOS: dict[str, tuple] = {
    "Hb":         ("Hemoglobina",        "g/dL",   10,   12,   14),
    "Hto":        ("Hematocrito",        "%",      30,   36,   42),
    "Urea":       ("Urea",               "mg/dL",  None, 150,  200),
    "Creatinina": ("Creatinina",         "mg/dL",  None, None, None),
    "Kt_V":       ("Kt/V",               "",       1.2,  None, None),
    "K":          ("Potasio",            "mEq/L",  3.5,  5.5,  6.5),
    "Na":         ("Sodio",              "mEq/L",  135,  145,  150),
    "Ca":         ("Calcio",             "mg/dL",  8.5,  10.5, 11.5),
    "P":          ("Fósforo",            "mg/dL",  2.5,  5.5,  7.0),
    "Albumina":   ("Albúmina",           "g/dL",   3.5,  5.0,  None),
    "Ferritina":  ("Ferritina",          "ng/mL",  200,  500,  1000),
    "Sat_Transf": ("Sat. Transferrina",  "%",      20,   50,   None),
    "PTH":        ("PTH",                "pg/mL",  150,  600,  900),
    "PCR":        ("Proteína C Reactiva", "mg/L",  None, 10,   50),
}


def rangos(db: Session) -> dict[str, dict]:
    """Rangos vigentes por tipo: defectos + lo guardado en ``lab_rangos``."""
    out = {t: {"tipo": t, "etiqueta": d[0], "unidad": d[1], "minimo": d[2], "maximo": d[3],
               "muy_alto": d[4], "personalizado": False} for t, d in DEFECTOS.items()}
    for r in db.query(models.LabRango).all():
        if r.tipo in out:
            out[r.tipo].update(minimo=r.minimo, maximo=r.maximo, muy_alto=r.muy_alto, personalizado=True)
    return out


def estado(valor: Optional[float], rango: Optional[dict]) -> str:
    if valor is None:
        return "sin_dato"
    if not rango or all(rango.get(k) is None for k in ("minimo", "maximo", "muy_alto")):
        return "sin_rango"
    mn, mx, mxx = rango.get("minimo"), rango.get("maximo"), rango.get("muy_alto")
    if mn is not None and valor < mn:
        return "bajo"
    if mxx is not None and valor > mxx:
        return "muy_alto"
    if mx is not None and valor > mx:
        return "alto"
    return "normal"


def validar_rango(minimo, maximo, muy_alto) -> Optional[str]:
    """Coherencia: mínimo ≤ máximo ≤ muy alto (los que existan)."""
    vals = [v for v in (minimo, maximo, muy_alto) if v is not None]
    if vals != sorted(vals):
        return "Debe cumplirse mínimo ≤ máximo ≤ muy alto"
    return None


def ultimos_valores(db: Session, paciente_ids: Optional[set[int]] = None, tipo: Optional[str] = None
                    ) -> dict[tuple[int, str], models.Laboratorio]:
    """Última toma por (paciente, tipo). En empate de fecha gana el id más alto."""
    q = db.query(models.Laboratorio)
    if tipo:
        q = q.filter(models.Laboratorio.tipo == tipo)
    ult: dict[tuple[int, str], models.Laboratorio] = {}
    for lab in q.order_by(models.Laboratorio.fecha, models.Laboratorio.id).all():
        if paciente_ids is not None and lab.paciente_id not in paciente_ids:
            continue
        ult[(lab.paciente_id, lab.tipo)] = lab
    return ult
