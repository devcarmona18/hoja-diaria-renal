# Pedido de insumos (R5 / R6)

Menú **Pedido de insumos**. El pedido se hace **un día antes**: el pedido de hoy cubre las sesiones del **próximo día de diálisis** (se salta el domingo: el sábado se pide para el lunes). La fecha del pedido se puede cambiar en la pantalla.

## Secciones

| Sección | Qué incluye | ¿Suma en totales? |
|---|---|---|
| **Pedido** | Pacientes **activos** de la hoja compuesta del próximo día de diálisis, por turno (ubicación habitual + cambios de un día: movidos, transitorios, reemplazos). Los pacientes marcados como *adicional* no van aquí. | Sí |
| **Adicionales** | Pacientes adicionales que **llegaron hoy** (asistencia A o peso de entrada): paciente con el campo *Adicional* o fila de la hoja marcada «Adic.» solo ese día. Se cargan al pedido de **hoy**, no al de mañana. | Sí |
| **Devoluciones** | De lo que ya se pidió para hoy (pedido confirmado que cubre hoy; si no hay, se recalcula la hoja de hoy): pacientes con asistencia ≠ A (NA, H, F) **y sin peso de entrada**. Si la hoja ya se cerró, también los que quedaron sin marcar. | Se restan en «Neto» |
| **Revisar** | Lo que no se decide solo: marcado A sin peso, peso sin A, pedido que no figura en la hoja, asistió sin estar en el pedido (¿adicional?), adicional que ya estaba en el pedido, calibre o filtro faltante, acceso faltante. | No |

Mientras la hoja de un turno no está abierta o la asistencia está sin marcar, el paciente queda como **pendiente** (no se devuelve nada todavía).

**Totales:** por insumo y sección, y **Neto = pedido + adicionales − devoluciones**. Filtros por turno y estación (también aplican al CSV y a la impresión).

## Confirmar / Enviar

Mientras está en **borrador** el pedido se recalcula cada vez. Al **confirmar** se guarda una foto en `pedido_insumos` + `pedido_insumos_items` (paciente, ubicación, acceso e insumos de ese momento, con las reglas usadas): editar después pacientes o reglas **no** cambia un pedido ya enviado. Lo que aparezca después (adicionales que llegan tarde, nuevas devoluciones) se muestra aparte como «Novedades posteriores a la confirmación». El administrador puede **anular la confirmación** para volver a borrador. El rol demo solo consulta, imprime y exporta.

## Reglas por defecto

Por **cada sesión** del paciente:

| Acceso | Insumo | Cantidad |
|---|---|---|
| FAV | Kit de fístula | 1 |
| FAV | Aguja de fístula del calibre del paciente (15/16/17) | 2 |
| FAV | Línea arteriovenosa | 1 |
| FAV | SSN 0,9 % 1000 mL | 1 bolsa |
| FAV | Filtro del paciente | 1 |
| FAV | Guantes estériles | **no lleva** (ningún día) |
| CY (yugular o femoral) | Kit de catéter | 1 |
| CY | Línea arteriovenosa | 1 |
| CY | SSN 0,9 % 1000 mL | 1 bolsa |
| CY | Filtro del paciente | 1 |
| CY | Guantes estériles 6.5 (se piden **por par**) | Con citrato o heparina sódica: **2 pares, cualquier día**. Sin ellos (usan Tegos): **1 par lunes y martes**, 0 los demás días |
| CY | Apósito IV3000 | 1 lunes y martes |
| CY | Tego | 2 sin citrato ni heparina sódica |
| CY | Tapas luer-lock | 1 empaque (2 tapas) con citrato o heparina sódica |

- **Unidades** (confirmadas por el responsable): guantes estériles 6.5 por **par**; SSN 0,9 % 1000 mL por **bolsa**; tapas luer-lock por empaque (2 tapas).
- El **día** es el de la sesión (para el pedido, el día siguiente; para adicionales y devoluciones, hoy).
- **Citrato / heparina sódica**: casillas del paciente (Pacientes → editar, solo con catéter). En adicionales y devoluciones también cuentan las casillas C / HS marcadas en la fila de la hoja de ese día.
- **Calibre o filtro faltante**: no se adivina; se omite esa línea y el paciente aparece con el aviso y en «Revisar».

## Cómo editar las reglas

1. **Desde la app (administrador):** Pedido de insumos → **Reglas** → editar el JSON → **Guardar reglas**. Se valida antes de guardar (insumos del catálogo, días, condiciones, cantidades 0-100); si algo falla no se cambia nada. **Restaurar predeterminadas** vuelve al archivo por defecto.
2. **Por API:** `GET /api/insumos/reglas`, `PUT /api/insumos/reglas` (cuerpo = JSON de reglas), `DELETE /api/insumos/reglas` (restaurar). Las reglas guardadas viven en la tabla `insumos_config`.
3. **Valores por defecto del proyecto:** `services/insumos_reglas.json` (se usa cuando no hay reglas guardadas).

### Formato

```json
{
  "version": 1,
  "insumos": {
    "aguja_fav_{calibre}": {"nombre": "Aguja de fístula calibre {calibre}", "unidad": "unidad"},
    "tapas_luer_lock": {"nombre": "Tapas luer-lock", "unidad": "empaque", "detalle": "1 empaque (2 tapas)"}
  },
  "faltantes": {"calibre": "Calibre faltante", "filtro": "Filtro faltante"},
  "reglas": [
    {"insumo": "aguja_fav_{calibre}", "si": {"acceso": ["FAV"]}, "cantidad": 2},
    {"insumo": "guantes_esteriles_6_5", "si": {"acceso": ["CY"]}, "cantidad": [
      {"si": {"citrato_o_heparina_sodica": true}, "cantidad": 2},
      {"si": {"dia_semana": ["lunes", "martes"]}, "cantidad": 1},
      {"cantidad": 0}
    ]}
  ]
}
```

- **Marcadores** en el código y el nombre del insumo: `{calibre}` (calibre de aguja de la FAV) y `{filtro}` (filtro del paciente).
- **`cantidad`**: un número, o una lista de casos; gana el primero que cumpla (un caso sin `si` siempre cumple). 0 = no se pide.
- **Condiciones** (`si`, todas deben cumplirse): `acceso` (FAV, CY), `sitio` (yugular, femoral), `estado_fav` (limpia, alto_riesgo, aneurismatica), `turno` (M, T, N), `dia_semana` (lunes … sábado), `citrato`, `heparina_sodica`, `citrato_o_heparina_sodica` (true / false).
- Si dos reglas dan el mismo insumo, se suman.

## API

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/insumos/pedido?fecha=&turno=&estacion=` | Pedido del día (vivo o confirmado) |
| GET | `/api/insumos/pedido.csv?…` | CSV (separador `;`, UTF-8 con BOM para Excel) |
| POST | `/api/insumos/pedido/confirmar` `{"fecha": "AAAA-MM-DD"}` | Confirmar / enviar (foto) |
| DELETE | `/api/insumos/pedido/{fecha}` | Anular la confirmación |
| GET | `/api/insumos/pedidos` | Pedidos confirmados |
| PATCH | `/api/sesiones/registros/{id}` `{"adicional": true}` | Adicional solo de esa sesión |

Código: `services/insumos_reglas.py` (reglas puras), `services/insumos.py` (composición y foto), `routers/insumos.py`, `static/js/insumos.js`. Pruebas: `tests/test_insumos_reglas.py`, `tests/test_insumos_pedido.py`.
