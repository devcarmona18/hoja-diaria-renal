def test_api_requiere_login(anonimo):
    assert anonimo.get("/api/pacientes").status_code == 401


def test_pagina_redirige_a_login(anonimo):
    r = anonimo.get("/", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"
    assert anonimo.get("/login").status_code == 200


def test_login_incorrecto(anonimo):
    r = anonimo.post("/api/auth/login", json={"usuario": "admin", "password": "mala"})
    assert r.status_code == 401
    assert anonimo.get("/api/auth/me").json()["autenticado"] is False


def test_login_correcto(admin):
    me = admin.get("/api/auth/me").json()
    assert me["autenticado"] is True
    assert me["rol"] == "admin"
    assert me["demo_mode"] is True
    assert me["ia_enabled"] is False


def test_logout(admin):
    admin.post("/api/auth/logout")
    assert admin.get("/api/pacientes").status_code == 401


def test_demo_puede_leer(demo):
    assert demo.get("/api/auth/me").json()["rol"] == "demo"
    assert len(demo.get("/api/pacientes?turno=M").json()) == 48


def test_demo_no_puede_escribir(demo):
    pac = demo.get("/api/pacientes?turno=M").json()[0]
    r = demo.put(f"/api/pacientes/{pac['id']}", json={**pac, "nombre": "Hackeado"})
    assert r.status_code == 403
    assert demo.delete(f"/api/pacientes/{pac['id']}").status_code == 403
    assert demo.get(f"/api/pacientes?turno=M").json()[0]["nombre"] == pac["nombre"]
