/* ============================================================
   Hoja Diaria — Unidad Renal  |  app.js  (Core v3)
   ============================================================ */

// ── Constantes ───────────────────────────────────────────────────────────────
const TURNOS     = { M: "Mañana", T: "Tarde", N: "Noche" }
const EST_LABEL  = { 1: "Amarilla", 2: "Azul", 3: "Roja" }
const EST_COLORS = { 1: "#a16207", 2: "#1d4ed8", 3: "#b91c1c" }
const SAVE_DELAY = 1500

// ── Estado global ─────────────────────────────────────────────────────────────
let G = {
  sesion:     null,
  registros:  [],
  vista:      "dashboard",
  saveTimers: {},
  pendientes: new Set(),
}

// ── Utilidades ────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id)
const app = () => $("app")

function hoy() { return new Date().toISOString().slice(0, 10) }

function fmtFecha(iso) {
  if (!iso) return ""
  const [y, m, d] = iso.split("-")
  return `${d}/${m}/${y}`
}

function fmtPeso(val) { return val == null ? "—" : Number(val).toFixed(1) }

/** Número de cama global 1-48 (en lugar de 1-16 por estación) */
function displayCama(cama, estacion) { return cama + (estacion - 1) * 16 }

function clsPerdida(perdida, ganancia) {
  if (perdida == null) return ""
  if (perdida > 4.5) return "perdida-crit"
  if (ganancia != null && perdida > ganancia) return "perdida-warn"
  return "perdida-ok"
}

/** Badge HTML de tipo de acceso vascular */
function accesoHTML(p) {
  if (!p || !p.acceso) return ""
  const cm = p.acceso_cm || 15
  const map = {
    CY:      `<span class="badge-acceso badge-cy">CY</span>`,
    FAV_L:   `<span class="badge-acceso badge-fav">FAV</span>`,
    FAV_AR:  `<span class="badge-acceso badge-fav-ar">FAV ⚠</span>`,
    FAV_ANE: `<span class="badge-acceso badge-fav-ane">⚠ ${cm}cm</span>`,
    F16:     `<span class="badge-acceso badge-fav">G16</span>`,
    F17:     `<span class="badge-acceso badge-fav">G17</span>`,
  }
  return map[p.acceso] || ""
}

/** Subtítulo informativo: filtro + dosis heparina calculada + watson */
function pacSubtxt(p) {
  if (!p) return ""
  const parts = []
  if (p.tipo_filtro) parts.push(p.tipo_filtro)
  if (p.heparina_unidades && p.peso_seco) {
    const dosis = Math.round(p.peso_seco * 4 * p.heparina_unidades)
    parts.push(`Hep: ${dosis} UI (${p.heparina_unidades} UI/h)`)
  }
  if (p.watson) parts.push(`V=${p.watson.toFixed(1)} L`)
  return parts.join(" · ")
}

// ── Toast ─────────────────────────────────────────────────────────────────────
let _toastTimer = null
function toast(msg, tipo = "ok") {
  const el = $("toast"), inner = $("toast-inner")
  inner.textContent = msg
  inner.className = "px-4 py-3 rounded-lg shadow-xl text-white text-sm font-medium"
  inner.classList.add(tipo === "ok" ? "bg-emerald-700" : tipo === "err" ? "bg-red-700" : "bg-amber-600")
  el.classList.remove("hidden")
  clearTimeout(_toastTimer)
  _toastTimer = setTimeout(() => el.classList.add("hidden"), 2800)
}

// ── API ───────────────────────────────────────────────────────────────────────
async function apiGet(path) {
  const r = await fetch(path)
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText) }
  return r.json()
}
async function apiPost(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText) }
  return r.json()
}
async function apiPatch(path, body) {
  const r = await fetch(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText) }
  return r.json()
}
async function apiPut(path, body) {
  const r = await fetch(path, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText) }
  return r.json()
}
async function apiDelete(path) {
  const r = await fetch(path, { method: "DELETE" })
  if (!r.ok && r.status !== 204) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText) }
}

// ── Modal global ──────────────────────────────────────────────────────────────
function openModal(title, bodyHTML, footerHTML) {
  $("modal-title").innerHTML = title
  $("modal-body").innerHTML  = bodyHTML
  $("modal-footer").innerHTML = footerHTML
  $("modal-overlay").classList.remove("hidden")
}
function closeModal() { $("modal-overlay").classList.add("hidden") }

// ── Header ────────────────────────────────────────────────────────────────────
function updateHeader() {
  const hasSesion = !!G.sesion
  const enSesion  = G.vista === "sesion"

  $("header-info").classList.toggle("hidden", !hasSesion)
  $("btn-inicio").classList.toggle("hidden", G.vista === "dashboard")
  $("btn-cierre").classList.toggle("hidden", !hasSesion || !enSesion)
  $("btn-programar").classList.toggle("hidden", !hasSesion || !enSesion)
  $("header-save").classList.toggle("hidden", !hasSesion)

  if (hasSesion) {
    $("header-fecha").textContent = fmtFecha(G.sesion.fecha)
    $("header-turno").textContent = TURNOS[G.sesion.turno]
    $("header-cerrada").classList.toggle("hidden", !G.sesion.cerrada)
  }
}

// ── VIEW: DASHBOARD ───────────────────────────────────────────────────────────
function goHome() {
  G.sesion = null; G.registros = []; G.vista = "dashboard"
  updateHeader(); renderDashboard()
}

let _turnoSel = "M"
let _estFiltro = 0
let _slotAllPacientes = null
let _reemplazoPac = null
let _reemplDropIdx = -1
function selTurno(t) {
  _turnoSel = t
  ;["M", "T", "N"].forEach(x => $("btn-" + x).classList.toggle("selected", x === t))
}

function renderDashboard() {
  G.vista = "dashboard"
  updateHeader()
  app().innerHTML = `
    <div class="max-w-lg mx-auto mt-10 space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-8">
        <div class="text-center mb-6">
          <div class="inline-flex items-center justify-center w-14 h-14 bg-blue-100 rounded-full mb-2">
            <svg class="w-7 h-7 text-blue-800" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </div>
          <h2 class="text-xl font-bold text-blue-900">Abrir sesión del día</h2>
        </div>
        <div class="mb-4">
          <label class="block text-sm font-semibold text-slate-600 mb-1">Fecha</label>
          <input type="date" id="inp-fecha" value="${hoy()}"
            class="w-full border border-slate-300 rounded-lg px-3 py-2 text-base focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
        <div class="mb-6">
          <label class="block text-sm font-semibold text-slate-600 mb-2">Turno</label>
          <div class="flex gap-2 justify-center">
            <button class="turno-btn selected" id="btn-M" onclick="selTurno('M')">Mañana</button>
            <button class="turno-btn" id="btn-T" onclick="selTurno('T')">Tarde</button>
            <button class="turno-btn" id="btn-N" onclick="selTurno('N')">Noche</button>
          </div>
        </div>
        <button onclick="abrirSesion()"
          class="w-full bg-blue-800 hover:bg-blue-700 text-white font-bold py-3 rounded-xl text-base transition-colors">
          Abrir sesión →
        </button>
        <div id="dash-error" class="text-red-600 text-sm text-center mt-3 hidden"></div>
      </div>

      <!-- Accesos rápidos -->
      <div class="grid grid-cols-2 gap-3">
        <button onclick="renderCRUD()"
          class="bg-white hover:bg-amber-50 border border-amber-200 text-amber-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">👥</div>
          <div class="font-semibold text-sm">Pacientes</div>
          <div class="text-xs text-slate-400 mt-0.5">CRUD · acceso · heparina · filtro</div>
        </button>
        <button onclick="renderHistorial()"
          class="bg-white hover:bg-blue-50 border border-blue-200 text-blue-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">📊</div>
          <div class="font-semibold text-sm">Historial</div>
          <div class="text-xs text-slate-400 mt-0.5">Por fecha / mes</div>
        </button>
        <button onclick="renderEstadisticas()"
          class="bg-white hover:bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">📈</div>
          <div class="font-semibold text-sm">Estadísticas</div>
          <div class="text-xs text-slate-400 mt-0.5">Sesiones por paciente / mes</div>
        </button>
        <button onclick="renderLabPanel()"
          class="bg-white hover:bg-purple-50 border border-purple-200 text-purple-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">🔬</div>
          <div class="font-semibold text-sm">Panel Labs (F5)</div>
          <div class="text-xs text-slate-400 mt-0.5">Hb, PTH, Ferritina… por color</div>
        </button>
        <button onclick="renderAutoProgram()"
          class="bg-white hover:bg-teal-50 border border-teal-200 text-teal-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">💊</div>
          <div class="font-semibold text-sm">EPO / Fe del mes</div>
          <div class="text-xs text-slate-400 mt-0.5">Auto-programación mensual</div>
        </button>
        <button onclick="renderIA(null, null)"
          class="bg-white hover:bg-indigo-50 border border-indigo-200 text-indigo-800 rounded-xl p-4 text-left shadow-sm">
          <div class="text-xl mb-1">🤖</div>
          <div class="font-semibold text-sm">IA Clínica (F4)</div>
          <div class="text-xs text-slate-400 mt-0.5">Consulta sobre historial del paciente</div>
        </button>
      </div>
    </div>
  `
}

async function abrirSesion() {
  const fecha = $("inp-fecha").value
  if (!fecha) { showError("dash-error", "Seleccione una fecha"); return }
  hideError("dash-error")
  try {
    G.sesion    = await apiGet(`/api/sesiones/${fecha}/${_turnoSel}`)
    G.registros = await apiGet(`/api/sesiones/${G.sesion.id}/registros`)
    G.vista = "sesion"; updateHeader(); renderSesion()
  } catch (e) { showError("dash-error", e.message) }
}

function showError(id, msg) { const el = $(id); el.textContent = msg; el.classList.remove("hidden") }
function hideError(id) { $(id).classList.add("hidden") }

// ── Drag & Drop de filas ──────────────────────────────────────────────────────
let _dragRow = null

function dragStart(e, tr) {
  _dragRow = tr
  e.dataTransfer.effectAllowed = "move"
  setTimeout(() => tr.classList.add("dragging"), 0)
}
function dragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = "move" }
function dragEnter(e, tr) { tr.classList.add("drag-over") }
function dragLeave(e, tr) { tr.classList.remove("drag-over") }
function dragDrop(e, tr) {
  e.stopPropagation()
  tr.classList.remove("drag-over")
  if (_dragRow && _dragRow !== tr) {
    const parent = tr.parentNode
    const srcSibling = _dragRow.nextSibling
    if (srcSibling === tr) {
      parent.insertBefore(tr, _dragRow)
    } else {
      parent.insertBefore(_dragRow, tr)
      if (srcSibling) parent.insertBefore(tr, srcSibling)
      else parent.appendChild(tr)
    }
  }
  _dragRow = null
}
function dragEnd(e, tr) {
  tr.classList.remove("dragging")
  document.querySelectorAll("tr.drag-over").forEach(r => r.classList.remove("drag-over"))
  _dragRow = null
}

// ── VIEW: SESIÓN ──────────────────────────────────────────────────────────────
function renderSesion(estFiltro = 0) {
  _estFiltro = estFiltro
  G.vista = "sesion"; updateHeader()
  const cerrada = G.sesion.cerrada

  const tabsCfg = [
    { est: 0, label: "Todas",                    on: "tab-todas",   off: "tab-todas-off" },
    { est: 1, label: "Est. 1 – Amarilla (1-16)", on: "tab-1-on",    off: "tab-1-off"     },
    { est: 2, label: "Est. 2 – Azul (17-32)",    on: "tab-2-on",    off: "tab-2-off"     },
    { est: 3, label: "Est. 3 – Roja (33-48)",    on: "tab-3-on",    off: "tab-3-off"     },
  ]
  const tabs = tabsCfg.map(t => {
    const cls = estFiltro === t.est ? t.on : t.off
    return `<button class="tab-est ${cls}" onclick="renderSesion(${t.est})">${t.label}</button>`
  }).join("")

  const regs   = (estFiltro === 0 ? G.registros : G.registros.filter(r => r.paciente?.estacion === estFiltro))
                  .filter(r => r.paciente?.activo !== false)
  const byEst  = { 1: [], 2: [], 3: [] }
  regs.forEach(r => { if (r.paciente) byEst[r.paciente.estacion]?.push(r) })

  // Ordenar: activos (A/sin_marcar) primero, NA después, H y F al final
  for (const est of [1, 2, 3]) {
    byEst[est].sort((a, b) => (a.paciente?.cama ?? 0) - (b.paciente?.cama ?? 0))
  }

  let tbodyHTML = ""
  const hnaRows = []

  for (const est of [1, 2, 3]) {
    const allEst = byEst[est]
    if (!allEst.length) continue

    const activos     = allEst.filter(r => r.asistencia !== "H" && r.asistencia !== "NA" && r.asistencia !== "F")
    const hna         = allEst.filter(r => r.asistencia === "H" || r.asistencia === "NA" || r.asistencia === "F")
    const conSuplente = hna.filter(r => r.asistencia === "H" && r.transitorio_paciente)

    hnaRows.push(...hna)

    // Mezclar activos y suplentes ordenados por cama del paciente original
    const filasPrinc = [...activos, ...conSuplente]
      .sort((a, b) => (a.paciente?.cama ?? 0) - (b.paciente?.cama ?? 0))

    if (!filasPrinc.length) continue

    tbodyHTML += `<tr class="row-estacion-hdr est-${est}"><td colspan="13">ESTACIÓN ${est} — MACRO ${EST_LABEL[est].toUpperCase()} · CAMAS ${(est-1)*16+1}–${est*16}</td></tr>`
    filasPrinc.forEach(r => {
      tbodyHTML += (r.asistencia === "H" && r.transitorio_paciente)
        ? buildRowSuplente(r, cerrada)
        : buildRow(r, cerrada)
    })
  }

  if (hnaRows.length) {
    hnaRows.sort((a, b) => {
      const prioA = a.asistencia === "H" ? 0 : a.asistencia === "NA" ? 1 : 2
      const prioB = b.asistencia === "H" ? 0 : b.asistencia === "NA" ? 1 : 2
      return prioA !== prioB ? prioA - prioB : (a.paciente?.cama ?? 0) - (b.paciente?.cama ?? 0)
    })
    tbodyHTML += `<tr class="row-hna-section-hdr"><td colspan="13">🏥&nbsp; HOSPITALIZADOS · NO ASISTEN · FALLECIDOS&nbsp;(${hnaRows.length})</td></tr>`
    hnaRows.forEach(r => { tbodyHTML += buildHnaRow(r, cerrada) })
  }

  const res = calcResumen(regs)

  app().innerHTML = `
    <div class="max-w-full">
      <div class="flex flex-wrap gap-2 mb-3 print:hidden">${tabs}
        ${cerrada ? '<span class="ml-auto text-red-600 font-bold text-sm self-center">SESIÓN CERRADA</span>' : ""}
      </div>

      <div class="flex flex-wrap gap-2 mb-3 text-sm print:hidden">
        <div class="bg-white rounded-lg px-3 py-1.5 border border-slate-200 shadow-sm">Total: <strong>${res.total}</strong></div>
        <div class="bg-emerald-50 rounded-lg px-3 py-1.5 border border-emerald-200"><span class="text-emerald-700 font-bold">A</span> ${res.A}</div>
        <div class="bg-slate-50 rounded-lg px-3 py-1.5 border border-slate-300"><span class="badge-NA">NA</span> ${res.NA}</div>
        <div class="bg-amber-50 rounded-lg px-3 py-1.5 border border-amber-200"><span class="text-amber-700 font-bold">H</span> ${res.H}</div>
        <div class="bg-red-50 rounded-lg px-3 py-1.5 border border-red-200"><span class="text-red-600 font-bold">F</span> ${res.F}</div>
        <div class="bg-orange-50 rounded-lg px-3 py-1.5 border border-orange-200">Sin marcar: <strong class="${res.sinMarcar > 0 ? "text-orange-600" : "text-slate-400"}">${res.sinMarcar}</strong></div>
        <div class="bg-blue-50 rounded-lg px-3 py-1.5 border border-blue-200">EPO: <strong class="text-blue-700">${res.epo}</strong></div>
        <div class="bg-orange-50 rounded-lg px-3 py-1.5 border border-orange-200">Fe: <strong class="text-orange-700">${res.hierro}</strong></div>
        <div class="ml-auto self-center"><span class="save-dot"></span><span id="save-status" class="text-xs text-slate-400">Guardado</span></div>
      </div>

      <div class="tbl-sesion-wrap bg-white">
        <table class="tbl-sesion">
          <thead>
            <tr>
              <th title="Cama 1-48 · Arrastra para mover">#</th>
              <th>Paciente / Acceso</th>
              <th>P.Seco</th>
              <th>Estado</th>
              <th>P.Ent.</th>
              <th>P.Sal.</th>
              <th>Pérd.</th>
              <th>GID</th>
              <th>EPO</th>
              <th>Fe</th>
              <th>Kt/V</th>
              <th title="Catéter: Citrato (C) / Hep.Sódica (HS)">Cat.</th>
              <th>Obs.</th>
            </tr>
          </thead>
          <tbody id="tbl-body">${tbodyHTML}</tbody>
        </table>
      </div>
      <p class="text-xs text-slate-400 mt-1.5 print:hidden">
        GID = Ganancia Interdialítica (Ent−P.Seco). Rojo si Pérd &gt;4.5 kg.
        Arrastra una fila por el número de cama para moverla. NA/H/F van al final de la estación.
      </p>
    </div>
  `
}

function buildRow(r, cerrada) {
  const p = r.paciente; if (!p) return ""
  const rowCls = r.asistencia === "F" ? "row-F"
               : r.asistencia === "H" ? "row-H"
               : r.asistencia === "NA" ? "row-NA" : ""
  const dis      = cerrada ? "disabled" : ""
  const perdCls  = clsPerdida(r.perdida_real, r.ganancia_id)
  const perdHTML = r.perdida_real != null ? `<span class="${perdCls}">${r.perdida_real.toFixed(2)}</span>` : "—"
  const gidHTML  = r.ganancia_id  != null ? `<span class="ganancia-val">${r.ganancia_id.toFixed(2)}</span>` : "—"
  const subtxt   = pacSubtxt(p)
  const hasTrans = !!r.transitorio_nombre

  const catCell = p.acceso === "CY" ? `<td>
    <label class="flex items-center gap-0.5 text-xs cursor-pointer select-none">
      <input type="checkbox" class="w-3 h-3" ${r.citrato ? "checked" : ""} ${dis}
        onchange="setCheck(${r.id},'citrato',this.checked)" title="Citrato" />C
    </label>
    <label class="flex items-center gap-0.5 text-xs cursor-pointer select-none">
      <input type="checkbox" class="w-3 h-3" ${r.heparina_sodica ? "checked" : ""} ${dis}
        onchange="setCheck(${r.id},'heparina_sodica',this.checked)" title="Heparina sódica" />HS
    </label>
  </td>` : `<td class="text-center text-slate-300 text-xs">—</td>`

  return `
    <tr class="row-est-${p.estacion} ${rowCls}" data-rid="${r.id}"
        draggable="true"
        ondragstart="dragStart(event,this)" ondragover="dragOver(event)"
        ondragenter="dragEnter(event,this)" ondragleave="dragLeave(event,this)"
        ondrop="dragDrop(event,this)" ondragend="dragEnd(event,this)">
      <td class="font-mono text-slate-500 text-xs text-center font-bold">${displayCama(p.cama, p.estacion)}</td>
      <td>
        <div class="flex items-center gap-1.5">
          ${accesoHTML(p)}
          <div>
            <span class="font-medium text-sm ${hasTrans ? "line-through text-slate-400" : ""}">${p.nombre}</span>
            ${subtxt ? `<span class="pac-subtxt">${subtxt}</span>` : ""}
          </div>
          ${!cerrada ? `<button class="btn-reemplazar" onclick="abrirModalReemplazar(${r.id})" title="Reemplazar este paciente hoy">↕</button>` : ""}
        </div>
      </td>
      <td class="text-slate-500 text-xs">${fmtPeso(p.peso_seco)}</td>
      <td>
        <div class="flex gap-0.5">
          <button class="btn-asist ${r.asistencia === "A"  ? "active-A"  : ""}" ${dis} onclick="setAsistencia(${r.id},'A')">A</button>
          <button class="btn-asist ${r.asistencia === "NA" ? "active-NA" : ""}" ${dis} onclick="setAsistencia(${r.id},'NA')">NA</button>
          <button class="btn-asist ${r.asistencia === "H"  ? "active-H"  : ""}" ${dis} onclick="setAsistencia(${r.id},'H')">H</button>
          <button class="btn-asist ${r.asistencia === "F"  ? "active-F"  : ""}" ${dis} onclick="setAsistencia(${r.id},'F')">F</button>
        </div>
      </td>
      <td><input type="number" step="0.1" min="30" max="150" class="peso-input" value="${r.peso_entrada ?? ""}"
          placeholder="kg" ${dis} oninput="schedSave(${r.id},'peso_entrada',this.value)" /></td>
      <td><input type="number" step="0.1" min="30" max="150" class="peso-input" value="${r.peso_salida ?? ""}"
          placeholder="kg" ${dis} oninput="schedSave(${r.id},'peso_salida',this.value)" /></td>
      <td class="text-center cell-perdida">${perdHTML}</td>
      <td class="text-center cell-gid">${gidHTML}</td>
      <td class="text-center"><input type="checkbox" class="chk-epo" ${r.epo ? "checked" : ""} ${dis}
          onchange="setCheck(${r.id},'epo',this.checked)" /></td>
      <td class="text-center"><input type="checkbox" class="chk-hierro" ${r.hierro ? "checked" : ""} ${dis}
          onchange="setCheck(${r.id},'hierro',this.checked)" /></td>
      <td><input type="number" step="0.01" min="0" max="5" class="ktv-input"
          value="${r.ktv != null ? r.ktv : ""}" placeholder="—" ${dis}
          oninput="schedSave(${r.id},'ktv',this.value)" /></td>
      ${catCell}
      <td><input type="text" class="obs-input" value="${r.observaciones || ""}" placeholder="…" ${dis}
          oninput="schedSave(${r.id},'observaciones',this.value)" /></td>
    </tr>`
}

function buildRowSuplente(r, cerrada) {
  const posP = r.paciente;           if (!posP) return ""
  const p    = r.transitorio_paciente; if (!p)   return ""
  const dis     = cerrada ? "disabled" : ""
  const perdCls = clsPerdida(r.perdida_real, r.ganancia_id)
  const perdHTML = r.perdida_real != null ? `<span class="${perdCls}">${r.perdida_real.toFixed(2)}</span>` : "—"
  const gidHTML  = r.ganancia_id  != null ? `<span class="ganancia-val">${r.ganancia_id.toFixed(2)}</span>` : "—"
  const subtxt  = pacSubtxt(p)

  const catCell = p.acceso === "CY" ? `<td>
    <label class="flex items-center gap-0.5 text-xs cursor-pointer select-none">
      <input type="checkbox" class="w-3 h-3" ${r.citrato ? "checked" : ""} ${dis}
        onchange="setCheck(${r.id},'citrato',this.checked)" title="Citrato" />C
    </label>
    <label class="flex items-center gap-0.5 text-xs cursor-pointer select-none">
      <input type="checkbox" class="w-3 h-3" ${r.heparina_sodica ? "checked" : ""} ${dis}
        onchange="setCheck(${r.id},'heparina_sodica',this.checked)" title="Heparina sódica" />HS
    </label>
  </td>` : `<td class="text-center text-slate-300 text-xs">—</td>`

  return `
    <tr class="row-est-${posP.estacion} row-suplente" data-rid="${r.id}"
        draggable="${!cerrada}"
        ondragstart="dragStart(event,this)" ondragover="dragOver(event)"
        ondragenter="dragEnter(event,this)" ondragleave="dragLeave(event,this)"
        ondrop="dragDrop(event,this)" ondragend="dragEnd(event,this)">
      <td class="font-mono text-slate-500 text-xs text-center font-bold">${displayCama(posP.cama, posP.estacion)}</td>
      <td>
        <div class="flex items-center gap-1.5">
          ${accesoHTML(p)}
          <div>
            <span class="font-medium text-sm">${p.nombre}</span>
            ${subtxt ? `<span class="pac-subtxt">${subtxt}</span>` : ""}
          </div>
          ${!cerrada ? `<button class="btn-restaurar btn-restaurar-hover" onclick="restaurarPaciente(${r.id})" title="Restaurar paciente original">↩</button>` : ""}
        </div>
      </td>
      <td class="text-slate-500 text-xs">${fmtPeso(p.peso_seco)}</td>
      <td>
        <div class="flex gap-0.5">
          <button class="btn-asist ${r.transitorio_asistencia === "A"  ? "active-A"  : ""}" ${dis} onclick="setTransitorioAsistencia(${r.id},'A')">A</button>
          <button class="btn-asist ${r.transitorio_asistencia === "NA" ? "active-NA" : ""}" ${dis} onclick="setTransitorioAsistencia(${r.id},'NA')">NA</button>
          <button class="btn-asist ${r.transitorio_asistencia === "H"  ? "active-H"  : ""}" ${dis} onclick="setTransitorioAsistencia(${r.id},'H')">H</button>
          <button class="btn-asist ${r.transitorio_asistencia === "F"  ? "active-F"  : ""}" ${dis} onclick="setTransitorioAsistencia(${r.id},'F')">F</button>
        </div>
      </td>
      <td><input type="number" step="0.1" min="30" max="150" class="peso-input" value="${r.peso_entrada ?? ""}"
          placeholder="kg" ${dis} oninput="schedSave(${r.id},'peso_entrada',this.value)" /></td>
      <td><input type="number" step="0.1" min="30" max="150" class="peso-input" value="${r.peso_salida ?? ""}"
          placeholder="kg" ${dis} oninput="schedSave(${r.id},'peso_salida',this.value)" /></td>
      <td class="text-center cell-perdida">${perdHTML}</td>
      <td class="text-center cell-gid">${gidHTML}</td>
      <td class="text-center"><input type="checkbox" class="chk-epo" ${r.epo ? "checked" : ""} ${dis}
          onchange="setCheck(${r.id},'epo',this.checked)" /></td>
      <td class="text-center"><input type="checkbox" class="chk-hierro" ${r.hierro ? "checked" : ""} ${dis}
          onchange="setCheck(${r.id},'hierro',this.checked)" /></td>
      <td><input type="number" step="0.01" min="0" max="5" class="ktv-input"
          value="${r.ktv != null ? r.ktv : ""}" placeholder="—" ${dis}
          oninput="schedSave(${r.id},'ktv',this.value)" /></td>
      ${catCell}
      <td><input type="text" class="obs-input" value="${r.observaciones || ""}" placeholder="…" ${dis}
          oninput="schedSave(${r.id},'observaciones',this.value)" /></td>
    </tr>`
}

function buildHnaRow(r, cerrada) {
  const p = r.paciente; if (!p) return ""
  const badgeMap = {
    H:  '<span class="badge-H font-bold">H</span>',
    NA: '<span class="badge-NA font-bold">NA</span>',
    F:  '<span class="badge-F font-bold">F</span>',
  }
  const badge = badgeMap[r.asistencia] || ""
  const camaGlobal = displayCama(p.cama, p.estacion)
  const rowCls = r.asistencia === "F" ? "row-F" : r.asistencia === "H" ? "row-H" : "row-NA"
  return `
    <tr class="${rowCls}" data-rid="${r.id}">
      <td class="font-mono text-slate-400 text-xs text-center">${camaGlobal}</td>
      <td>
        <div class="flex items-center gap-2">
          ${badge}
          <div>
            <span class="font-medium text-sm">${p.nombre}</span>
            <span class="pac-subtxt">Est. ${EST_LABEL[p.estacion]} · Cama ${camaGlobal}</span>
            ${r.transitorio_nombre ? `<span class="pac-subtxt text-amber-700">→ Cama ocupada por: <strong>${r.transitorio_nombre}</strong></span>` : ""}
          </div>
        </div>
      </td>
      <td class="text-slate-400 text-xs">${fmtPeso(p.peso_seco)}</td>
      <td colspan="10">
        <div class="flex items-center gap-2">
          ${!cerrada && r.asistencia !== "F" ? `<button class="btn-restaurar" onclick="restaurarPaciente(${r.id})" title="Restaurar al puesto">↩ Restaurar</button>` : ""}
          <input type="text" class="obs-input" value="${r.observaciones || ""}" placeholder="Observación…"
            ${cerrada ? "disabled" : ""}
            oninput="schedSave(${r.id},'observaciones',this.value)" />
        </div>
      </td>
    </tr>`
}

function abrirModalReemplazar(rid) {
  const r = getReg(rid); if (!r) return
  _reemplazoPac = null
  _reemplDropIdx = -1
  openModal(
    `Reemplazar a ${r.paciente.nombre}`,
    `<p class="text-sm text-slate-500 mb-3">El paciente original quedará en la zona de Hospitalizados. La cama será ocupada hoy por el sustituto.</p>
     <label class="form-label">Paciente sustituto</label>
     <div class="slot-search-wrap mt-1">
       <input type="text" class="slot-input" id="modal-reempl-inp" style="width:100%"
              placeholder="Escriba nombre o cédula para buscar…"
              oninput="modalReemplSugerir(${rid})"
              onfocus="slotCargarLista()"
              onkeydown="modalReemplKeyNav(event,${rid})"
              onblur="setTimeout(()=>document.getElementById('modal-reempl-drop')?.classList.add('hidden'),150)"
              autocomplete="off" />
       <div class="slot-dropdown hidden" id="modal-reempl-drop"></div>
     </div>
     <div id="modal-reempl-sel" class="hidden mt-2 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-sm text-emerald-800"></div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg font-medium">Cancelar</button>
     <button onclick="confirmarReemplazo(${rid})" class="bg-amber-600 hover:bg-amber-500 text-white text-sm px-4 py-2 rounded-lg font-medium ml-2">Confirmar</button>`
  )
  _slotAllPacientes = null  // forzar recarga de lista al abrir
  setTimeout(() => { slotCargarLista(); document.getElementById("modal-reempl-inp")?.focus() }, 60)
}

function modalReemplSugerir(rid) {
  const r = getReg(rid)
  const txt = document.getElementById("modal-reempl-inp")?.value?.trim() || ""
  const drop = document.getElementById("modal-reempl-drop")
  if (!drop) return
  if (txt.length < 1) { drop.classList.add("hidden"); drop.innerHTML = ""; return }

  const lista = _slotAllPacientes || []
  const lower = txt.toLowerCase()
  const matches = lista
    .filter(p => p.id !== r?.paciente?.id)
    .filter(p => p.nombre.toLowerCase().includes(lower) || (p.cedula || "").includes(txt))
    .slice(0, 8)

  if (!matches.length) { drop.classList.add("hidden"); drop.innerHTML = ""; return }

  drop.innerHTML = matches.map((p, idx) => {
    const camaGlobal = displayCama(p.cama, p.estacion)
    const otroTurno = p.turno !== G.sesion.turno
    return `
      <div class="slot-drop-item" id="modal-reempl-item-${idx}"
           onmousedown="modalReemplSeleccionar(${p.id})">
        ${accesoHTML(p)}
        <div class="flex-1 min-w-0">
          <span class="font-semibold text-slate-800 text-sm">${p.nombre}</span>
          <span class="text-slate-400 text-xs ml-1.5">${EST_LABEL[p.estacion]} · Cama ${camaGlobal}</span>
          ${otroTurno ? `<span class="text-amber-600 text-xs ml-1">⚠ ${TURNOS[p.turno]}</span>` : ""}
        </div>
        <span class="text-xs text-slate-300 shrink-0">${p.cedula || ""}</span>
      </div>`
  }).join("")

  _reemplDropIdx = -1
  drop.classList.remove("hidden")
}

function modalReemplSeleccionar(pacienteId) {
  const p = (_slotAllPacientes || []).find(x => x.id === pacienteId)
  if (!p) return
  _reemplazoPac = p
  document.getElementById("modal-reempl-drop")?.classList.add("hidden")
  const inp = document.getElementById("modal-reempl-inp")
  if (inp) inp.value = p.nombre
  const sel = document.getElementById("modal-reempl-sel")
  if (sel) {
    const camaGlobal = displayCama(p.cama, p.estacion)
    const otroTurno = p.turno !== G.sesion.turno
    sel.innerHTML = `✔ <strong>${p.nombre}</strong> · ${EST_LABEL[p.estacion]} · Cama ${camaGlobal}${otroTurno ? ` · <span class="text-amber-600">⚠ ${TURNOS[p.turno]}</span>` : ""}`
    sel.classList.remove("hidden")
  }
}

function modalReemplKeyNav(e, rid) {
  const drop = document.getElementById("modal-reempl-drop")
  const hidden = !drop || drop.classList.contains("hidden")
  if (hidden) { if (e.key === "Enter") confirmarReemplazo(rid); return }
  const items = drop.querySelectorAll(".slot-drop-item")
  if (!items.length) return
  if (e.key === "ArrowDown") {
    e.preventDefault()
    _reemplDropIdx = Math.min(_reemplDropIdx + 1, items.length - 1)
  } else if (e.key === "ArrowUp") {
    e.preventDefault()
    _reemplDropIdx = Math.max(_reemplDropIdx - 1, 0)
  } else if (e.key === "Enter") {
    e.preventDefault()
    if (_reemplDropIdx >= 0 && items[_reemplDropIdx]) items[_reemplDropIdx].dispatchEvent(new MouseEvent("mousedown"))
    return
  } else if (e.key === "Escape") {
    drop.classList.add("hidden"); return
  } else { return }
  items.forEach((el, idx) => el.classList.toggle("active", idx === _reemplDropIdx))
  items[_reemplDropIdx]?.scrollIntoView({ block: "nearest" })
}

async function confirmarReemplazo(rid) {
  const nombre = _reemplazoPac?.nombre || document.getElementById("modal-reempl-inp")?.value?.trim()
  if (!nombre) { toast("Seleccione el paciente sustituto", "warn"); return }
  closeModal()
  try {
    await patchRegistro(rid, {
      asistencia: "H",
      transitorio_nombre: nombre,
      transitorio_paciente_id: _reemplazoPac?.id ?? null,
    })
    G.registros = await apiGet(`/api/sesiones/${G.sesion.id}/registros`)
    renderSesion(_estFiltro)
    toast(`${nombre} asignado a la cama`)
  } catch (e) { toast(e.message, "err") }
}

async function restaurarPaciente(rid) {
  const r = getReg(rid); if (!r) return
  const nom = r.paciente?.nombre || ""
  try {
    await patchRegistro(rid, { asistencia: null, transitorio_nombre: "", transitorio_paciente_id: null, transitorio_asistencia: null })
    G.registros = await apiGet(`/api/sesiones/${G.sesion.id}/registros`)
    renderSesion(_estFiltro)
    toast(`${nom} restaurado a su puesto`)
  } catch (e) { toast(e.message, "err") }
}

// ── Caché de pacientes para búsqueda en modal ────────────────────────────────

async function slotCargarLista() {
  if (_slotAllPacientes) return
  try { _slotAllPacientes = await apiGet("/api/pacientes?activo=true") } catch (_) {}
}

function calcResumen(regs) {
  return {
    total:     regs.length,
    A:         regs.filter(r => r.asistencia === "A").length,
    NA:        regs.filter(r => r.asistencia === "NA").length,
    H:         regs.filter(r => r.asistencia === "H").length,
    F:         regs.filter(r => r.asistencia === "F").length,
    sinMarcar: regs.filter(r => !r.asistencia).length,
    epo:       regs.filter(r => r.epo   && r.asistencia === "A").length,
    hierro:    regs.filter(r => r.hierro && r.asistencia === "A").length,
  }
}

// ── Actualización quirúrgica (no destruye inputs en foco) ────────────────────
function updateCalculatedCells(id) {
  const r = getReg(id); if (!r) return
  const tr = document.querySelector(`tr[data-rid="${id}"]`); if (!tr) return
  const perdCell = tr.querySelector(".cell-perdida")
  const gidCell  = tr.querySelector(".cell-gid")
  if (perdCell) perdCell.innerHTML = r.perdida_real != null
    ? `<span class="${clsPerdida(r.perdida_real, r.ganancia_id)}">${r.perdida_real.toFixed(2)}</span>` : "—"
  if (gidCell)  gidCell.innerHTML  = r.ganancia_id  != null
    ? `<span class="ganancia-val">${r.ganancia_id.toFixed(2)}</span>` : "—"
}

// ── Mutaciones de estado ──────────────────────────────────────────────────────
function getReg(id) { return G.registros.find(r => r.id === id) }

function updateRegLocal(id, patch) {
  const r = getReg(id); if (!r) return
  Object.assign(r, patch)
  if (r.peso_entrada != null && r.peso_salida != null)
    r.perdida_real = Math.round((r.peso_entrada - r.peso_salida) * 100) / 100
  else r.perdida_real = null
  if (r.peso_entrada != null && r.paciente?.peso_seco != null)
    r.ganancia_id = Math.round((r.peso_entrada - r.paciente.peso_seco) * 100) / 100
  else r.ganancia_id = null
  if (r.peso_salida != null && r.paciente?.peso_seco != null)
    r.balance_seco = Math.round((r.peso_salida - r.paciente.peso_seco) * 100) / 100
  else r.balance_seco = null
}

async function patchRegistro(id, data) {
  try {
    setSaveStatus(true)
    const updated = await apiPatch(`/api/sesiones/registros/${id}`, data)
    updateRegLocal(id, updated)
    setSaveStatus(false)
    updateCalculatedCells(id)
  } catch (e) {
    setSaveStatus(false); toast(e.message, "err")
  }
}

function schedSave(id, field, value) {
  let parsed
  if (field === "peso_entrada" || field === "peso_salida" || field === "ktv")
    parsed = value === "" ? null : parseFloat(value)
  else
    parsed = value

  updateRegLocal(id, { [field]: parsed })
  if (field === "peso_entrada" || field === "peso_salida") updateCalculatedCells(id)

  clearTimeout(G.saveTimers[id + field])
  G.pendientes.add(id + field)
  setSaveStatus(true)
  G.saveTimers[id + field] = setTimeout(async () => {
    G.pendientes.delete(id + field)
    const r = getReg(id); if (!r) return
    const payload = {}
    if      (field === "peso_entrada")       payload.peso_entrada       = r.peso_entrada
    else if (field === "peso_salida")        payload.peso_salida        = r.peso_salida
    else if (field === "observaciones")      payload.observaciones      = r.observaciones
    else if (field === "ktv")               payload.ktv                = r.ktv
    else if (field === "transitorio_nombre") payload.transitorio_nombre = r.transitorio_nombre
    await patchRegistro(id, payload)
  }, SAVE_DELAY)
}

function setCheck(id, field, checked) {
  updateRegLocal(id, { [field]: checked })
  patchRegistro(id, { [field]: checked })
}

async function setAsistencia(id, estado) {
  const r = getReg(id); if (!r) return
  const nuevo = r.asistencia === estado ? null : estado
  updateRegLocal(id, { asistencia: nuevo })
  await patchRegistro(id, { asistencia: nuevo })
  refreshRow(id)
}

async function setTransitorioAsistencia(id, estado) {
  const r = getReg(id); if (!r) return
  const nuevo = r.transitorio_asistencia === estado ? null : estado
  updateRegLocal(id, { transitorio_asistencia: nuevo })
  await patchRegistro(id, { transitorio_asistencia: nuevo })
  refreshRow(id)
}

function refreshRow(id) {
  const r = getReg(id); if (!r) return
  const tr = document.querySelector(`tr[data-rid="${id}"]`); if (!tr) return
  const tmp = document.createElement("tbody")
  const isSuplente = r.asistencia === "H" && r.transitorio_paciente
  tmp.innerHTML = isSuplente ? buildRowSuplente(r, G.sesion.cerrada) : buildRow(r, G.sesion.cerrada)
  const newTr = tmp.firstElementChild
  if (newTr) tr.replaceWith(newTr)
}

function setSaveStatus(pending) {
  const dot = document.querySelector(".save-dot")
  if (dot) dot.classList.toggle("pending", pending)
  const lbl = $("save-status")
  if (lbl) lbl.textContent = pending ? "Guardando…" : "Guardado"
}

// ── VIEW: CIERRE ──────────────────────────────────────────────────────────────
$("btn-cierre").addEventListener("click", renderCierre)

async function renderCierre() {
  G.vista = "cierre"; updateHeader()
  let data
  try { data = await apiGet(`/api/cierre/${G.sesion.id}`) }
  catch (e) { toast(e.message, "err"); return }

  const { sesion, estaciones, totales } = data

  function fila(f, cls = "") {
    const est = f.estacion === 0 ? "TOTAL" : `Est. ${f.estacion} (${EST_LABEL[f.estacion]})`
    return `<tr class="${cls}">
      <td class="text-left">${est}</td>
      <td>${f.total}</td>
      <td class="${cls ? "" : "badge-A"}">${f.asistidos}</td>
      <td class="${cls ? "" : "badge-NA"}">${f.no_asiste}</td>
      <td class="${cls ? "" : "badge-H"}">${f.hospitalizados}</td>
      <td class="${cls ? "" : "badge-F"}">${f.fallecidos}</td>
      <td class="${f.sin_marcar > 0 && !cls ? "text-orange-500 font-bold" : ""}">${f.sin_marcar}</td>
      <td class="${cls ? "" : "text-blue-700 font-semibold"}">${f.epo_count}</td>
      <td class="${cls ? "" : "text-amber-700 font-semibold"}">${f.hierro_count}</td>
    </tr>`
  }

  app().innerHTML = `
    <div class="max-w-3xl mx-auto">
      <div class="bg-white rounded-2xl shadow-xl p-6 print-section">
        <div class="flex items-start justify-between mb-5 print:mb-3">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Cierre de sesión</h2>
            <p class="text-slate-500 text-sm mt-0.5">${fmtFecha(sesion.fecha)} · ${TURNOS[sesion.turno]}
              ${sesion.cerrada ? '<span class="ml-2 text-red-600 font-semibold text-xs">CERRADA</span>' : ""}</p>
          </div>
          <div class="flex gap-2 print:hidden">
            <button onclick="window.print()"
              class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">Imprimir</button>
            ${!sesion.cerrada
              ? `<button onclick="cerrarSesion()" class="bg-red-600 hover:bg-red-500 text-white text-sm px-3 py-1.5 rounded-lg font-medium">Cerrar sesión definitivo</button>`
              : `<button onclick="reabrirSesion()" class="bg-slate-600 hover:bg-slate-500 text-white text-sm px-3 py-1.5 rounded-lg font-medium">Reabrir sesión</button>`}
          </div>
        </div>

        <div class="overflow-x-auto mb-6">
          <table class="tbl-cierre w-full">
            <thead><tr>
              <th class="text-left">Estación</th><th>Total</th>
              <th>A</th><th>NA</th><th>H</th><th>F</th>
              <th>Sin marcar</th><th>EPO</th><th>Fe</th>
            </tr></thead>
            <tbody>
              ${estaciones.map(e => fila(e)).join("")}
              ${fila(totales, "total-row")}
            </tbody>
          </table>
        </div>

        <!-- 4 Firmas -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-6 mt-10 print-section">
          ${[
            { label: "Macro Est. Amarilla", color: "#a16207" },
            { label: "Macro Est. Azul",     color: "#1d4ed8" },
            { label: "Macro Est. Roja",     color: "#b91c1c" },
            { label: "Jefe de Enfermería",  color: "#1e3a5f" },
          ].map(f => `
            <div class="text-center">
              <div class="h-12 border-b-2 mb-2" style="border-color:${f.color}"></div>
              <p class="text-xs font-semibold" style="color:${f.color}">${f.label}</p>
            </div>
          `).join("")}
        </div>
      </div>

      <div class="mt-4 flex gap-3 print:hidden">
        <button onclick="renderSesion()" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg font-medium">← Volver a la sesión</button>
      </div>
    </div>
  `
}

async function cerrarSesion() {
  if (!confirm("¿Cerrar la sesión definitivamente? Los registros quedarán bloqueados.")) return
  try { G.sesion = await apiPost(`/api/cierre/${G.sesion.id}/cerrar`, {}); toast("Sesión cerrada"); renderCierre() }
  catch (e) { toast(e.message, "err") }
}
async function reabrirSesion() {
  if (!confirm("¿Reabrir la sesión?")) return
  try {
    G.sesion    = await apiPost(`/api/cierre/${G.sesion.id}/reabrir`, {})
    G.registros = await apiGet(`/api/sesiones/${G.sesion.id}/registros`)
    toast("Sesión reabierta"); renderCierre()
  } catch (e) { toast(e.message, "err") }
}

// ── VIEW: PROGRAMACIÓN ────────────────────────────────────────────────────────
$("btn-programar").addEventListener("click", renderProgramacion)

async function renderProgramacion() {
  G.vista = "programacion"; updateHeader()
  const mañana = new Date(G.sesion.fecha); mañana.setDate(mañana.getDate() + 1)
  const fechaSig = mañana.toISOString().slice(0, 10)
  const turnoSig = G.sesion.turno
  const pacientes = G.registros.map(r => r.paciente).filter(Boolean)

  const checkMap = {}, epoMap = {}, hierroMap = {}
  pacientes.forEach(p => {
    const reg = G.registros.find(r => r.paciente_id === p.id)
    checkMap[p.id]  = reg?.asistencia !== "F" && reg?.asistencia !== "NA"
    epoMap[p.id]    = reg?.epo    || false
    hierroMap[p.id] = reg?.hierro || false
  })

  window.toggleIncl   = (pid, v) => { checkMap[pid]  = v }
  window.toggleEpo    = (pid, v) => { epoMap[pid]    = v }
  window.toggleHierro = (pid, v) => { hierroMap[pid] = v }

  window.guardarProgramacion = async function () {
    const fecha = $("prog-fecha").value
    const turno = document.querySelector("input[name=prog-turno]:checked")?.value
    if (!fecha || !turno) { toast("Complete fecha y turno", "warn"); return }
    const items = pacientes.filter(p => checkMap[p.id])
      .map(p => ({ paciente_id: p.id, epo_programado: epoMap[p.id] || false, hierro_programado: hierroMap[p.id] || false }))
    try {
      await apiPost("/api/programacion", { fecha, turno, items })
      toast(`Programación guardada — ${items.length} pacientes para ${fmtFecha(fecha)} ${TURNOS[turno]}`)
      renderSesion()
    } catch (e) { toast(e.message, "err") }
  }

  const byEst = { 1: [], 2: [], 3: [] }
  pacientes.forEach(p => byEst[p.estacion]?.push(p))
  let rows = ""
  for (const est of [1, 2, 3]) {
    if (!byEst[est].length) continue
    rows += `<tr style="background:${EST_COLORS[est]}"><td colspan="4" class="text-white font-bold text-xs py-1 px-3 tracking-wide">ESTACIÓN ${est} — ${EST_LABEL[est].toUpperCase()}</td></tr>`
    byEst[est].forEach(p => {
      rows += `<tr class="row-est-${p.estacion}" data-pid="${p.id}">
        <td><input type="checkbox" class="w-4 h-4 cursor-pointer" ${checkMap[p.id] ? "checked" : ""} onchange="toggleIncl(${p.id},this.checked)" /></td>
        <td class="font-medium">${p.nombre} <span class="text-slate-400 text-xs">${p.cedula}</span></td>
        <td class="text-center"><input type="checkbox" class="w-4 h-4 cursor-pointer" style="accent-color:#2563eb" ${epoMap[p.id] ? "checked" : ""} onchange="toggleEpo(${p.id},this.checked)" /></td>
        <td class="text-center"><input type="checkbox" class="w-4 h-4 cursor-pointer" style="accent-color:#b45309" ${hierroMap[p.id] ? "checked" : ""} onchange="toggleHierro(${p.id},this.checked)" /></td>
      </tr>`
    })
  }

  app().innerHTML = `
    <div class="max-w-3xl mx-auto">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <h2 class="text-xl font-bold text-blue-900 mb-1">Programar próxima sesión</h2>
        <p class="text-slate-500 text-sm mb-5">Basada en sesión ${fmtFecha(G.sesion.fecha)} · ${TURNOS[G.sesion.turno]}</p>
        <div class="flex flex-wrap gap-4 mb-5">
          <div>
            <label class="block text-sm font-semibold text-slate-600 mb-1">Fecha siguiente</label>
            <input type="date" id="prog-fecha" value="${fechaSig}" class="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label class="block text-sm font-semibold text-slate-600 mb-1">Turno</label>
            <div class="flex gap-2">${["M","T","N"].map(t=>`<label class="flex items-center gap-1 cursor-pointer"><input type="radio" name="prog-turno" value="${t}" ${t===turnoSig?"checked":""} class="accent-blue-700"/><span class="text-sm">${TURNOS[t]}</span></label>`).join("")}</div>
          </div>
          <div class="self-end ml-auto">
            <button onclick="guardarProgramacion()" class="bg-emerald-700 hover:bg-emerald-600 text-white px-5 py-2 rounded-lg font-semibold text-sm">Guardar programación</button>
          </div>
        </div>
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-prog w-full">
            <thead><tr><th class="w-10 text-center">Incluir</th><th>Paciente</th><th class="w-20 text-center">EPO</th><th class="w-20 text-center">Fe</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="mt-4"><button onclick="renderSesion()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg">← Volver</button></div>
      </div>
    </div>
  `
}

// ── VIEW: AUTO-PROGRAMACIÓN EPO/Fe MENSUAL ────────────────────────────────────
async function renderAutoProgram() {
  G.vista = "autoprogram"; updateHeader()
  const hoyDate = new Date()
  const anioHoy = hoyDate.getFullYear()
  const mesHoy  = hoyDate.getMonth() + 1

  let _previewData = null
  let _anio = anioHoy
  let _mes  = mesHoy
  let _turno = "M"

  const MESES_ES = ["Enero","Febrero","Marzo","Abril","Mayo","Junio",
                    "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"]

  function _renderVista(preview = null, programado = false) {
    const turnoTabs = ["M","T","N"].map(t =>
      `<button onclick="_apTurno('${t}')"
        class="px-3 py-1.5 rounded-full text-sm font-semibold border transition-colors
          ${_turno === t ? "bg-teal-700 text-white border-teal-700" : "bg-white text-slate-600 border-slate-300 hover:border-teal-400"}">
        ${TURNOS[t]}</button>`
    ).join("")

    let prevHTML = ""
    if (preview && preview.pacientes.length) {
      const rows = preview.pacientes.map(p => `<tr>
        <td class="font-medium text-sm text-left">${p.nombre}</td>
        <td class="text-xs text-slate-400 text-center">${p.dias || "—"}</td>
        <td class="text-center font-semibold">${p.sesiones}</td>
        <td class="text-center text-blue-700 font-semibold">${p.epo_count > 0 ? p.epo_count : "—"}</td>
        <td class="text-center text-amber-700 font-semibold">${p.hierro_count > 0 ? p.hierro_count : "—"}</td>
      </tr>`).join("")

      const totEpo    = preview.pacientes.reduce((a, p) => a + p.epo_count, 0)
      const totHierro = preview.pacientes.reduce((a, p) => a + p.hierro_count, 0)
      const totSes    = preview.pacientes.reduce((a, p) => a + p.sesiones, 0)

      prevHTML = `
        <div class="mt-5">
          <div class="flex items-center justify-between mb-2">
            <h3 class="font-semibold text-slate-700 text-sm">
              Vista previa — ${MESES_ES[_mes-1]} ${_anio} · Turno ${TURNOS[_turno]}
            </h3>
            <div class="flex gap-2 text-xs">
              <span class="bg-blue-100 text-blue-700 px-2 py-0.5 rounded font-semibold">EPO total: ${totEpo}</span>
              <span class="bg-amber-100 text-amber-700 px-2 py-0.5 rounded font-semibold">Fe total: ${totHierro}</span>
              <span class="bg-slate-100 text-slate-600 px-2 py-0.5 rounded font-semibold">Sesiones: ${totSes}</span>
            </div>
          </div>
          <div class="overflow-x-auto rounded-xl border border-slate-200">
            <table class="tbl-stats w-full">
              <thead><tr>
                <th class="text-left">Paciente</th>
                <th class="text-center">Días</th>
                <th class="text-center">Sesiones</th>
                <th class="text-center text-blue-700">EPO aplic.</th>
                <th class="text-center text-amber-700">Fe aplic.</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
          ${!programado ? `<div class="mt-4 flex gap-3">
            <button onclick="_apEjecutar()"
              class="bg-teal-700 hover:bg-teal-600 text-white px-5 py-2 rounded-lg font-semibold text-sm">
              ✓ Confirmar y programar ${MESES_ES[_mes-1]}
            </button>
            <p class="text-xs text-slate-400 self-center">Esto reemplaza cualquier programación previa del mes para este turno.</p>
          </div>` : `<div class="mt-4 bg-teal-50 border border-teal-200 rounded-lg px-4 py-2 text-teal-800 text-sm font-semibold">
            ✓ Programación guardada — ${preview.programados} entradas creadas para ${MESES_ES[_mes-1]} ${_anio}
          </div>`}
        </div>`
    } else if (preview && !preview.pacientes.length) {
      prevHTML = `<p class="text-center text-slate-400 py-4 text-sm">
        No hay pacientes con días (LMV/TJS) configurados para el turno ${TURNOS[_turno]}.
        Configure los días en <strong>Gestión de Pacientes → Editar</strong>.
      </p>`
    }

    app().innerHTML = `
      <div class="max-w-4xl mx-auto">
        <div class="bg-white rounded-2xl shadow-xl p-6">
          <div class="flex items-center justify-between mb-5">
            <div>
              <h2 class="text-xl font-bold text-blue-900">Auto-programación EPO / Fe</h2>
              <p class="text-slate-500 text-sm mt-0.5">
                Distribuye las dosis del mes entre los días de cada paciente (LMV o TJS)
              </p>
            </div>
            <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg">← Inicio</button>
          </div>

          <div class="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-5 text-sm text-blue-800">
            <strong>¿Cómo funciona?</strong> Para cada paciente con EPO/Fe configurado en su ficha:<br/>
            · EPO: distribuye <em>epo_mensual ÷ epo_dosis</em> aplicaciones de forma equidistante en sus sesiones del mes.<br/>
            · Fe i.v.: distribuye las aplicaciones indicadas de forma equidistante.
          </div>

          <div class="flex flex-wrap gap-4 mb-4 items-end">
            <div>
              <label class="block text-sm font-semibold text-slate-600 mb-1">Mes</label>
              <select id="ap-mes" class="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-teal-500"
                onchange="_anio=parseInt(this.value.split('-')[0]); _mes=parseInt(this.value.split('-')[1])">
                ${Array.from({length: 6}, (_, i) => {
                  const d = new Date(anioHoy, mesHoy - 1 + i)
                  const y = d.getFullYear(), m = d.getMonth() + 1
                  const sel = (y === _anio && m === _mes) ? "selected" : ""
                  return `<option value="${y}-${m}" ${sel}>${MESES_ES[m-1]} ${y}</option>`
                }).join("")}
              </select>
            </div>
            <div>
              <label class="block text-sm font-semibold text-slate-600 mb-1">Turno</label>
              <div class="flex gap-2" id="ap-turno-btns">${turnoTabs}</div>
            </div>
            <button onclick="_apPreview()"
              class="ml-auto bg-slate-700 hover:bg-slate-600 text-white px-4 py-2 rounded-lg text-sm font-semibold self-end">
              Ver vista previa
            </button>
          </div>

          <div id="ap-preview">${prevHTML}</div>
        </div>
      </div>
    `
  }

  window._apTurno = function(t) {
    _turno = t
    _renderVista()
  }

  window._apPreview = async function() {
    const selMes = $("ap-mes")
    if (selMes) { const [y,m] = selMes.value.split("-"); _anio = parseInt(y); _mes = parseInt(m) }
    try {
      _previewData = await apiGet(`/api/programacion/resumen-mes?anio=${_anio}&mes=${_mes}&turno=${_turno}`)
      _renderVista(_previewData)
    } catch (e) { toast(e.message, "err") }
  }

  window._apEjecutar = async function() {
    const selMes = $("ap-mes")
    if (selMes) { const [y,m] = selMes.value.split("-"); _anio = parseInt(y); _mes = parseInt(m) }
    if (!confirm(`¿Programar EPO/Fe de ${MESES_ES[_mes-1]} ${_anio} para turno ${TURNOS[_turno]}?\nEsto reemplazará la programación previa del mes.`)) return
    try {
      const res = await apiPost("/api/programacion/auto-mes", { anio: _anio, mes: _mes, turno: _turno })
      toast(`✓ ${res.programados} entradas creadas para ${res.pacientes.length} pacientes`)
      _renderVista(res, true)
    } catch (e) { toast(e.message, "err") }
  }

  _renderVista()
}

// ── INIT ──────────────────────────────────────────────────────────────────────
renderDashboard()
