try:  # Carga variables desde .env si python-dotenv está instalado
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import models
from database import engine
from routers import pacientes, sesiones, cierre, programacion, laboratorios, historial, estadisticas, ia

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Hoja Diaria — Unidad Renal", version="4.0.0")

app.include_router(pacientes.router,     prefix="/api/pacientes",     tags=["pacientes"])
app.include_router(sesiones.router,      prefix="/api/sesiones",      tags=["sesiones"])
app.include_router(cierre.router,        prefix="/api/cierre",        tags=["cierre"])
app.include_router(programacion.router,  prefix="/api/programacion",  tags=["programacion"])
app.include_router(laboratorios.router,  prefix="/api/laboratorios",  tags=["laboratorios"])
app.include_router(historial.router,     prefix="/api/historial",     tags=["historial"])
app.include_router(estadisticas.router,  prefix="/api/estadisticas",  tags=["estadisticas"])
app.include_router(ia.router,            prefix="/api/ia",            tags=["ia"])

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return FileResponse("static/index.html")
