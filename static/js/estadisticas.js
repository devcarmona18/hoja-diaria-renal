/* ============================================================
   estadisticas.js — Sesiones por paciente por mes
   Depende de: app.js
   ============================================================ */

let _statsMes = null

async function renderEstadisticas(mes = null) {
  G.vista = "estadisticas"
  updateHeader()
  _statsMes = mes

  let meses = [], datos = []
  try {
    meses = await apiGet("/api/estadisticas/meses")
    if (!mes && meses.length) mes = meses[0]
    _statsMes = mes
    if (mes) {
      const [y, m] = mes.split("-")
      datos = await apiGet(`/api/estadisticas/mes/${y}/${m}`)
    }
  } catch (e) { toast(e.message, "err"); return }

  // Chips de mes
  const chips = meses.slice(0, 18).map(m => {
    const [y, mo] = m.split("-")
    const label = `${["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"][parseInt(mo)-1]} ${y}`
    return `<button onclick="renderEstadisticas('${m}')"
      class="px-3 py-1 rounded-full text-xs font-semibold border ${_statsMes === m
        ? "bg-blue-800 text-white border-blue-800"
        : "bg-white text-slate-600 border-slate-300 hover:border-blue-400"}">
      ${label}</button>`
  }).join("") || `<span class="text-slate-400 text-sm">Sin sesiones registradas aún.</span>`

  // Totales
  const sumTotal = datos.reduce((a, d) => a + d.total, 0)
  const sumA     = datos.reduce((a, d) => a + d.A, 0)
  const sumNA    = datos.reduce((a, d) => a + d.NA, 0)
  const sumH     = datos.reduce((a, d) => a + d.H, 0)
  const sumF     = datos.reduce((a, d) => a + d.F, 0)

  // Filas de la tabla, agrupadas por estación
  let rows = ""
  const byEst = { 1: [], 2: [], 3: [] }
  datos.forEach(d => byEst[d.estacion]?.push(d))

  for (const est of [1, 2, 3]) {
    if (!byEst[est].length) continue
    rows += `<tr style="background:${EST_COLORS[est]}">
      <td colspan="9" class="text-white font-bold text-xs py-1 px-3 tracking-wide">
        ESTACIÓN ${est} — MACRO ${EST_LABEL[est].toUpperCase()} · CAMAS ${(est-1)*16+1}–${est*16}
      </td>
    </tr>`
    byEst[est].forEach(d => {
      const pct = d.total > 0 ? Math.round((d.A / d.total) * 100) : 0
      rows += `<tr class="row-est-${est}">
        <td class="font-mono font-bold text-xs">${displayCama(d.cama, d.estacion)}</td>
        <td class="font-medium text-sm text-left">${d.nombre}</td>
        <td class="text-xs text-slate-400">${d.turno === "M" ? "Mañana" : d.turno === "T" ? "Tarde" : "Noche"}</td>
        <td class="text-xs text-slate-400">${d.medico || "—"}</td>
        <td class="font-semibold">${d.total}</td>
        <td class="badge-A">${d.A}</td>
        <td class="badge-NA">${d.NA}</td>
        <td class="badge-H">${d.H}</td>
        <td class="badge-F">${d.F}</td>
        <td>
          <div class="flex items-center gap-1">
            <div class="h-2 rounded-full bg-emerald-200 flex-1 relative overflow-hidden" style="width:60px">
              <div class="h-full bg-emerald-500 rounded-full" style="width:${pct}%"></div>
            </div>
            <span class="text-xs text-slate-500">${pct}%</span>
          </div>
        </td>
      </tr>`
    })
  }

  // Fila total
  const pctTotal = sumTotal > 0 ? Math.round((sumA / sumTotal) * 100) : 0
  rows += `<tr class="total-row" style="background:#1e3a5f;color:#fff">
    <td colspan="4" class="text-left font-bold">TOTAL</td>
    <td class="font-bold">${sumTotal}</td>
    <td class="font-bold">${sumA}</td>
    <td class="font-bold">${sumNA}</td>
    <td class="font-bold">${sumH}</td>
    <td class="font-bold">${sumF}</td>
    <td class="font-bold">${pctTotal}% asist.</td>
  </tr>`

  app().innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Estadísticas de Asistencia</h2>
            <p class="text-slate-500 text-sm mt-0.5">Sesiones por paciente en el período seleccionado</p>
          </div>
          <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Inicio</button>
        </div>

        <!-- Selector de mes -->
        <div class="flex flex-wrap gap-2 mb-5">${chips}</div>

        <!-- Resumen -->
        ${_statsMes ? `<div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
          ${[
            { l: "Total programados", v: sumTotal,      c: "bg-slate-50 border-slate-200 text-slate-700" },
            { l: "Asistidos (A)",     v: sumA,           c: "bg-emerald-50 border-emerald-200 text-emerald-700" },
            { l: "No asiste (NA)",    v: sumNA,          c: "bg-slate-100 border-slate-300 text-slate-600" },
            { l: "Hospitalizados (H)", v: sumH,          c: "bg-amber-50 border-amber-200 text-amber-700" },
            { l: "Fallecidos (F)",    v: sumF,           c: "bg-red-50 border-red-200 text-red-700" },
          ].map(c => `<div class="rounded-xl border p-3 ${c.c}">
            <div class="text-2xl font-bold">${c.v}</div>
            <div class="text-xs font-medium mt-0.5">${c.l}</div>
          </div>`).join("")}
        </div>` : ""}

        <!-- Tabla -->
        ${datos.length ? `
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-stats w-full">
            <thead><tr>
              <th class="w-10">#</th>
              <th class="text-left">Paciente</th>
              <th>Turno</th>
              <th>Médico</th>
              <th>Total</th>
              <th>A</th>
              <th>NA</th>
              <th>H</th>
              <th>F</th>
              <th>% Asist.</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="text-xs text-slate-400 mt-2">
          A=Asiste · NA=No asiste · H=Hospitalizado · F=Falleció · % = A / Total del mes
        </p>` : `<p class="text-center text-slate-400 py-10">Seleccione un mes para ver las estadísticas.</p>`}
      </div>
    </div>
  `
}
