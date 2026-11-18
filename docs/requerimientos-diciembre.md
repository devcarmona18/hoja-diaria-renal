# Requerimientos — pulido para la entrega del 1 de diciembre de 2026

Fuente: lista de cambios de David Carmona (17-nov-2026). Debajo de cada punto va su texto original resumido y la **interpretación técnica** usada para implementarlo. Lo marcado como **SUPUESTO** se confirma con David; todo lo configurable queda en tablas o JSON editables, no fijo en el código.

Reglas generales:
- Solo datos ficticios. Nunca nombres ni cédulas reales en código, pruebas, semillas ni capturas.
- El resto de la app sigue funcionando igual salvo lo que se cambia aquí. Las pruebas existentes deben seguir pasando (SQLite y PostgreSQL).
- Interfaz en español, consistente con el diseño actual (Tailwind). Rol demo = solo lectura.
- Migraciones aditivas y seguras en SQLite y PostgreSQL (`migrate.py`). No borrar datos existentes.

---

## R1. Nuevo paciente — tipos de acceso vascular
Quitar las opciones "G16 / G17" sueltas. El acceso vascular queda así:
- **Fístula (FAV)** con estado: limpia, alto riesgo, aneurismática; y **calibre de aguja**: 15, 16 o 17.
- **Catéter (CY)**: yugular o femoral.
Migrar los datos existentes (F16 → FAV limpia calibre 16, F17 → FAV limpia calibre 17, CY → CY yugular, FAV_L/FAV_AR/FAV_ANE → FAV con su estado y calibre vacío).

## R2. Programar la próxima sesión (día siguiente)
En la unidad se programa un día antes (el lunes se programan los pacientes del martes). La pantalla de programación debe funcionar **igual que la página principal**: mover pacientes entre camas/estaciones (arrastrar y soltar), reemplazos, y **buscar paciente**.

## R3. PA y FC de salida + resumen de sesiones por paciente
- En cada sesión, al lado del **peso de salida**: **PA de pie** (sistólica/diastólica, la última tomada) y **FC**.
- Un botón junto a **Observaciones** (al final de la fila) abre el **resumen del paciente**: sus sesiones de la semana/últimas sesiones (p. ej. L-M-V) con peso de entrada, peso de salida, peso seco, ganancia, pérdida, PA de pie, FC, Kt/V, observaciones.

## R4. Datos visibles del paciente en la hoja
En la fila del paciente se ven: **filtro**, **dosis de heparina**, **cédula** (ficticia en demo) y **UI**.
**Confirmado por David**: "UI" es la dosis de **heparina en unidades internacionales por kilo de peso (UI/kg)**, rango válido **10 a 20 UI/kg**. Se puede mostrar el total calculado ≈ UI/kg × peso seco.

## R5 + R6. Pedido de insumos
Nuevo apartado **"Pedido de insumos"** con todos los pacientes **activos** programados.
- El pedido se hace **un día antes**: el pedido de hoy corresponde a las sesiones programadas para **mañana**.
- Reglas por paciente (configurables en tabla/JSON):
  - **Fístula**: kit fístula, 2 agujas del calibre del paciente (15/16/17), línea, SSN 1000 mL, filtro (el del paciente).
  - **Catéter (CY)**: kit catéter, línea, SSN 1000 mL, filtro.
    - Guantes estériles 6.5: **2** si tiene citrato o heparina sódica; si no tiene ninguno y el día de la sesión es **lunes o martes**, **1**; en otro caso **0**.
    - Si el día es **lunes o martes**: apósito **IV3000**.
    - Sin citrato ni heparina sódica: **2 Tegos**. Con citrato o heparina sódica: **tapas luer-lock: 2** (normalmente 1 empaque que trae las 2; mostrar "1 empaque (2 tapas)").
  - **Confirmado**: los guantes estériles aplican **solo a CY**; las fístulas **no** llevan guantes.
- **Devoluciones**: si un paciente programado **no asistió** (asistencia ≠ A) **y no tiene peso de entrada**, sus insumos de ese día pasan a la sección **Devolución**.
- **Adicionales**: al crear/editar paciente, campo **Adicional (sí/no; vacío = no)**. Un paciente adicional que llega **hoy** carga sus insumos al **pedido actual** marcado como "Adicional", no al de mañana.
- Totales por insumo, impresión y exportación (CSV/PDF imprimible).
- Pacientes **inactivos** (R10) no cuentan.

## R7. Cambios de un día vs. cambios permanentes
Un cambio hecho al programar un día (p. ej. martes: paciente en otra silla) **solo aplica ese día**; el jueves todo vuelve a la ubicación habitual. Solo si se marca **"Cambio permanente"** se actualiza la ubicación base del paciente. Debe poder editarse/deshacerse.

## R8. Burbuja "Próximamente"
Debe verse **solo en la pantalla de inicio** (antes de entrar a la hoja) y además quedar como **apartado del menú**, igual que Historial o EPO, **en la última posición**.

## R9. NefroIA dentro de la app
Apartado **"IA"** que integra NefroIA (asistente de IA para enfermería renal) con inicio de sesión compartido. Reemplaza el módulo de IA actual (que envía el nombre del paciente al modelo). Detrás de configuración (`NEFROIA_URL`); si no está configurado, el apartado muestra "Próximamente / no configurado".

## R10. Paciente activo / inactivo
Campo **estado**: activo / inactivo (motivo: hospitalizado u otro). Los inactivos no cuentan en el pedido de insumos ni en la programación automática.

## R11. Historial de sesiones
- Ver la **hoja completa de un día cerrado**, tal como quedó (todas las filas, pesos de entrada y salida, etc.), guardada **por fecha y turno**.
- Resumen por día seleccionado: número de sesiones, total asistidos, **EPO aplicada** y **Fe aplicado** ese día (no de todos los días).

## R12. Estadísticas de asistencia (facturación)
- Por paciente y mes: **días asistidos / días que le tocaban**; la barra de % llega a 100 % si asistió a todas sus sesiones programadas del mes.
- Guardar el **registro mensual** (cierre de mes) porque con esto se factura.
- Consultar cualquier mes: cuántos asistieron, totales.

## R13. Panel clínico / laboratorios
- Filtrar pacientes por estado del resultado (bajo / normal / alto / muy alto), p. ej. Hb baja.
- Mostrar valor, estado, última muestra **y médico tratante**.
- Gráfica comparativa entre meses / tomas por paciente.
- **Notificación por Microsoft Teams** al médico correspondiente **2 veces por mes** (días configurables). SUPUESTO: vía webhook (Workflows de Teams) por médico, **apagado por defecto** (`TEAMS_ENABLED=false`) hasta que la unidad lo autorice; el mensaje usa iniciales, no nombres completos.
- **Eliminar paciente** (fallecimiento u otro) — **confirmado: archivar**. El paciente archivado deja de aparecer en listas, hoja, programación y pedidos. **A los 2 meses de archivado desaparece automáticamente también de la lista de Archivados** (purga automática del listado). Por la obligación legal de conservar los registros clínicos y de facturación, sus sesiones, laboratorios e historial **no se borran**: siguen consultables en Historial/Estadísticas. El plazo es configurable (`ARCHIVO_DIAS=60`).

## R14. Auto-programación EPO / Hierro
Vista mensual por paciente: **nombre**, dos casillas pequeñas **EPO del mes** y **Fe del mes**, **iniciales del nefrólogo**, y a la derecha **columnas con los días del mes** en que el paciente asiste (según sus días de diálisis).
- **1 jeringa de EPO = 4.000 UI.**
- EPO: repartir las jeringas del mes **uniformemente** entre las sesiones del mes. Si hay más jeringas que sesiones (p. ej. 14 EPO y 13 sesiones), se ponen **2 jeringas (8.000 UI)** en algunas sesiones, repartidas.
- Hierro: repartir uniformemente con reglas:
  - Balancear la **carga diaria de la unidad** (no concentrar muchos hierros el mismo día).
  - La **mayoría antes del día de laboratorio**. Día de laboratorio: **miércoles y jueves de la segunda semana** del mes (configurable). Esos días **no** se programa nada salvo que sea inevitable por la dosis.
- La programación **llena automáticamente** la EPO y el Fe de la hoja diaria (sin marcarlos a mano).
- **Inasistencia**: si un paciente con EPO programada no asiste, se **reprograma**: la siguiente sesión lleva su EPO + la perdida (p. ej. 2). Si es **hierro**, se pasa a una sesión futura que **no** tenga hierro.
- Se ve todo el mes; al terminar el mes puede borrarse.

## R15. Otras automatizaciones
Ver propuestas en la respuesta del chat (no se implementan sin aprobación).
