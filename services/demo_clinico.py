"""
Datos clínicos FICTICIOS para la demo (solo con DEMO_MODE): médicos tratantes y
laboratorios de los últimos meses, para que el panel, la comparativa y la
notificación de Teams tengan algo que mostrar. Nunca pisa datos existentes.
"""
from __future__ import annotations

from datetime import date, timedelta

import models
from services.medicos import asegurar_medicos, iniciales_medico

MEDICOS_DEMO = ["Dra. Valeria Montoya", "Dr. Camilo Restrepo", "Dra. Natalia Ospina", "Dr. Andrés Villegas"]

# tipo -> (base, amplitud de variación): valores plausibles; algunos pacientes salen de rango
PERFIL = {
    "Hb": (10.8, 2.6), "Ferritina": (420, 520), "PTH": (380, 650), "K": (5.0, 1.6), "P": (4.6, 3.0),
}


def sembrar_clinico_demo(db) -> dict:
    res = {"medicos": 0, "labs": 0}
    pacs = db.query(models.Paciente).order_by(models.Paciente.id).all()
    if not pacs:
        return res
    if not any(p.medico for p in pacs):
        for i, p in enumerate(pacs):
            p.medico = MEDICOS_DEMO[(p.estacion - 1 + (i // 16)) % len(MEDICOS_DEMO)]
        db.flush()
        res["medicos"] = len(MEDICOS_DEMO)
    if not db.query(models.Medico).count():
        asegurar_medicos(db)
        for m in db.query(models.Medico).all():
            m.iniciales = m.iniciales or iniciales_medico(m.nombre)
    if db.query(models.Laboratorio).count() == 0:
        hoy = date.today()
        tomas = [(hoy.replace(day=1) - timedelta(days=30 * k)).replace(day=10) for k in (3, 2, 1, 0)]
        for p in pacs:
            for j, (tipo, (base, amp)) in enumerate(PERFIL.items()):
                for k, f in enumerate(tomas):
                    # determinista por paciente/analito/toma, sin aleatoriedad
                    u = ((p.id * 31 + j * 17 + k * 7) % 100) / 100.0
                    valor = round(base + (u - 0.5) * amp, 1)
                    db.add(models.Laboratorio(paciente_id=p.id, fecha=f.isoformat(), tipo=tipo, valor=valor,
                                              unidad=""))
                    res["labs"] += 1
    db.commit()
    return res
