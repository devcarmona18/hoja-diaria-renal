"""R4 (heparina UI/kg y datos visibles) y R10 (paciente activo/inactivo con motivo)."""
import pytest

import models
from database import SessionLocal
from services.pacientes import consulta_activos, esta_activo, ids_activos, listar_activos
from tests.helpers_w1 import borrar_sesion, paciente_temporal


# ── R4 ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("valor,ok", [(10, True), (15, True), (20, True), (9, False), (21, False), (0, False), (-5, False)])
def test_heparina_ui_kg_rango_10_a_20(admin, valor, ok):
    with paciente_temporal(admin, "T-R4-001", heparina_ui_kg=valor) as r:
        assert r.status_code == (201 if ok else 422), r.text
        if ok:
            assert r.json()["heparina_ui_kg"] == valor


def test_heparina_ui_kg_opcional_y_heparina_uh_intacta(admin):
    with paciente_temporal(admin, "T-R4-002", heparina_unidades=12) as r:
        assert r.status_code == 201
        assert r.json()["heparina_ui_kg"] is None and r.json()["heparina_unidades"] == 12


def test_registro_expone_datos_visibles_en_hoja(admin):
    ses = admin.get("/api/sesiones/2026-05-05/M").json()
    try:
        reg = admin.get(f"/api/sesiones/{ses['id']}/registros").json()[0]
        p = reg["paciente"]
        for campo in ("tipo_filtro", "heparina_unidades", "heparina_ui_kg", "cedula", "acceso_estado", "acceso_sitio"):
            assert campo in p
        assert p["cedula"].startswith("V-") and p["tipo_filtro"]
        assert 10 <= p["heparina_ui_kg"] <= 20
    finally:
        borrar_sesion("2026-05-05", "M")


# ── R10 ──────────────────────────────────────────────────────────────────────
def test_desactivar_con_motivo_y_reactivar(admin):
    pid = admin.get("/api/pacientes?turno=T").json()[0]["id"]
    try:
        r = admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={"motivo": "hospitalizado", "motivo_texto": "  Clínica ficticia  "})
        assert r.status_code == 200, r.text
        p = r.json()
        assert (p["activo"], p["motivo_inactivo"], p["motivo_inactivo_texto"]) == (False, "hospitalizado", "Clínica ficticia")
        assert pid not in {x["id"] for x in admin.get("/api/pacientes?activo=true").json()}
        assert pid in {x["id"] for x in admin.get("/api/pacientes?activo=false").json()}
        p = admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={}).json()
        assert (p["activo"], p["motivo_inactivo"], p["motivo_inactivo_texto"]) == (True, None, None)
    finally:
        with SessionLocal() as db:
            db.get(models.Paciente, pid).activo = True
            db.commit()


def test_toggle_sin_cuerpo_sigue_funcionando(admin):
    pid = admin.get("/api/pacientes?turno=T").json()[1]["id"]
    try:
        p = admin.patch(f"/api/pacientes/{pid}/toggle-activo").json()
        assert p["activo"] is False and p["motivo_inactivo"] is None
    finally:
        admin.patch(f"/api/pacientes/{pid}/toggle-activo")


def test_motivo_invalido_rechazado(admin):
    pid = admin.get("/api/pacientes?turno=T").json()[2]["id"]
    r = admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={"motivo": "vacaciones"})
    assert r.status_code == 422


def test_put_inactivo_guarda_motivo_y_activo_lo_limpia(admin):
    with paciente_temporal(admin, "T-R10-001") as r:
        p = r.json()
        base = {k: v for k, v in p.items() if k != "id"}
        r = admin.put(f"/api/pacientes/{p['id']}", json={**base, "activo": False, "motivo_inactivo": "otro", "motivo_inactivo_texto": "Traslado"})
        assert r.status_code == 200 and r.json()["motivo_inactivo"] == "otro"
        r = admin.put(f"/api/pacientes/{p['id']}", json={**base, "activo": True, "motivo_inactivo": "otro"})
        assert r.json()["motivo_inactivo"] is None


def test_inactivo_no_entra_en_hojas_nuevas_ni_en_helper(admin):
    pid = admin.get("/api/pacientes?turno=N").json()[0]["id"]
    admin.patch(f"/api/pacientes/{pid}/toggle-activo", json={"motivo": "otro"})
    try:
        ses = admin.get("/api/sesiones/2026-05-06/N").json()
        regs = admin.get(f"/api/sesiones/{ses['id']}/registros").json()
        assert len(regs) == 47 and pid not in {r["paciente_id"] for r in regs}
        with SessionLocal() as db:
            assert pid not in ids_activos(db)
            assert len(listar_activos(db, turno="N")) == 47
            assert consulta_activos(db).filter(models.Paciente.turno == "N").count() == 47
            assert not esta_activo(db.get(models.Paciente, pid))
    finally:
        borrar_sesion("2026-05-06", "N")
        admin.patch(f"/api/pacientes/{pid}/toggle-activo")
