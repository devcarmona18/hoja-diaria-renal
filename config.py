"""
Configuración central leída de variables de entorno.
En local se pueden definir en un archivo .env (ver .env.example).
"""
import os

try:  # Carga .env si python-dotenv está instalado (solo útil en local)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return (os.getenv(name) or str(default)).strip().lower() in ("1", "true", "yes", "si", "sí")


def normalizar_database_url(url: str) -> str:
    """Adapta URLs de Postgres de proveedores (postgres://…) al driver psycopg 3."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


DATABASE_URL = normalizar_database_url(os.getenv("DATABASE_URL") or "sqlite:///./renal.db")

# Si está activo y la BD no tiene pacientes, se cargan los ficticios de seed.py al arrancar.
DEMO_MODE = _bool("DEMO_MODE")

# Login. Si APP_USER/APP_PASSWORD no están definidos, el login se desactiva (solo para desarrollo local).
APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
AUTH_ENABLED = bool(APP_USER and APP_PASSWORD)

# Firma de la cookie de sesión. En producción debe ser un valor aleatorio largo.
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-insecure-secret-change-me"
# En producción (HTTPS) la cookie solo viaja por conexiones seguras.
COOKIE_SECURE = _bool("COOKIE_SECURE")

# Módulo IA: solo se activa si existe la clave.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
IA_ENABLED = bool(ANTHROPIC_API_KEY)
