"""
Migración v3: añade campos clínicos a pacientes y registros.
Ejecutar UNA sola vez: python migrate.py
"""
import sqlite3, os

DB_PATH = os.path.join(os.path.dirname(__file__), "renal.db")

MIGRACIONES = [
    # v3 — Paciente: campos clínicos
    "ALTER TABLE pacientes ADD COLUMN acceso TEXT",
    "ALTER TABLE pacientes ADD COLUMN acceso_cm INTEGER",
    "ALTER TABLE pacientes ADD COLUMN heparina_unidades INTEGER",
    "ALTER TABLE pacientes ADD COLUMN tipo_filtro TEXT",
    "ALTER TABLE pacientes ADD COLUMN watson REAL",
    "ALTER TABLE pacientes ADD COLUMN medico TEXT",
    # v3 — Registro: KtV, catéter, transitorio
    "ALTER TABLE registros ADD COLUMN ktv REAL",
    "ALTER TABLE registros ADD COLUMN citrato INTEGER DEFAULT 0",
    "ALTER TABLE registros ADD COLUMN heparina_sodica INTEGER DEFAULT 0",
    "ALTER TABLE registros ADD COLUMN transitorio_nombre TEXT",
    # v4 — Paciente: programación EPO/Fe mensual
    "ALTER TABLE pacientes ADD COLUMN dias TEXT",            # LMV | TJS
    "ALTER TABLE pacientes ADD COLUMN epo_mensual REAL",    # UI totales al mes
    "ALTER TABLE pacientes ADD COLUMN epo_dosis REAL",      # UI por aplicación
    "ALTER TABLE pacientes ADD COLUMN hierro_mensual INTEGER",  # Nº aplic. Fe/mes
]

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
aplicadas = 0
for sql in MIGRACIONES:
    try:
        cur.execute(sql)
        aplicadas += 1
        print(f"OK  : {sql[:70]}")
    except sqlite3.OperationalError as e:
        if "duplicate column" in str(e).lower():
            print(f"Skip: {sql[:70]}  [ya existe]")
        else:
            print(f"ERR : {e}")
con.commit()
con.close()
print(f"\nMigracion lista. {aplicadas} columna(s) nueva(s) agregada(s).")
