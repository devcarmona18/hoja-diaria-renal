/* ============================================================
   estadisticas.js — Asistencia mensual por paciente (R12)
   asistidas / programadas, cierre de mes para facturación, CSV
   Depende de: app.js
   ============================================================ */

let _statsMes = null
const _MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

function _mesLabel(m) {
  const [y, mo] = m.split("-")
  return `${_MESES_ES[parseInt(mo) - 1]} ${y}`
}

/** Barra de % accesible: llega al 100 % cuando asistió a todas las sesiones programadas. */
function barraAsistencia(pct) {
  const v = pct == null ? 0 : pct
  const cls = v >= 90 ? "" : v >= 70 ? "medio" : "bajo"
  return `<span class="asis-bar ${cls}" role="progressbar" aria-valuemin="0" aria-valuemax="100"
      aria-valuenow="${v}" aria-label="Asistencia ${v} por ciento"><span style="width:${Math.min(100, v)}%"></span></span>
    <span class="asis-pct">${pct == null ? "—" : v.toFixed(v % 1 ? 1 : 0) + "%"}</span>`
}

async function renderEstadisticas(mes = null) {
  G.vista = "estadisticas"
  updateHeader()

  let meses = [], d
  try {
    meses = await apiGet("/api/estadisticas/meses")
    if (!mes) mes = meses[0] || hoy().slice(0, 7)
    _statsMes = mes
    const [y, m] = mes.split("-")
    d = await apiGet(`/api/estadisticas/asistencia/${y}/${m}`)
  } catch (e) { toast(e.message, "err"); return }

  const chips = meses.slice(0, 12).map(m => `
    <button onclick="renderEstadisticas('${m}')" aria-pressed="${m === mes}" class="chip-filtro">${_mesLabel(m)}</button>`).join("")

  const t = d.totales
  const tarjetas = [
    { l: "Pacientes atendidos",   v: t.pacientes_atendidos,  c: "bg-emerald-50 border-emerald-200 text-emerald-800" },
    { l: "Sesiones programadas",  v: t.sesiones_programadas, c: "bg-slate-50 border-slate-200 text-slate-700" },
    { l: "Sesiones asistidas",    v: t.sesiones_asistidas,   c: "bg-blue-50 border-blue-200 text-blue-800" },
    { l: "Asistencia del mes",    v: t.porcentaje == null ? "—" : t.porcentaje + " %", c: "bg-amber-50 border-amber-200 text-amber-800" },
  ].map(c => `<div class="rounded-xl border p-3 ${c.c}"><div class="text-2xl font-bold">${c.v}</div>
      <div class="text-xs font-medium mt-0.5">${c.l}</div></div>`).join("")

  const [anio, nmes] = mes.split("-")
  let rows = ""
  d.pacientes.forEach(f => {
    const marcas = [f.archivado ? `<span class="badge-inactivo">Archivado</span>` : "",
                    f.inactivo ? `<span class="badge-inactivo">Inactivo</span>` : ""].join(" ")
    rows += `<tr>
      <td class="text-left font-medium">${escHtml(f.nombre)} ${marcas}</td>
      <td class="text-xs text-slate-600">${TURNOS[f.turno] || f.turno}</td>
      <td class="text-xs text-slate-600 text-left">${escHtml(f.medico) || "—"}</td>
      <td class="font-semibold">${f.programadas}</td>
      <td class="badge-A">${f.asistidas}</td>
      <td>${f.faltas}</td>
      <td class="text-xs text-slate-500">${f.excluidas == null ? "—" : f.excluidas}</td>
      <td class="whitespace-nowrap">${barraAsistencia(f.porcentaje)}</td>
    </tr>`
  })
  rows += `<tr class="total-row"><td class="text-left" colspan="3">TOTAL · ${t.pacientes_programados} pacientes</td>
      <td>${t.sesiones_programadas}</td><td>${t.sesiones_asistidas}</td><td>${t.sesiones_programadas - t.sesiones_asistidas}</td><td></td>
      <td>${t.porcentaje == null ? "—" : t.porcentaje + " %"}</td></tr>`

  const cierre = d.cierre
  const aviso = d.cerrado
    ? `<div class="hoja-aviso cerrada" role="status">Mes <strong>cerrado</strong> por ${escHtml(cierre.cerrado_por)} el ${fmtFecha(cierre.cerrado_en.slice(0, 10))}:
        este registro es inmutable y es el que se usa para facturar. Para corregirlo hay que reabrirlo (administrador).</div>`
    : `<div class="hoja-aviso abierta" role="status">Mes <strong>abierto</strong>: las cifras se calculan en vivo y cambian si se corrige una hoja. Ciérrelo cuando termine para fijarlo.</div>`

  app().innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex flex-wrap items-start justify-between gap-2 mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Estadísticas de Asistencia · ${_mesLabel(mes)}
              <span class="badge-mes ${d.cerrado ? "cerrado" : "abierto"} align-middle ml-1">${d.cerrado ? "Cerrado" : "Abierto"}</span></h2>
            <p class="text-slate-500 text-sm mt-0.5">Días asistidos / días que le tocaban a cada paciente (base de la facturación)</p>
          </div>
          <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">← Inicio</button>
        </div>

        <div class="flex flex-wrap items-end gap-2 mb-4">
          ${chips}
          <div class="ml-auto flex items-end gap-2">
            <div><label class="form-label" for="stats-mes">Consultar otro mes</label>
              <input id="stats-mes" type="month" class="form-input" value="${mes}" onchange="if(this.value) renderEstadisticas(this.value)" /></div>
          </div>
        </div>

        ${aviso}
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">${tarjetas}</div>

        <div class="flex flex-wrap gap-2 mb-4">
          <a href="/api/estadisticas/asistencia/${anio}/${nmes}/csv" download
             class="bg-slate-100 hover:bg-slate-200 text-slate-800 text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Exportar CSV</a>
          <button onclick="statsAuditoria('${mes}')" class="bg-slate-100 hover:bg-slate-200 text-slate-800 text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Ver auditoría del cierre</button>
          ${d.cerrado
            ? `<button onclick="statsReabrir('${mes}')" class="solo-admin bg-amber-100 hover-amber text-amber-900 text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Reabrir mes</button>`
            : `<button onclick="statsCerrar('${mes}')" ${d.pacientes.length ? "" : "disabled"}
                 class="solo-admin bg-blue-800 hover:bg-blue-700 disabled:opacity-40 text-white text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Cerrar mes</button>`}
        </div>

        ${d.pacientes.length ? `
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-stats w-full">
            <thead><tr>
              <th class="text-left">Paciente</th><th>Turno</th><th class="text-left">Médico</th>
              <th title="Días de diálisis del paciente en el mes">Programadas</th>
              <th title="Días que asistió (A)">Asistidas</th>
              <th title="Programadas − asistidas">Faltas</th>
              <th title="Días no contados: inactivo, archivado, hospitalizado (H) o falleció (F)">Excluidas</th>
              <th>% asistencia</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="text-xs text-slate-500 mt-2">
          Programadas = días de diálisis del paciente (L-M-V o M-J-S) en que la unidad operó, desde su primera hoja.
          No se cuentan los días en que estaba inactivo o archivado, ni los marcados H (hospitalizado) o F (falleció).
          Un día asistido siempre cuenta. % = asistidas / programadas.</p>`
        : `<p class="text-center text-slate-500 py-10">No hay asistencia registrada en este mes.</p>`}
      </div>
    </div>`
}

function statsCerrar(mes) {
  openModal(`Cerrar ${_mesLabel(mes)}`,
    `<p class="text-sm text-slate-700">Se guardará el registro mensual de asistencia de cada paciente.
       Quedará <strong>inmutable</strong> y se usará para facturar. Reabrirlo requiere ser administrador, indicar un motivo y queda auditado.</p>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cancelar</button>
     <button onclick="_statsConfirmarCierre('${mes}')" class="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-semibold btn-foco">Cerrar mes</button>`)
}

async function _statsConfirmarCierre(mes) {
  const [y, m] = mes.split("-")
  closeModal()
  try {
    await apiPost(`/api/estadisticas/asistencia/${y}/${m}/cerrar`, {})
    toast(`${_mesLabel(mes)} cerrado`)
    renderEstadisticas(mes)
  } catch (e) { toast(e.message, "err") }
}

function statsReabrir(mes) {
  openModal(`Reabrir ${_mesLabel(mes)}`,
    `<p class="text-sm text-slate-700 mb-3">El cierre anterior queda en el historial de auditoría. Indique por qué se reabre.</p>
     <label class="form-label" for="reabrir-motivo">Motivo *</label>
     <input id="reabrir-motivo" class="form-input" maxlength="300" />
     <div id="reabrir-error" class="text-red-700 text-sm mt-2 hidden" role="alert"></div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cancelar</button>
     <button onclick="_statsConfirmarReapertura('${mes}')" class="bg-amber-600 hover:bg-amber-700 text-white px-4 py-2 rounded-lg text-sm font-semibold btn-foco">Reabrir mes</button>`)
}

async function _statsConfirmarReapertura(mes) {
  const motivo = ($("reabrir-motivo").value || "").trim()
  const err = $("reabrir-error")
  if (motivo.length < 3) { err.textContent = "Indique el motivo (mínimo 3 caracteres)"; err.classList.remove("hidden"); return }
  const [y, m] = mes.split("-")
  try {
    await apiPost(`/api/estadisticas/asistencia/${y}/${m}/reabrir`, { motivo })
    closeModal(); toast(`${_mesLabel(mes)} reabierto`); renderEstadisticas(mes)
  } catch (e) { err.textContent = e.message; err.classList.remove("hidden") }
}

async function statsAuditoria(mes) {
  const [y, m] = mes.split("-")
  let a = []
  try { a = await apiGet(`/api/estadisticas/asistencia/${y}/${m}/auditoria`) } catch (e) { toast(e.message, "err"); return }
  const filas = a.map(x => `<tr><td>${fmtFecha(x.fecha.slice(0, 10))} ${x.fecha.slice(11, 16)} UTC</td>
      <td>${x.accion === "cerrar" ? "Cierre" : "Reapertura"}</td><td>${escHtml(x.usuario)}</td><td class="text-left">${escHtml(x.motivo) || "—"}</td></tr>`).join("")
  openModal(`Auditoría · ${_mesLabel(mes)}`,
    a.length ? `<table class="tbl-resumen w-full"><thead><tr><th>Fecha</th><th>Acción</th><th>Usuario</th><th>Detalle</th></tr></thead><tbody>${filas}</tbody></table>`
             : `<p class="text-sm text-slate-500">Este mes no se ha cerrado ni reabierto.</p>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cerrar</button>`)
}
