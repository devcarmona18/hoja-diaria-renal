/* ============================================================
   programacion.js — Programar la próxima sesión (R2) con la misma
   hoja de la página principal, y cambios de un día vs. permanentes (R7).
   Depende de: app.js (G, $, app, apiGet/apiPost/apiDelete, toast,
   openModal/closeModal, TURNOS, EST_LABEL, accesoHTML, pacInfoHTML…)
   API: /api/asignaciones/*  ·  EPO/Fe/incluir: /api/programacion
   ============================================================ */

const PROG = {
  fecha: null,      // fecha que se programa (AAAA-MM-DD)
  turno: "M",
  est: 0,           // filtro de estación (0 = todas)
  hoja: null,       // respuesta de /api/asignaciones/hoja
  dragPid: null,
  buscarIdx: -1,
  saveTimer: null,
}

const DIAS_ES = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"]

function progEsc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
}
function progBloqueada() { return G.readonly || !PROG.hoja?.editable }
function progFechaLarga(iso) {
  const d = new Date(iso + "T12:00:00")
  return `${DIAS_ES[d.getDay()]} ${fmtFecha(iso)}`
}

// ── Entrada ───────────────────────────────────────────────────────────────────
async function renderProgramacion() {
  G.vista = "programacion"; updateHeader()
  $("toast")?.setAttribute("role", "status")
  PROG.turno = G.sesion?.turno || PROG.turno
  try {
    const desde = G.sesion?.fecha ? `?desde=${G.sesion.fecha}` : ""
    PROG.fecha = (await apiGet(`/api/asignaciones/proximo-dia${desde}`)).fecha
  } catch (e) { toast(e.message, "err"); return }
  await progCargar()
}

async function progCargar() {
  try {
    PROG.hoja = await apiGet(`/api/asignaciones/hoja/${PROG.fecha}/${PROG.turno}`)
    progDibujar()
  } catch (e) { toast(e.message, "err") }
}

function progCambiarFecha(v) { if (v) { PROG.fecha = v; progCargar() } }
function progCambiarTurno(t) { PROG.turno = t; progCargar() }
function progFiltro(est) { PROG.est = est; progDibujar() }

// ── Dibujo de la hoja ─────────────────────────────────────────────────────────
function progDibujar(enfocarPid = null) {
  const h = PROG.hoja; if (!h) return
  const bloq = progBloqueada()
  const porCama = {}
  h.puestos.forEach(p => { (porCama[`${p.estacion}-${p.cama}`] ||= []).push(p) })

  const tabsCfg = [
    { est: 0, label: "Todas",                    on: "tab-todas", off: "tab-todas-off" },
    { est: 1, label: "Est. 1 – Amarilla (1-16)", on: "tab-1-on",  off: "tab-1-off" },
    { est: 2, label: "Est. 2 – Azul (17-32)",    on: "tab-2-on",  off: "tab-2-off" },
    { est: 3, label: "Est. 3 – Roja (33-48)",    on: "tab-3-on",  off: "tab-3-off" },
  ]
  const tabs = tabsCfg.map(t => `<button class="tab-est ${PROG.est === t.est ? t.on : t.off}"
      aria-pressed="${PROG.est === t.est}" onclick="progFiltro(${t.est})">${t.label}</button>`).join("")

  let filas = ""
  for (const est of [1, 2, 3]) {
    if (PROG.est && PROG.est !== est) continue
    filas += `<tr class="row-estacion-hdr est-${est}"><td colspan="8">ESTACIÓN ${est} — MACRO ${EST_LABEL[est].toUpperCase()} · CAMAS ${(est - 1) * 16 + 1}–${est * 16}</td></tr>`
    for (let cama = 1; cama <= 16; cama++) {
      const ocup = porCama[`${est}-${cama}`] || []
      if (!ocup.length) filas += progFilaLibre(est, cama, bloq)
      else ocup.forEach(p => { filas += progFilaPuesto(p, bloq, ocup.length > 1) })
    }
  }

  const cambios = h.puestos.filter(p => p.asignacion).length
  const libres = 48 - new Set(h.puestos.map(p => `${p.estacion}-${p.cama}`)).size
  const epo = h.puestos.filter(p => p.epo).length
  const fe = h.puestos.filter(p => p.hierro).length

  const conflictosHTML = h.conflictos.length ? `
    <div role="alert" class="prog-alerta mb-3">
      <strong>Conflictos de cama:</strong>
      ${h.conflictos.map(c => `cama ${c.cama_global}: ${c.pacientes.map(x => progEsc(x.nombre)).join(" y ")}`).join(" · ")}
    </div>` : ""

  const avisoBloq = G.readonly
    ? `<div class="prog-aviso mb-3">Modo demo: solo lectura. Puede consultar y buscar, pero no hacer cambios.</div>`
    : h.mes_cerrado
      ? `<div class="prog-aviso mb-3" role="status"><span class="badge-mes-cerrado"><span aria-hidden="true">🔒</span> Mes cerrado</span> El mes está cerrado; reábralo para editar.</div>`
    : !h.editable
      ? `<div class="prog-aviso mb-3">La hoja de este día y turno ya está <strong>cerrada</strong>: no admite cambios.</div>`
      : h.sesion
        ? `<div class="prog-aviso mb-3">La hoja de este día ya está abierta: los cambios se aplican también a ella.</div>`
        : ""

  app().innerHTML = `
    <div class="max-w-full" id="prog-vista">
      <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-4 mb-3">
        <div class="flex flex-wrap gap-4 items-end">
          <div class="mr-2">
            <h2 class="text-xl font-bold text-blue-900">Programar próxima sesión</h2>
            <p class="text-slate-500 text-sm mt-0.5">
              <span class="capitalize">${progFechaLarga(h.fecha)}</span>${h.grupo_dias ? ` · pacientes ${h.grupo_dias}` : ""} · ${TURNOS[h.turno]}
            </p>
          </div>
          <div>
            <label for="prog-fecha" class="form-label">Fecha a programar</label>
            <input type="date" id="prog-fecha" value="${h.fecha}" onchange="progCambiarFecha(this.value)"
              class="border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div role="group" aria-label="Turno">
            <span class="form-label">Turno</span>
            <div class="flex gap-2">${["M", "T", "N"].map(t => `<button class="turno-btn ${t === h.turno ? "selected" : ""}"
              aria-pressed="${t === h.turno}" onclick="progCambiarTurno('${t}')">${TURNOS[t]}</button>`).join("")}</div>
          </div>
          <div class="slot-search-wrap prog-buscar-wrap">
            <label for="prog-buscar" class="form-label">Buscar paciente</label>
            <input type="search" id="prog-buscar" class="slot-input prog-buscar-input" autocomplete="off"
              placeholder="Nombre o cédula…" role="combobox" aria-expanded="false"
              aria-controls="prog-buscar-drop" aria-autocomplete="list"
              oninput="progBuscar(this.value)" onkeydown="progBuscarTeclas(event)"
              onblur="setTimeout(progCerrarBusqueda,150)" />
            <div id="prog-buscar-drop" class="slot-dropdown hidden" role="listbox" aria-label="Resultados"></div>
          </div>
          ${G.sesion ? `<button onclick="renderSesion()" class="ml-auto bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg">← Volver a la hoja</button>` : ""}
        </div>
        <p class="text-xs text-slate-500 mt-3">
          Los cambios aplican <strong>solo a este día</strong>: el siguiente día de diálisis cada paciente vuelve a su cama habitual.
          Para cambiar la cama habitual use <strong>«Hacer permanente»</strong> o marque <strong>«Cambio permanente»</strong> al mover.
        </p>
      </div>

      ${avisoBloq}${conflictosHTML}
      <div class="flex flex-wrap gap-2 mb-3 print:hidden">${tabs}</div>
      <div class="flex flex-wrap gap-2 mb-3 text-sm">
        <div class="bg-white rounded-lg px-3 py-1.5 border border-slate-200 shadow-sm">En la hoja: <strong>${h.puestos.length}</strong></div>
        <div class="bg-amber-50 rounded-lg px-3 py-1.5 border border-amber-200">Cambios del día: <strong>${cambios}</strong></div>
        <div class="bg-slate-50 rounded-lg px-3 py-1.5 border border-slate-300">Camas libres: <strong>${libres}</strong></div>
        <div class="bg-blue-50 rounded-lg px-3 py-1.5 border border-blue-200">EPO: <strong class="text-blue-700">${epo}</strong></div>
        <div class="bg-orange-50 rounded-lg px-3 py-1.5 border border-orange-200">Fe: <strong class="text-orange-700">${fe}</strong></div>
        <div class="ml-auto self-center text-xs text-slate-400">${h.programado ? "Lista programada guardada" : "Lista según días de diálisis"}</div>
      </div>

      <div class="tbl-sesion-wrap bg-white">
        <table class="tbl-sesion prog-tabla">
          <caption class="sr-only">Hoja programada del ${fmtFecha(h.fecha)}, turno ${TURNOS[h.turno]}. Arrastre una fila a otra cama o use el botón Mover.</caption>
          <thead><tr>
            <th scope="col" title="Cama 1-48 · arrastra la fila para mover">#</th>
            <th scope="col">Paciente / Acceso</th>
            <th scope="col">Días</th>
            <th scope="col">Cambio del día</th>
            <th scope="col">EPO</th>
            <th scope="col">Fe</th>
            <th scope="col" title="Incluir en la programación de ese día">Incl.</th>
            <th scope="col">Acciones</th>
          </tr></thead>
          <tbody>${filas}</tbody>
        </table>
      </div>
      ${progFueraDeHoja(h, bloq)}
      <p class="text-xs text-slate-400 mt-1.5">
        Arrastra una fila sobre otra cama: si está libre se mueve; si está ocupada se intercambian. EPO/Fe e «Incl.» se guardan solos.
      </p>
    </div>`

  if (enfocarPid) progResaltar(enfocarPid)
}

function progDragAttrs(pid, bloq) {
  if (bloq) return ""
  return `draggable="true" ondragstart="progDragStart(event,${pid})" ondragend="progDragEnd(event)"`
}
function progDropAttrs(est, cama, bloq) {
  if (bloq) return ""
  return `ondragover="progDragOver(event)" ondragenter="this.classList.add('drag-over')"
          ondragleave="this.classList.remove('drag-over')" ondrop="progDrop(event,${est},${cama})"`
}

function progFilaLibre(est, cama, bloq) {
  const g = cama + (est - 1) * 16
  return `
    <tr class="row-est-${est} prog-libre" data-cama="${est}-${cama}" ${progDropAttrs(est, cama, bloq)}>
      <td class="font-mono text-slate-400 text-xs text-center font-bold">${g}</td>
      <td colspan="6" class="text-slate-400 text-xs italic">Cama libre</td>
      <td>${bloq ? "" : `<button class="prog-btn" onclick="progModalAsignar(${est},${cama})"
            aria-label="Asignar un paciente a la cama ${g}">+ Asignar</button>`}</td>
    </tr>`
}

const PROG_TIPO = {
  mover:       { cls: "prog-badge-mover",  txt: "Solo este día" },
  transitorio: { cls: "prog-badge-trans",  txt: "Transitorio (solo este día)" },
  reemplazo:   { cls: "prog-badge-reempl", txt: "Reemplazo (solo este día)" },
}

function progFilaPuesto(pu, bloq, conflicto) {
  const p = pu.paciente, a = pu.asignacion
  const nombre = progEsc(p.nombre)
  const t = PROG_TIPO[pu.tipo]
  let cambio = ""
  if (t) {
    const habitual = p.turno !== PROG.hoja.turno
      ? `${TURNOS[p.turno]} · cama ${pu.base.cama_global}` : `cama ${pu.base.cama_global}`
    cambio = `<span class="prog-badge ${t.cls}">${t.txt}</span>
      <span class="pac-subtxt">${pu.reemplaza ? `En lugar de ${progEsc(pu.reemplaza.nombre)} · ` : ""}Habitual: ${habitual}</span>`
  }
  const acciones = bloq ? "" : `
    <div class="flex gap-1 items-center">
      <button class="prog-btn" onclick="progModalMover(${p.id})" aria-label="Mover a ${nombre} a otra cama">Mover</button>
      ${pu.tipo === "base" || pu.tipo === "mover" ? `<button class="prog-btn" onclick="progModalReemplazar(${p.id})"
          aria-label="Reemplazar a ${nombre} ese día">Reemplazar</button>` : ""}
      ${a ? `<button class="prog-btn prog-btn-undo" onclick="progDeshacer(${a.id})" aria-label="Deshacer el cambio de ${nombre}">↩ Deshacer</button>` : ""}
      ${a && a.tipo !== "reemplazo" ? `<button class="prog-btn prog-btn-perm" onclick="progPermanente(${a.id})"
          aria-label="Hacer permanente la nueva cama de ${nombre}">Hacer permanente</button>` : ""}
    </div>`
  const dis = bloq ? "disabled" : ""
  const inclDis = bloq || a ? "disabled" : ""
  return `
    <tr class="row-est-${pu.estacion} ${a ? "prog-cambio" : ""} ${conflicto ? "prog-conflicto" : ""}"
        data-pid="${p.id}" data-cama="${pu.estacion}-${pu.cama}" tabindex="-1"
        ${progDragAttrs(p.id, bloq)} ${progDropAttrs(pu.estacion, pu.cama, bloq)}>
      <td class="font-mono text-slate-500 text-xs text-center font-bold">${pu.cama_global}</td>
      <td>
        <div class="flex items-center gap-1.5">
          ${accesoHTML(p)}
          <div>
            <span class="font-medium text-sm">${nombre}</span>
            ${pacInfoHTML(p)}
          </div>
        </div>
      </td>
      <td class="text-xs text-slate-500">${p.dias || "—"}</td>
      <td>${cambio}</td>
      <td class="text-center"><input type="checkbox" class="chk-epo" ${pu.epo ? "checked" : ""} ${dis}
          aria-label="EPO para ${nombre}" onchange="progFlag(${p.id},'epo',this.checked)" /></td>
      <td class="text-center"><input type="checkbox" class="chk-hierro" ${pu.hierro ? "checked" : ""} ${dis}
          aria-label="Hierro para ${nombre}" onchange="progFlag(${p.id},'hierro',this.checked)" /></td>
      <td class="text-center"><input type="checkbox" class="w-4 h-4" checked ${inclDis}
          title="${a ? "Deshaga el cambio para quitarlo" : "Quitar de la programación de ese día"}"
          aria-label="Incluir a ${nombre} ese día" onchange="progIncluir(${p.id},this.checked)" /></td>
      <td>${acciones}</td>
    </tr>`
}

function progFueraDeHoja(h, bloq) {
  if (!h.desplazados.length && !h.excluidos.length) return ""
  const filas = [
    ...h.desplazados.map(d => `<li class="prog-fuera-item">
        <span class="badge-H font-bold">H</span>
        <span class="font-medium">${progEsc(d.paciente.nombre)}</span>
        <span class="text-xs text-slate-500">cama ${d.cama_global} · la ocupa ${progEsc(d.reemplazado_por.nombre)} ese día</span>
        ${bloq ? "" : `<button class="prog-btn prog-btn-undo" onclick="progDeshacer(${d.asignacion_id})"
            aria-label="Deshacer el reemplazo de ${progEsc(d.paciente.nombre)}">↩ Deshacer reemplazo</button>`}
      </li>`),
    ...h.excluidos.map(e => `<li class="prog-fuera-item">
        <span class="font-medium">${progEsc(e.paciente.nombre)}</span>
        <span class="text-xs text-slate-500">${progEsc(e.motivo)}</span>
        ${!bloq && e.motivo.startsWith("No incluido") ? `<button class="prog-btn" onclick="progIncluir(${e.paciente.id},true)"
            aria-label="Incluir a ${progEsc(e.paciente.nombre)}">Incluir</button>` : ""}
      </li>`),
  ]
  return `
    <section class="bg-white rounded-xl border border-slate-200 p-4 mt-3" aria-labelledby="prog-fuera-tit">
      <h3 id="prog-fuera-tit" class="font-semibold text-slate-700 text-sm mb-2">Fuera de la hoja ese día (${filas.length})</h3>
      <ul class="prog-fuera-lista">${filas.join("")}</ul>
    </section>`
}

function progResaltar(pid) {
  const tr = document.querySelector(`#prog-vista tr[data-pid="${pid}"]`)
  if (!tr) return
  tr.classList.add("prog-encontrado")
  tr.scrollIntoView({ block: "center", behavior: "smooth" })
  tr.focus({ preventScroll: true })
  setTimeout(() => tr.classList.remove("prog-encontrado"), 2500)
}

// ── Operaciones (todas devuelven la hoja actualizada) ─────────────────────────
async function progEnviar(body, okMsg) {
  try {
    PROG.hoja = await apiPost("/api/asignaciones", { fecha: PROG.fecha, turno: PROG.turno, ...body })
    progDibujar(body.paciente_id)
    if (okMsg) toast(okMsg)
    return true
  } catch (e) { toast(e.message, "err"); return false }
}

async function progMover(pid, est, cama, { permanente = false } = {}) {
  const g = cama + (est - 1) * 16
  return progEnviar({ paciente_id: pid, estacion: est, cama, intercambiar: true, permanente },
    permanente ? `Cama habitual actualizada (cama ${g})` : `Movido a la cama ${g} solo el ${fmtFecha(PROG.fecha)}`)
}

async function progDeshacer(id) {
  try {
    const r = await fetch(`/api/asignaciones/${id}`, { method: "DELETE" })
    PROG.hoja = await (await _apiCheck(r)).json()
    progDibujar(); toast("Cambio deshecho")
  } catch (e) { toast(e.message, "err") }
}

async function progPermanente(id) {
  if (!confirm("¿Convertir este cambio en la ubicación habitual del paciente?\nAfectará todos sus próximos días de diálisis (las hojas pasadas no cambian).")) return
  try {
    PROG.hoja = await apiPost(`/api/asignaciones/${id}/permanente`, {})
    progDibujar(); toast("Ubicación habitual actualizada")
  } catch (e) { toast(e.message, "err") }
}

// EPO / Fe / incluir → lista programada del día (POST /api/programacion), con guardado automático.
function progFlag(pid, campo, valor) {
  const pu = PROG.hoja.puestos.find(p => p.paciente.id === pid); if (!pu) return
  pu[campo] = valor
  progGuardarLista()
}
function progIncluir(pid, incluir) {
  const h = PROG.hoja
  if (incluir) {
    const ex = h.excluidos.find(e => e.paciente.id === pid); if (!ex) return
    h.excluidos = h.excluidos.filter(e => e !== ex)
    const p = ex.paciente
    h.puestos.push({ paciente: p, estacion: p.estacion, cama: p.cama, epo: false, hierro: false, tipo: "base" })
  } else {
    const pu = h.puestos.find(p => p.paciente.id === pid); if (!pu) return
    h.puestos = h.puestos.filter(p => p !== pu)
    h.excluidos.push({ paciente: pu.paciente, motivo: "No incluido en la programación" })
  }
  progGuardarLista(true)
}
function progGuardarLista(recargar = false) {
  clearTimeout(PROG.saveTimer)
  const fecha = PROG.fecha, turno = PROG.turno
  const items = PROG.hoja.puestos.map(p => ({ paciente_id: p.paciente.id, epo_programado: !!p.epo, hierro_programado: !!p.hierro }))
  PROG.saveTimer = setTimeout(async () => {
    try {
      await apiPost("/api/programacion", { fecha, turno, items })
      if (recargar || !PROG.hoja.programado) await progCargar()
      toast("Programación guardada")
    } catch (e) { toast(e.message, "err"); progCargar() }
  }, recargar ? 0 : 600)
}

// ── Arrastrar y soltar ────────────────────────────────────────────────────────
function progDragStart(e, pid) {
  PROG.dragPid = pid
  e.dataTransfer.effectAllowed = "move"
  e.dataTransfer.setData("text/plain", String(pid))
  setTimeout(() => e.target.classList?.add("dragging"), 0)
}
function progDragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = "move" }
function progDragEnd() {
  document.querySelectorAll("#prog-vista tr.dragging, #prog-vista tr.drag-over")
    .forEach(tr => tr.classList.remove("dragging", "drag-over"))
  PROG.dragPid = null
}
function progDrop(e, est, cama) {
  e.preventDefault(); e.stopPropagation()
  const pid = PROG.dragPid || parseInt(e.dataTransfer.getData("text/plain"))
  progDragEnd()
  if (!pid) return
  const pu = PROG.hoja.puestos.find(p => p.paciente.id === pid)
  if (pu && pu.estacion === est && pu.cama === cama) return
  progMover(pid, est, cama)
}

// ── Modales (alternativa accesible por teclado al arrastrar) ──────────────────
function progOpcionesCama(est, excluirPid) {
  const ocup = {}
  PROG.hoja.puestos.forEach(p => { if (p.estacion === est) (ocup[p.cama] ||= []).push(p.paciente) })
  let html = ""
  for (let c = 1; c <= 16; c++) {
    const g = c + (est - 1) * 16
    const quien = (ocup[c] || []).filter(x => x.id !== excluirPid)
    html += `<option value="${c}">Cama ${g}${quien.length ? " — " + progEsc(quien.map(x => x.nombre).join(", ")) + " (intercambiar)" : " — libre"}</option>`
  }
  return html
}

function progModalEscape(e) { if (e.key === "Escape") closeModal() }

function progModalUbicacion(titulo, intro, pid, estIni, camaIni, onConfirm, conPermanente = true) {
  window._progConfirmar = onConfirm
  openModal(titulo, `
    <p class="text-sm text-slate-500 mb-3">${intro}</p>
    <div class="grid grid-cols-2 gap-3" onkeydown="progModalEscape(event)">
      <div>
        <label for="prog-m-est" class="form-label">Estación</label>
        <select id="prog-m-est" class="form-input"
          onchange="document.getElementById('prog-m-cama').innerHTML = progOpcionesCama(parseInt(this.value), ${pid || 0})">
          ${[1, 2, 3].map(e => `<option value="${e}" ${e === estIni ? "selected" : ""}>${e} — ${EST_LABEL[e]}</option>`).join("")}
        </select>
      </div>
      <div>
        <label for="prog-m-cama" class="form-label">Cama</label>
        <select id="prog-m-cama" class="form-input">${progOpcionesCama(estIni, pid)}</select>
      </div>
    </div>
    ${conPermanente ? `<label class="flex items-start gap-2 mt-4 text-sm cursor-pointer select-none">
      <input type="checkbox" id="prog-m-perm" class="w-4 h-4 mt-0.5" />
      <span><strong>Cambio permanente</strong><span class="block text-xs text-slate-500">Actualiza la cama habitual del paciente para todos sus próximos días. Sin marcar, el cambio es solo para el ${fmtFecha(PROG.fecha)}.</span></span>
    </label>` : ""}`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg font-medium">Cancelar</button>
     <button onclick="_progConfirmar()" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg font-medium ml-2">Confirmar</button>`)
  const sel = $("prog-m-cama")
  if (sel) { sel.value = String(camaIni); sel.focus() }
}

function _progLeerModal() {
  return {
    est: parseInt($("prog-m-est").value),
    cama: parseInt($("prog-m-cama").value),
    permanente: !!$("prog-m-perm")?.checked,
  }
}

function progModalMover(pid) {
  const pu = PROG.hoja.puestos.find(p => p.paciente.id === pid); if (!pu) return
  progModalUbicacion(`Mover a ${progEsc(pu.paciente.nombre)}`,
    `Hoy está en la cama ${pu.cama_global}. Si la cama elegida está ocupada, los dos pacientes se intercambian.`,
    pid, pu.estacion, pu.cama, async () => {
      const m = _progLeerModal()
      if (m.est === pu.estacion && m.cama === pu.cama && !m.permanente) { closeModal(); return }
      closeModal()
      await progMover(pid, m.est, m.cama, { permanente: m.permanente })
    })
}

// Selector de paciente con búsqueda (para reemplazos y camas libres).
function progSelectorPaciente(idPrefijo) {
  return `
    <label for="${idPrefijo}-inp" class="form-label">Paciente</label>
    <div class="slot-search-wrap mt-1">
      <input type="search" id="${idPrefijo}-inp" class="slot-input" style="width:100%" autocomplete="off"
        placeholder="Escriba nombre o cédula…" role="combobox" aria-expanded="false"
        aria-controls="${idPrefijo}-drop" aria-autocomplete="list"
        oninput="progSelBuscar('${idPrefijo}')" onkeydown="progSelTeclas(event,'${idPrefijo}')" />
      <div class="slot-dropdown hidden" id="${idPrefijo}-drop" role="listbox"></div>
    </div>
    <div id="${idPrefijo}-sel" class="hidden mt-2 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2 text-sm text-emerald-800" aria-live="polite"></div>`
}

let _progSel = null
let _progSelTimer = null
function progSelBuscar(pref) {
  clearTimeout(_progSelTimer)
  _progSelTimer = setTimeout(async () => {
    const q = $(`${pref}-inp`)?.value.trim()
    const drop = $(`${pref}-drop`); if (!drop) return
    if (!q) { drop.classList.add("hidden"); return }
    try {
      const res = await apiGet(`/api/asignaciones/buscar?q=${encodeURIComponent(q)}&fecha=${PROG.fecha}&limite=10`)
      window._progSelRes = res
      drop.innerHTML = res.length ? res.map((r, i) => progItemBusqueda(r, i, `progSelElegir('${pref}',${i})`)).join("")
        : `<div class="slot-drop-item text-slate-400">Sin resultados</div>`
      drop.classList.remove("hidden")
      $(`${pref}-inp`).setAttribute("aria-expanded", "true")
    } catch (e) { toast(e.message, "err") }
  }, 200)
}
function progSelElegir(pref, i) {
  const r = window._progSelRes?.[i]; if (!r) return
  _progSel = r
  $(`${pref}-drop`).classList.add("hidden")
  $(`${pref}-inp`).value = r.paciente.nombre
  $(`${pref}-inp`).setAttribute("aria-expanded", "false")
  const sel = $(`${pref}-sel`)
  sel.innerHTML = `✔ <strong>${progEsc(r.paciente.nombre)}</strong> · ${progDondeEsta(r)}`
  sel.classList.remove("hidden")
}
function progSelTeclas(e, pref) {
  _progNavLista(e, $(`${pref}-drop`), i => progSelElegir(pref, i))
}

function progDondeEsta(r) {
  const u = r.en_hoja
  if (u && u.tipo === "reemplazado") return `reemplazado ese día`
  if (u) return `ese día: ${TURNOS[u.turno]} · cama ${u.cama_global}`
  if (r.activo === false) return "inactivo"
  return r.le_toca === false ? "no le toca ese día" : "no está en ninguna hoja ese día"
}

function progItemBusqueda(r, i, accion) {
  const p = r.paciente
  return `<div class="slot-drop-item" role="option" id="prog-opt-${i}" onmousedown="${accion}">
      ${accesoHTML(p)}
      <div class="flex-1 min-w-0">
        <span class="font-semibold text-slate-800 text-sm">${progEsc(p.nombre)}</span>
        <span class="text-slate-400 text-xs ml-1.5">${progDondeEsta(r)}</span>
      </div>
      <span class="text-xs text-slate-400 shrink-0">${progEsc(p.cedula)}</span>
    </div>`
}

function _progNavLista(e, drop, elegir) {
  if (!drop || drop.classList.contains("hidden")) return
  const items = drop.querySelectorAll(".slot-drop-item[role=option]")
  if (!items.length) return
  let idx = [...items].findIndex(x => x.classList.contains("active"))
  if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(idx + 1, items.length - 1) }
  else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(idx - 1, 0) }
  else if (e.key === "Enter") { e.preventDefault(); elegir(Math.max(idx, 0)); return }
  else if (e.key === "Escape") { drop.classList.add("hidden"); return }
  else return
  items.forEach((el, k) => el.classList.toggle("active", k === idx))
  items[idx]?.scrollIntoView({ block: "nearest" })
  e.target.setAttribute("aria-activedescendant", items[idx]?.id || "")
}

function progModalReemplazar(pid) {
  const pu = PROG.hoja.puestos.find(p => p.paciente.id === pid); if (!pu) return
  _progSel = null
  window._progConfirmar = async () => {
    if (!_progSel) { toast("Seleccione el paciente que ocupará la cama", "warn"); return }
    closeModal()
    await progEnviar({ paciente_id: _progSel.paciente.id, tipo: "reemplazo", reemplaza_paciente_id: pid },
      `${_progSel.paciente.nombre} ocupa la cama ${pu.cama_global} solo el ${fmtFecha(PROG.fecha)}`)
  }
  openModal(`Reemplazar a ${progEsc(pu.paciente.nombre)}`,
    `<div onkeydown="progModalEscape(event)">
       <p class="text-sm text-slate-500 mb-3">Solo el ${fmtFecha(PROG.fecha)}: ${progEsc(pu.paciente.nombre)} no viene y la cama ${pu.cama_global} la ocupa otro paciente. Su cama habitual no cambia.</p>
       ${progSelectorPaciente("prog-r")}
     </div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg font-medium">Cancelar</button>
     <button onclick="_progConfirmar()" class="bg-amber-600 hover:bg-amber-500 text-white text-sm px-4 py-2 rounded-lg font-medium ml-2">Confirmar reemplazo</button>`)
  setTimeout(() => $("prog-r-inp")?.focus(), 30)
}

function progModalAsignar(est, cama, preseleccion = null) {
  const g = cama + (est - 1) * 16
  _progSel = preseleccion
  window._progConfirmar = async () => {
    if (!_progSel) { toast("Seleccione un paciente", "warn"); return }
    const perm = !!$("prog-a-perm")?.checked
    closeModal()
    await progMover(_progSel.paciente.id, est, cama, { permanente: perm })
  }
  openModal(`Asignar paciente a la cama ${g}`,
    `<div onkeydown="progModalEscape(event)">
       <p class="text-sm text-slate-500 mb-3">Paciente transitorio (de otro turno, de otros días o nuevo) en la cama libre ${g} del ${fmtFecha(PROG.fecha)}, ${TURNOS[PROG.turno]}.</p>
       ${progSelectorPaciente("prog-a")}
       <label class="flex items-start gap-2 mt-4 text-sm cursor-pointer select-none">
         <input type="checkbox" id="prog-a-perm" class="w-4 h-4 mt-0.5" />
         <span><strong>Cambio permanente</strong><span class="block text-xs text-slate-500">La cama ${g} del turno ${TURNOS[PROG.turno]} pasa a ser su cama habitual.</span></span>
       </label>
     </div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-4 py-2 rounded-lg font-medium">Cancelar</button>
     <button onclick="_progConfirmar()" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-4 py-2 rounded-lg font-medium ml-2">Asignar</button>`)
  setTimeout(() => {
    if (preseleccion) { window._progSelRes = [preseleccion]; progSelElegir("prog-a", 0) }
    $("prog-a-inp")?.focus()
  }, 30)
}

// ── Buscador de la barra superior ─────────────────────────────────────────────
let _progBuscarTimer = null
function progBuscar(q) {
  clearTimeout(_progBuscarTimer)
  _progBuscarTimer = setTimeout(async () => {
    const drop = $("prog-buscar-drop"); if (!drop) return
    q = (q || "").trim()
    if (!q) { progCerrarBusqueda(); return }
    try {
      const res = await apiGet(`/api/asignaciones/buscar?q=${encodeURIComponent(q)}&fecha=${PROG.fecha}&limite=10`)
      window._progBuscarRes = res
      drop.innerHTML = res.length ? res.map((r, i) => progItemBusqueda(r, i, `progIrA(${i})`)).join("")
        : `<div class="slot-drop-item text-slate-400">Sin resultados</div>`
      drop.classList.remove("hidden")
      $("prog-buscar").setAttribute("aria-expanded", "true")
    } catch (e) { toast(e.message, "err") }
  }, 200)
}
function progBuscarTeclas(e) { _progNavLista(e, $("prog-buscar-drop"), progIrA) }
function progCerrarBusqueda() {
  $("prog-buscar-drop")?.classList.add("hidden")
  $("prog-buscar")?.setAttribute("aria-expanded", "false")
}

async function progIrA(i) {
  const r = window._progBuscarRes?.[i]; if (!r) return
  progCerrarBusqueda()
  const u = r.en_hoja
  if (u) {
    if (u.turno !== PROG.turno) { PROG.turno = u.turno; await progCargar() }
    if (PROG.est && PROG.est !== u.estacion) PROG.est = 0
    progDibujar(r.paciente.id)
    if (u.tipo === "reemplazado") toast(`${r.paciente.nombre} está reemplazado ese día (ver «Fuera de la hoja»)`, "warn")
    return
  }
  if (progBloqueada()) { toast(`${r.paciente.nombre}: ${progDondeEsta(r)}`, "warn"); return }
  // No está en ninguna hoja ese día: ofrecer asignarlo a la primera cama libre.
  const ocup = new Set(PROG.hoja.puestos.map(p => `${p.estacion}-${p.cama}`))
  for (const est of [1, 2, 3]) for (let c = 1; c <= 16; c++) {
    if (!ocup.has(`${est}-${c}`)) { progModalAsignar(est, c, r); return }
  }
  toast(`No hay camas libres en el turno ${TURNOS[PROG.turno]}; use «Reemplazar»`, "warn")
}
