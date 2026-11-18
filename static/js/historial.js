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
    rows += `<tr onclick="renderHojaDia('${s.fecha}','${s.turno}')" onkeydown="if(event.key==='Enter')renderHojaDia('${s.fecha}','${s.turno}')"
      tabindex="0" title="Ver la hoja completa de este día y turno">
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

        <div class="flex flex-wrap gap-2 mb-4">${mesChips}</div>

        <form class="flex flex-wrap items-end gap-3 mb-5 bg-slate-50 border border-slate-200 rounded-xl p-3"
              onsubmit="event.preventDefault(); verHojaDesdeFormulario()" aria-label="Ver la hoja de un día">
          <div>
            <label class="form-label" for="hist-fecha">Fecha</label>
            <input id="hist-fecha" type="date" class="form-input" value="${_hojaFecha || hoy()}" required />
          </div>
          <div>
            <label class="form-label" for="hist-turno">Turno</label>
            <select id="hist-turno" class="form-input form-select">
              <option value="">Todos los turnos</option>
              ${["M","T","N"].map(t => `<option value="${t}" ${_hojaTurno === t ? "selected" : ""}>${TURNOS[t]}</option>`).join("")}
            </select>
          </div>
          <button type="submit" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg font-semibold btn-foco">Ver hoja completa</button>
        </form>

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
        <p class="text-xs text-slate-400 mt-2">Clic (o Enter) en una fila para ver la hoja completa de ese día y turno.</p>
      </div>
    </div>
  `
}

// ── R11: hoja completa de un día (fecha + turno), tal como quedó ─────────────
let _hojaFecha = null
let _hojaTurno = ""

function verHojaDesdeFormulario() {
  const f = $("hist-fecha").value, t = $("hist-turno").value
  if (!f) { toast("Elija una fecha", "warn"); return }
  renderHojaDia(f, t)
}

function _hojaFmtUI(n) { return Number(n).toLocaleString("es-CO") }

async function renderHojaDia(fecha, turno = "") {
  G.vista = "historial"
  updateHeader()
  _hojaFecha = fecha; _hojaTurno = turno || ""
  let h
  try {
    h = await apiGet(`/api/historial/hoja?fecha=${fecha}${turno ? "&turno=" + turno : ""}`)
  } catch (e) { toast(e.message, "err"); return }

  const r = h.resumen
  const nomTurno = turno ? TURNOS[turno] : "Todos los turnos"
  const multiTurno = h.sesiones.length > 1

  let rows = "", turnoAct = null, estAct = null
  h.filas.forEach(f => {
    if (multiTurno && f.sesion_turno !== turnoAct) {
      turnoAct = f.sesion_turno; estAct = null
      rows += `<tr class="fila-turno"><td colspan="14">TURNO ${TURNOS[turnoAct].toUpperCase()}</td></tr>`
    }
    if (f.estacion !== estAct) {
      estAct = f.estacion
      rows += `<tr style="background:${EST_COLORS[f.estacion] || "#475569"}"><td colspan="14" class="text-white text-xs font-bold py-1 px-3 text-left">
        ESTACIÓN ${f.estacion} — ${(EST_LABEL[f.estacion] || "").toUpperCase()}</td></tr>`
    }
    const asis = f.asistencia
    const asisTxt = asis === "A" ? "A" : asis === "NA" ? "NA" : asis === "H" ? "H" : asis === "F" ? "F" : "—"
    const asisCls = asis === "A" ? "text-emerald-700 font-bold" : asis === "NA" ? "badge-NA"
                  : asis === "F" ? "text-red-700 font-bold" : asis === "H" ? "text-amber-700 font-bold" : "text-slate-500"
    const pa = f.pa_pie_sistolica != null && f.pa_pie_diastolica != null ? `${f.pa_pie_sistolica}/${f.pa_pie_diastolica}` : "—"
    const hep = [f.heparina_ui_kg != null ? `${f.heparina_ui_kg} UI/kg` : "", f.heparina_sodica ? "Hep. sódica" : "", f.citrato ? "Citrato" : ""].filter(Boolean).join(" · ") || "—"
    rows += `<tr>
      <td class="font-mono">${f.cama_display}</td>
      <td class="izq font-medium">${escHtml(f.nombre)}${f.transitorio ? `<span class="sub">Transitorio: ${escHtml(f.transitorio)}</span>` : ""}
        <span class="sub">${escHtml(f.acceso || "")}${f.tipo_filtro ? " · filtro " + escHtml(f.tipo_filtro) : ""}</span></td>
      <td class="${asisCls}">${asisTxt}</td>
      <td>${fmtPeso(f.peso_entrada)}</td>
      <td>${fmtPeso(f.peso_salida)}</td>
      <td>${f.perdida != null ? f.perdida.toFixed(2) : "—"}</td>
      <td>${f.ganancia != null ? f.ganancia.toFixed(2) : "—"}</td>
      <td class="whitespace-nowrap">${pa}</td>
      <td>${f.fc ?? "—"}</td>
      <td>${f.ktv != null ? f.ktv.toFixed(2) : "—"}</td>
      <td>${f.epo ? (f.epo_jeringas ? (f.epo_jeringas * 4000).toLocaleString("es-CO") + " UI" : "Sí") : "—"}</td>
      <td>${f.hierro ? "Sí" : "—"}</td>
      <td class="whitespace-nowrap">${hep}</td>
      <td class="obs">${escHtml(f.observaciones) || "—"}</td>
    </tr>`
  })

  const epoDetalle = r.epo_aplicaciones
    ? `${r.epo_aplicaciones} aplic. · ${_hojaFmtUI(r.epo_ui)} UI (${r.epo_jeringas} jer.)` : "0"
  const tarjetas = [
    { l: "Sesiones del día",  v: r.sesiones,      c: "bg-slate-50 border-slate-200 text-slate-700" },
    { l: "Pacientes en hoja", v: r.pacientes,     c: "bg-slate-50 border-slate-200 text-slate-700" },
    { l: "Total asistidos",   v: r.asistidos,     c: "bg-emerald-50 border-emerald-200 text-emerald-800" },
    { l: "EPO aplicada ese día", v: epoDetalle,   c: "bg-blue-50 border-blue-200 text-blue-800", chico: true },
    { l: "Fe aplicado ese día",  v: r.fe_aplicado, c: "bg-amber-50 border-amber-200 text-amber-800" },
  ].map(c => `<div class="rounded-xl border p-3 ${c.c}">
      <div class="${c.chico ? "text-base" : "text-2xl"} font-bold">${c.v}</div>
      <div class="text-xs font-medium mt-0.5">${c.l}</div></div>`).join("")

  const aviso = h.todas_cerradas
    ? `<div class="hoja-aviso cerrada no-print" role="status">Hoja <strong>cerrada</strong>: se muestra tal como quedó (cama, peso seco y filtro de ese día).</div>`
    : `<div class="hoja-aviso abierta no-print" role="status">Hay sesiones <strong>abiertas</strong> este día: los datos se muestran en vivo y pueden cambiar.</div>`

  app().innerHTML = `
    <div class="max-w-7xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6 hoja-print">
        <div class="solo-print mb-2"><strong>Unidad Renal · Hoja diaria</strong> — ${fmtFecha(fecha)} — ${nomTurno}</div>
        <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Hoja del ${fmtFecha(fecha)} · ${nomTurno}</h2>
            <p class="text-slate-500 text-sm mt-0.5">Todas las filas de la hoja, por estación${multiTurno ? " y turno" : ""}.</p>
          </div>
          <div class="flex gap-2 no-print">
            <button onclick="window.print()" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Imprimir</button>
            <button onclick="renderHistorial(${_histMes ? `'${_histMes}'` : "null"})" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">← Historial</button>
          </div>
        </div>
        ${aviso}
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-4">${tarjetas}</div>
        ${r.epo_dosis_estimada ? `<p class="text-xs text-slate-500 mb-3 no-print">En ${r.epo_dosis_estimada} aplicación(es) el paciente no tiene dosis de EPO registrada: se asumió 1 jeringa = 4.000 UI.</p>` : ""}
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-hoja">
            <thead><tr>
              <th>Cama</th><th class="izq">Paciente</th><th title="A asiste · NA no asiste · H hospitalizado · F falleció">Asist.</th>
              <th>P. entrada</th><th>P. salida</th><th>Pérdida</th><th>Ganancia</th>
              <th>PA de pie</th><th>FC</th><th>Kt/V</th><th>EPO</th><th>Fe</th><th>Heparina</th><th class="izq">Observaciones</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="text-xs text-slate-500 mt-2">Pesos en kg · Ganancia = peso de entrada − peso seco · A asiste, NA no asiste, H hospitalizado, F falleció.</p>
      </div>
    </div>`
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
