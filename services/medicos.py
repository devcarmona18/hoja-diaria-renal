"""
Directorio de médicos tratantes y utilidades de iniciales (R13).

``pacientes.medico`` sigue siendo texto libre (así lo usan la hoja y la
auto-programación); la tabla ``medicos`` guarda por nombre las iniciales y el
webhook de Teams. ``asegurar_medicos`` crea las filas que falten a partir de los
nombres que ya existen en pacientes (idempotente).
"""
from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

import config
import models

_TRATAMIENTOS = {"dr", "dra", "doctor", "doctora", "dr.", "dra."}
_PARTICULAS = {"de", "del", "la", "las", "los", "y", "e", "da", "di"}


def normalizar(nombre: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (nombre or "").strip()).lower()


def _palabras(nombre: str) -> list[str]:
    return [w for w in re.split(r"[\s,.;]+", nombre or "") if w]


def iniciales_medico(nombre: str) -> str:
    """«Dra. Valeria Montoya» -> «VM»."""
    pals = [w for w in _palabras(nombre) if w.lower().rstrip(".") not in _TRATAMIENTOS
            and w.lower() not in _PARTICULAS]
    return "".join(w[0].upper() for w in pals)[:4]


def iniciales_paciente(nombre: str) -> str:
    """«García Silva, María» -> «GSM». Solo iniciales: es lo único que sale en notificaciones."""
    return "".join(w[0].upper() for w in _palabras(nombre) if w.lower() not in _PARTICULAS)[:6]


def asegurar_medicos(db: Session) -> dict[str, models.Medico]:
    """Crea los médicos que aparecen en pacientes y no están en el directorio. Devuelve {nombre normalizado: Medico}."""
    existentes = {normalizar(m.nombre): m for m in db.query(models.Medico).all()}
    nuevos = False
    for (nombre,) in db.query(models.Paciente.medico).distinct().all():
        clave = normalizar(nombre)
        if not clave or clave in existentes:
            continue
        m = models.Medico(nombre=re.sub(r"\s+", " ", nombre.strip()), iniciales=iniciales_medico(nombre))
        db.add(m)
        existentes[clave] = m
        nuevos = True
    if nuevos:
        db.flush()
    return existentes


def webhook_valido(url: Optional[str]) -> bool:
    """https y dominio de Microsoft permitido (TEAMS_HOSTS_PERMITIDOS): evita usar la app como proxy (SSRF)."""
    if not url:
        return False
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or u.username or u.password:
        return False
    return any(host == d or host.endswith("." + d) for d in config.TEAMS_HOSTS_PERMITIDOS)


def enmascarar(url: Optional[str]) -> str:
    """El webhook es un secreto: la API nunca lo devuelve completo."""
    if not url:
        return ""
    u = urlparse(url)
    return f"{u.scheme}://{u.hostname}/…{url[-6:]}"
