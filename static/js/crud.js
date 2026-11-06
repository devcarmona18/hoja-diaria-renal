/* ============================================================
   crud.js — Gestión de Pacientes (CRUD completo v3)
   Depende de: app.js
   ============================================================ */

let _crudTurno        = "M"
let _crudPacientes    = []
let _crudVerInactivos = false

// Tipos de acceso vascular para el selector
const ACCESO_OPCIONES = [
  { v: "",        l: "— Sin asignar —" },
  { v: "CY",      l: "CY — Catéter yugular" },
  { v: "FAV_L",   l: "FAV — Fístula Limpia" },
  { v: "FAV_AR",  l: "FAV ⚠ — Alto Riesgo" },
  { v: "FAV_ANE", l: "⚠ FAV Aneurismática" },
  { v: "F16",     l: "G16 — Agujas Fístula G16" },
  { v: "F17",     l: "G17 — Agujas Fístula G17" },
]

const FILTROS_COMUNES = ["R-300", "R-400", "B-18", "B-20", "B-15", "B-12", "FX60", "FX80", "Purema Plus"]

async function renderCRUD(turno = "M") {
  G.vista = "crud"
  _crudTurno = turno
  updateHeader()

  try {
    _crudPacientes = await apiGet(`/api/pacientes?turno=${turno}`)
  } catch (e) {
    toast(e.message, "err"); return
  }

  const visibles = _crudVerInactivos ? _crudPacientes : _crudPacientes.filter(p => p.activo)
  const inactivosCount = _crudPacientes.filter(p => !p.activo).length

  const byEst = { 1: [], 2: [], 3: [] }
  visibles.forEach(p => byEst[p.estacion]?.push(p))

  let rows = ""
  for (const est of [1, 2, 3]) {
    if (!byEst[est].length) continue
    rows += `<tr style="background:${EST_COLORS[est]}">
      <td colspan="9" class="text-white font-bold text-xs py-1.5 px-3 tracking-wide">
        ESTACIÓN ${est} — MACRO ${EST_LABEL[est].toUpperCase()} · CAMAS ${(est-1)*16+1}–${est*16}
      </td>
    </tr>`
    byEst[est].forEach(p => {
      const accBadge = p.acceso ? accesoHTML(p) : `<span class="text-slate-300 text-xs">—</span>`
      const dosis = (p.heparina_unidades && p.peso_seco)
        ? `<span class="text-blue-600 text-xs">${Math.round(p.peso_seco * 4 * p.heparina_unidades)} UI</span>` : ""
      const nomEsc = p.nombre.replace(/'/g, "\\'")
      rows += `<tr class="row-est-${p.estacion} ${p.activo ? "" : "inactivo"}" data-pid="${p.id}">
        <td class="font-mono text-xs text-slate-500 font-bold">${displayCama(p.cama, p.estacion)}</td>
        <td class="font-medium">${p.nombre}</td>
        <td class="text-slate-500 text-xs">${p.cedula}</td>
        <td>${accBadge}</td>
        <td class="text-xs text-slate-500">${p.tipo_filtro || "—"}</td>
        <td class="text-right font-mono text-xs">${p.peso_seco != null ? p.peso_seco.toFixed(1) : "—"}</td>
        <td class="text-center text-xs">${dosis}</td>
        <td class="text-center">
          ${p.activo
            ? `<span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Activo</span>`
            : `<span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-600">Inactivo</span>`}
        </td>
        <td class="text-right">
          <div class="flex gap-1 justify-end">
            <button onclick="crudEditar(${p.id})"
              class="solo-admin bg-blue-100 hover:bg-blue-200 text-blue-800 text-xs px-2 py-1 rounded font-medium">Editar</button>
            ${p.activo
              ? `<button onclick="crudEliminar(${p.id},'${nomEsc}')"
                   class="solo-admin bg-red-100 hover:bg-red-200 text-red-700 text-xs px-2 py-1 rounded font-medium">Eliminar</button>`
              : `<button onclick="crudReactivar(${p.id},'${nomEsc}')"
                   class="solo-admin bg-emerald-100 hover:bg-emerald-200 text-emerald-700 text-xs px-2 py-1 rounded font-medium">Reactivar</button>`}
            <button onclick="crudVerLabs(${p.id})"
              class="bg-purple-100 hover:bg-purple-200 text-purple-800 text-xs px-2 py-1 rounded font-medium">Labs</button>
            <button onclick="crudVerIA(${p.id}, '${nomEsc}')"
              class="solo-ia solo-admin bg-indigo-100 hover:bg-indigo-200 text-indigo-800 text-xs px-2 py-1 rounded font-medium">IA</button>
          </div>
        </td>
      </tr>`
    })
  }

  const turnoTabs = ["M", "T", "N"].map(t => `
    <button onclick="renderCRUD('${t}')"
      class="px-4 py-1.5 rounded-full text-sm font-semibold border transition-colors
        ${_crudTurno === t ? "bg-blue-800 text-white border-blue-800" : "bg-white text-slate-600 border-slate-300 hover:border-blue-400"}">
      ${TURNOS[t]}
    </button>`).join("")

  app().innerHTML = `
    <div class="max-w-6xl mx-auto">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-5">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Gestión de Pacientes</h2>
            <p class="text-slate-500 text-sm mt-0.5">
              ${visibles.length} pacientes activos en turno ${TURNOS[turno]}
              ${inactivosCount > 0 ? `· <span class="text-red-500">${inactivosCount} inactivo${inactivosCount > 1 ? "s" : ""}</span>` : ""}
            </p>
          </div>
          <div class="flex gap-2 items-center">
            ${inactivosCount > 0 ? `
              <button onclick="_crudToggleVerInactivos()"
                class="${_crudVerInactivos ? "bg-red-100 text-red-700 border-red-300" : "bg-slate-100 text-slate-600 border-slate-300"} border text-xs px-3 py-1.5 rounded-lg font-medium hover:opacity-80 transition">
                ${_crudVerInactivos ? "Ocultar inactivos" : `Ver inactivos (${inactivosCount})`}
              </button>` : ""}
            <button onclick="crudNuevo()"
              class="solo-admin bg-blue-800 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg font-semibold">
              + Nuevo paciente
            </button>
          </div>
        </div>

        <div class="flex gap-2 mb-4 flex-wrap">
          ${turnoTabs}
          <button onclick="goHome()" class="ml-auto text-slate-500 hover:text-slate-700 text-sm underline">← Inicio</button>
        </div>

        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-crud w-full">
            <thead>
              <tr>
                <th class="w-10">#</th>
                <th>Nombre</th>
                <th>Cédula</th>
                <th class="w-20">Acceso</th>
                <th class="w-20">Filtro</th>
                <th class="w-16 text-right">P.Seco</th>
                <th class="w-20 text-center">Hep.Dosis</th>
                <th class="w-20 text-center">Estado</th>
                <th class="w-36 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody>${rows || `<tr><td colspan='9' class='text-center py-8 text-slate-400'>${_crudVerInactivos ? "No hay pacientes para este turno." : "No hay pacientes activos para este turno."}</td></tr>`}</tbody>
          </table>
        </div>
        <p class="text-xs text-slate-400 mt-2">Hep.Dosis = P.Seco × 4h × UI/h. Columnas configurables en Editar.</p>
      </div>
    </div>
  `
}

// ── Formulario paciente ───────────────────────────────────────────────────────
function _formPaciente(p = null) {
  // Cama 1-48: si editando, calcular el global
  const camaGlobal = p ? displayCama(p.cama, p.estacion) : ""

  const accesoOpts = ACCESO_OPCIONES.map(o =>
    `<option value="${o.v}" ${p?.acceso === o.v ? "selected" : ""}>${o.l}</option>`).join("")

  const filtroList = FILTROS_COMUNES.map(f =>
    `<option value="${f}">${f}</option>`).join("")

  return `
    <div class="space-y-3">
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Nombre completo *</label>
          <input id="f-nombre" class="form-input" value="${p?.nombre || ""}" placeholder="Apellido, Nombre" />
        </div>
        <div>
          <label class="form-label">Cédula *</label>
          <input id="f-cedula" class="form-input" value="${p?.cedula || ""}" placeholder="V-12345678" />
        </div>
      </div>

      <div class="grid grid-cols-3 gap-3">
        <div>
          <label class="form-label">Turno *</label>
          <select id="f-turno" class="form-input form-select">
            ${["M","T","N"].map(t => `<option value="${t}" ${p?.turno===t?"selected":""}>${TURNOS[t]}</option>`).join("")}
          </select>
        </div>
        <div>
          <label class="form-label">Cama (1-48) *</label>
          <input id="f-cama" type="number" min="1" max="48" class="form-input"
            value="${camaGlobal}" placeholder="1-48"
            oninput="_actualizarEstacion()" />
        </div>
        <div>
          <label class="form-label">Estación (auto)</label>
          <input id="f-estacion-display" class="form-input bg-slate-50" readonly
            value="${p ? `${p.estacion} — ${EST_LABEL[p.estacion]}` : ""}" />
          <input type="hidden" id="f-estacion" value="${p?.estacion || ""}" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Peso seco (kg)</label>
          <input id="f-peso-seco" type="number" step="0.1" min="30" max="150" class="form-input"
            value="${p?.peso_seco != null ? p.peso_seco : ""}" placeholder="Ej. 65.5" />
        </div>
        <div>
          <label class="form-label">Watson V (litros)</label>
          <input id="f-watson" type="number" step="0.1" class="form-input"
            value="${p?.watson != null ? p.watson : ""}" placeholder="Ej. 32.4" />
        </div>
      </div>

      <hr class="border-slate-200" />
      <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Datos clínicos</p>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Acceso vascular</label>
          <select id="f-acceso" class="form-input form-select" onchange="_toggleAccesoCm()">
            ${accesoOpts}
          </select>
        </div>
        <div id="f-acceso-cm-group" class="${p?.acceso === "FAV_ANE" ? "" : "hidden"}">
          <label class="form-label">Cm cinta acetato (FAV ANE)</label>
          <input id="f-acceso-cm" type="number" min="5" max="30" class="form-input"
            value="${p?.acceso_cm || 15}" placeholder="15" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Tipo de filtro</label>
          <input id="f-filtro" class="form-input" list="filtros-list"
            value="${p?.tipo_filtro || ""}" placeholder="R-300, B-18…" />
          <datalist id="filtros-list">${filtroList}</datalist>
        </div>
        <div>
          <label class="form-label">Heparina (UI/h, 10-20)</label>
          <input id="f-heparina" type="number" min="10" max="20" class="form-input"
            value="${p?.heparina_unidades || ""}" placeholder="0 = sin heparina" />
        </div>
      </div>

      <div>
        <label class="form-label">Médico nefrólogo tratante</label>
        <input id="f-medico" class="form-input" value="${p?.medico || ""}" placeholder="Dr. Apellido" />
      </div>

      <hr class="border-slate-200" />
      <p class="text-xs font-semibold text-slate-500 uppercase tracking-wide">Programación EPO / Fe mensual</p>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">Días de diálisis</label>
          <select id="f-dias" class="form-input form-select" onchange="_actualizarPreviewEpo()">
            <option value="" ${!p?.dias ? "selected" : ""}>— Sin asignar —</option>
            <option value="LMV" ${p?.dias === "LMV" ? "selected" : ""}>LMV — Lunes, Miércoles, Viernes</option>
            <option value="TJS" ${p?.dias === "TJS" ? "selected" : ""}>TJS — Martes, Jueves, Sábado</option>
          </select>
        </div>
        <div>
          <label class="form-label">Aplicaciones Fe i.v. / mes</label>
          <input id="f-hierro-mensual" type="number" min="0" max="13" class="form-input"
            value="${p?.hierro_mensual != null ? p.hierro_mensual : ""}"
            placeholder="0" oninput="_actualizarPreviewEpo()" />
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label">EPO prescrita (UI/mes)</label>
          <input id="f-epo-mensual" type="number" min="0" step="500" class="form-input"
            value="${p?.epo_mensual != null ? p.epo_mensual : ""}"
            placeholder="Ej. 6000" oninput="_actualizarPreviewEpo()" />
        </div>
        <div>
          <label class="form-label">Dosis EPO por aplicación (UI)</label>
          <input id="f-epo-dosis" type="number" min="0" step="500" class="form-input"
            value="${p?.epo_dosis != null ? p.epo_dosis : ""}"
            placeholder="Ej. 3000" oninput="_actualizarPreviewEpo()" />
        </div>
      </div>
      <p id="epo-preview" class="text-xs text-blue-600 font-medium min-h-[1rem]"></p>

      ${p ? `<div class="flex items-center gap-2 mt-1">
        <input type="checkbox" id="f-activo" ${p.activo ? "checked" : ""} class="w-4 h-4" />
        <label for="f-activo" class="text-sm text-slate-600 cursor-pointer">Paciente activo</label>
      </div>` : ""}

      <div id="form-error" class="text-red-600 text-sm hidden"></div>
    </div>
  `
}

function _actualizarEstacion() {
  const cama = parseInt($("f-cama")?.value)
  if (isNaN(cama) || cama < 1 || cama > 48) {
    $("f-estacion-display").value = ""
    $("f-estacion").value = ""
    return
  }
  const est = Math.ceil(cama / 16)
  $("f-estacion-display").value = `${est} — ${EST_LABEL[est]}`
  $("f-estacion").value = est
}

function _toggleAccesoCm() {
  const acceso = $("f-acceso")?.value
  $("f-acceso-cm-group").classList.toggle("hidden", acceso !== "FAV_ANE")
}

function _actualizarPreviewEpo() {
  const prev = $("epo-preview"); if (!prev) return
  const mensual = parseFloat($("f-epo-mensual")?.value)
  const dosis   = parseFloat($("f-epo-dosis")?.value)
  const dias    = $("f-dias")?.value
  const hierro  = parseInt($("f-hierro-mensual")?.value)

  const parts = []
  if (mensual > 0 && dosis > 0) {
    const n = Math.round(mensual / dosis)
    parts.push(`EPO: ${n} aplic/mes (${dosis.toFixed(0)} UI c/u)`)
  }
  if (hierro > 0) parts.push(`Fe: ${hierro} aplic/mes`)
  if (!dias && (mensual || hierro)) parts.push("⚠ Asigne días (LMV/TJS) para auto-programar")

  prev.textContent = parts.join("  ·  ")
}

function _leerFormulario() {
  const err = (msg) => { const e = $("form-error"); e.textContent = msg; e.classList.remove("hidden"); return null }
  const nombre   = $("f-nombre").value.trim()
  const cedula   = $("f-cedula").value.trim()
  const turno    = $("f-turno").value
  const camaG    = parseInt($("f-cama").value)      // 1-48
  const estacion = parseInt($("f-estacion").value)
  const pesoSeco = $("f-peso-seco").value === "" ? null : parseFloat($("f-peso-seco").value)
  const watson   = $("f-watson").value === "" ? null : parseFloat($("f-watson").value)
  const acceso       = $("f-acceso").value || null
  const accesoCm     = acceso === "FAV_ANE" ? (parseInt($("f-acceso-cm").value) || 15) : null
  const hepUn        = $("f-heparina").value === "" ? null : parseInt($("f-heparina").value)
  const filtro       = $("f-filtro").value.trim() || null
  const medico       = $("f-medico").value.trim() || null
  const dias         = $("f-dias").value || null
  const epoMensual   = $("f-epo-mensual").value   === "" ? null : parseFloat($("f-epo-mensual").value)
  const epoDosis     = $("f-epo-dosis").value      === "" ? null : parseFloat($("f-epo-dosis").value)
  const hierroMens   = $("f-hierro-mensual").value === "" ? null : parseInt($("f-hierro-mensual").value)

  if (!nombre)  return err("El nombre es obligatorio")
  if (!cedula)  return err("La cédula es obligatoria")
  if (!turno)   return err("Seleccione un turno")
  if (isNaN(camaG) || camaG < 1 || camaG > 48) return err("La cama debe ser 1-48")
  if (isNaN(estacion)) return err("Cama inválida — no se pudo determinar la estación")

  const camaLocal = ((camaG - 1) % 16) + 1   // convierte 1-48 a 1-16 por estación

  const data = {
    nombre, cedula, turno,
    estacion, cama: camaLocal,
    peso_seco: pesoSeco, watson, activo: true,
    acceso, acceso_cm: accesoCm,
    heparina_unidades: hepUn, tipo_filtro: filtro, medico,
    dias, epo_mensual: epoMensual, epo_dosis: epoDosis, hierro_mensual: hierroMens,
  }
  const activoChk = $("f-activo")
  if (activoChk) data.activo = activoChk.checked
  return data
}

// ── CRUD acciones ─────────────────────────────────────────────────────────────
function crudNuevo() {
  openModal(
    "Nuevo Paciente",
    _formPaciente(),
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">Cancelar</button>
     <button onclick="_guardarNuevo()" class="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">Guardar</button>`
  )
}

async function _guardarNuevo() {
  const data = _leerFormulario(); if (!data) return
  try {
    await apiPost("/api/pacientes", data)
    closeModal(); toast("Paciente creado correctamente")
    renderCRUD(_crudTurno)
  } catch (e) {
    const el = $("form-error"); el.textContent = e.message; el.classList.remove("hidden")
  }
}

function crudEditar(id) {
  const p = _crudPacientes.find(x => x.id === id); if (!p) return
  openModal(
    `Editar: ${p.nombre}`,
    _formPaciente(p),
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">Cancelar</button>
     <button onclick="_guardarEdicion(${id})" class="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">Guardar cambios</button>`
  )
}

async function _guardarEdicion(id) {
  const data = _leerFormulario(); if (!data) return
  try {
    await apiPut(`/api/pacientes/${id}`, data)
    closeModal(); toast("Paciente actualizado")
    renderCRUD(_crudTurno)
  } catch (e) {
    const el = $("form-error"); el.textContent = e.message; el.classList.remove("hidden")
  }
}

async function crudToggleActivo(id) {
  try {
    const p = await apiPatch(`/api/pacientes/${id}/toggle-activo`, {})
    toast(`Paciente ${p.activo ? "activado" : "desactivado"}`)
    renderCRUD(_crudTurno)
  } catch (e) { toast(e.message, "err") }
}

function crudEliminar(id, nombre) {
  openModal(
    "Eliminar de estaciones",
    `<div class="space-y-3">
       <div class="bg-amber-50 border border-amber-200 rounded-lg p-3 flex gap-2">
         <span class="text-amber-500 text-lg">⚠</span>
         <div class="text-sm text-amber-800">
           <strong>${nombre}</strong> será retirado de las estaciones activas.<br>
           <span class="text-amber-600">Sus datos quedan guardados en el sistema y podrá ser reactivado si regresa.</span>
         </div>
       </div>
       <p class="text-sm text-slate-500">Esta acción <strong>no elimina</strong> al paciente de la base de datos.</p>
     </div>`,
    `<button onclick="closeModal()"
       class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">
       Cancelar
     </button>
     <button onclick="_confirmarEliminar(${id})"
       class="bg-red-600 hover:bg-red-700 text-white px-4 py-2 rounded-lg text-sm font-medium">
       Eliminar de estaciones
     </button>`
  )
}

async function _confirmarEliminar(id) {
  closeModal()
  try {
    await apiPatch(`/api/pacientes/${id}/toggle-activo`, {})
    toast("Paciente retirado de las estaciones")
    renderCRUD(_crudTurno)
  } catch (e) { toast(e.message, "err") }
}

function crudReactivar(id, nombre) {
  openModal(
    "Reactivar paciente",
    `<div class="space-y-3">
       <div class="bg-emerald-50 border border-emerald-200 rounded-lg p-3 flex gap-2">
         <span class="text-emerald-500 text-lg">✔</span>
         <div class="text-sm text-emerald-800">
           <strong>${nombre}</strong> volverá a aparecer en las estaciones activas de su turno y cama original.
         </div>
       </div>
     </div>`,
    `<button onclick="closeModal()"
       class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">
       Cancelar
     </button>
     <button onclick="_confirmarReactivar(${id})"
       class="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-medium">
       Reactivar
     </button>`
  )
}

async function _confirmarReactivar(id) {
  closeModal()
  try {
    await apiPatch(`/api/pacientes/${id}/toggle-activo`, {})
    toast("Paciente reactivado")
    renderCRUD(_crudTurno)
  } catch (e) { toast(e.message, "err") }
}

function _crudToggleVerInactivos() {
  _crudVerInactivos = !_crudVerInactivos
  renderCRUD(_crudTurno)
}

function crudVerLabs(pacienteId) {
  const p = _crudPacientes.find(x => x.id === pacienteId)
  if (typeof renderLabs === "function") renderLabs(pacienteId, p?.nombre || "Paciente")
  else toast("Módulo de laboratorios no disponible", "warn")
}

function crudVerIA(pacienteId, pacienteNombre) {
  if (typeof renderIA === "function") renderIA(pacienteId, pacienteNombre)
  else toast("Módulo IA no disponible", "warn")
}
