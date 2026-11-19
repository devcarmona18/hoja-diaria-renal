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
# Demo: asignar días LMV/MJS y EPO/Fe del mes (con días, cada sesión trae solo la mitad de los
# pacientes del turno). Los tests lo apagan para conservar los 48 por turno.
# Solo para despliegues de demostración con datos ficticios: asigna días y dosis
# de ejemplo si ningún paciente tiene días. Apagado por defecto para no tocar datos reales.
DEMO_EPO_FE = _bool("DEMO_EPO_FE", False)

# Login. Si APP_USER/APP_PASSWORD no están definidos, el login se desactiva (solo para desarrollo local).
APP_USER = os.getenv("APP_USER", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
AUTH_ENABLED = bool(APP_USER and APP_PASSWORD)

# Firma de la cookie de sesión. En producción debe ser un valor aleatorio largo.
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-insecure-secret-change-me"
# En producción (HTTPS) la cookie solo viaja por conexiones seguras.
COOKIE_SECURE = _bool("COOKIE_SECURE")

# ── R9: apartado «IA» = NefroIA integrado con inicio de sesión único ────────
# Ver docs/integracion-nefroia.md. Sin NEFROIA_URL o sin un NEFROIA_SSO_SECRET
# de al menos 32 caracteres, el apartado solo muestra «NefroIA no está
# configurado todavía» y NO se hace ninguna llamada ni se emite ningún token.
# Solo se envía la identidad del usuario de Hoja Diaria, nunca datos de pacientes.
def _url_nefroia(valor: str) -> str:
    valor = (valor or "").strip().rstrip("/")
    if not valor.startswith(("https://", "http://")) or any(c in valor for c in " \"'<>?#"):
        return ""
    return valor


NEFROIA_URL = _url_nefroia(os.getenv("NEFROIA_URL", ""))
NEFROIA_SSO_SECRET = (os.getenv("NEFROIA_SSO_SECRET") or "").strip()
NEFROIA_SSO_MIN_SECRET = 32
# Vida del token de acceso en segundos (máx. 120; NefroIA rechaza más).
NEFROIA_TOKEN_TTL = max(10, min(120, int(os.getenv("NEFROIA_TOKEN_TTL") or 60)))
NEFROIA_ENABLED = bool(NEFROIA_URL and len(NEFROIA_SSO_SECRET) >= NEFROIA_SSO_MIN_SECRET)

# Integración HL7 con las máquinas AK 98 («Próximamente»). APAGADA por defecto:
# con false los endpoints /api/hl7/* de ingesta y bandeja responden 404 y la
# interfaz solo muestra la burbuja informativa «Próximamente».
HL7_ENABLED = _bool("HL7_ENABLED")
# Secreto compartido con el puente local (firma HMAC-SHA256 de cada mensaje).
HL7_BRIDGE_SECRET = os.getenv("HL7_BRIDGE_SECRET", "")
# Tolerancia (segundos) del sello de tiempo de la firma: evita reenvíos tardíos.
HL7_VENTANA_SEGUNDOS = int(os.getenv("HL7_VENTANA_SEGUNDOS") or 300)
# Ruta del archivo de mapeo OBX → Hoja Diaria (por defecto hl7/mapeo_ak98.json).
HL7_MAPEO_PATH = os.getenv("HL7_MAPEO_PATH", "")


# ── R13: archivo de pacientes ────────────────────────────────────────────────
# Días que un paciente archivado sigue apareciendo en la lista «Archivados» (y que
# se puede restaurar). Pasado el plazo solo desaparece del LISTADO: sus sesiones,
# laboratorios y asistencia nunca se borran.
ARCHIVO_DIAS = int(os.getenv("ARCHIVO_DIAS") or 180)   # 6 meses

# ── R13: notificaciones a Microsoft Teams (APAGADAS por defecto) ─────────────
# Con TEAMS_ENABLED=false no se hace NINGUNA llamada HTTP saliente.
TEAMS_ENABLED = _bool("TEAMS_ENABLED")
# Días del mes (separados por coma) en que corresponde enviar el reporte.
TEAMS_DIAS = os.getenv("TEAMS_DIAS", "1,15")
# Token del trabajo programado (GitHub Actions): Authorization: Bearer <token>.
# Vacío = solo el administrador con sesión puede disparar el envío.
TEAMS_JOB_TOKEN = os.getenv("TEAMS_JOB_TOKEN", "")
TEAMS_TIMEOUT = int(os.getenv("TEAMS_TIMEOUT") or 10)
# Dominios permitidos para los webhooks (protección contra SSRF).
TEAMS_HOSTS_PERMITIDOS = tuple(
    h.strip().lower() for h in (os.getenv("TEAMS_HOSTS_PERMITIDOS") or
    "webhook.office.com,office.com,office365.com,logic.azure.com,powerplatform.com,microsoft.com").split(",")
    if h.strip()
)
