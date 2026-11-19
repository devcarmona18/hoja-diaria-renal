# EPO / Hierro del mes — auto-programación (R14)

Pantalla **«EPO / Fe del mes»** del menú de inicio. Reemplaza la antigua «Auto-programación EPO/FE», que repartía las dosis sin las reglas de la unidad y además fijaba la lista de pacientes de **todos** los días del mes (así un paciente nuevo no aparecía en la hoja).

## Qué se ve

- Una fila por paciente **activo** con días de diálisis (LMV o MJS/TJS): nombre, casillas **EPO del mes** (jeringas de 4.000 UI) y **Fe del mes** (dosis), **iniciales del nefrólogo** (tabla de médicos) y una columna por cada día del mes (lunes a sábado; el domingo no existe).
- Cada sesión del paciente muestra **4.000** (1 jeringa), **8.000** (2 jeringas) y/o **Fe**. Las columnas rayadas son los **días de laboratorio**. **NA** = no asistió (su dosis se reprogramó). **H** = hospitalizado (su dosis se canceló; se recupera al volver). Borde morado = ajuste manual; raya naranja = recibe una dosis reprogramada.
- Fila final: total de jeringas y de hierros de la unidad por día.
- Botones (solo administrador): Generar, + Pacientes nuevos, Recalcular, Regenerar mes, Días de laboratorio y Borrar mes (solo un mes ya terminado). Imprimir (A4 horizontal) y CSV para todos. El usuario demo solo mira.

## Datos de partida

Al **generar** un mes se toman los pacientes activos (no inactivos ni archivados) con días LMV/MJS:

- **EPO del mes** = `EPO mensual (UI) de la ficha ÷ 4.000`, redondeado, con **tope de 24 jeringas** y de **2 × sesiones** del paciente en el mes (si la ficha pide más se limita y queda en la bitácora).
- **Fe del mes** = `Fe mensual` de la ficha.

Se pueden cambiar en la grilla solo para ese mes (la ficha del paciente no cambia). Al cambiarlas se reparte de nuevo ese paciente. La EPO del mes se valida: **máximo 24 jeringas** y **máximo 2 por sesión del paciente** ese mes (p. ej. con 8 sesiones, 16); si no, se responde con un mensaje claro en español.

**Tope confirmado por la unidad: máximo 2 jeringas (8.000 UI) por sesión de diálisis**, en el reparto, en los ajustes, en la hoja diaria (selector: —, 4.000 u 8.000) y en las reprogramaciones.

**Sesiones del paciente** = los días del mes de su grupo (LMV = lunes, miércoles, viernes; MJS = martes, jueves, sábado), sin domingos y sin los días en que estuvo **inactivo o archivado** (periodos de inactividad de R10/R13).

## Días de laboratorio

Regla por defecto: el **segundo miércoles del mes** (siempre cae entre el 8 y el 14, la «segunda semana» si la semana 1 son los días 1-7) y el **jueves de esa misma semana** (LMV se toma muestras el miércoles, MJS el jueves). Ejemplos: diciembre 2026 → 9 y 10; octubre 2026 → 14 y 15.

Se puede cambiar por mes con «Días de laboratorio» (o dejar el mes sin días). Esos días **no se programa nada** salvo que la dosis no quepa en las demás sesiones.

## Reparto de EPO (por paciente)

`E` = jeringas del mes, `N` = sesiones del paciente que no son de laboratorio.

1. **E ≤ N**: E sesiones con 1 jeringa en posiciones **uniformes y centradas**: la i-ésima va en la sesión `⌊(2i+1)·N / 2E⌋`. Ej.: 4 jeringas en 12 sesiones → sesiones 2.ª, 5.ª, 8.ª y 11.ª (cada 3). Así no quedan juntas, ni todas al final, ni pegadas al mes siguiente.
2. **N < E ≤ 2N**: todas las sesiones llevan 1 y las `E − N` que sobran convierten sesiones en **2 jeringas (8.000 UI)**, también repartidas de forma uniforme. Ej.: 14 jeringas en 13 sesiones → 12 de 4.000 y 1 de 8.000 si no hay laboratorio; con laboratorio (12 sesiones normales) → 2 de 8.000 separadas medio mes.
3. **E > 2N** (inevitable): 2 en cada sesión normal y el resto en los días de laboratorio (máx. 2). Nunca más de 2 por sesión: si aún sobra, no se programa y la grilla avisa «EPO programada x de y» (raro, porque la EPO del mes ya se valida).

**Regla elegida para el laboratorio en EPO**: primero se dobla una sesión normal (8.000 UI) antes que poner EPO el día de laboratorio, porque la regla dice «esos días no se programa nada». El total del mes siempre se entrega.

## Reparto de hierro (toda la unidad a la vez) — «opción B» (confirmada)

El hierro se reparte para **todos los pacientes juntos**, lo **más parejo posible en el mes**, dando prioridad a que la **carga diaria de la unidad** quede equilibrada.

Para cada paciente con `F` dosis:

1. **Un poco más de la mitad antes del laboratorio**: al menos `⌈F/2⌉` dosis en las sesiones anteriores al primer día de laboratorio (si no hay tantas, las que haya). F=1 → la única dosis va antes si se puede; F=2 → 1 antes; F=3 → 2; F=4 → 2; F=5 → 3. Las demás van **donde el reparto parejo y la carga lo indiquen** (antes o después).
2. **Espaciado**: las sesiones normales del mes se parten en `F` **bloques seguidos** (igual tamaño ±1) y cada dosis va en su propio bloque. Si ese reparto no deja `⌈F/2⌉` bloques antes del laboratorio, se usan `⌈F/2⌉` bloques antes y el resto después.
3. **Carga de la unidad**: dentro del bloque se escoge el día con **menos hierros en toda la unidad**. Empates: que no quede pegada a otra dosis del mismo paciente, la más cercana al centro del bloque, la más temprana.
4. **Orden**: primero los pacientes más «apretados» (más dosis por sesión disponible), luego los de más dosis, luego por número de paciente.
5. **Mejora final**: se mueve una dosis, dentro de su bloque ampliado medio bloque a cada lado, desde un día cargado a otro con al menos 2 hierros menos, sin pegarla a otra dosis del paciente y sin bajar del mínimo antes del laboratorio; se repite hasta que no haya mejora.
6. **Días de laboratorio**: solo si `F` es mayor que las sesiones normales del paciente (inevitable; la grilla lo avisa). Máximo 1 dosis de hierro por sesión.

Es **determinista**: los mismos datos dan siempre la misma programación.

**Carga resultante** (prueba con 40 pacientes ficticios en diciembre de 2026, 20 LMV y 20 MJS con 1, 2, 3 y 4 dosis; laboratorio 9 y 10):

| | Antes del laboratorio (1-8 dic, 7 días) | Después (11-31 dic, 18 días) |
|---|---|---|
| Regla anterior `⌊F/2⌋+1` | 80 dosis · máx. 15 / mín. 10 por día | 20 dosis · máx. 2 / mín. 1 |
| Opción B `⌈F/2⌉` | 60 dosis · máx. 10 / mín. 7 por día | 40 dosis · máx. 3 / mín. 2 |

Las 60 dosis antes del laboratorio son exactamente el mínimo exigido (`Σ⌈F/2⌉`); como antes del laboratorio solo hay 3-4 sesiones por paciente, esos días siguen más cargados que el resto del mes, pero el máximo diario baja de 15 a 10.

## Ajustes manuales

- Clic en una sesión (administrador): se fija la EPO (0-2 jeringas) y el hierro de ese día. Queda **fijo** (borde morado): «Recalcular», cambiar totales o los días de laboratorio no lo tocan. Las demás sesiones automáticas del paciente se reparten de nuevo para **mantener el total del mes**.
- «Volver a automático» quita el ajuste de esa sesión.
- **Regenerar mes** rehace todo con los totales guardados y **borra los ajustes manuales** (pide confirmación).
- Los días **ya cerrados** (hoja cerrada) nunca se cambian: lo que pasó, pasó.

## Llenado automático de la hoja diaria

Al abrir la hoja de un día, cada fila trae su **EPO (4.000 / 8.000 UI)** y su **Fe** desde esta programación; no hay que marcarlos. Si la programación cambia (ajuste, reprogramación), las hojas **abiertas** se actualizan solas.

El personal puede cambiar la EPO o el Fe de una fila; desde ese momento esa fila queda «cambiada a mano» y la programación ya no la sobrescribe. Si un mes no tiene programación, la hoja usa como antes las casillas de «Programar próxima».

En la base de datos la fila guarda `registros.epo_jeringas` (jeringas de 4.000 UI) y el antiguo `registros.epo` (sí/no) se mantiene coherente. Las filas antiguas (sin número de jeringas) se siguen contando como antes en Historial y Estadísticas: una aplicación con la dosis por aplicación de la ficha o, si falta, 4.000 UI.

## Inasistencias: reprogramación

Se considera que el paciente **no asistió** (falta, «NA») un día cuando su hoja de ese día está **cerrada** y su fila no tiene asistencia **A** ni **peso de entrada** (la misma regla del pedido de insumos: `hoja_dia.llego` / `hoja_dia.falto`), o cuando su hoja habitual de ese día se cerró y él no aparece en ninguna hoja de ese día. Los días en que estaba inactivo/archivado no cuentan como falta. Si fue reemplazado por un suplente, la falta es de él; el suplente asiste según su propia marca.

Se hace **solo al cerrar la hoja** (y al reabrirla), y también con el botón **Recalcular**:

- **EPO**: la EPO de ese día pasa a la **siguiente sesión** del paciente que siga abierta (saltando un día de laboratorio si hay otra después), **sin pasar nunca de 2 jeringas (8.000 UI)**: si esa tenía 1 jeringa queda con 2 y lo que exceda sigue a las sesiones siguientes (máx. 2 cada una).
- **Hierro**: la dosis pasa a una sesión futura abierta del paciente que **no tenga hierro**: primero las que no son de laboratorio, luego el día con menos hierros en la unidad, luego la más cercana.
- Si ya no queda ninguna sesión en el mes, la dosis queda **«pendiente sin sesión»** (aviso en la fila y en la bitácora).
- Si después se corrige la asistencia (sí vino) y se vuelve a cerrar, la reprogramación **se deshace**.

Cada cosa queda en la **bitácora** del mes (quién, cuándo, de qué día a cuál).

## Hospitalizado (H): se cancela y se recupera al volver

Si la hoja cerrada de un día tiene al paciente con asistencia **H** (hospitalizado), la EPO y el hierro de ese día **se cancelan**: no pasan a la sesión siguiente (a diferencia de una falta NA, F u hoja sin su fila, que se arrastran como arriba).

Cuando el paciente **vuelve** (primera sesión cerrada a la que asiste después de la hospitalización), el sistema **recupera lo cancelado del mes** en las sesiones abiertas que quedan después de ese día: repartido parejo, con el tope de 2 jeringas por sesión, 1 hierro por sesión y evitando el laboratorio salvo que no haya otra. Lo que no quepa en el mes se avisa («No se pudo recuperar en el mes»). Mientras siga hospitalizado la fila avisa «Hospitalizado: … cancelada(s); se recupera al volver». Si se corrige la asistencia (H → NA o A) y se vuelve a cerrar, se aplica la regla nueva.

En la base de datos, `epo_fe_movimientos.motivo` distingue `falta` (arrastre) de `hosp` (cancelada / recuperada; destino vacío = aún no se recupera).

## Mes cerrado (R12)

Con el mes cerrado en Estadísticas, su programación es de **solo lectura**: generar, agregar pacientes nuevos, regenerar, recalcular, cambiar totales o celdas, días de laboratorio y borrar responden **409** («El mes está cerrado; reábralo para editar») y la pantalla muestra el candado sin botones. El recálculo que dispara el cierre o la reapertura de un día nunca modifica un mes cerrado, y las hojas de ese mes no se rellenan. Al reabrir el mes (administrador + motivo) todo vuelve a funcionar.

Solo entran a la programación los pacientes **activos y no archivados** (`consulta_activos`); si alguno se archiva o inactiva después, sus días desde entonces cuentan como inactivos.

## Borrar el mes

Un mes que ya terminó se puede borrar (administrador). Se borran solo las tablas de programación; las hojas diarias, el historial y las estadísticas **no se tocan**. La bitácora conserva la anotación del borrado.

## Reglas confirmadas por la unidad

1. Tope de EPO: **2 jeringas (8.000 UI) por sesión** y, por lo tanto, **24 jeringas al mes** como máximo.
2. Hierro «opción B»: lo más parejo posible, priorizando la carga diaria; antes del laboratorio solo «un poco más de la mitad» = `⌈F/2⌉`.
3. Hospitalizado (H): la dosis se cancela y al volver se recupera lo que quepa en el mes.

## Supuestos pendientes de confirmar

1. «Segunda semana» = la del **segundo miércoles** (día 8-14) y el jueves siguiente. Se puede cambiar por mes.
2. EPO: antes de usar un día de laboratorio se pone una sesión de 8.000 UI.
3. La EPO o el hierro que no alcanzan a reprogramarse en el mes no pasan al mes siguiente (quedan avisados).
4. Un paciente reemplazado por un suplente sin marca H cuenta como falta (se arrastra).

## Código

- `services/epo_fe_algoritmo.py` — algoritmo puro (sin base de datos).
- `services/epo_fe.py` — guardar, ajustes, reprogramación, llenado de la hoja, grilla y CSV.
- `routers/epo_fe.py` — API `/api/epo-fe/{AAAA-MM}`.
- `static/js/epo_fe.js`, `static/css/epo_fe.css` — pantalla.
- Pruebas: `tests/test_r14_algoritmo.py`, `tests/test_r14_epo_fe.py`.
