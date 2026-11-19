from config import normalizar_database_url


def test_health(anonimo):
    r = anonimo.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


def test_demo_mode_siembra_144_pacientes_ficticios(admin):
    pacs = admin.get("/api/pacientes").json()
    assert len(pacs) == 144
    assert all(p["cedula"].startswith("V-") for p in pacs)


def test_normaliza_url_postgres():
    assert normalizar_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalizar_database_url("postgresql://u:p@h/db?sslmode=require") == \
        "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalizar_database_url("sqlite:///./renal.db") == "sqlite:///./renal.db"
