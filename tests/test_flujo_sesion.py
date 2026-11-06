"""Flujo completo de un turno (antes test_api.py): abrir sesión, registrar, cierre y programación."""


def test_flujo_completo_turno(admin):
    pacs = admin.get("/api/pacientes?turno=M").json()
    assert len(pacs) == 48

    # Abrir sesión del día
    r = admin.get("/api/sesiones/2026-07-15/M")
    assert r.status_code == 200, r.text
    sesion = r.json()
    assert sesion["cerrada"] is False

    # Registros: uno por paciente del turno
    r = admin.get(f"/api/sesiones/{sesion['id']}/registros")
    assert r.status_code == 200, r.text
    regs = r.json()
    assert len(regs) == 48

    # Marcar asistencia y pesos → cálculos automáticos
    r = admin.patch(f"/api/sesiones/registros/{regs[0]['id']}",
                    json={"asistencia": "A", "peso_entrada": 68.5, "peso_salida": 65.2})
    assert r.status_code == 200, r.text
    upd = r.json()
    assert upd["perdida_real"] == round(68.5 - 65.2, 2)
    assert upd["ganancia_id"] == round(68.5 - regs[0]["paciente"]["peso_seco"], 2)

    # Cierre del día
    r = admin.get(f"/api/cierre/{sesion['id']}")
    assert r.status_code == 200, r.text
    tot = r.json()["totales"]
    assert tot["total"] == 48
    assert tot["asistidos"] == 1

    # Programación de la próxima sesión
    r = admin.post("/api/programacion", json={
        "fecha": "2026-07-17",
        "turno": "M",
        "items": [{"paciente_id": pacs[0]["id"], "epo_programado": True, "hierro_programado": False}],
    })
    assert r.status_code == 201, r.text
    assert len(r.json()) == 1
