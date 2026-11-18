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

// R13: los rangos viven en el servidor (configurables). Se mezclan sobre LAB_CONFIG al abrir cada vista.
async function cargarRangosLab() {
  try {
    const rangos = await apiGet("/api/labs/rangos")
    rangos.forEach(r => {
      const c = LAB_CONFIG[r.tipo]; if (!c) return
      c.min = r.minimo; c.max = r.maximo; c.muy_alto = r.muy_alto
    })
  } catch (e) { /* se queda con los rangos por defecto de arriba */ }
}

const ESTADO_LAB = {
  bajo:      { txt: "Bajo",     sim: "▼",  orden: 2 },
  normal:    { txt: "Normal",   sim: "●",  orden: 4 },
  alto:      { txt: "Alto",     sim: "▲",  orden: 1 },
  muy_alto:  { txt: "Muy alto", sim: "▲▲", orden: 0 },
  sin_dato:  { txt: "Sin dato", sim: "—",  orden: 5 },
  sin_rango: { txt: "Sin rango", sim: "—", orden: 5 },
}
function estadoLabHTML(est) {
  const e = ESTADO_LAB[est] || ESTADO_LAB.sin_dato
  return `<span class="est-badge est-${est}"><span aria-hidden="true">${e.sim}</span>${e.txt}</span>`
}

let _labChart = null
let _labCmpChart = null
let _labCmpTipo = null
let _labCmpModo = "toma"
let _labPacId = null
let _labPacNombre = ""
let _labData = []
let _labSelTipo = null

// ── Vista principal de labs de un paciente ────────────────────────────────────
async function renderLabs(pacienteId, pacienteNombre = "", tipo = null) {
  G.vista = "labs"
  if (tipo) { _labSelTipo = tipo; _labCmpTipo = tipo }
  _labPacId = pacienteId
  _labPacNombre = pacienteNombre
  updateHeader()

  try {
    await cargarRangosLab()
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

        ${tiposConDatos.length ? `
        <section class="mb-5 bg-slate-50 rounded-xl p-4" aria-labelledby="cmp-titulo">
          <div class="flex flex-wrap items-end gap-3 mb-3">
            <h3 id="cmp-titulo" class="text-sm font-semibold text-slate-700 mr-auto">Comparación entre tomas y meses</h3>
            <div><label class="form-label" for="cmp-tipo">Examen</label>
              <select id="cmp-tipo" class="form-input form-select" onchange="labCmpCambiar(this.value, null)">
                ${tiposConDatos.map(t => `<option value="${t}" ${t === (_labCmpTipo || tiposConDatos[0]) ? "selected" : ""}>${LAB_CONFIG[t]?.label || t}</option>`).join("")}
              </select></div>
            <div role="group" aria-label="Agrupar por" class="flex gap-1">
              <button class="chip-filtro" aria-pressed="${_labCmpModo === "toma"}" onclick="labCmpCambiar(null,'toma')">Por toma</button>
              <button class="chip-filtro" aria-pressed="${_labCmpModo === "mes"}" onclick="labCmpCambiar(null,'mes')">Promedio por mes</button>
            </div>
          </div>
          <div style="position:relative; height:240px"><canvas id="lab-cmp-chart" role="img" aria-label="Gráfica comparativa del examen seleccionado"></canvas></div>
          <div id="lab-cmp-tabla" class="mt-3 overflow-x-auto"></div>
        </section>` : ""}

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
  if (tiposConDatos.length) {
    if (!tiposConDatos.includes(_labCmpTipo)) _labCmpTipo = tiposConDatos[0]
    _cargarComparativa()
  }
}

function labCmpCambiar(tipo, modo) {
  if (tipo) _labCmpTipo = tipo
  if (modo) _labCmpModo = modo
  _renderLabsView()
}

// R13: comparación por toma o por mes (estados según los rangos configurados en el servidor)
async function _cargarComparativa() {
  let d
  try { d = await apiGet(`/api/labs/comparativa/${_labPacId}?tipo=${_labCmpTipo}`) } catch (e) { toast(e.message, "err"); return }
  const canvas = $("lab-cmp-chart"); if (!canvas) return
  if (_labCmpChart) { _labCmpChart.destroy(); _labCmpChart = null }
  const cfg = LAB_CONFIG[_labCmpTipo] || {}
  const COL = { bajo: "#d97706", normal: "#059669", alto: "#ea580c", muy_alto: "#dc2626", sin_rango: "#64748b" }
  const porMes = _labCmpModo === "mes"
  const pts = porMes ? d.meses.map(m => ({ x: _mesLabel(m.mes), y: m.promedio, e: m.estado }))
                     : d.tomas.map(t => ({ x: fmtFecha(t.fecha), y: t.valor, e: t.estado }))
  const n = pts.length
  const datasets = [porMes
    ? { type: "bar", label: "Promedio del mes", data: pts.map(p => p.y), backgroundColor: pts.map(p => COL[p.e] || "#64748b") }
    : { type: "line", label: cfg.label || _labCmpTipo, data: pts.map(p => p.y), borderColor: "#1e40af", backgroundColor: "#1e40af22",
        tension: 0.25, pointRadius: 5, pointBackgroundColor: pts.map(p => COL[p.e] || "#64748b"), fill: false }]
  const ref = (v, etq) => v != null && datasets.push({ type: "line", label: etq, data: Array(n).fill(v), borderColor: "#94a3b8",
        borderDash: [4, 4], pointRadius: 0, borderWidth: 1, fill: false })
  ref(d.rango.minimo, `Mín (${d.rango.minimo})`); ref(d.rango.maximo, `Máx (${d.rango.maximo})`); ref(d.rango.muy_alto, `Muy alto (${d.rango.muy_alto})`)
  _labCmpChart = new Chart(canvas, {
    data: { labels: pts.map(p => p.x), datasets },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { boxWidth: 12, font: { size: 11 } } } },
      scales: { x: { ticks: { font: { size: 10 } } }, y: { ticks: { font: { size: 10 } } } } },
  })
  const filas = porMes
    ? d.meses.map(m => `<tr><td>${_mesLabel(m.mes)}</td><td class="text-right font-mono">${m.promedio.toFixed(2)}</td><td class="text-center">${m.tomas}</td>
        <td>${estadoLabHTML(m.estado)}</td><td class="text-right font-mono">${m.variacion == null ? "—" : (m.variacion > 0 ? "+" : "") + m.variacion.toFixed(2)}</td></tr>`)
    : d.tomas.map((t, i) => `<tr><td>${fmtFecha(t.fecha)}</td><td class="text-right font-mono">${t.valor.toFixed(2)}</td><td class="text-center">1</td>
        <td>${estadoLabHTML(t.estado)}</td><td class="text-right font-mono">${i ? ((t.valor - d.tomas[i-1].valor) > 0 ? "+" : "") + (t.valor - d.tomas[i-1].valor).toFixed(2) : "—"}</td></tr>`)
  $("lab-cmp-tabla").innerHTML = n ? `<table class="tbl-labs w-full"><thead><tr><th class="text-left">${porMes ? "Mes" : "Fecha"}</th>
      <th class="text-right">${porMes ? "Promedio" : "Valor"} ${cfg.unidad ? "(" + cfg.unidad + ")" : ""}</th><th>Tomas</th><th class="text-left">Estado</th><th class="text-right">Variación</th></tr></thead>
      <tbody>${filas.join("")}</tbody></table>` : `<p class="text-sm text-slate-500">Sin tomas de este examen.</p>`
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

// ── R13: Panel clínico — filtrar pacientes por estado del resultado ──────────

let _panelTipo = "Hb"
let _panelEstados = new Set()      // vacío = todos
let _panelMedico = ""
let _panelTurno = ""

const _TURNO_NOM = { M: "Mañana", T: "Tarde", N: "Noche" }

let _panelFilas = []
function panelComparar(id) {
  const f = _panelFilas.find(x => x.paciente_id === id)
  renderLabs(id, f ? f.nombre : "Paciente", _panelTipo)
}

function panelToggleEstado(e) {
  if (e === "todos") _panelEstados = new Set()
  else if (_panelEstados.has(e)) _panelEstados.delete(e)
  else _panelEstados.add(e)
  renderLabPanel()
}

async function renderLabPanel(tipo = null) {
  G.vista = "labpanel"
  updateHeader()
  if (typeof tipo === "string" && tipo) _panelTipo = tipo

  let d
  try {
    await cargarRangosLab()
    const q = new URLSearchParams({ tipo: _panelTipo })
    if (_panelEstados.size) q.set("estado", [..._panelEstados].join(","))
    if (_panelMedico) q.set("medico", _panelMedico)
    if (_panelTurno) q.set("turno", _panelTurno)
    d = await apiGet(`/api/labs/panel?${q}`)
  } catch (e) { toast(e.message, "err"); return }

  const cfg = LAB_CONFIG[_panelTipo] || {}
  const r = d.rango
  const tipoOpts = Object.entries(LAB_CONFIG).map(([k, v]) =>
    `<option value="${k}" ${k === _panelTipo ? "selected" : ""}>${v.label}</option>`).join("")
  const medOpts = [`<option value="">Todos los médicos</option>`,
    ...d.medicos.map(m => `<option value="${escHtml(m)}" ${m === _panelMedico ? "selected" : ""}>${escHtml(m)}</option>`)].join("")

  _panelFilas = d.pacientes
  const orden = e => (ESTADO_LAB[e] || ESTADO_LAB.sin_dato).orden
  const filas = [...d.pacientes].sort((a, b) => orden(a.estado) - orden(b.estado) || a.nombre.localeCompare(b.nombre))
  const rows = filas.map(f => `<tr>
      <td class="font-mono text-xs">${displayCama(f.cama, f.estacion)}</td>
      <td class="text-left font-medium">${escHtml(f.nombre)}</td>
      <td class="text-xs text-slate-600">${_TURNO_NOM[f.turno] || f.turno}</td>
      <td class="text-left text-xs text-slate-700">${escHtml(f.medico) || "—"}</td>
      <td class="text-right font-mono font-bold">${f.valor != null ? f.valor.toFixed(2) + " " + escHtml(f.unidad || "") : "—"}</td>
      <td>${estadoLabHTML(f.estado)}</td>
      <td class="text-xs text-slate-600">${f.fecha ? fmtFecha(f.fecha) : "—"}</td>
      <td><button class="text-blue-800 hover:underline text-xs btn-foco" onclick="panelComparar(${f.paciente_id})">Comparar</button></td>
    </tr>`).join("")

  const c = d.conteo
  const chips = [["todos", "Todos", d.total], ["bajo", "Bajo", c.bajo || 0], ["normal", "Normal", c.normal || 0],
                 ["alto", "Alto", c.alto || 0], ["muy_alto", "Muy alto", c.muy_alto || 0], ["sin_dato", "Sin dato", c.sin_dato || 0]]
    .map(([k, l, n]) => `<button class="chip-filtro" aria-pressed="${k === "todos" ? _panelEstados.size === 0 : _panelEstados.has(k)}"
        onclick="panelToggleEstado('${k}')">${l} (${n})</button>`).join("")

  app().innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Panel Clínico — Laboratorios por estado</h2>
            <p class="text-slate-500 text-sm">Último valor de cada paciente activo para el examen seleccionado</p>
          </div>
          <div class="flex gap-2">
            <button onclick="renderLabConfig()" class="solo-admin bg-slate-100 hover:bg-slate-200 text-slate-800 text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Rangos y Teams</button>
            <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">← Inicio</button>
          </div>
        </div>

        <div class="flex flex-wrap items-end gap-3 mb-3">
          <div><label class="form-label" for="pn-tipo">Examen</label>
            <select id="pn-tipo" class="form-input form-select" onchange="renderLabPanel(this.value)">${tipoOpts}</select></div>
          <div><label class="form-label" for="pn-med">Médico tratante</label>
            <select id="pn-med" class="form-input form-select" onchange="_panelMedico=this.value; renderLabPanel()">${medOpts}</select></div>
          <div><label class="form-label" for="pn-turno">Turno</label>
            <select id="pn-turno" class="form-input form-select" onchange="_panelTurno=this.value; renderLabPanel()">
              <option value="">Todos</option>${["M","T","N"].map(t => `<option value="${t}" ${t === _panelTurno ? "selected" : ""}>${_TURNO_NOM[t]}</option>`).join("")}</select></div>
          <span class="text-xs text-slate-700 bg-slate-50 px-3 py-1 rounded-full border">
            Rangos: bajo &lt; ${r.minimo ?? "—"} · normal hasta ${r.maximo ?? "—"} · muy alto &gt; ${r.muy_alto ?? "—"} ${escHtml(r.unidad || "")}${r.personalizado ? " (personalizado)" : ""}
          </span>
        </div>

        <div class="flex flex-wrap gap-2 mb-4" role="group" aria-label="Filtrar por estado del resultado">${chips}</div>

        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-stats w-full">
            <thead><tr>
              <th class="w-10">Cama</th><th class="text-left">Paciente</th><th>Turno</th><th class="text-left">Médico tratante</th>
              <th class="text-right">${escHtml(cfg.label || _panelTipo)} ${cfg.unidad ? "(" + escHtml(cfg.unidad) + ")" : ""}</th>
              <th>Estado</th><th>Última muestra</th><th><span class="sr-only">Acciones</span></th>
            </tr></thead>
            <tbody>${rows || `<tr><td colspan="8" class="py-8 text-center text-slate-500">Ningún paciente con ese filtro.</td></tr>`}</tbody>
          </table>
        </div>
        <p class="text-xs text-slate-500 mt-2">${filas.length} de ${d.total} pacientes activos. Los pacientes archivados no aparecen; sus resultados se conservan.
          El estado se calcula con los rangos configurados por el administrador.</p>
      </div>
    </div>`
}
