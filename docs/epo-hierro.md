# EPO / Hierro del mes — auto-programación (R14)

Pantalla **«EPO / Fe del mes»** del menú de inicio. Reemplaza la antigua «Auto-programación EPO/FE», que repartía las dosis sin las reglas de la unidad y además fijaba la lista de pacientes de **todos** los días del mes (así un paciente nuevo no aparecía en la hoja).

## Qué se ve

- Una fila por paciente **activo** con días de diálisis (LMV o MJS/TJS): nombre, casillas **EPO del mes** (jeringas de 4.000 UI) y **Fe del mes** (dosis), **iniciales del nefrólogo** (tabla de médicos) y una columna por cada día del mes (lunes a sábado; el domingo no existe).
- Cada sesión del paciente muestra **4.000** (1 jeringa), **8.000** (2 jeringas) y/o **Fe**. Las columnas rayadas son los **días de laboratorio**. **NA** = no asistió (su dosis se reprogramó). Borde morado = ajuste manual; raya naranja = recibe una dosis reprogramada.
- Fila final: total de jeringas y de hierros de la unidad por día.
- Botones (solo administrador): Generar, + Pacientes nuevos, Recalcular, Regenerar mes, Días de laboratorio y Borrar mes (solo un mes ya terminado). Imprimir (A4 horizontal) y CSV para todos. El usuario demo solo mira.

## Datos de partida

Al **generar** un mes se toman los pacientes activos (no inactivos ni archivados) con días LMV/MJS:

- **EPO del mes** = `EPO mensual (UI) de la ficha ÷ 4.000`, redondeado.
- **Fe del mes** = `Fe mensual` de la ficha.

Se pueden cambiar en la grilla solo para ese mes (la ficha del paciente no cambia). Al cambiarlas se reparte de nuevo ese paciente.

**Sesiones del paciente** = los días del mes de su grupo (LMV = lunes, miércoles, viernes; MJS = martes, jueves, sábado), sin domingos y sin los días en que estuvo **inactivo o archivado** (periodos de inactividad de R10/R13).

## Días de laboratorio

Regla por defecto: el **segundo miércoles del mes** (siempre cae entre el 8 y el 14, la «segunda semana» si la semana 1 son los días 1-7) y el **jueves de esa misma semana** (LMV se toma muestras el miércoles, MJS el jueves). Ejemplos: diciembre 2026 → 9 y 10; octubre 2026 → 14 y 15.

Se puede cambiar por mes con «Días de laboratorio» (o dejar el mes sin días). Esos días **no se programa nada** salvo que la dosis no quepa en las demás sesiones.

## Reparto de EPO (por paciente)

`E` = jeringas del mes, `N` = sesiones del paciente que no son de laboratorio.

1. **E ≤ N**: E sesiones con 1 jeringa en posiciones **uniformes y centradas**: la i-ésima va en la sesión `⌊(2i+1)·N / 2E⌋`. Ej.: 4 jeringas en 12 sesiones → sesiones 2.ª, 5.ª, 8.ª y 11.ª (cada 3). Así no quedan juntas, ni todas al final, ni pegadas al mes siguiente.
2. **N < E ≤ 2N**: todas las sesiones llevan 1 y las `E − N` que sobran convierten sesiones en **2 jeringas (8.000 UI)**, también repartidas de forma uniforme. Ej.: 14 jeringas en 13 sesiones → 12 de 4.000 y 1 de 8.000 si no hay laboratorio; con laboratorio (12 sesiones normales) → 2 de 8.000 separadas medio mes.
3. **E > 2N** (inevitable): 2 en cada sesión normal, el resto en los días de laboratorio (máx. 2) y, si aún sobra, reparto parejo en todas.

**Regla elegida para el laboratorio en EPO**: primero se dobla una sesión normal (8.000 UI) antes que poner EPO el día de laboratorio, porque la regla dice «esos días no se programa nada». El total del mes siempre se entrega.

## Reparto de hierro (toda la unidad a la vez)

El hierro se reparte para **todos los pacientes juntos**, para que ningún día se cargue de hierros.

Para cada paciente con `F` dosis:

1. **Mayoría antes del laboratorio**: `⌊F/2⌋ + 1` dosis en las sesiones anteriores al primer día de laboratorio (si no hay tantas, las que haya); el resto después. Si después no caben, se pasan antes. Ej.: F=4 → 3 antes y 1 después; F=1 → antes; F=2 → las 2 antes.
2. **Espaciado**: dentro de cada tramo (antes / después) las sesiones se parten en tantos **bloques seguidos** como dosis (de igual tamaño ±1) y cada dosis va en su propio bloque. Nunca quedan dos dosis en el mismo bloque.
3. **Carga de la unidad**: dentro del bloque se escoge la sesión del día con **menos hierros en toda la unidad**. Empates: que no quede pegada a otra dosis del mismo paciente, la más cercana al centro del bloque, la más temprana.
4. **Orden**: primero los pacientes más «apretados» (más dosis por sesión disponible), luego los de más dosis, luego por número de paciente. Así los que no tienen dónde escoger se ubican primero.
5. **Mejora final**: se revisa toda la unidad y se mueve una dosis, dentro de su mismo bloque, desde un día cargado a otro con al menos 2 hierros menos; se repite hasta que no haya mejora. Esto baja el máximo diario sin romper el espaciado ni la regla del laboratorio.
6. **Días de laboratorio**: solo si `F` es mayor que las sesiones normales del paciente, y solo las dosis que sobran (inevitable; la grilla lo avisa). Máximo 1 dosis de hierro por sesión: si `F` supera las sesiones, lo que sobra se avisa como «Fe programado x de y».

Es **determinista**: los mismos datos dan siempre la misma programación (no hay azar), así se puede revisar y defender.

Con 60 pacientes LMV de 2 dosis sin laboratorio la carga queda en 9-10 hierros por día (el mínimo posible es ⌈120/13⌉ = 10). Hay que tener presente que la regla «mayoría antes del laboratorio» concentra el hierro en los primeros días del mes (solo hay 3-5 sesiones antes del laboratorio): el algoritmo los reparte de forma pareja **entre esos días**, pero no puede llevarlos después sin romper esa regla.

## Ajustes manuales

- Clic en una sesión (administrador): se fija la EPO (0-3 jeringas) y el hierro de ese día. Queda **fijo** (borde morado): «Recalcular», cambiar totales o los días de laboratorio no lo tocan. Las demás sesiones automáticas del paciente se reparten de nuevo para **mantener el total del mes**.
- «Volver a automático» quita el ajuste de esa sesión.
- **Regenerar mes** rehace todo con los totales guardados y **borra los ajustes manuales** (pide confirmación).
- Los días **ya cerrados** (hoja cerrada) nunca se cambian: lo que pasó, pasó.

## Llenado automático de la hoja diaria

Al abrir la hoja de un día, cada fila trae su **EPO (4.000 / 8.000 UI)** y su **Fe** desde esta programación; no hay que marcarlos. Si la programación cambia (ajuste, reprogramación), las hojas **abiertas** se actualizan solas.

El personal puede cambiar la EPO o el Fe de una fila; desde ese momento esa fila queda «cambiada a mano» y la programación ya no la sobrescribe. Si un mes no tiene programación, la hoja usa como antes las casillas de «Programar próxima».

En la base de datos la fila guarda `registros.epo_jeringas` (jeringas de 4.000 UI) y el antiguo `registros.epo` (sí/no) se mantiene coherente. Las filas antiguas (sin número de jeringas) se siguen contando como antes en Historial y Estadísticas: una aplicación con la dosis por aplicación de la ficha o, si falta, 4.000 UI.

## Inasistencias: reprogramación

Se considera que el paciente **no asistió** un día cuando su hoja de ese día está **cerrada** y su fila no tiene asistencia **A** ni **peso de entrada** (la misma regla del pedido de insumos), o cuando su hoja habitual de ese día se cerró y él no aparece en ninguna hoja de ese día. Los días en que estaba inactivo/archivado no cuentan como falta. Si fue reemplazado por un suplente, la falta es de él; el suplente asiste según su propia marca.

Se hace **solo al cerrar la hoja** (y al reabrirla), y también con el botón **Recalcular**:

- **EPO**: toda la EPO de ese día pasa a la **siguiente sesión** del paciente que siga abierta (saltando un día de laboratorio si hay otra después). Si esa tenía 1 jeringa, queda con 2 (8.000 UI). Si vuelve a faltar, se sigue acumulando y la grilla avisa cuando pasa de 2 jeringas.
- **Hierro**: la dosis pasa a una sesión futura abierta del paciente que **no tenga hierro**: primero las que no son de laboratorio, luego el día con menos hierros en la unidad, luego la más cercana.
- Si ya no queda ninguna sesión en el mes, la dosis queda **«pendiente sin sesión»** (aviso en la fila y en la bitácora).
- Si después se corrige la asistencia (sí vino) y se vuelve a cerrar, la reprogramación **se deshace**.

Cada cosa queda en la **bitácora** del mes (quién, cuándo, de qué día a cuál).

## Borrar el mes

Un mes que ya terminó se puede borrar (administrador). Se borran solo las tablas de programación; las hojas diarias, el historial y las estadísticas **no se tocan**. La bitácora conserva la anotación del borrado.

## Para confirmar con la unidad (supuestos)

1. «Segunda semana» = la del **segundo miércoles** (día 8-14) y el jueves siguiente. Se puede cambiar por mes.
2. EPO: antes de usar un día de laboratorio se pone una sesión de 8.000 UI.
3. «Mayoría antes del laboratorio» = `⌊F/2⌋ + 1` dosis de cada paciente.
4. No hay tope para la EPO acumulada por faltas (se avisa desde 3 jeringas = 12.000 UI).
5. La EPO o el hierro que no alcanzan a reprogramarse en el mes no pasan al mes siguiente (quedan avisados).
6. EPO del mes por defecto = EPO mensual de la ficha ÷ 4.000.

## Código

- `services/epo_fe_algoritmo.py` — algoritmo puro (sin base de datos).
- `services/epo_fe.py` — guardar, ajustes, reprogramación, llenado de la hoja, grilla y CSV.
- `routers/epo_fe.py` — API `/api/epo-fe/{AAAA-MM}`.
- `static/js/epo_fe.js`, `static/css/epo_fe.css` — pantalla.
- Pruebas: `tests/test_r14_algoritmo.py`, `tests/test_r14_epo_fe.py`.
