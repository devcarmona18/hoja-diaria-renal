import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

import config
import models
import auth
import migraciones
from database import engine, SessionLocal
from routers import pacientes, sesiones, cierre, programacion, laboratorios, historial, estadisticas, ia
from routers import archivo, labs  # R13
from routers import epo_fe  # R14: auto-programación EPO / hierro
from routers import hl7  # «Próximamente»: inactivo mientras HL7_ENABLED=false
from routers import asignaciones  # R2/R7: programar el día siguiente, cambios de un día

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    models.Base.metadata.create_all(bind=engine)
    for accion in migraciones.aplicar(engine):   # única migración aditiva (R1/R3/R4/R10, R2/R7 y R11–R13)
        log.info("migración: %s", accion)
    if config.DEMO_MODE:
        import seed
        with SessionLocal() as db:
            n = seed.sembrar_si_vacia(db)
            if n:
                log.info("DEMO_MODE: base vacía, se cargaron %d pacientes ficticios", n)
                from services import demo_clinico   # R13: médicos y laboratorios ficticios
                demo_clinico.sembrar_clinico_demo(db)
    if not config.AUTH_ENABLED:
        log.warning("APP_USER/APP_PASSWORD no definidos: login DESACTIVADO (solo para desarrollo local)")
    yield


app = FastAPI(title="Hoja Diaria — Unidad Renal", version="5.0.0", lifespan=lifespan)

# Orden importa: el último middleware agregado es el más externo.
# SessionMiddleware debe envolver al middleware de autenticación.
app.middleware("http")(auth.middleware_auth)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    session_cookie="renal_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=config.COOKIE_SECURE,
)

app.include_router(auth.router,          prefix="/api/auth",          tags=["auth"])
app.include_router(pacientes.router,     prefix="/api/pacientes",     tags=["pacientes"])
app.include_router(sesiones.router,      prefix="/api/sesiones",      tags=["sesiones"])
app.include_router(cierre.router,        prefix="/api/cierre",        tags=["cierre"])
app.include_router(programacion.router,  prefix="/api/programacion",  tags=["programacion"])
app.include_router(laboratorios.router,  prefix="/api/laboratorios",  tags=["laboratorios"])
app.include_router(historial.router,     prefix="/api/historial",     tags=["historial"])
app.include_router(estadisticas.router,  prefix="/api/estadisticas",  tags=["estadisticas"])
app.include_router(ia.router,            prefix="/api/ia",            tags=["ia"])
app.include_router(asignaciones.router,  prefix="/api/asignaciones",  tags=["programacion"])
app.include_router(archivo.router,       prefix="/api/pacientes",     tags=["archivo"])
app.include_router(labs.router,          prefix="/api/labs",          tags=["labs"])
app.include_router(epo_fe.router,        prefix="/api/epo-fe",        tags=["epo-fe"])
app.include_router(hl7.router,           prefix="/api/hl7",           tags=["hl7"], include_in_schema=config.HL7_ENABLED)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health", tags=["infra"])
def health():
    """Chequeo de vida para Render: verifica que la app y la BD respondan."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "db": "ok"}
    except Exception:
        return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if auth.rol_actual(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse("static/login.html")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return FileResponse("static/index.html")
