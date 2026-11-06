"""
Autenticación sencilla basada en cookie de sesión firmada.

Roles:
  - admin: usuario/contraseña de APP_USER / APP_PASSWORD. Lectura y escritura.
  - demo:  botón "Ver demo" (solo si DEMO_MODE=true). Solo lectura.

Si APP_USER/APP_PASSWORD no están definidos, el login se desactiva y todo
el mundo es admin (pensado para desarrollo local).
"""
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

import config

router = APIRouter()

METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}
RUTAS_PUBLICAS = ("/health", "/login", "/static/", "/api/auth/", "/favicon.ico")

# Freno simple contra fuerza bruta: máx. 10 intentos fallidos por IP cada 15 min.
_MAX_FALLOS, _VENTANA = 10, 15 * 60
_fallos: dict[str, list[float]] = defaultdict(list)


def rol_actual(request: Request) -> str | None:
    if not config.AUTH_ENABLED:
        return "admin"
    return request.session.get("rol")


async def middleware_auth(request: Request, call_next):
    path = request.url.path
    if any(path == r or path.startswith(r) for r in RUTAS_PUBLICAS):
        return await call_next(request)

    rol = rol_actual(request)
    es_api = path.startswith("/api/")

    if rol is None:
        if es_api:
            return JSONResponse({"detail": "No autenticado"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    if rol == "demo" and request.method not in METODOS_LECTURA:
        return JSONResponse(
            {"detail": "Modo demo: solo lectura. Inicia sesión para hacer cambios."},
            status_code=403,
        )

    return await call_next(request)


class LoginInput(BaseModel):
    usuario: str
    password: str


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


@router.post("/login")
def login(data: LoginInput, request: Request):
    if not config.AUTH_ENABLED:
        return {"rol": "admin"}

    ip, ahora = _ip(request), time.time()
    _fallos[ip] = [t for t in _fallos[ip] if ahora - t < _VENTANA]
    if len(_fallos[ip]) >= _MAX_FALLOS:
        raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")

    ok_user = secrets.compare_digest(data.usuario.encode(), config.APP_USER.encode())
    ok_pass = secrets.compare_digest(data.password.encode(), config.APP_PASSWORD.encode())
    if not (ok_user and ok_pass):
        _fallos[ip].append(ahora)
        raise HTTPException(401, "Usuario o contraseña incorrectos")

    _fallos.pop(ip, None)
    request.session.clear()
    request.session["rol"] = "admin"
    request.session["usuario"] = config.APP_USER
    return {"rol": "admin"}


@router.post("/demo")
def login_demo(request: Request):
    if not config.DEMO_MODE:
        raise HTTPException(404, "El acceso demo no está habilitado")
    request.session.clear()
    request.session["rol"] = "demo"
    request.session["usuario"] = "demo"
    return {"rol": "demo"}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    rol = rol_actual(request)
    return {
        "autenticado": rol is not None,
        "rol": rol,
        "usuario": request.session.get("usuario") if config.AUTH_ENABLED else None,
        "auth_enabled": config.AUTH_ENABLED,
        "demo_mode": config.DEMO_MODE,
        "ia_enabled": config.IA_ENABLED,
    }
