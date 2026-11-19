"""
R9 — Apartado «IA»: NefroIA integrado con inicio de sesión único.

Reemplaza el antiguo módulo IA (routers/ia.py), que enviaba el nombre y el
historial del paciente a un modelo de lenguaje. Aquí NO sale ningún dato de
pacientes: Hoja Diaria solo firma un token corto con la identidad del usuario
y el navegador lo entrega a NefroIA (iframe o pestaña nueva).

Rutas (todas GET: el rol demo también puede abrir NefroIA, con límites):
  /api/nefroia/estado  → {"configurado": bool, ...}
  /api/nefroia/sso     → {"url": ".../sso?token=…&embed=1&lang=es"} para el iframe
  /api/nefroia/abrir   → 303 a NefroIA en una pestaña nueva (mismo flujo SSO)
"""
import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

import config
from auth import rol_actual
from services import nefroia_sso

router = APIRouter()

_SIN_CACHE = {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"}


def _identidad(request: Request) -> tuple[str, str, str]:
    """(sub, rol, nombre) del usuario de la sesión. Sin datos de pacientes."""
    if not config.AUTH_ENABLED:
        # Sin login todo el mundo sería «admin»: no se emiten identidades.
        raise HTTPException(403, "NefroIA requiere el inicio de sesión de Hoja Diaria (APP_USER/APP_PASSWORD).")
    rol = rol_actual(request)
    if rol is None:
        raise HTTPException(401, "No autenticado")
    if rol == "demo":
        # Cada visitante demo tiene su propio usuario en NefroIA (no comparten chats).
        demo_id = request.session.get("nefroia_demo_id")
        if not demo_id:
            demo_id = secrets.token_hex(6)
            request.session["nefroia_demo_id"] = demo_id
        return f"demo-{demo_id}", "demo", "Visitante demo"
    if rol != "admin":
        raise HTTPException(403, "Rol sin acceso a NefroIA")
    usuario = request.session.get("usuario") or config.APP_USER or "admin"
    sub = re.sub(r"[^A-Za-z0-9._@-]", "-", usuario)[:60].lstrip("._@-") or "admin"
    return sub, "admin", usuario[:100]


def _no_configurado():
    raise HTTPException(404, "NefroIA no está configurado todavía")


@router.get("/estado")
def estado():
    return JSONResponse(
        {"configurado": config.NEFROIA_ENABLED,
         "origen": nefroia_sso.origen_nefroia() if config.NEFROIA_ENABLED else None},
        headers=_SIN_CACHE,
    )


@router.get("/sso")
def token_iframe(request: Request):
    """URL de un solo uso para el iframe. Se pide cada vez que se abre el apartado."""
    if not config.NEFROIA_ENABLED:
        _no_configurado()
    sub, rol, nombre = _identidad(request)
    token = nefroia_sso.emitir_token(sub, rol, nombre)
    return JSONResponse(
        {"url": nefroia_sso.url_sso(token, embed=True), "expira_en": config.NEFROIA_TOKEN_TTL},
        headers=_SIN_CACHE,
    )


@router.get("/abrir")
def abrir_pestana(request: Request):
    """Alternativa sin iframe (navegadores que bloquean cookies de terceros)."""
    if not config.NEFROIA_ENABLED:
        _no_configurado()
    # Solo desde la propia app (evita que otro sitio dispare el inicio de sesión).
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        raise HTTPException(403, "Abre NefroIA desde Hoja Diaria")
    sub, rol, nombre = _identidad(request)
    token = nefroia_sso.emitir_token(sub, rol, nombre)
    return RedirectResponse(nefroia_sso.url_sso(token, embed=False), status_code=303, headers=_SIN_CACHE)
