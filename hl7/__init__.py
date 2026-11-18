"""
Integración HL7 v2 con las máquinas de hemodiálisis AK 98 — «Próximamente».

Paquete de Python puro (solo biblioteca estándar) para que el puente local
(`hl7/puente.py`) pueda correr en un PC de la unidad sin instalar la app.

Módulos:
  - parser   : lectura de mensajes HL7 v2.x ORU^R01 (MSH, PID, OBR, OBX).
  - mapeo    : traduce las observaciones OBX a los campos de la Hoja Diaria.
  - mllp     : marco MLLP (0x0B … 0x1C 0x0D) y construcción de ACK.
  - firma    : firma HMAC-SHA256 con sello de tiempo (puente → app).

Dirección ÚNICA: máquina → app. Este paquete nunca construye mensajes que
envíen prescripciones o parámetros a las máquinas.

La funcionalidad está INACTIVA mientras HL7_ENABLED=false (ver config.py).
"""

__all__ = ["parser", "mapeo", "mllp", "firma"]
