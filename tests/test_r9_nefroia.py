"""R9 — Apartado «IA»: NefroIA integrado con SSO (token HS256 corto, sin datos de pacientes)."""
import base64
import hashlib
import hmac
import importlib
import json
import re
import time
from pathlib import Path

import pytest

import config
from services import nefroia_sso

ROOT = Path(__file__).resolve().parent.parent
SECRETO = "secreto-compartido-de-pruebas-nefroia-0123456789"
URL = "https://nefroia.example.org"


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _decodificar(token: str, secreto: str = SECRETO) -> tuple[dict, dict, bool]:
    h, p, f = token.split(".")
    esperada = hmac.new(secreto.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return json.loads(_b64d(h)), json.loads(_b64d(p)), hmac.compare_digest(esperada, _b64d(f))


def _token_de_url(url: str) -> str:
    m = re.search(r"[?&]token=([^&]+)", url)
    assert m, url
    return m.group(1)


@pytest.fixture
def nefroia_on(monkeypatch):
    monkeypatch.setattr(config, "NEFROIA_URL", URL)
    monkeypatch.setattr(config, "NEFROIA_SSO_SECRET", SECRETO)
    monkeypatch.setattr(config, "NEFROIA_ENABLED", True)
    monkeypatch.setattr(config, "NEFROIA_TOKEN_TTL", 60)


# ── Interruptor apagado: tarjeta limpia, sin llamadas ni tokens ──────────────

def test_sin_configurar_no_emite_tokens(admin):
    assert admin.get("/api/auth/me").json()["nefroia_configurado"] is False
    assert admin.get("/api/nefroia/estado").json() == {"configurado": False, "origen": None}
    assert admin.get("/api/nefroia/sso").status_code == 404
    assert admin.get("/api/nefroia/abrir", follow_redirects=False).status_code == 404
    with pytest.raises(RuntimeError):
        nefroia_sso.emitir_token("admin", "admin", "admin")


def test_tarjeta_no_configurado_en_el_front(anonimo):
    js = anonimo.get("/static/js/nefroia.js").text
    assert "NefroIA no está configurado todavía" in js
    # la tarjeta se pinta ANTES de cualquier fetch
    i_card = js.index("NefroIA no está configurado todavía")
    assert i_card < js.index('apiGet("/api/nefroia/sso")')
    assert "if (!G.me.nefroia_configurado)" in js


def test_secreto_corto_o_url_invalida_dejan_el_apartado_apagado(monkeypatch):
    try:
        monkeypatch.setenv("NEFROIA_URL", URL)
        monkeypatch.setenv("NEFROIA_SSO_SECRET", "corto")
        assert importlib.reload(config).NEFROIA_ENABLED is False
        monkeypatch.setenv("NEFROIA_SSO_SECRET", SECRETO)
        monkeypatch.setenv("NEFROIA_URL", "javascript:alert(1)")
        assert importlib.reload(config).NEFROIA_ENABLED is False
        monkeypatch.setenv("NEFROIA_URL", URL + "/")
        cfg = importlib.reload(config)
        assert cfg.NEFROIA_ENABLED is True and cfg.NEFROIA_URL == URL
        monkeypatch.setenv("NEFROIA_TOKEN_TTL", "900")
        assert importlib.reload(config).NEFROIA_TOKEN_TTL == 120     # nunca > 2 min
    finally:
        monkeypatch.undo()
        importlib.reload(config)
    assert config.NEFROIA_ENABLED is False


# ── Token: claims, firma, caducidad ──────────────────────────────────────────

def test_token_admin_claims_y_firma(admin, nefroia_on):
    r = admin.get("/api/nefroia/sso")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"
    url = r.json()["url"]
    assert url.startswith(f"{URL}/sso?token=") and "embed=1" in url and "lang=es" in url
    header, claims, firma_ok = _decodificar(_token_de_url(url))
    assert firma_ok
    assert header == {"alg": "HS256", "typ": "JWT"}
    assert set(claims) == {"iss", "aud", "sub", "role", "name", "iat", "exp", "jti"}
    assert claims["iss"] == "hoja-diaria-renal" and claims["aud"] == "nefroia"
    assert claims["sub"] == "admin" and claims["role"] == "admin" and claims["name"] == "admin"
    assert 0 < claims["exp"] - claims["iat"] <= 120
    assert abs(claims["iat"] - time.time()) < 5
    assert len(claims["jti"]) >= 16


def test_token_firma_invalida_con_otro_secreto_y_jti_unico(admin, nefroia_on):
    t1 = _token_de_url(admin.get("/api/nefroia/sso").json()["url"])
    t2 = _token_de_url(admin.get("/api/nefroia/sso").json()["url"])
    assert _decodificar(t1, "otro-secreto-cualquiera-0123456789-abcdef")[2] is False
    assert _decodificar(t1)[1]["jti"] != _decodificar(t2)[1]["jti"]


def test_token_caduca(nefroia_on):
    viejo = nefroia_sso.emitir_token("admin", "admin", "admin", ahora=time.time() - 600)
    _, claims, ok = _decodificar(viejo)
    assert ok and claims["exp"] < time.time()


def test_rol_no_valido(nefroia_on):
    with pytest.raises(ValueError):
        nefroia_sso.emitir_token("x", "superadmin", "x")


def test_demo_lleva_rol_demo_y_usuario_propio_por_sesion(demo, nefroia_on, anonimo):
    _, c1, _ = _decodificar(_token_de_url(demo.get("/api/nefroia/sso").json()["url"]))
    _, c2, _ = _decodificar(_token_de_url(demo.get("/api/nefroia/sso").json()["url"]))
    assert c1["role"] == "demo" and c1["name"] == "Visitante demo"
    assert re.fullmatch(r"demo-[0-9a-f]{12}", c1["sub"])
    assert c1["sub"] == c2["sub"]                       # estable dentro de la sesión
    anonimo.post("/api/auth/demo")
    _, c3, _ = _decodificar(_token_de_url(anonimo.get("/api/nefroia/sso").json()["url"]))
    assert c3["sub"] != c1["sub"]                       # otro visitante, otro usuario


def test_sin_sesion_no_hay_token(anonimo, nefroia_on):
    assert anonimo.get("/api/nefroia/sso").status_code == 401


def test_login_desactivado_no_emite_identidades(admin, nefroia_on, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    assert admin.get("/api/nefroia/sso").status_code == 403


def test_abrir_en_pestana_nueva(admin, nefroia_on):
    r = admin.get("/api/nefroia/abrir", follow_redirects=False)
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith(f"{URL}/sso?token=") and "embed=0" in loc
    assert _decodificar(_token_de_url(loc))[2]
    r = admin.get("/api/nefroia/abrir", follow_redirects=False, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_no_se_envian_datos_de_pacientes(admin, nefroia_on):
    pacientes = admin.get("/api/pacientes?turno=M").json()
    url = admin.get("/api/nefroia/sso").json()["url"]
    _, claims, _ = _decodificar(_token_de_url(url))
    texto = json.dumps(claims, ensure_ascii=False) + url
    for p in pacientes:
        assert p["nombre"] not in texto
        assert p["cedula"] not in texto


# ── El módulo IA antiguo (enviaba nombres de pacientes) ya no existe ─────────

def test_endpoints_ia_antiguos_eliminados(admin):
    assert admin.get("/api/ia/status").status_code == 404
    assert admin.post("/api/ia/consulta", json={"paciente_id": 1, "pregunta": "hola"}).status_code in (404, 405)
    assert admin.get("/static/js/ia.js").status_code == 404
    assert not (ROOT / "routers" / "ia.py").exists()
    html = admin.get("/").text
    assert "/static/js/ia.js" not in html and "/static/js/nefroia.js" in html
    assert "crudVerIA" not in admin.get("/static/js/crud.js").text
    assert "anthropic" not in (ROOT / "requirements.txt").read_text().lower()


def test_menu_ia_tras_secciones_operativas_y_proximamente_al_final(anonimo):
    js = anonimo.get("/static/js/app.js").text
    bloque = js[js.index("const MENU_INICIO = ["):]
    bloque = bloque[:bloque.index("\n]\n")]
    ids = re.findall(r'\{ id: "([a-z]+)"', bloque)
    assert ids[-1] == "proximamente"
    assert ids.index("ia") == ids.index("epo") + 1 and ids.index("insumos") == ids.index("ia") + 1
    assert "solo-admin" not in bloque.split('id: "ia"')[1].split("},")[0]   # demo también entra
