"""R12 — Con el mes cerrado TODAS sus hojas diarias son de solo lectura (409);
reabrir el mes (admin + motivo) las desbloquea. Datos FICTICIOS."""
import models
from database import SessionLocal
from services import bloqueo_mes
from tests.helpers_w2a import marcar, paciente_y_mes, registro_de

MES = "2025-07"
LUN, MIE, VIE, SAB = "2025-07-07", "2025-07-09", "2025-07-11", "2025-07-05"
MSG = "El mes está cerrado; reábralo para editar"


def _es_409(r):
    assert r.status_code == 409, (r.status_code, r.text)
    assert r.json()["detail"] == MSG and r.json()["codigo"] == "mes_cerrado"


def _limpiar_mes():
    with SessionLocal() as db:
        ids = [p.id for p in db.query(models.PedidoInsumos).filter(models.PedidoInsumos.fecha_pedido.startswith(MES))]
        if ids:
            db.query(models.PedidoInsumosItem).filter(models.PedidoInsumosItem.pedido_id.in_(ids)).delete(
                synchronize_session=False)
            db.query(models.PedidoInsumos).filter(models.PedidoInsumos.id.in_(ids)).delete(synchronize_session=False)
        db.query(models.AsignacionDia).filter(models.AsignacionDia.fecha.startswith(MES)).delete(
            synchronize_session=False)
        db.query(models.Programacion).filter(models.Programacion.fecha.startswith(MES)).delete(
            synchronize_session=False)
        db.commit()


def test_mes_cerrado_bloquea_hojas_programacion_e_insumos(admin):
    try:
        with paciente_y_mes(admin, "T-R12B-001", MES) as p:
            pid = p["id"]
            ses, reg = marcar(admin, LUN, "N", pid, asistencia="A")
            ses_cerrada = admin.get(f"/api/sesiones/{MIE}/N").json()
            assert admin.post(f"/api/cierre/{ses_cerrada['id']}/cerrar").status_code == 200
            # antes de cerrar el mes: un cambio de un día y un pedido confirmado
            otro = next(pu["paciente"]["id"] for pu in admin.get(f"/api/asignaciones/hoja/{VIE}/N").json()["puestos"]
                        if pu["paciente"]["id"] != pid)
            r = admin.post("/api/asignaciones", json={"fecha": VIE, "turno": "N", "paciente_id": pid,
                                                      "tipo": "reemplazo", "reemplaza_paciente_id": otro})
            assert r.status_code == 201, r.text
            asig = next(pu["asignacion"]["id"] for pu in r.json()["puestos"]
                        if pu["paciente"]["id"] == pid and pu["asignacion"])
            assert admin.post("/api/insumos/pedido/confirmar", json={"fecha": SAB}).status_code == 201

            assert admin.post("/api/estadisticas/asistencia/2025/07/cerrar").status_code == 200
            assert bloqueo_mes.mes_cerrado(SessionLocal(), LUN)

            # hoja existente: se ve, marcada como de mes cerrado; nada se edita
            h = admin.get(f"/api/sesiones/{LUN}/N").json()
            assert h["mes_cerrado"] is True and h["cerrada"] is False
            assert admin.get(f"/api/sesiones/{h['id']}/registros").status_code == 200
            _es_409(admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"asistencia": "NA"}))
            _es_409(admin.post(f"/api/sesiones/{h['id']}/paciente/{pid}"))
            # ni cerrar ni reabrir un día
            _es_409(admin.post(f"/api/cierre/{h['id']}/cerrar"))
            _es_409(admin.post(f"/api/cierre/{ses_cerrada['id']}/reabrir"))
            # no se crean hojas nuevas en el mes cerrado
            _es_409(admin.get("/api/sesiones/2025-07-14/N"))
            # programación EPO/Fe del día y auto-programación del mes
            _es_409(admin.post("/api/programacion", json={"fecha": "2025-07-14", "turno": "N",
                                                          "items": [{"paciente_id": pid}]}))
            _es_409(admin.post("/api/programacion/auto-mes", json={"anio": 2025, "mes": 7, "turno": "N"}))
            # cambios de un día
            _es_409(admin.post("/api/asignaciones", json={"fecha": "2025-07-16", "turno": "N",
                                                          "paciente_id": pid, "estacion": 3, "cama": 16}))
            _es_409(admin.delete(f"/api/asignaciones/{asig}"))
            _es_409(admin.post(f"/api/asignaciones/{asig}/permanente"))
            # pedido de insumos: confirmar otro día del mes o anular el ya confirmado
            _es_409(admin.post("/api/insumos/pedido/confirmar", json={"fecha": "2025-07-08"}))
            _es_409(admin.delete(f"/api/insumos/pedido/{SAB}"))
            # banderas para la UI (candado, entradas deshabilitadas)
            assert admin.get(f"/api/insumos/pedido?fecha={SAB}").json()["mes_cerrado"] is True
            assert admin.get("/api/insumos/pedido?fecha=2025-06-10").json()["mes_cerrado"] is False
            hp = admin.get(f"/api/asignaciones/hoja/{VIE}/N").json()
            assert hp["mes_cerrado"] is True and hp["editable"] is False
            # limpiar el mes
            _es_409(admin.delete("/api/historial/mes/2025/07"))
            # el pedido del 31 de julio cubre agosto, pero se hace en julio: también bloqueado
            _es_409(admin.post("/api/insumos/pedido/confirmar", json={"fecha": "2025-07-31"}))
            # otro mes sigue abierto
            assert admin.post("/api/insumos/pedido/confirmar", json={"fecha": "2025-06-10"}).status_code == 201
            assert admin.delete("/api/insumos/pedido/2025-06-10").status_code == 200

            # reabrir (admin + motivo) desbloquea
            r = admin.post("/api/estadisticas/asistencia/2025/07/reabrir", json={"motivo": "Corregir asistencia"})
            assert r.status_code == 200, r.text
            assert admin.get(f"/api/sesiones/{LUN}/N").json()["mes_cerrado"] is False
            r = admin.patch(f"/api/sesiones/registros/{reg['id']}", json={"asistencia": "NA"})
            assert r.status_code == 200, r.text
            assert admin.post(f"/api/cierre/{ses_cerrada['id']}/reabrir").status_code == 200
            assert admin.delete(f"/api/insumos/pedido/{SAB}").status_code == 200
            assert admin.post("/api/programacion", json={"fecha": "2025-07-14", "turno": "N",
                                                         "items": [{"paciente_id": pid}]}).status_code == 201
            _, reg2 = registro_de(admin, "2025-07-14", "N", pid)       # ya se puede crear la hoja
            assert reg2["paciente_id"] == pid
    finally:
        _limpiar_mes()


def test_mes_de():
    assert bloqueo_mes.mes_de("2025-07-31") == "2025-07"
    assert bloqueo_mes.mes_de("2025-07") == "2025-07"
    assert bloqueo_mes.mes_de("") is None and bloqueo_mes.mes_de("julio") is None
