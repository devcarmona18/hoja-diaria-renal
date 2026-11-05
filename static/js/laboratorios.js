/* ============================================================
   laboratorios.js — Fase 2: Labs + gráficos Chart.js
                     Fase 5: Panel Clínico (filtro por valor)
   Depende de: app.js, Chart.js (CDN en index.html)
   ============================================================ */

const LAB_CONFIG = {
  Hb:         { label: "Hemoglobina",        unidad: "g/dL",    min: 10,   max: 12,    color: "#ef4444" },
  Hto:        { label: "Hematocrito",         unidad: "%",       min: 30,   max: 36,    color: "#f97316" },
  Urea:       { label: "Urea",                unidad: "mg/dL",   min: null, max: 150,   color: "#eab308" },
  Creatinina: { label: "Creatinina",          unidad: "mg/dL",   min: null, max: null,  color: "#84cc16" },
  Kt_V:       { label: "Kt/V",               unidad: "",         min: 1.2,  max: null,  color: "#22c55e" },
  K:          { label: "Potasio",             unidad: "mEq/L",   min: 3.5,  max: 5.5,   color: "#06b6d4" },
  Na:         { label: "Sodio",               unidad: "mEq/L",   min: 135,  max: 145,   color: "#3b82f6" },
  Ca:         { label: "Calcio",              unidad: "mg/dL",   min: 8.5,  max: 10.5,  color: "#8b5cf6" },
  P:          { label: "Fósforo",             unidad: "mg/dL",   min: 2.5,  max: 5.5,   color: "#ec4899" },
  Albumina:   { label: "Albúmina",            unidad: "g/dL",    min: 3.5,  max: 5.0,   color: "#14b8a6" },
  Ferritina:  { label: "Ferritina",           unidad: "ng/mL",   min: 200,  max: 500,   color: "#f59e0b" },
  Sat_Transf: { label: "Sat. Transferrina",   unidad: "%",       min: 20,   max: 50,    color: "#6366f1" },
  PTH:        { label: "PTH",                 unidad: "pg/mL",   min: 150,  max: 600,   color: "#a78bfa" },
  PCR:        { label: "Proteína C Reactiva", unidad: "mg/L",    min: null, max: 10,    color: "#fb923c" },
}

let _labChart = null
let _labPacId = null
let _labPacNombre = ""
let _labData = []
let _labSelTipo = null

// ── Vista principal de labs de un paciente ────────────────────────────────────
async function renderLabs(pacienteId, pacienteNombre = "") {
  G.vista = "labs"
  _labPacId = pacienteId
  _labPacNombre = pacienteNombre
  updateHeader()

  try {
    _labData = await apiGet(`/api/laboratorios/${pacienteId}`)
  } catch (e) { toast(e.message, "err"); return }

  _renderLabsView()
}

function _renderLabsView() {
  const porTipo = {}
  _labData.forEach(l => {
    if (!porTipo[l.tipo]) porTipo[l.tipo] = []
    porTipo[l.tipo].push(l)
  })
  Object.values(porTipo).forEach(arr => arr.sort((a, b) => a.fecha.localeCompare(b.fecha)))

  const tiposConDatos = Object.keys(porTipo)
  const cards = tiposConDatos.map(tipo => {
    const cfg  = LAB_CONFIG[tipo] || {}
    const arr  = porTipo[tipo]
    const ult  = arr[arr.length - 1]
    const cls  = _labClase(ult.valor, cfg.min, cfg.max)
    const tendHTML = arr.length >= 2 ? _tendencia(arr) : ""
    return `
      <div class="bg-white rounded-xl border border-slate-200 p-3 cursor-pointer hover:shadow-md transition-shadow ${_labSelTipo === tipo ? "ring-2 ring-blue-500" : ""}"
        onclick="labSelTipo('${tipo}')">
        <div class="text-xs text-slate-500 mb-0.5">${cfg.label || tipo}</div>
        <div class="flex items-end gap-1">
          <span class="text-xl font-bold ${cls}">${ult.valor.toFixed(1)}</span>
          <span class="text-xs text-slate-400 mb-0.5">${cfg.unidad || ""}</span>
          <span class="ml-auto">${tendHTML}</span>
        </div>
        <div class="text-xs text-slate-400 mt-0.5">${fmtFecha(ult.fecha)}</div>
        ${cfg.min != null || cfg.max != null ? `<div class="text-xs text-slate-300 mt-0.5">Ref: ${cfg.min ?? "—"} – ${cfg.max ?? "—"} ${cfg.unidad || ""}</div>` : ""}
      </div>`
  }).join("") || `<p class="col-span-full text-center text-slate-400 py-6">Sin resultados de laboratorio registrados.</p>`

  const histRows = [..._labData].reverse().map(l => {
    const cfg = LAB_CONFIG[l.tipo] || {}
    const cls = _labClase(l.valor, cfg.min, cfg.max)
    return `<tr>
      <td>${fmtFecha(l.fecha)}</td>
      <td class="font-medium">${cfg.label || l.tipo}</td>
      <td class="text-right font-mono ${cls}">${l.valor.toFixed(2)}</td>
      <td class="text-slate-400">${cfg.unidad || l.unidad || ""}</td>
      <td class="text-slate-400 text-xs">${l.observaciones || ""}</td>
      <td class="text-right">
        <button onclick="labEliminar(${l.id})" class="text-red-400 hover:text-red-700 text-xs">Eliminar</button>
      </td>
    </tr>`
  }).join("")

  app().innerHTML = `
    <div class="max-w-5xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Laboratorios — ${_labPacNombre}</h2>
            <p class="text-slate-500 text-sm">Clic en una tarjeta para ver la evolución</p>
          </div>
          <div class="flex gap-2">
            <button onclick="labAgregar()" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-3 py-1.5 rounded-lg font-medium">+ Agregar resultado</button>
            <button onclick="renderCRUD()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Pacientes</button>
          </div>
        </div>

        <div class="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-3 mb-5">
          ${cards}
        </div>

        ${_labSelTipo ? `
        <div class="mb-5 bg-slate-50 rounded-xl p-4">
          <h3 class="text-sm font-semibold text-slate-600 mb-3">
            Evolución: ${LAB_CONFIG[_labSelTipo]?.label || _labSelTipo}
            ${LAB_CONFIG[_labSelTipo]?.unidad ? `(${LAB_CONFIG[_labSelTipo].unidad})` : ""}
          </h3>
          <div style="position:relative; height:200px">
            <canvas id="lab-chart"></canvas>
          </div>
        </div>` : ""}

        ${histRows ? `
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-labs w-full">
            <thead><tr>
              <th class="text-left">Fecha</th><th class="text-left">Tipo</th>
              <th class="text-right">Valor</th><th class="text-left">Unidad</th>
              <th class="text-left">Obs.</th><th></th>
            </tr></thead>
            <tbody>${histRows}</tbody>
          </table>
        </div>` : ""}
      </div>
    </div>
  `

  if (_labSelTipo) _drawChart(_labSelTipo, porTipo[_labSelTipo] || [])
}

function _labClase(val, min, max) {
  if (min != null && val < min) return "lab-bajo"
  if (max != null && val > max) return "lab-alto"
  return "lab-normal"
}

function _tendencia(arr) {
  if (arr.length < 2) return ""
  const diff = arr[arr.length - 1].valor - arr[arr.length - 2].valor
  if (Math.abs(diff) < 0.01) return `<span class="text-slate-400 text-xs">→</span>`
  return diff > 0
    ? `<span class="text-red-500 text-xs">↑</span>`
    : `<span class="text-emerald-600 text-xs">↓</span>`
}

function labSelTipo(tipo) {
  _labSelTipo = _labSelTipo === tipo ? null : tipo
  _renderLabsView()
}

function _drawChart(tipo, datos) {
  const canvas = $("lab-chart"); if (!canvas) return
  if (_labChart) { _labChart.destroy(); _labChart = null }
  const cfg    = LAB_CONFIG[tipo] || {}
  const labels = datos.map(d => fmtFecha(d.fecha))
  const values = datos.map(d => d.valor)

  const datasets = [{ label: cfg.label || tipo, data: values, borderColor: cfg.color || "#3b82f6", backgroundColor: (cfg.color || "#3b82f6") + "22", tension: 0.3, pointRadius: 4, fill: true }]

  if (cfg.min != null) datasets.push({ label: `Mín (${cfg.min})`, data: Array(values.length).fill(cfg.min), borderColor: "#94a3b8", borderDash: [4,4], pointRadius: 0, borderWidth: 1, fill: false })
  if (cfg.max != null) datasets.push({ label: `Máx (${cfg.max})`, data: Array(values.length).fill(cfg.max), borderColor: "#94a3b8", borderDash: [4,4], pointRadius: 0, borderWidth: 1, fill: false })

  _labChart = new Chart(canvas, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: {
        x: { ticks: { font: { size: 10 } } },
        y: { ticks: { font: { size: 10 } } },
      },
    },
  })
}

function labAgregar() {
  const tipoOpts = Object.entries(LAB_CONFIG).map(([k, v]) =>
    `<option value="${k}">${v.label}</option>`).join("")

  openModal(
    "Agregar resultado de laboratorio",
    `<div class="space-y-3">
      <div>
        <label class="form-label">Tipo *</label>
        <select id="lab-tipo" class="form-input form-select" onchange="labActualizarUnidad()">${tipoOpts}</select>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Valor *</label>
          <input id="lab-valor" type="number" step="0.01" class="form-input" placeholder="Ej. 11.5" />
        </div>
        <div>
          <label class="form-label">Unidad</label>
          <input id="lab-unidad" class="form-input" placeholder="g/dL" readonly />
        </div>
      </div>
      <div>
        <label class="form-label">Fecha *</label>
        <input id="lab-fecha" type="date" class="form-input" value="${hoy()}" />
      </div>
      <div>
        <label class="form-label">Observaciones</label>
        <input id="lab-obs" class="form-input" placeholder="Opcional" />
      </div>
      <div id="lab-error" class="text-red-600 text-sm hidden"></div>
    </div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">Cancelar</button>
     <button onclick="_guardarLab()" class="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">Guardar</button>`
  )
  labActualizarUnidad()
}

function labActualizarUnidad() {
  const tipo = $("lab-tipo")?.value
  const unid = $("lab-unidad"); if (!unid) return
  unid.value = tipo ? (LAB_CONFIG[tipo]?.unidad || "") : ""
}

async function _guardarLab() {
  const tipo  = $("lab-tipo")?.value
  const valor = parseFloat($("lab-valor")?.value)
  const fecha = $("lab-fecha")?.value
  const obs   = $("lab-obs")?.value || ""
  const unid  = LAB_CONFIG[tipo]?.unidad || $("lab-unidad")?.value || ""
  const errEl = $("lab-error")

  if (!tipo || isNaN(valor) || !fecha) {
    errEl.textContent = "Complete tipo, valor y fecha"; errEl.classList.remove("hidden"); return
  }
  try {
    await apiPost("/api/laboratorios", { paciente_id: _labPacId, fecha, tipo, valor, unidad: unid, observaciones: obs })
    _labData = await apiGet(`/api/laboratorios/${_labPacId}`)
    closeModal(); toast("Resultado guardado"); _renderLabsView()
  } catch (e) {
    errEl.textContent = e.message; errEl.classList.remove("hidden")
  }
}

async function labEliminar(id) {
  if (!confirm("¿Eliminar este resultado de laboratorio?")) return
  try {
    await apiDelete(`/api/laboratorios/${id}`)
    _labData = _labData.filter(l => l.id !== id)
    toast("Resultado eliminado"); _renderLabsView()
  } catch (e) { toast(e.message, "err") }
}

// ── FASE 5: Panel Clínico — filtrar todos los pacientes por parámetro ─────────

let _panelTipo = "Hb"

/** Función para determinar color y clase CSS según tipo y valor (Fase 5) */
function _panelColor(tipo, valor) {
  if (valor == null) return { cls: "text-slate-300", bgCls: "panel-none", label: "Sin dato" }

  // Escala especial para Hemoglobina
  if (tipo === "Hb") {
    if (valor < 6)  return { cls: "lab-ph6",  bgCls: "panel-ph6",  label: "Crítico" }
    if (valor < 10) return { cls: "lab-ph10", bgCls: "panel-ph10", label: "Bajo" }
    if (valor < 11) return { cls: "lab-ph11", bgCls: "panel-ph11", label: "Límite" }
    return { cls: "lab-ok", bgCls: "panel-ok", label: "Normal" }
  }

  // Escala especial para Hematocrito
  if (tipo === "Hto") {
    if (valor < 20) return { cls: "lab-ph6",  bgCls: "panel-ph6",  label: "Crítico" }
    if (valor < 30) return { cls: "lab-ph10", bgCls: "panel-ph10", label: "Bajo" }
    if (valor < 36) return { cls: "lab-ph11", bgCls: "panel-ph11", label: "Límite" }
    return { cls: "lab-ok", bgCls: "panel-ok", label: "Normal" }
  }

  // Para el resto: usar LAB_CONFIG min/max
  const cfg = LAB_CONFIG[tipo] || {}
  if (cfg.max != null && valor > cfg.max) return { cls: "lab-ph10", bgCls: "panel-ph10", label: "Alto" }
  if (cfg.min != null && valor < cfg.min) return { cls: "lab-ph11", bgCls: "panel-ph11", label: "Bajo" }
  return { cls: "lab-ok", bgCls: "panel-ok", label: "Normal" }
}

async function renderLabPanel(tipo = null) {
  G.vista = "labpanel"
  updateHeader()
  if (tipo) _panelTipo = tipo

  let datos = []
  try {
    datos = await apiGet(`/api/laboratorios/panel?tipo=${_panelTipo}`)
  } catch (e) { toast(e.message, "err"); return }

  const cfg      = LAB_CONFIG[_panelTipo] || {}
  const tipoOpts = Object.entries(LAB_CONFIG).map(([k, v]) =>
    `<option value="${k}" ${k === _panelTipo ? "selected" : ""}>${v.label}</option>`).join("")

  // Agrupar por estado para el resumen
  const sinDato  = datos.filter(d => d.valor == null).length
  const conDato  = datos.filter(d => d.valor != null)
  const ph6Count = conDato.filter(d => _panelColor(_panelTipo, d.valor).bgCls === "panel-ph6").length
  const ph10Count = conDato.filter(d => _panelColor(_panelTipo, d.valor).bgCls === "panel-ph10").length
  const ph11Count = conDato.filter(d => _panelColor(_panelTipo, d.valor).bgCls === "panel-ph11").length
  const okCount   = conDato.filter(d => _panelColor(_panelTipo, d.valor).bgCls === "panel-ok").length

  // Filas por estación
  const byEst = { 1: [], 2: [], 3: [] }
  datos.forEach(d => byEst[d.estacion]?.push(d))

  let rows = ""
  for (const est of [1, 2, 3]) {
    if (!byEst[est].length) continue
    rows += `<tr style="background:${EST_COLORS[est]}">
      <td colspan="7" class="text-white text-xs font-bold py-1 px-3">
        ESTACIÓN ${est} — MACRO ${EST_LABEL[est].toUpperCase()}
      </td>
    </tr>`
    // Ordenar: con dato primero (por valor asc para mostrar los más críticos arriba)
    byEst[est].sort((a, b) => {
      if (a.valor == null && b.valor != null) return 1
      if (a.valor != null && b.valor == null) return -1
      return (a.valor ?? 0) - (b.valor ?? 0)
    })
    byEst[est].forEach(d => {
      const { cls, bgCls, label } = _panelColor(_panelTipo, d.valor)
      rows += `<tr class="row-est-${est} ${bgCls}">
        <td class="font-mono font-bold text-xs">${displayCama(d.cama, d.estacion)}</td>
        <td class="font-medium text-sm">${d.nombre}</td>
        <td class="text-xs text-slate-500">${d.turno === "M" ? "Mañana" : d.turno === "T" ? "Tarde" : "Noche"}</td>
        <td class="text-xs text-slate-400">${d.medico || "—"}</td>
        <td class="text-right font-mono font-bold ${cls}">
          ${d.valor != null ? d.valor.toFixed(2) + " " + (cfg.unidad || "") : "—"}
        </td>
        <td class="text-center">
          <span class="text-xs font-semibold ${cls}">${label}</span>
        </td>
        <td class="text-xs text-slate-400">${d.fecha ? fmtFecha(d.fecha) : "—"}</td>
      </tr>`
    })
  }

  app().innerHTML = `
    <div class="max-w-5xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Panel Clínico — Filtro de Laboratorios</h2>
            <p class="text-slate-500 text-sm">Último valor de cada paciente activo para el parámetro seleccionado</p>
          </div>
          <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Inicio</button>
        </div>

        <!-- Selector de parámetro -->
        <div class="flex items-center gap-3 mb-5">
          <label class="text-sm font-semibold text-slate-600">Parámetro:</label>
          <select class="form-input form-select w-64" onchange="renderLabPanel(this.value)">
            ${tipoOpts}
          </select>
          ${cfg.min != null || cfg.max != null ? `
          <span class="text-xs text-slate-400 bg-slate-50 px-3 py-1 rounded-full border">
            Ref: ${cfg.min ?? "—"} – ${cfg.max ?? "—"} ${cfg.unidad || ""}
          </span>` : ""}
        </div>

        <!-- Leyenda de colores -->
        <div class="flex flex-wrap gap-2 mb-5">
          ${_panelTipo === "Hb" || _panelTipo === "Hto" ? `
            <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-purple-500 inline-block"></span>Crítico (Hb&lt;6)</span>
            <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-red-500 inline-block"></span>Bajo (Hb&lt;10)</span>
            <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-amber-500 inline-block"></span>Límite (Hb&lt;11)</span>
            <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-emerald-500 inline-block"></span>Normal (Hb≥11)</span>
          ` : `
            ${cfg.max != null ? `<span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-red-500 inline-block"></span>Alto (&gt;${cfg.max})</span>` : ""}
            ${cfg.min != null ? `<span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-amber-500 inline-block"></span>Bajo (&lt;${cfg.min})</span>` : ""}
            <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-emerald-500 inline-block"></span>Normal</span>
          `}
          <span class="flex items-center gap-1 text-xs"><span class="w-3 h-3 rounded bg-slate-200 inline-block"></span>Sin dato</span>
        </div>

        <!-- Resumen rápido -->
        <div class="grid grid-cols-2 md:grid-cols-5 gap-3 mb-5">
          ${[
            { l: "Total pacientes", v: datos.length, c: "bg-slate-50 border-slate-200 text-slate-700" },
            { l: "Críticos",        v: ph6Count,     c: "bg-purple-50 border-purple-200 text-purple-700" },
            { l: "Bajos",           v: ph10Count,    c: "bg-red-50 border-red-200 text-red-700" },
            { l: "Límite",          v: ph11Count,    c: "bg-amber-50 border-amber-200 text-amber-700" },
            { l: "Normales",        v: okCount,      c: "bg-emerald-50 border-emerald-200 text-emerald-700" },
          ].map(c => `<div class="rounded-xl border p-3 ${c.c}">
            <div class="text-2xl font-bold">${c.v}</div>
            <div class="text-xs font-medium mt-0.5">${c.l}</div>
          </div>`).join("")}
        </div>

        <!-- Tabla -->
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-stats w-full">
            <thead><tr>
              <th class="w-10">#</th>
              <th class="text-left">Paciente</th>
              <th class="text-left">Turno</th>
              <th class="text-left">Médico</th>
              <th class="text-right">${cfg.label || _panelTipo} (${cfg.unidad || ""})</th>
              <th>Estado</th>
              <th>Última muestra</th>
            </tr></thead>
            <tbody>
              ${rows || `<tr><td colspan="7" class="py-8 text-center text-slate-400">Sin datos</td></tr>`}
            </tbody>
          </table>
        </div>
        <p class="text-xs text-slate-400 mt-2">
          Los pacientes sin dato se muestran al final de cada estación.
          Para registrar laboratorios ve a Gestionar Pacientes → Labs.
        </p>
      </div>
    </div>
  `
}
