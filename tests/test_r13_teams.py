"""R13 — notificaciones a Teams: apagado = cero llamadas; encendido = solo iniciales; token/admin; días configurables."""
import json
from datetime import date

import pytest

import config
import models
from database import SessionLocal
from services import teams
from tests.helpers_w2a import borrar_paciente_total, crear_paciente

MEDICO = "Dra. Elena Ficticia Prueba"
WEBHOOK = "https://prod-00.westus.logic.azure.com:443/workflows/abc123/triggers/manual/paths/invoke?sig=FICTICIA"
NOMBRE_COMPLETO = "Quintero Zambrano, Wilfredo"
CEDULA = "T-R13T-001"


@pytest.fixture
def escenario(admin):
    p = crear_paciente(admin, CEDULA, nombre=NOMBRE_COMPLETO, medico=MEDICO)
    ok = crear_paciente(admin, "T-R13T-002", nombre="Normal Ficticio, Pedro", medico=MEDICO, cama=15)
    admin.post("/api/laboratorios", json={"paciente_id": p["id"], "fecha": "2026-11-02", "tipo": "Hb", "valor": 8.1})
    admin.post("/api/laboratorios", json={"paciente_id": p["id"], "fecha": "2026-11-02", "tipo": "K", "valor": 7.0})
    admin.post("/api/laboratorios", json={"paciente_id": ok["id"], "fecha": "2026-11-02", "tipo": "Hb", "valor": 11.0})
    medico = next(m for m in admin.get("/api/labs/medicos").json() if m["nombre"] == MEDICO)
    yield {"paciente": p, "medico_id": medico["id"]}
    with SessionLocal() as db:
        db.query(models.TeamsEnvio).filter_by(medico_id=medico["id"]).delete()
        db.commit()
    borrar_paciente_total(CEDULA)
    borrar_paciente_total("T-R13T-002")
    with SessionLocal() as db:
        db.query(models.Medico).filter_by(nombre=MEDICO).delete()
        db.commit()


@pytest.fixture
def http(monkeypatch):
    llamadas = []
    monkeypatch.setattr(teams, "_post_json", lambda url, payload, timeout: llamadas.append((url, payload)) or 202)
    return llamadas


def _con_webhook(admin, medico_id, url=WEBHOOK):
    r = admin.put(f"/api/labs/medicos/{medico_id}", json={"teams_webhook_url": url})
    assert r.status_code == 200, r.text
    return r


def test_apagado_por_defecto_no_hace_ninguna_llamada_http(admin, escenario, http):
    assert config.TEAMS_ENABLED is False
    _con_webhook(admin, escenario["medico_id"])
    for cuerpo in (None, {"forzar": True}):
        r = admin.post("/api/labs/notificaciones/enviar", json=cuerpo) if cuerpo else admin.post("/api/labs/notificaciones/enviar")
        assert r.status_code == 200
        assert r.json()["enabled"] is False and r.json()["enviados"] == []
    assert http == []
    with SessionLocal() as db:
        assert db.query(models.TeamsEnvio).filter_by(medico_id=escenario["medico_id"]).count() == 0


def test_apagado_la_funcion_real_nunca_abre_la_red(admin, escenario, monkeypatch):
    """Aunque nadie sustituya _post_json, con TEAMS_ENABLED=false no se llega a ella."""
    _con_webhook(admin, escenario["medico_id"])
    def prohibido(*a, **k):
        raise AssertionError("llamada HTTP con Teams apagado")
    monkeypatch.setattr(teams, "_post_json", prohibido)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", prohibido)
    with SessionLocal() as db:
        assert teams.enviar_notificaciones(db, forzar=True)["enviados"] == []


def test_encendido_envia_solo_iniciales(admin, escenario, http, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_ENABLED", True)
    _con_webhook(admin, escenario["medico_id"])
    r = admin.post("/api/labs/notificaciones/enviar", json={"forzar": True, "medico_id": escenario["medico_id"]})
    assert r.status_code == 200, r.text
    assert r.json()["enviados"] == [{"medico": MEDICO, "pacientes": 1, "http_status": 202}]
    assert len(http) == 1
    url, payload = http[0]
    assert url == WEBHOOK
    texto = json.dumps(payload, ensure_ascii=False)
    assert "QZW" in texto                                   # iniciales del paciente
    assert "Quintero" not in texto and "Wilfredo" not in texto and "Zambrano" not in texto
    assert CEDULA not in texto and "Normal Ficticio" not in texto
    assert "Hemoglobina 8.1 g/dL (bajo" in texto and "Potasio 7 mEq/L (muy alto" in texto
    assert payload["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    # el paciente con resultados normales no aparece
    assert texto.count("**") == 2                           # un solo paciente en la tarjeta


def test_reporte_agrupa_por_medico_y_no_incluye_normales_ni_inactivos(admin, escenario):
    admin.patch(f"/api/pacientes/{escenario['paciente']['id']}/toggle-activo", json={"motivo": "otro"})
    with SessionLocal() as db:
        reportes = [r for r in teams.construir_reportes(db) if r["medico"] == MEDICO]
        db.commit()
    assert reportes == []                                   # su único paciente anormal está inactivo


def test_dias_de_envio_configurables(admin, escenario, http, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_ENABLED", True)
    _con_webhook(admin, escenario["medico_id"])
    assert config.TEAMS_DIAS == "1,15" and teams.dias_de_envio() == [1, 15]
    assert teams.es_dia_de_envio(date(2026, 12, 1)) and teams.es_dia_de_envio(date(2026, 12, 15))
    assert not teams.es_dia_de_envio(date(2026, 12, 2))
    monkeypatch.setattr(config, "TEAMS_DIAS", "5, 20 ,x,40")
    assert teams.dias_de_envio() == [5, 20]
    with SessionLocal() as db:
        r = teams.enviar_notificaciones(db, hoy=date(2026, 12, 2), medico_id=escenario["medico_id"])
        assert r["programado_hoy"] is False and r["enviados"] == [] and http == []
        r = teams.enviar_notificaciones(db, hoy=date(2026, 12, 5), medico_id=escenario["medico_id"])
        assert len(r["enviados"]) == 1 and len(http) == 1
        # el mismo día no se repite, salvo forzar
        r = teams.enviar_notificaciones(db, hoy=date(2026, 12, 5), medico_id=escenario["medico_id"])
        assert r["enviados"] == [] and r["omitidos"][0]["motivo"] == "ya enviado hoy"
        r = teams.enviar_notificaciones(db, hoy=date(2026, 12, 5), forzar=True, medico_id=escenario["medico_id"])
        assert len(r["enviados"]) == 1 and len(http) == 2


def test_error_del_webhook_queda_registrado(admin, escenario, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_ENABLED", True)
    _con_webhook(admin, escenario["medico_id"])
    monkeypatch.setattr(teams, "_post_json", lambda *a: 500)
    r = admin.post("/api/labs/notificaciones/enviar", json={"forzar": True, "medico_id": escenario["medico_id"]}).json()
    assert r["enviados"] == [] and r["omitidos"][0]["motivo"] == "HTTP 500"
    def cae(*a):
        raise TimeoutError("sin red")
    monkeypatch.setattr(teams, "_post_json", cae)
    r = admin.post("/api/labs/notificaciones/enviar", json={"forzar": True, "medico_id": escenario["medico_id"]}).json()
    assert r["omitidos"][0]["motivo"] == "TimeoutError"
    est = admin.get("/api/labs/notificaciones/estado").json()
    assert [e["estado"] for e in est["ultimos_envios"][:2]] == ["error", "error"]


def test_medico_sin_webhook_se_omite(admin, escenario, http, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_ENABLED", True)
    r = admin.post("/api/labs/notificaciones/enviar", json={"forzar": True, "medico_id": escenario["medico_id"]}).json()
    assert r["omitidos"] == [{"medico": MEDICO, "pacientes": 1, "motivo": "sin webhook válido"}] and http == []


@pytest.mark.parametrize("url", ["http://prod.logic.azure.com/x", "https://evil.example.com/hook",
                                 "https://127.0.0.1/hook", "https://logic.azure.com.evil.com/x",
                                 "https://user:pw@logic.azure.com/x", "ftp://logic.azure.com/x"])
def test_webhooks_no_permitidos_se_rechazan(admin, escenario, url):
    assert admin.put(f"/api/labs/medicos/{escenario['medico_id']}", json={"teams_webhook_url": url}).status_code == 422


def test_el_webhook_no_se_devuelve_completo(admin, escenario):
    r = _con_webhook(admin, escenario["medico_id"]).json()
    assert r["tiene_webhook"] and r["webhook_valido"]
    assert "sig=FICTICIA" not in json.dumps(r) and "abc123" not in json.dumps(r)
    assert "sig=FICTICIA" not in admin.get("/api/labs/medicos").text
    r = admin.put(f"/api/labs/medicos/{escenario['medico_id']}", json={"teams_webhook_url": ""}).json()
    assert r["tiene_webhook"] is False


def test_autorizacion_admin_o_token(admin, demo, anonimo, escenario, http, monkeypatch):
    monkeypatch.setattr(config, "TEAMS_ENABLED", True)
    _con_webhook(admin, escenario["medico_id"])
    cuerpo = {"forzar": True, "medico_id": escenario["medico_id"]}
    url = "/api/labs/notificaciones/enviar"
    assert anonimo.post(url, json=cuerpo).status_code == 401                  # sin token configurado
    assert demo.post(url, json=cuerpo).status_code == 403
    monkeypatch.setattr(config, "TEAMS_JOB_TOKEN", "token-ficticio-largo")
    assert anonimo.post(url, json=cuerpo).status_code == 401
    assert anonimo.post(url, json=cuerpo, headers={"Authorization": "Bearer otro"}).status_code == 401
    assert demo.post(url, json=cuerpo, headers={"Authorization": "Bearer otro"}).status_code == 403
    assert http == []
    r = anonimo.post(url, json=cuerpo, headers={"Authorization": "Bearer token-ficticio-largo"})
    assert r.status_code == 200 and len(r.json()["enviados"]) == 1
    r = anonimo.post(url, json=cuerpo, headers={"X-Job-Token": "token-ficticio-largo"})
    assert r.status_code == 200
    # el resto de la API sigue protegida para el token (solo abre esa ruta)
    assert anonimo.get("/api/pacientes", headers={"Authorization": "Bearer token-ficticio-largo"}).status_code == 401


def test_vista_previa_no_envia_y_requiere_admin(admin, demo, escenario, http):
    assert demo.get("/api/labs/notificaciones/vista-previa").status_code == 403
    d = admin.get(f"/api/labs/notificaciones/vista-previa?medico_id={escenario['medico_id']}").json()
    assert d["enabled"] is False and http == []
    rep = d["reportes"][0]
    assert rep["total_pacientes"] == 1 and rep["pacientes"][0]["iniciales"] == "QZW"
    assert "Quintero" not in json.dumps(d)


def test_medicos_migrados_desde_el_texto_libre(admin, escenario):
    nombres = {m["nombre"]: m for m in admin.get("/api/labs/medicos").json()}
    assert nombres[MEDICO]["iniciales"] == "EFP"
