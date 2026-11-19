/* ============================================================
   R14 · EPO / Hierro del mes — auto-programación mensual
   Reglas y algoritmo: docs/epo-hierro.md
   ============================================================ */

const EF = { mes: null, data: null }
const EF_MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
                  "Septiembre", "Octubre", "Noviembre", "Diciembre"]

function _efMesActual() { return hoy().slice(0, 7) }
function _efUI(n) { return (n * 4000).toLocaleString("es-CO") }
function _efMesNombre(mes) { const [y, m] = mes.split("-"); return `${EF_MESES[parseInt(m, 10) - 1]} ${y}` }
// R12: con el mes cerrado la programación es de solo lectura (el servidor responde 409)
function _efEditable() { return !G.readonly && !(EF.data && EF.data.mes_cerrado) }

async function renderAutoProgram(mes) {
  G.vista = "epofe"; updateHeader()
  EF.mes = mes || EF.mes || _efMesActual()
  app().innerHTML = `<p class="text-sm text-slate-500 p-4" role="status">Cargando programación…</p>`
  try { EF.data = await apiGet(`/api/epo-fe/${EF.mes}`) }
  catch (e) { toast(e.message, "err"); app().innerHTML = ""; return }
  _efPintar()
}

function _efCelda(f, d) {
  const c = f.celdas[d.fecha]
  if (!c) return `<td class="ef-c ef-no${d.lab ? " ef-lab" : ""}" aria-hidden="true"></td>`
  const cls = ["ef-c"]
  if (d.lab) cls.push("ef-lab")
  if (c.manual) cls.push("ef-manual")
  if (c.estado === "falto") cls.push("ef-falto")
  if (c.estado === "inactivo") cls.push("ef-inact")
  if (c.llega.length) cls.push("ef-llega")
  const tit = [`${f.nombre} · ${d.dow} ${d.dia}`]
  let txt = ""
  if (c.estado === "falto") {
    txt = `<span class="ef-na">NA</span>`
    c.sale.forEach(s => tit.push(`No asistió: ${s.tipo === "epo" ? s.cantidad + " jer. EPO" : "Fe"} → ${s.hacia ? fmtFecha(s.hacia) : "sin sesión libre"}`))
  } else {
    if (c.epo) txt += `<span class="ef-epo${c.epo > 1 ? " ef-epo2" : ""}">${_efUI(c.epo)}</span>`
    if (c.fe) txt += `<span class="ef-fe">Fe</span>`
    if (c.epo) tit.push(`EPO ${c.epo} jeringa(s) = ${_efUI(c.epo)} UI`)
    if (c.fe) tit.push("Hierro: 1 dosis")
  }
  c.llega.forEach(l => tit.push(`Reprogramado desde ${fmtFecha(l.desde)} (${l.tipo === "epo" ? l.cantidad + " jer. EPO" : "Fe"})`))
  if (c.manual) tit.push("Ajuste manual (el recálculo no lo cambia)")
  if (c.estado === "asistio") tit.push("Día cerrado: asistió")
  if (d.lab) tit.push("Día de laboratorio")
  const click = _efEditable() && !c.estado ? ` onclick="_efEditarCelda(${f.paciente_id},'${d.fecha}')" role="button" tabindex="0"` : ""
  return `<td class="${cls.join(" ")}" title="${escHtml(tit.join(" · "))}"${click}>${txt}</td>`
}

function _efFila(f, dias) {
  const ro = _efEditable() ? "" : "disabled"
  const avisos = f.avisos.length
    ? `<span class="ef-aviso" title="${escHtml(f.avisos.join(" · "))}">⚠ ${escHtml(f.avisos[0])}${f.avisos.length > 1 ? ` (+${f.avisos.length - 1})` : ""}</span>` : ""
  return `<tr class="${f.activo ? "" : "ef-fila-inactiva"}">
    <th scope="row" class="ef-pac"><span class="ef-nombre">${escHtml(f.nombre)}</span>
      <span class="ef-sub">${f.dias || "—"} · ${TURNOS[f.turno] || f.turno}${f.activo ? "" : " · inactivo"}</span>${avisos}</th>
    <td class="ef-tot"><input type="number" min="0" max="24" class="ef-inp" value="${f.epo_mes}" ${ro}
        aria-label="EPO del mes de ${escHtml(f.nombre)} (jeringas de 4.000 UI)" onchange="_efTotales(${f.paciente_id},'epo_jeringas',this.value)" /></td>
    <td class="ef-tot"><input type="number" min="0" max="26" class="ef-inp" value="${f.fe_mes}" ${ro}
        aria-label="Hierro del mes de ${escHtml(f.nombre)} (dosis)" onchange="_efTotales(${f.paciente_id},'fe_dosis',this.value)" /></td>
    <td class="ef-nef" title="${escHtml(f.medico)}">${escHtml(f.iniciales) || "—"}</td>
    ${dias.map(d => _efCelda(f, d)).join("")}
  </tr>`
}

function _efPintar() {
  const g = EF.data, adm = _efEditable()
  const dias = g.dias
  let cuerpo = ""
  let turno = null
  g.filas.forEach(f => {
    if (f.turno !== turno) {
      turno = f.turno
      cuerpo += `<tr class="ef-grupo"><th colspan="${4 + dias.length}" scope="rowgroup">Turno ${TURNOS[turno] || turno}</th></tr>`
    }
    cuerpo += _efFila(f, dias)
  })
  const tot = dias.map(d => {
    const t = g.totales_dia[d.fecha]
    return `<td class="ef-c ef-totdia${d.lab ? " ef-lab" : ""}">${t.epo_jeringas ? `<span class="ef-epo">${t.epo_jeringas}</span>` : ""}${t.fe ? `<span class="ef-fe">${t.fe}</span>` : ""}</td>`
  }).join("")
  const sumEpo = g.filas.reduce((a, f) => a + f.epo_mes, 0), sumFe = g.filas.reduce((a, f) => a + f.fe_mes, 0)
  const labTxt = g.dias_lab.length ? g.dias_lab.map(fmtFecha).join(" y ") : "ninguno"

  const botones = adm ? `
      ${g.generado
        ? `<button onclick="_efGenerar(false)" class="ef-btn" title="Agrega los pacientes activos que aún no están">+ Pacientes nuevos</button>
           <button onclick="_efRecalcular()" class="ef-btn" title="Reprograma las dosis de los días cerrados en que el paciente no asistió">↻ Recalcular</button>
           <button onclick="_efGenerar(true)" class="ef-btn ef-btn-warn" title="Rehace el reparto del mes; borra los ajustes manuales (los días cerrados no cambian)">Regenerar mes</button>`
        : `<button onclick="_efGenerar(false)" class="ef-btn ef-btn-main">Generar programación de ${_efMesNombre(g.mes)}</button>`}
      <button onclick="_efLab()" class="ef-btn">Días de laboratorio</button>
      ${g.puede_borrar && g.generado ? `<button onclick="_efBorrar()" class="ef-btn ef-btn-del">Borrar mes</button>` : ""}` : ""

  app().innerHTML = `
  <div class="ef-wrap">
    <div class="ef-cab print:hidden">
      <div>
        <h2 class="text-xl font-bold text-blue-900">EPO / Hierro del mes</h2>
        <p class="text-slate-500 text-sm">1 jeringa de EPO = 4.000 UI · reparto parejo en las sesiones del paciente · sin dosis en días de laboratorio salvo que no quepan</p>
      </div>
      <div class="ef-acciones">
        <label class="text-sm font-semibold text-slate-600" for="ef-mes">Mes</label>
        <input type="month" id="ef-mes" value="${g.mes}" class="border border-slate-300 rounded-lg px-2 py-1 text-sm"
          onchange="this.value && renderAutoProgram(this.value)" />
        ${g.mes_cerrado ? `<span class="badge-mes-cerrado self-center" role="status" title="${typeof AVISO_MES_CERRADO !== "undefined" ? AVISO_MES_CERRADO : "Mes cerrado"}"><span aria-hidden="true">🔒</span> Mes cerrado · solo lectura</span>` : ""}
        <button onclick="window.print()" class="ef-btn">Imprimir</button>
        <a href="/api/epo-fe/${g.mes}/csv" class="ef-btn" download>CSV</a>
        ${botones}
        <button onclick="goHome()" class="ef-btn">← Inicio</button>
      </div>
    </div>
    <h2 class="ef-titulo-print">Programación EPO / Hierro · ${_efMesNombre(g.mes)}</h2>
    <div class="ef-info">
      <span><strong>${_efMesNombre(g.mes)}</strong></span>
      <span>Laboratorio: <strong>${labTxt}</strong>${g.dias_lab_por_defecto ? " (2.º miércoles y jueves)" : " (fijado para este mes)"}</span>
      <span>Pacientes: <strong>${g.filas.length}</strong></span>
      <span>EPO del mes: <strong>${sumEpo}</strong> jer. (${_efUI(sumEpo)} UI)</span>
      <span>Fe del mes: <strong>${sumFe}</strong> dosis</span>
      ${g.sin_programacion && g.generado ? `<span class="text-amber-700">${g.sin_programacion} paciente(s) activo(s) sin programar</span>` : ""}
      ${g.sin_dias ? `<span class="text-slate-500" title="Sin días LMV/MJS no se pueden programar">${g.sin_dias} sin días de diálisis</span>` : ""}
    </div>
    <div class="ef-leyenda print:hidden">
      <span><span class="ef-epo">4.000</span> EPO 1 jeringa</span><span><span class="ef-epo ef-epo2">8.000</span> 2 jeringas</span>
      <span><span class="ef-fe">Fe</span> hierro</span><span><span class="ef-lab ef-muestra"></span> día de laboratorio</span>
      <span><span class="ef-na">NA</span> no asistió (dosis reprogramada)</span>
      <span><span class="ef-manual ef-muestra"></span> ajuste manual</span><span><span class="ef-llega ef-muestra"></span> recibe reprogramación</span>
      ${adm ? "<span>· Clic en una sesión para ajustarla</span>" : ""}
    </div>
    ${g.generado ? `
    <div class="ef-tabla-wrap">
      <table class="ef-tabla">
        <caption class="sr-only">Programación de EPO y hierro de ${_efMesNombre(g.mes)} por paciente y día</caption>
        <thead><tr>
          <th scope="col" class="ef-pac">Paciente</th>
          <th scope="col" class="ef-tot" title="Jeringas de EPO de 4.000 UI del mes">EPO<br>mes</th>
          <th scope="col" class="ef-tot" title="Dosis de hierro del mes">Fe<br>mes</th>
          <th scope="col" class="ef-nef" title="Nefrólogo">Nef.</th>
          ${dias.map(d => `<th scope="col" class="ef-dia${d.lab ? " ef-lab" : ""}" title="${fmtFecha(d.fecha)}${d.lab ? " · laboratorio" : ""}">${d.dow}<br>${d.dia}</th>`).join("")}
        </tr></thead>
        <tbody>${cuerpo}</tbody>
        <tfoot><tr><th scope="row" class="ef-pac" colspan="4">Total del día (jer. EPO / dosis Fe)</th>${tot}</tr></tfoot>
      </table>
    </div>` : `<div class="ef-vacio">Aún no hay programación para ${_efMesNombre(g.mes)}.
        ${adm ? "Pulse «Generar programación»: se toman los pacientes activos con días LMV/MJS y sus dosis de la ficha (EPO mensual ÷ 4.000 UI, Fe mensual)." : ""}</div>`}
    ${g.auditoria.length ? `<details class="ef-audit print:hidden"><summary>Bitácora (${g.auditoria.length})</summary>
      <ul>${g.auditoria.map(a => `<li><span class="text-slate-400">${a.creado_en.replace("T", " ")} · ${escHtml(a.usuario || "")}</span> — ${escHtml(a.detalle || a.accion)}</li>`).join("")}</ul></details>` : ""}
  </div>`
}

async function _efRecargar(msg) {
  EF.data = await apiGet(`/api/epo-fe/${EF.mes}`)
  _efPintar()
  if (msg) toast(msg)
}

async function _efGenerar(regenerar) {
  if (regenerar && !confirm(`¿Regenerar ${_efMesNombre(EF.mes)}?\nSe rehace el reparto de todos los pacientes y se BORRAN los ajustes manuales. Los días ya cerrados no cambian.`)) return
  try {
    const r = await apiPost(`/api/epo-fe/${EF.mes}/generar`, { regenerar })
    await _efRecargar(regenerar ? "Mes regenerado" : `Programación lista (${r.nuevos} paciente(s) nuevo(s))`)
  } catch (e) { toast(e.message, "err") }
}

async function _efRecalcular() {
  try {
    const r = await apiPost(`/api/epo-fe/${EF.mes}/recalcular`, {})
    await _efRecargar(`Recalculado: ${r.reprogramadas} reprogramada(s), ${r.revertidas} revertida(s)`)
  } catch (e) { toast(e.message, "err") }
}

async function _efTotales(pid, campo, valor) {
  const n = parseInt(valor, 10)
  if (Number.isNaN(n) || n < 0) { toast("Valor inválido", "warn"); return }
  try {
    await apiPut(`/api/epo-fe/${EF.mes}/pacientes/${pid}`, { [campo]: n })
    await _efRecargar("Reparto actualizado")
  } catch (e) { toast(e.message, "err"); _efPintar() }
}

function _efEditarCelda(pid, fecha) {
  const f = EF.data.filas.find(x => x.paciente_id === pid); if (!f) return
  const c = f.celdas[fecha] || { epo: 0, fe: 0, epo_plan: 0, fe_plan: 0, manual: false, llega: [] }
  const ops = [0, 1, 2].map(v => `<option value="${v}" ${v === c.epo_plan ? "selected" : ""}>${v ? `${v} jeringa(s) · ${_efUI(v)} UI` : "Sin EPO"}</option>`).join("")
  const llega = c.llega.length ? `<p class="text-xs text-amber-700 mt-2">Además recibe reprogramado: ${c.llega.map(l => `${l.tipo === "epo" ? l.cantidad + " jer. EPO" : "Fe"} del ${fmtFecha(l.desde)}`).join(", ")}.</p>` : ""
  openModal(`${escHtml(f.nombre)} · ${fmtFecha(fecha)}`,
    `<p class="text-sm text-slate-500 mb-3">El ajuste queda fijo: «Recalcular» no lo cambia (solo «Regenerar mes»). Las demás sesiones automáticas se reparten de nuevo para mantener el total del mes.</p>
     <label class="form-label" for="ef-c-epo">EPO</label>
     <select id="ef-c-epo" class="border border-slate-300 rounded-lg px-2 py-1 text-sm w-full mb-3">${ops}</select>
     <label class="flex items-center gap-2 text-sm"><input type="checkbox" id="ef-c-fe" ${c.fe_plan ? "checked" : ""} /> Hierro (1 dosis)</label>
     ${llega}`,
    `${c.manual ? `<button onclick="_efGuardarCelda(${pid},'${fecha}',true)" class="ef-btn">Volver a automático</button>` : ""}
     <button onclick="closeModal()" class="ef-btn">Cancelar</button>
     <button onclick="_efGuardarCelda(${pid},'${fecha}',false)" class="ef-btn ef-btn-main">Guardar ajuste</button>`)
}

async function _efGuardarCelda(pid, fecha, quitar) {
  const body = { paciente_id: pid, fecha, quitar_ajuste: !!quitar }
  if (!quitar) { body.epo = parseInt($("ef-c-epo").value, 10); body.fe = $("ef-c-fe").checked ? 1 : 0 }
  closeModal()
  try {
    await apiPut(`/api/epo-fe/${EF.mes}/celdas`, body)
    await _efRecargar(quitar ? "Sesión de nuevo automática" : "Ajuste guardado")
  } catch (e) { toast(e.message, "err") }
}

function _efLab() {
  const g = EF.data
  const habiles = g.dias.map(d => d.fecha)
  openModal("Días de laboratorio",
    `<p class="text-sm text-slate-500 mb-3">Por defecto: segundo miércoles del mes (día 8 a 14) y el jueves siguiente. Esos días no se programa EPO ni hierro salvo que no quepan en otras sesiones. Al cambiarlos se rehace el reparto (los ajustes manuales se respetan).</p>
     <div class="ef-lab-lista">${habiles.map(f => `<label class="text-sm"><input type="checkbox" class="ef-lab-chk" value="${f}" ${g.dias_lab.includes(f) ? "checked" : ""} /> ${fmtFecha(f)}</label>`).join("")}</div>`,
    `<button onclick="_efGuardarLab(true)" class="ef-btn">Usar regla por defecto</button>
     <button onclick="closeModal()" class="ef-btn">Cancelar</button>
     <button onclick="_efGuardarLab(false)" class="ef-btn ef-btn-main">Guardar</button>`, { ancho: true })
}

async function _efGuardarLab(defecto) {
  const fechas = defecto ? null : [...document.querySelectorAll(".ef-lab-chk:checked")].map(x => x.value)
  closeModal()
  try {
    await apiPut(`/api/epo-fe/${EF.mes}/laboratorio`, { fechas })
    await _efRecargar("Días de laboratorio guardados")
  } catch (e) { toast(e.message, "err") }
}

async function _efBorrar() {
  if (!confirm(`¿Borrar la programación de ${_efMesNombre(EF.mes)}? Las hojas diarias y el historial NO se tocan.`)) return
  try {
    await apiDelete(`/api/epo-fe/${EF.mes}`)
    await _efRecargar("Programación del mes borrada")
  } catch (e) { toast(e.message, "err") }
}
