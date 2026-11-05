/* ============================================================
   historial.js — Historial de sesiones + reinicio mensual
   Depende de: app.js
   ============================================================ */

let _histMes = null

async function renderHistorial(mes = null) {
  G.vista = "historial"
  updateHeader()
  _histMes = mes

  let meses = [], sesiones = []
  try {
    meses    = await apiGet("/api/historial/meses")
    const url = mes ? `/api/historial?anio=${mes.slice(0,4)}&mes=${mes.slice(5,7)}` : "/api/historial"
    sesiones = await apiGet(url)
  } catch (e) { toast(e.message, "err"); return }

  const mesChips = [
    `<button onclick="renderHistorial(null)"
      class="px-3 py-1 rounded-full text-xs font-semibold border ${!mes ? "bg-blue-800 text-white border-blue-800" : "bg-white text-slate-600 border-slate-300"}">
      Todos</button>`,
    ...meses.slice(0, 12).map(m => {
      const [y, mo] = m.split("-")
      const label = `${["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"][parseInt(mo)-1]} ${y}`
      return `<button onclick="renderHistorial('${m}')"
        class="px-3 py-1 rounded-full text-xs font-semibold border ${mes === m ? "bg-blue-800 text-white border-blue-800" : "bg-white text-slate-600 border-slate-300 hover:border-blue-400"}">
        ${label}</button>`
    })
  ].join("")

  let rows = ""
  sesiones.forEach(s => {
    const turnoColor = s.turno === "M" ? "text-amber-700 bg-amber-50" : s.turno === "T" ? "text-blue-700 bg-blue-50" : "text-slate-700 bg-slate-100"
    rows += `<tr onclick="historialDetalle(${s.id})" title="Ver detalle">
      <td class="text-left">${fmtFecha(s.fecha)}</td>
      <td><span class="px-2 py-0.5 rounded text-xs font-semibold ${turnoColor}">${TURNOS[s.turno]}</span></td>
      <td>${s.total}</td>
      <td class="badge-A">${s.asistidos}</td>
      <td class="badge-NA">${s.no_asiste || 0}</td>
      <td class="badge-H">${s.hospitalizados}</td>
      <td class="badge-F">${s.fallecidos}</td>
      <td class="${s.sin_marcar > 0 ? "text-orange-500 font-bold" : "text-slate-400"}">${s.sin_marcar}</td>
      <td class="text-blue-700 font-semibold">${s.epo_count}</td>
      <td class="text-amber-700 font-semibold">${s.hierro_count}</td>
      <td><span class="px-1.5 py-0.5 rounded text-xs ${s.cerrada ? "bg-slate-200 text-slate-500" : "bg-amber-100 text-amber-700"}">${s.cerrada ? "Cerrada" : "Abierta"}</span></td>
    </tr>`
  })

  const sumA   = sesiones.reduce((a, s) => a + s.asistidos, 0)
  const sumEpo = sesiones.reduce((a, s) => a + s.epo_count, 0)
  const sumFe  = sesiones.reduce((a, s) => a + s.hierro_count, 0)

  app().innerHTML = `
    <div class="max-w-5xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Historial de Sesiones</h2>
            <p class="text-slate-500 text-sm mt-0.5">${sesiones.length} sesiones ${mes ? "en " + mes : "en total"}</p>
          </div>
          <div class="flex gap-2">
            ${mes ? `<button onclick="confirmarLimpiarMes('${mes}')"
              class="bg-red-100 hover:bg-red-200 text-red-700 text-sm px-3 py-1.5 rounded-lg font-medium">
              Limpiar ${mes}</button>` : ""}
            <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Inicio</button>
          </div>
        </div>

        <div class="flex flex-wrap gap-2 mb-5">${mesChips}</div>

        <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          ${[
            { label: "Sesiones",        val: sesiones.length, color: "bg-slate-50 border-slate-200 text-slate-700" },
            { label: "Total asistidos", val: sumA,            color: "bg-emerald-50 border-emerald-200 text-emerald-700" },
            { label: "EPO aplicado",    val: sumEpo,          color: "bg-blue-50 border-blue-200 text-blue-700" },
            { label: "Fe aplicado",     val: sumFe,           color: "bg-amber-50 border-amber-200 text-amber-700" },
          ].map(c => `<div class="rounded-xl border p-3 ${c.color}">
            <div class="text-2xl font-bold">${c.val}</div>
            <div class="text-xs font-medium mt-0.5">${c.label}</div>
          </div>`).join("")}
        </div>

        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-hist w-full">
            <thead><tr>
              <th class="text-left">Fecha</th><th>Turno</th><th>Total</th>
              <th>A</th><th>NA</th><th>H</th><th>F</th>
              <th>Sin marcar</th><th>EPO</th><th>Fe</th><th>Estado</th>
            </tr></thead>
            <tbody>
              ${rows || `<tr><td colspan="11" class="py-8 text-slate-400 text-center">No hay sesiones registradas.</td></tr>`}
            </tbody>
          </table>
        </div>
        <p class="text-xs text-slate-400 mt-2">Clic en cualquier fila para ver el detalle de esa sesión.</p>
      </div>
    </div>
  `
}

async function historialDetalle(sesionId) {
  let regs
  try {
    regs = await apiGet(`/api/sesiones/${sesionId}/registros`)
  } catch (e) { toast(e.message, "err"); return }

  if (!regs.length) { toast("Sesión sin registros", "warn"); return }

  const byEst = { 1: [], 2: [], 3: [] }
  regs.forEach(r => { if (r.paciente) byEst[r.paciente.estacion]?.push(r) })

  let rows = ""
  for (const est of [1, 2, 3]) {
    if (!byEst[est].length) continue
    rows += `<tr style="background:${EST_COLORS[est]}"><td colspan="6" class="text-white text-xs font-bold py-1 px-3">ESTACIÓN ${est} — ${EST_LABEL[est].toUpperCase()}</td></tr>`
    byEst[est].forEach(r => {
      const p = r.paciente
      const asistBadge = r.asistencia === "A"  ? "text-emerald-700 font-bold"
                       : r.asistencia === "NA" ? "badge-NA"
                       : r.asistencia === "F"  ? "text-red-600 font-bold"
                       : r.asistencia === "H"  ? "text-amber-600 font-bold"
                       : "text-slate-400"
      const transTxt = r.transitorio_nombre ? `<span class="text-amber-600 text-xs"> → ${r.transitorio_nombre}</span>` : ""
      rows += `<tr class="row-est-${p.estacion}">
        <td class="text-xs text-slate-400 font-mono">${displayCama(p.cama, p.estacion)}</td>
        <td class="font-medium text-sm">${p.nombre}${transTxt}</td>
        <td class="text-center ${asistBadge}">${r.asistencia || "—"}</td>
        <td class="text-xs text-center">${r.perdida_real != null ? r.perdida_real.toFixed(2) + " kg" : "—"}</td>
        <td class="text-xs text-center">${r.ktv != null ? "KtV " + r.ktv.toFixed(2) : "—"}</td>
        <td class="text-xs text-center">${[r.epo?"EPO":"", r.hierro?"Fe":""].filter(Boolean).join(" / ") || "—"}</td>
      </tr>`
    })
  }

  openModal(
    `Detalle sesión`,
    `<div class="max-h-96 overflow-y-auto">
      <table class="tbl-labs w-full text-xs">
        <thead><tr><th class="text-left w-8">#</th><th class="text-left">Paciente</th><th>Estado</th><th>Pérdida</th><th>Kt/V</th><th>Meds</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">Cerrar</button>`
  )
}

async function confirmarLimpiarMes(mes) {
  const [y, m] = mes.split("-")
  const nombres = ["Enero","Febrero","Marzo","Abril","Mayo","Junio","Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]
  if (!confirm(`¿Eliminar TODAS las sesiones de ${nombres[parseInt(m)-1]} ${y}?\nEsta acción no se puede deshacer. Los pacientes se conservan.`)) return
  try {
    const r = await fetch(`/api/historial/mes/${y}/${m}`, { method: "DELETE" })
    if (r.ok || r.status === 204) {
      const data = await r.json().catch(() => ({}))
      toast(`${data.eliminadas || 0} sesiones eliminadas`)
    } else {
      const e = await r.json().catch(() => ({})); throw new Error(e.detail || "Error al limpiar")
    }
    renderHistorial(null)
  } catch (e) { toast(e.message, "err") }
}
