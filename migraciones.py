"""
Migraciones aditivas e idempotentes (SQLite y PostgreSQL).

Se ejecuta en cada arranque (main.py) y también desde ``python migrate.py``.
Solo AGREGA columnas que falten y convierte valores antiguos; nunca borra datos.

Cambios de esta entrega:
  R1  pacientes.acceso_estado / acceso_calibre / acceso_sitio y conversión de los
      valores antiguos de ``acceso``:
        F16     -> FAV, estado limpia, calibre 16
        F17     -> FAV, estado limpia, calibre 17
        FAV_L   -> FAV, estado limpia,        calibre vacío
        FAV_AR  -> FAV, estado alto_riesgo,   calibre vacío
        FAV_ANE -> FAV, estado aneurismatica, calibre vacío (conserva acceso_cm)
        CY      -> CY,  sitio yugular (solo la primera vez, al crear la columna)
  R3  registros.pa_pie_sistolica / pa_pie_diastolica / fc
  R4  pacientes.heparina_ui_kg (heparina UI/kg, 10-20)
  R10 pacientes.motivo_inactivo / motivo_inactivo_texto
  R2/R7 tabla asignaciones_dia (cambios de un día) y registros.estacion / cama
      (ubicación de cada sesión). Al crear esas columnas se rellenan los registros
      existentes con la ubicación base actual del paciente, así las hojas pasadas
      se ven igual que antes.
  R5/R6 pacientes.adicional / citrato / heparina_sodica, registros.adicional y
      tablas insumos_config, pedido_insumos, pedido_insumos_items (pedido de insumos).

Es la ÚNICA ruta de migración de esquema: main.py (arranque) y migrate.py
llaman a ``aplicar``; no hay que duplicar ALTER TABLE en otros módulos.
"""
from __future__ import annotations

from sqlalchemy import inspect, text

import models

# (tabla, columna, tipo SQL portable)
COLUMNAS_NUEVAS = [
    ("pacientes", "acceso_estado", "VARCHAR(20)"),
    ("pacientes", "acceso_calibre", "INTEGER"),
    ("pacientes", "acceso_sitio", "VARCHAR(20)"),
    ("pacientes", "heparina_ui_kg", "INTEGER"),
    ("pacientes", "motivo_inactivo", "VARCHAR(20)"),
    ("pacientes", "motivo_inactivo_texto", "VARCHAR(200)"),
    ("registros", "pa_pie_sistolica", "INTEGER"),
    ("registros", "pa_pie_diastolica", "INTEGER"),
    ("registros", "fc", "INTEGER"),
    ("registros", "estacion", "INTEGER"),
    ("registros", "cama", "INTEGER"),
    # R5/R6 pedido de insumos
    ("pacientes", "adicional", "BOOLEAN"),
    ("pacientes", "citrato", "BOOLEAN"),
    ("pacientes", "heparina_sodica", "BOOLEAN"),
    ("registros", "adicional", "BOOLEAN"),
]

# R5/R6: tablas nuevas (orden: la de items depende de pedido_insumos)
TABLAS_NUEVAS = ("insumos_config", "pedido_insumos", "pedido_insumos_items")

# valor antiguo de pacientes.acceso -> (acceso nuevo, estado, calibre)
CONVERSION_ACCESO = {
    "F16":     ("FAV", "limpia", 16),
    "F17":     ("FAV", "limpia", 17),
    "FAV_L":   ("FAV", "limpia", None),
    "FAV_AR":  ("FAV", "alto_riesgo", None),
    "FAV_ANE": ("FAV", "aneurismatica", None),
}


def aplicar(engine) -> list[str]:
    """Aplica las migraciones pendientes. Devuelve la lista de acciones realizadas."""
    insp = inspect(engine)
    tablas = set(insp.get_table_names())
    hechas: list[str] = []

    # R2/R7: tabla nueva (depende de «pacientes» por clave foránea)
    if "pacientes" in tablas and "asignaciones_dia" not in tablas:
        models.AsignacionDia.__table__.create(bind=engine, checkfirst=True)
        hechas.append("+tabla asignaciones_dia")

    for nombre in TABLAS_NUEVAS:
        if "pacientes" in tablas and nombre not in tablas:
            models.Base.metadata.tables[nombre].create(bind=engine, checkfirst=True)
            hechas.append(f"+tabla {nombre}")

    with engine.begin() as con:
        agregadas: set[tuple[str, str]] = set()
        for tabla, col, tipo in COLUMNAS_NUEVAS:
            if tabla not in tablas:
                continue
            existentes = {c["name"] for c in inspect(con).get_columns(tabla)}
            if col not in existentes:
                con.execute(text(f'ALTER TABLE {tabla} ADD COLUMN {col} {tipo}'))
                agregadas.add((tabla, col))
                hechas.append(f"+{tabla}.{col}")

        if {("registros", "estacion"), ("registros", "cama")} & agregadas and "pacientes" in tablas:
            cols_pac = {c["name"] for c in inspect(con).get_columns("pacientes")}
            if {"estacion", "cama"} <= cols_pac:
                r = con.execute(text(
                    "UPDATE registros SET "
                    "estacion = (SELECT p.estacion FROM pacientes p WHERE p.id = registros.paciente_id), "
                    "cama = (SELECT p.cama FROM pacientes p WHERE p.id = registros.paciente_id) "
                    "WHERE estacion IS NULL"))
                if r.rowcount:
                    hechas.append(f"registros: ubicación base fijada ({r.rowcount})")

        cols_pac = ({c["name"] for c in inspect(con).get_columns("pacientes")}
                    if "pacientes" in tablas else set())
        if "acceso" in cols_pac:   # BD muy antigua (antes de v3) sin columna acceso: nada que convertir
            for viejo, (nuevo, estado, calibre) in CONVERSION_ACCESO.items():
                r = con.execute(
                    text("UPDATE pacientes SET acceso = :nuevo, acceso_estado = :estado, "
                         "acceso_calibre = :calibre WHERE acceso = :viejo"),
                    {"nuevo": nuevo, "estado": estado, "calibre": calibre, "viejo": viejo},
                )
                if r.rowcount:
                    hechas.append(f"acceso {viejo} -> {nuevo}/{estado}/{calibre} ({r.rowcount})")
            if ("pacientes", "acceso_sitio") in agregadas:
                r = con.execute(text("UPDATE pacientes SET acceso_sitio = 'yugular' WHERE acceso = 'CY'"))
                if r.rowcount:
                    hechas.append(f"acceso CY -> yugular ({r.rowcount})")
    return hechas
