"""R1 — tipos de acceso vascular: validación, migración de valores antiguos y etiquetas."""
import pytest
from sqlalchemy import create_engine, text

import migraciones
from services.pacientes import etiqueta_acceso
from tests.helpers_w1 import paciente_temporal


def test_crear_fav_con_estado_y_calibre(admin):
    with paciente_temporal(admin, "T-R1-001", acceso="FAV", acceso_estado="alto_riesgo", acceso_calibre=15) as r:
        assert r.status_code == 201, r.text
        p = r.json()
        assert (p["acceso"], p["acceso_estado"], p["acceso_calibre"], p["acceso_sitio"]) == ("FAV", "alto_riesgo", 15, None)


def test_crear_cy_femoral_descarta_campos_de_fav(admin):
    with paciente_temporal(admin, "T-R1-002", acceso="CY", acceso_sitio="femoral",
                           acceso_estado="limpia", acceso_calibre=16) as r:
        assert r.status_code == 201, r.text
        p = r.json()
        assert (p["acceso"], p["acceso_sitio"], p["acceso_estado"], p["acceso_calibre"]) == ("CY", "femoral", None, None)


@pytest.mark.parametrize("extra", [
    {"acceso": "FAV"},                                             # falta estado
    {"acceso": "FAV", "acceso_estado": "limpia", "acceso_calibre": 18},
    {"acceso": "FAV", "acceso_estado": "rara"},
    {"acceso": "CY"},                                              # falta sitio
    {"acceso": "CY", "acceso_sitio": "braquial"},
    {"acceso": "F16"},                                             # valores antiguos ya no se aceptan
    {"acceso": "FAV_L"},
])
def test_accesos_invalidos_rechazados(admin, extra):
    with paciente_temporal(admin, "T-R1-003", **extra) as r:
        assert r.status_code == 422, r.text


def test_demo_solo_lectura_no_crea(demo):
    r = demo.post("/api/pacientes", json={"nombre": "X", "cedula": "T-R1-004", "estacion": 1, "cama": 1, "turno": "M"})
    assert r.status_code == 403


def test_semilla_usa_solo_accesos_nuevos(admin):
    pacs = admin.get("/api/pacientes").json()
    assert {p["acceso"] for p in pacs} == {"FAV", "CY"}
    assert all(p["acceso_sitio"] in ("yugular", "femoral") for p in pacs if p["acceso"] == "CY")
    assert all(p["acceso_estado"] and p["acceso_calibre"] in (15, 16, 17) for p in pacs if p["acceso"] == "FAV")


def test_etiqueta_acceso():
    class P:  # objeto mínimo
        acceso = "FAV"; acceso_estado = "aneurismatica"; acceso_calibre = 17; acceso_cm = 12; acceso_sitio = None
    assert etiqueta_acceso(P) == "FAV aneurismática (12 cm), aguja calibre 17"
    P.acceso, P.acceso_sitio = "CY", "yugular"
    assert etiqueta_acceso(P) == "Catéter (CY) yugular"


def test_migracion_de_valores_antiguos(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/viejo.db")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE pacientes (id INTEGER PRIMARY KEY, nombre TEXT, acceso TEXT, acceso_cm INTEGER)"))
        c.execute(text("CREATE TABLE registros (id INTEGER PRIMARY KEY, sesion_id INTEGER)"))
        for i, (acc, cm) in enumerate([("F16", None), ("F17", None), ("CY", None), ("FAV_L", None),
                                       ("FAV_AR", None), ("FAV_ANE", 14), (None, None)], start=1):
            c.execute(text("INSERT INTO pacientes (id, nombre, acceso, acceso_cm) VALUES (:i, 'Ficticio', :a, :c)"),
                      {"i": i, "a": acc, "c": cm})
    hechas = migraciones.aplicar(eng)
    assert any("pacientes.acceso_estado" in h for h in hechas)

    def fila(i):
        with eng.connect() as c:
            return tuple(c.execute(text("SELECT acceso, acceso_estado, acceso_calibre, acceso_sitio, acceso_cm "
                                        "FROM pacientes WHERE id=:i"), {"i": i}).one())
    assert fila(1) == ("FAV", "limpia", 16, None, None)
    assert fila(2) == ("FAV", "limpia", 17, None, None)
    assert fila(3) == ("CY", None, None, "yugular", None)
    assert fila(4) == ("FAV", "limpia", None, None, None)
    assert fila(5) == ("FAV", "alto_riesgo", None, None, None)
    assert fila(6) == ("FAV", "aneurismatica", None, None, 14)
    assert fila(7) == (None, None, None, None, None)

    # columnas de las demás entregas
    with eng.connect() as c:
        cols = {r[1] for r in c.execute(text("PRAGMA table_info(pacientes)"))}
        cols_reg = {r[1] for r in c.execute(text("PRAGMA table_info(registros)"))}
    assert {"heparina_ui_kg", "motivo_inactivo", "motivo_inactivo_texto"} <= cols
    assert {"pa_pie_sistolica", "pa_pie_diastolica", "fc"} <= cols_reg

    # idempotente: no repite nada y un CY femoral posterior NO vuelve a yugular
    with eng.begin() as c:
        c.execute(text("UPDATE pacientes SET acceso_sitio='femoral' WHERE id=3"))
    assert migraciones.aplicar(eng) == []
    assert fila(3)[3] == "femoral"
