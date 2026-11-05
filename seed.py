"""
Pobla la BD con 144 pacientes ficticios.
Ejecutar: python seed.py
TODOS los datos son inventados; no corresponden a personas reales.
"""
import sys
from database import engine, SessionLocal
import models

models.Base.metadata.create_all(bind=engine)

PRIMEROS_F = [
    "María", "Ana", "Carmen", "Rosa", "Elena", "Isabel",
    "Laura", "Sofía", "Marta", "Lucía", "Patricia", "Sandra",
    "Gloria", "Beatriz", "Fernanda", "Diana", "Yolanda", "Gabriela",
    "Alejandra", "Teresa", "Claudia", "Rebeca", "Vanessa", "Marlene",
]
PRIMEROS_M = [
    "Carlos", "José", "Miguel", "Luis", "Pedro", "Juan",
    "Antonio", "Roberto", "Francisco", "Eduardo", "Andrés", "Rafael",
    "Javier", "Sergio", "Héctor", "Diego", "Pablo", "Ramón",
    "Manuel", "Óscar", "Simón", "Víctor", "Emilio", "Jorge",
]
APELLIDOS = [
    "García", "López", "Martínez", "Rodríguez", "González", "Hernández",
    "Pérez", "Sánchez", "Torres", "Ramírez", "Flores", "Cruz",
    "Morales", "Reyes", "Jiménez", "Castro", "Vásquez", "Romero",
    "Vargas", "Ramos", "Silva", "Medina", "Ruiz", "Molina",
]

PESOS_SECOS = [
    45.5, 48.0, 51.5, 53.0, 55.5, 57.0, 59.5, 61.0, 63.0, 64.5,
    66.0, 68.0, 70.5, 72.0, 74.5, 76.0, 78.5, 80.0, 82.5, 85.0,
    58.0, 60.0, 62.5, 65.0, 67.5, 69.0, 71.0, 73.5, 75.0, 77.5,
    52.0, 54.5, 56.0, 57.5, 64.0, 66.5, 69.5, 71.5, 76.5, 79.0,
    48.5, 50.0, 55.0, 58.5, 61.5, 63.5, 67.0, 70.0,
]


def generar_nombre(idx: int) -> str:
    mitad = len(PRIMEROS_F)
    if idx % 2 == 0:
        primero = PRIMEROS_F[idx % len(PRIMEROS_F)]
    else:
        primero = PRIMEROS_M[idx % len(PRIMEROS_M)]
    apellido1 = APELLIDOS[idx % len(APELLIDOS)]
    apellido2 = APELLIDOS[(idx + 7) % len(APELLIDOS)]
    return f"{apellido1} {apellido2}, {primero}"


def generar_cedula(idx: int) -> str:
    base = 10_000_000 + idx * 137
    return f"V-{base:08d}"


def main():
    db = SessionLocal()
    try:
        existentes = db.query(models.Paciente).count()
        if existentes > 0:
            print(f"Ya hay {existentes} pacientes. Usa --force para repoblar.")
            if "--force" not in sys.argv:
                return

            db.query(models.Programacion).delete()
            db.query(models.Registro).delete()
            db.query(models.Sesion).delete()
            db.query(models.Paciente).delete()
            db.commit()
            print("Base de datos limpiada.")

        pacientes = []
        idx = 0
        for turno in ("M", "T", "N"):
            for estacion in (1, 2, 3):
                for cama in range(1, 17):   # camas 1–16
                    p = models.Paciente(
                        nombre=generar_nombre(idx),
                        cedula=generar_cedula(idx),
                        estacion=estacion,
                        cama=cama,
                        turno=turno,
                        peso_seco=PESOS_SECOS[idx % len(PESOS_SECOS)],
                        activo=True,
                    )
                    pacientes.append(p)
                    idx += 1

        db.add_all(pacientes)
        db.commit()
        print(f"OK: {len(pacientes)} pacientes ficticios creados correctamente.")
        print("  Turno M: 48 pacientes (Est 1-3, camas 1-16)")
        print("  Turno T: 48 pacientes (Est 1-3, camas 1-16)")
        print("  Turno N: 48 pacientes (Est 1-3, camas 1-16)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
