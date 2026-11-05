"""Quick smoke test — run: python test_api.py"""
import main  # triggers create_all
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# pacientes
r = client.get("/api/pacientes?turno=M")
assert r.status_code == 200, r.text
pacs = r.json()
print("Pacientes turno M:", len(pacs))
assert len(pacs) == 48

# abrir sesion
r = client.get("/api/sesiones/2026-07-15/M")
assert r.status_code == 200, r.text
sesion = r.json()
print("Sesion id:", sesion["id"], "| cerrada:", sesion["cerrada"])

# registros
r = client.get("/api/sesiones/" + str(sesion["id"]) + "/registros")
assert r.status_code == 200, r.text
regs = r.json()
print("Registros cargados:", len(regs))
assert len(regs) == 48

# patch asistencia
primer_id = regs[0]["id"]
r = client.patch("/api/sesiones/registros/" + str(primer_id), json={"asistencia": "A", "peso_entrada": 68.5, "peso_salida": 65.2})
assert r.status_code == 200, r.text
updated = r.json()
print("Perdida real:", updated["perdida_real"], "| Ganancia ID:", updated["ganancia_id"])
assert updated["perdida_real"] == round(68.5 - 65.2, 2)

# cierre
r = client.get("/api/cierre/" + str(sesion["id"]))
assert r.status_code == 200, r.text
cierre = r.json()
tot = cierre["totales"]
print("Cierre -> total:", tot["total"], "| asistidos:", tot["asistidos"])

# programacion
r = client.post("/api/programacion", json={
    "fecha": "2026-07-17",
    "turno": "M",
    "items": [{"paciente_id": pacs[0]["id"], "epo_programado": True, "hierro_programado": False}]
})
assert r.status_code == 201, r.text
prog = r.json()
print("Programacion guardada:", len(prog), "pacientes")

print()
print("TODOS LOS TESTS PASARON")
