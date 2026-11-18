/* ============================================================
   crud.js — Gestión de Pacientes (CRUD completo v3)
   Depende de: app.js
   ============================================================ */

let _crudTurno        = "M"
let _crudPacientes    = []
let _crudVerInactivos = false

// R1: tipos de acceso vascular. FAV (estado + calibre de aguja) · CY (yugular / femoral)
const ACCESO_TIPOS = [
  { v: "",    l: "— Sin asignar —" },
  { v: "FAV", l: "FAV — Fístula arteriovenosa" },
  { v: "CY",  l: "CY — Catéter" },
]
const FAV_ESTADOS   = [{ v: "limpia", l: "Limpia" }, { v: "alto_riesgo", l: "Alto riesgo" }, { v: "aneurismatica", l: "Aneurismática" }]
const FAV_CALIBRES  = [15, 16, 17]
const CY_SITIOS     = [{ v: "yugular", l: "Yugular" }, { v: "femoral", l: "Femoral" }]
const MOTIVOS_INACTIVO = [{ v: "hospitalizado", l: "Hospitalizado" }, { v: "otro", l: "Otro" }]

const FILTROS_COMUNES = ["R-300", "R-400", "B-18", "B-20", "B-15", "B-12", "FX60", "FX80", "Purema Plus"]

/** R10: «Hospitalizado» / «Otro: texto» bajo el badge de inactivo */
function motivoInactivoHTML(p) {
  if (p.activo) return ""
  const base = p.motivo_inactivo === "hospitalizado" ? "Hospitalizado" : p.motivo_inactivo === "otro" ? "Otro" : ""
  const txt = [base, p.motivo_inactivo_texto].filter(Boolean).join(": ")
  return txt ? `<span class="motivo-inactivo">${escHtml(txt)}</span>` : ""
}

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
        <td class="font-medium">${p.nombre}${p.activo ? "" : ` <span class="badge-inactivo">Inactivo</span>`}</td>
        <td class="text-slate-500 text-xs">${p.cedula}</td>
        <td>${accBadge}</td>
        <td class="text-xs text-slate-500">${p.tipo_filtro || "—"}</td>
        <td class="text-right font-mono text-xs">${p.peso_seco != null ? p.peso_seco.toFixed(1) : "—"}</td>
        <td class="text-center text-xs">${dosis}</td>
        <td class="text-center">
          ${p.activo
            ? `<span class="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-700">Activo</span>`
            : `<span class="badge-inactivo">Inactivo</span>${motivoInactivoHTML(p)}`}
        </td>
        <td class="text-right">
          <div class="flex gap-1 justify-end">
            <button onclick="crudEditar(${p.id})"
              class="solo-admin bg-blue-100 hover:bg-blue-200 text-blue-800 text-xs px-2 py-1 rounded font-medium">Editar</button>
            ${p.activo
              ? `<button onclick="crudEliminar(${p.id},'${nomEsc}')"
                   class="solo-admin bg-red-100 hover:bg-red-200 text-red-700 text-xs px-2 py-1 rounded font-medium" title="Archiva al paciente: no borra su historial">Eliminar</button>`
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
            <button onclick="renderArchivados()"
              class="bg-slate-100 text-slate-700 border border-slate-300 text-xs px-3 py-1.5 rounded-lg font-medium hover:bg-slate-200 btn-foco">
              Archivados
            </button>
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

  const accesoOpts = ACCESO_TIPOS.map(o =>
    `<option value="${o.v}" ${(p?.acceso || "") === o.v ? "selected" : ""}>${o.l}</option>`).join("")
  const estadoOpts = `<option value="">— Elegir —</option>` + FAV_ESTADOS.map(o =>
    `<option value="${o.v}" ${p?.acceso_estado === o.v ? "selected" : ""}>${o.l}</option>`).join("")
  const calibreOpts = `<option value="">— Sin definir —</option>` + FAV_CALIBRES.map(c =>
    `<option value="${c}" ${p?.acceso_calibre === c ? "selected" : ""}>Calibre ${c}</option>`).join("")
  const sitioOpts = `<option value="">— Elegir —</option>` + CY_SITIOS.map(o =>
    `<option value="${o.v}" ${p?.acceso_sitio === o.v ? "selected" : ""}>${o.l}</option>`).join("")
  const motivoOpts = `<option value="">— Elegir —</option>` + MOTIVOS_INACTIVO.map(o =>
    `<option value="${o.v}" ${p?.motivo_inactivo === o.v ? "selected" : ""}>${o.l}</option>`).join("")

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
          <input id="f-peso-seco" type="number" step="0.1" min="30" max="150" class="form-input" oninput="_actualizarTotalHep()"
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
          <label class="form-label" for="f-acceso">Acceso vascular</label>
          <select id="f-acceso" class="form-input form-select" onchange="_toggleAcceso()">${accesoOpts}</select>
        </div>
        <div id="grp-fav-estado" class="${p?.acceso === "FAV" ? "" : "hidden"}">
          <label class="form-label" for="f-acceso-estado">Estado de la fístula *</label>
          <select id="f-acceso-estado" class="form-input form-select" onchange="_toggleAcceso()">${estadoOpts}</select>
        </div>
        <div id="grp-cy-sitio" class="${p?.acceso === "CY" ? "" : "hidden"}">
          <label class="form-label" for="f-acceso-sitio">Sitio del catéter *</label>
          <select id="f-acceso-sitio" class="form-input form-select">${sitioOpts}</select>
        </div>
      </div>
      <!-- R5/R6: el catéter con citrato o heparina sódica cambia el pedido de insumos -->
      <div id="grp-cy-sellado" class="flex gap-4 ${p?.acceso === "CY" ? "" : "hidden"}">
        <label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input type="checkbox" id="f-citrato" class="w-4 h-4" ${p?.citrato ? "checked" : ""} /> Citrato
        </label>
        <label class="flex items-center gap-2 text-sm text-slate-600 cursor-pointer">
          <input type="checkbox" id="f-heparina-sodica" class="w-4 h-4" ${p?.heparina_sodica ? "checked" : ""} /> Heparina sódica
        </label>
      </div>
      <div class="grid grid-cols-2 gap-3 ${p?.acceso === "FAV" ? "" : "hidden"}" id="grp-fav-extra">
        <div>
          <label class="form-label" for="f-acceso-calibre">Calibre de aguja</label>
          <select id="f-acceso-calibre" class="form-input form-select">${calibreOpts}</select>
        </div>
        <div id="f-acceso-cm-group" class="${p?.acceso_estado === "aneurismatica" ? "" : "hidden"}">
          <label class="form-label" for="f-acceso-cm">Cm cinta acetato (aneurismática)</label>
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
          <label class="form-label" for="f-heparina">Heparina (UI/h, 10-20)</label>
          <input id="f-heparina" type="number" min="10" max="20" class="form-input"
            value="${p?.heparina_unidades || ""}" placeholder="0 = sin heparina" />
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <div>
          <label class="form-label" for="f-heparina-ui-kg">Heparina (UI/kg, 10-20)</label>
          <input id="f-heparina-ui-kg" type="number" min="10" max="20" step="1" class="form-input"
            value="${p?.heparina_ui_kg ?? ""}" placeholder="10-20" oninput="_actualizarTotalHep()" />
        </div>
        <div>
          <label class="form-label">Total calculado</label>
          <p id="hep-total" class="text-xs text-slate-600 pt-2" aria-live="polite"></p>
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

      <div class="flex items-center gap-2 mt-1">
        <input type="checkbox" id="f-adicional" class="w-4 h-4" ${p?.adicional ? "checked" : ""} />
        <label for="f-adicional" class="text-sm text-slate-600 cursor-pointer">Paciente adicional
          <span class="text-xs text-slate-400">(sus insumos se piden el día que llega)</span></label>
      </div>

      ${p ? `<div class="flex items-center gap-2 mt-1">
        <input type="checkbox" id="f-activo" ${p.activo ? "checked" : ""} class="w-4 h-4" onchange="_toggleMotivo()" />
        <label for="f-activo" class="text-sm text-slate-600 cursor-pointer">Paciente activo</label>
      </div>
      <div id="grp-motivo" class="grid grid-cols-2 gap-3 ${p.activo ? "hidden" : ""}">
        <div>
          <label class="form-label" for="f-motivo">Motivo de inactividad *</label>
          <select id="f-motivo" class="form-input form-select">${motivoOpts}</select>
        </div>
        <div>
          <label class="form-label" for="f-motivo-texto">Detalle (opcional)</label>
          <input id="f-motivo-texto" class="form-input" maxlength="200" value="${escHtml(p.motivo_inactivo_texto || "")}" />
        </div>
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

function _toggleAcceso() {
  const acceso = $("f-acceso")?.value
  $("grp-fav-estado").classList.toggle("hidden", acceso !== "FAV")
  $("grp-fav-extra").classList.toggle("hidden", acceso !== "FAV")
  $("grp-cy-sitio").classList.toggle("hidden", acceso !== "CY")
  $("grp-cy-sellado")?.classList.toggle("hidden", acceso !== "CY")
  $("f-acceso-cm-group").classList.toggle("hidden", !(acceso === "FAV" && $("f-acceso-estado")?.value === "aneurismatica"))
}

function _toggleMotivo() {
  $("grp-motivo")?.classList.toggle("hidden", !!$("f-activo")?.checked)
}

/** R4: total de heparina = UI/kg × peso seco (solo cálculo informativo) */
function _actualizarTotalHep() {
  const el = $("hep-total"); if (!el) return
  const uikg = parseFloat($("f-heparina-ui-kg")?.value), ps = parseFloat($("f-peso-seco")?.value)
  el.textContent = (uikg > 0 && ps > 0) ? `≈ ${Math.round(uikg * ps)} UI (UI/kg × peso seco)` : ""
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
  const accesoEstado = acceso === "FAV" ? ($("f-acceso-estado").value || null) : null
  const accesoCal    = acceso === "FAV" && $("f-acceso-calibre").value ? parseInt($("f-acceso-calibre").value) : null
  const accesoSitio  = acceso === "CY" ? ($("f-acceso-sitio").value || null) : null
  const accesoCm     = accesoEstado === "aneurismatica" ? (parseInt($("f-acceso-cm").value) || 15) : null
  const hepUiKg      = $("f-heparina-ui-kg").value === "" ? null : parseInt($("f-heparina-ui-kg").value)
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
  if (acceso === "FAV" && !accesoEstado) return err("Indique el estado de la fístula")
  if (acceso === "CY" && !accesoSitio) return err("Indique el sitio del catéter (yugular o femoral)")
  if (hepUiKg != null && (isNaN(hepUiKg) || hepUiKg < 10 || hepUiKg > 20)) return err("Heparina UI/kg debe estar entre 10 y 20")
  const activoChk0 = $("f-activo")
  if (activoChk0 && !activoChk0.checked && !$("f-motivo").value) return err("Indique el motivo de inactividad")

  const camaLocal = ((camaG - 1) % 16) + 1   // convierte 1-48 a 1-16 por estación

  const data = {
    nombre, cedula, turno,
    estacion, cama: camaLocal,
    peso_seco: pesoSeco, watson, activo: true,
    acceso, acceso_estado: accesoEstado, acceso_calibre: accesoCal, acceso_sitio: accesoSitio, acceso_cm: accesoCm,
    heparina_ui_kg: hepUiKg,
    heparina_unidades: hepUn, tipo_filtro: filtro, medico,
    dias, epo_mensual: epoMensual, epo_dosis: epoDosis, hierro_mensual: hierroMens,
    // R5/R6 pedido de insumos (vacío = no)
    adicional: $("f-adicional")?.checked ? true : null,
    citrato: acceso === "CY" ? !!$("f-citrato")?.checked : null,
    heparina_sodica: acceso === "CY" ? !!$("f-heparina-sodica")?.checked : null,
  }
  const activoChk = $("f-activo")
  if (activoChk) {
    data.activo = activoChk.checked
    if (!data.activo) {
      data.motivo_inactivo = $("f-motivo").value || null
      data.motivo_inactivo_texto = $("f-motivo-texto").value.trim() || null
    }
  }
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
    // R13: la cédula es de un archivado -> ofrecer «Reactivar paciente archivado» (archivo.js)
    if (e.detalle && e.detalle.codigo === "cedula_archivada") { archivoOfrecerReactivar(e.detalle.paciente); return }
    const el = $("form-error"); el.textContent = e.message; el.classList.remove("hidden")
  }
}

// R13: tras reactivar un archivado se abre su ficha para revisar turno, cama y prescripción
async function crudEditarPorId(id, turno) {
  await renderCRUD(turno || _crudTurno)
  crudEditar(id)
}

function crudEditar(id) {
  const p = _crudPacientes.find(x => x.id === id); if (!p) return
  openModal(
    `Editar: ${p.nombre}`,
    _formPaciente(p),
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium">Cancelar</button>
     <button onclick="_guardarEdicion(${id})" class="bg-blue-800 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium">Guardar cambios</button>`
  )
  _actualizarTotalHep()
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

// R13: «Eliminar paciente» = ARCHIVAR (nada clínico se borra; ver archivo.js)
const MOTIVOS_ARCHIVO = ["Fallecimiento", "Traslado a otra unidad", "Retiro voluntario", "Trasplante", "Otro"]

function crudEliminar(id, nombre) {
  openModal(
    "Eliminar paciente (archivar)",
    `<div class="space-y-3">
       <div class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
         <strong>${escHtml(nombre)}</strong> dejará de aparecer en listas, hojas, programación y pedidos.
         Aparecerá en <strong>Archivados</strong> durante un tiempo y se podrá restaurar.
         Sus sesiones, laboratorios y asistencia <strong>no se borran</strong>: seguirán en Historial y Estadísticas.
       </div>
       <div class="grid grid-cols-2 gap-3">
         <div><label class="form-label" for="el-motivo">Motivo *</label>
           <select id="el-motivo" class="form-input form-select"><option value="">— Elegir —</option>
             ${MOTIVOS_ARCHIVO.map(o => `<option value="${o}">${o}</option>`).join("")}</select></div>
         <div><label class="form-label" for="el-texto">Detalle (opcional)</label>
           <input id="el-texto" class="form-input" maxlength="120" /></div>
       </div>
       <div id="el-error" class="text-red-700 text-sm hidden" role="alert"></div>
     </div>`,
    `<button onclick="closeModal()"
       class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">
       Cancelar
     </button>
     <button onclick="_confirmarEliminar(${id})"
       class="bg-red-700 hover:bg-red-800 text-white px-4 py-2 rounded-lg text-sm font-medium btn-foco">
       Archivar paciente
     </button>`
  )
}

async function _confirmarEliminar(id) {
  const motivo = $("el-motivo")?.value
  if (!motivo) { const e = $("el-error"); e.textContent = "Indique el motivo"; e.classList.remove("hidden"); return }
  const detalle = $("el-texto").value.trim()
  closeModal()
  try {
    await apiPost(`/api/pacientes/${id}/archivar`, { motivo: detalle ? `${motivo}: ${detalle}` : motivo })
    toast("Paciente archivado")
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
