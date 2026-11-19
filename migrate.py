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

# v6 — Integración HL7 «Próximamente»: crea SOLO las tablas nuevas hl7_* si no
# existen, en la BD de DATABASE_URL (SQLite o PostgreSQL). No altera tablas ni
# datos existentes. Es inocuo con HL7_ENABLED=false (las tablas quedan vacías).
try:
    from database import engine as _engine
    import models as _models  # noqa: F401  (registra «pacientes» para las claves foráneas)
    import models_hl7 as _models_hl7

    _models_hl7.crear_tablas(_engine)
    print("Tablas HL7 verificadas (hl7_mensaje, hl7_paciente_id, hl7_borrador_sesion, hl7_auditoria).")
except Exception as e:  # p. ej. la BD aún no tiene la tabla «pacientes»
    print(f"Tablas HL7 no creadas: {e}")


# v7 — Pulido de diciembre (R1, R3, R4, R10): columnas nuevas y conversión de los
#      tipos de acceso antiguos.
# v8 — Programación del día siguiente (R2/R7): tabla «asignaciones_dia» (cambios
#      de un día) y columnas registros.estacion/cama (ubicación de cada sesión).
# v9 — R11–R13: foto de la hoja al cerrar (registros.snapshot), asistencia mensual y
#      cierre de mes, periodos de inactividad, archivo de pacientes, médicos/Teams y
#      rangos de laboratorio.
#      R5/R6: pedido de insumos (pacientes.adicional/citrato/heparina_sodica,
#      registros.adicional, tablas insumos_config / pedido_insumos / _items).
# v10 — R14: auto-programación mensual de EPO / hierro (tablas epo_fe_* y
#      registros.epo_jeringas / epo_fe_manual).
# Todas viven en migraciones.aplicar(): una sola ruta idempotente, en SQLite y
# PostgreSQL, que la app también ejecuta sola al arrancar.
try:
    from database import engine as _engine2
    import migraciones as _migraciones

    for _accion in _migraciones.aplicar(_engine2):
        print(f"OK  : {_accion}")
    print("Migraciones v7 (acceso vascular, PA/FC, UI, estado del paciente), "
          "v8 (programación por día, insumos), v9 (historial, cierre de mes, archivo, "
          "médicos/Teams) y v10 (EPO / hierro del mes) verificadas.")
except Exception as e:
    print(f"Migraciones v7–v10 no aplicadas: {e}")
