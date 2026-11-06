"""
Configuración de pytest.

La app lee su configuración de variables de entorno al importarse, así que
se definen aquí ANTES de importar main.

- Por defecto usa una BD SQLite temporal.
- En CI se define TEST_DATABASE_URL para correr también contra PostgreSQL.
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # la app sirve archivos con rutas relativas (static/)

_tmp = tempfile.mkdtemp(prefix="renal-test-")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/test.db"
os.environ["APP_USER"] = "admin"
os.environ["APP_PASSWORD"] = "clave-de-prueba"
os.environ["SECRET_KEY"] = "secreto-solo-para-tests"
os.environ["DEMO_MODE"] = "true"
os.environ["COOKIE_SECURE"] = "false"
os.environ["ANTHROPIC_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import models  # noqa: E402
from database import engine  # noqa: E402
from main import app  # noqa: E402

ADMIN = {"usuario": "admin", "password": "clave-de-prueba"}


@pytest.fixture(scope="session", autouse=True)
def bd_limpia():
    """BD vacía al inicio: el arranque en DEMO_MODE debe sembrar los pacientes."""
    models.Base.metadata.drop_all(bind=engine)
    yield
    engine.dispose()


@pytest.fixture
def anonimo():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin():
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json=ADMIN)
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def demo():
    with TestClient(app) as c:
        r = c.post("/api/auth/demo")
        assert r.status_code == 200, r.text
        yield c
