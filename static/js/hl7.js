/* ============================================================
   hl7.js — Integración con máquinas AK 98 («Próximamente»)
   Depende de: app.js (G, apiGet, apiPost, toast, updateHeader, app, fmtFecha…)

   - Burbuja «Próximamente» visible para todos los roles (también demo):
     abre un panel con video ilustrativo y explicación.
   - «Bandeja de la máquina»: solo se monta si GET /api/hl7/estado devuelve
     {habilitado: true}. Con HL7_ENABLED=false no aparece nada más.
   ============================================================ */

const HL7_VIDEO  = "/static/media/hl7-proximamente.mp4"
const HL7_POSTER = "/static/media/hl7-proximamente.jpg"
const HL7_NOTA   = "Disponible próximamente. Requiere autorización de la unidad y activación técnica de las máquinas."

let _hl7Estado = { habilitado: false }
let _hl7FocoPrevio = null

function _hl7Esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]))
}

// ── Burbuja y panel «Próximamente» ───────────────────────────────────────────
function _hl7MontarBurbuja() {
  if (document.getElementById("hl7-flotantes")) return
  const cont = document.createElement("div")
  cont.id = "hl7-flotantes"
  cont.className = "hl7-flotantes print:hidden"
  cont.innerHTML = `
    <button type="button" id="hl7-burbuja" class="hl7-burbuja" title="Próximamente: integración AK 98"
      aria-haspopup="dialog" aria-controls="hl7-modal"
      aria-label="Próximamente: integración con máquinas AK 98. Nuevo">
      <span class="hl7-burbuja-icono" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="3" width="10" height="18" rx="2"/>
          <path d="M7 7h4M7 11h4"/><path d="M17 8c1.5 1 2.5 2.5 2.5 4s-1 3-2.5 4"/></svg>
      </span>
      <span class="hl7-texto">Próximamente</span>
      <span class="hl7-insignia" aria-hidden="true">Nuevo</span>
    </button>`
  document.body.appendChild(cont)
  document.getElementById("hl7-burbuja").addEventListener("click", hl7AbrirProximamente)

  // R8: la burbuja se ve SOLO en la pantalla de inicio; en el resto de la app
  // «Próximamente» se abre desde la sección del menú (renderProximamente).
  const compactar = () => {
    const enInicio = typeof G !== "undefined" && G.vista === "dashboard"
    cont.hidden = !enInicio
    if (!enInicio) hl7CerrarProximamente()
  }
  const raiz = document.getElementById("app")
  if (raiz) new MutationObserver(compactar).observe(raiz, { childList: true })
  compactar()
}

/** Contenido «Próximamente» (video + pasos). Lo comparten el panel de la burbuja y la sección del menú. */
function _hl7CuerpoHTML(pfx) {
  return `
      <div class="hl7-cuerpo">
        <div class="hl7-media">
          <video id="${pfx}-video" data-hl7-video controls muted loop playsinline preload="none" poster="${HL7_POSTER}"
            aria-label="Video ilustrativo: la máquina envía los datos y la hoja se llena sola"></video>
          <img id="${pfx}-poster" data-hl7-poster src="${HL7_POSTER}" alt="Ilustración de la integración con las máquinas AK 98" hidden>
          <div id="${pfx}-ilustracion" data-hl7-ilustracion class="hl7-ilustracion" hidden aria-hidden="true">
            <span>AK 98</span><span>→</span><span>Hoja diaria</span><span>→</span><span>✓ Confirmar</span>
          </div>
        </div>
        <p id="${pfx}-desc" class="mb-3">
          Estamos preparando la conexión directa con las máquinas de hemodiálisis de la unidad para que
          los datos de cada sesión lleguen solos a la hoja diaria, sin transcribir.
        </p>
        <ol class="hl7-pasos">
          <li class="hl7-paso"><span class="hl7-paso-num">1</span>
            <div><strong>La máquina envía</strong>Al terminar la sesión, la AK 98 envía peso de entrada y salida, UF, Kt/V, tensión, frecuencia, duración y alarmas.</div></li>
          <li class="hl7-paso"><span class="hl7-paso-num">2</span>
            <div><strong>Viaja de forma segura</strong>Un equipo de la unidad recibe los datos y los reenvía cifrados y firmados. Solo lectura: nunca se envían órdenes a la máquina.</div></li>
          <li class="hl7-paso"><span class="hl7-paso-num">3</span>
            <div><strong>La hoja se llena sola</strong>Los valores quedan como borrador en la «Bandeja de la máquina», con alertas si algo no cuadra.</div></li>
          <li class="hl7-paso"><span class="hl7-paso-num">4</span>
            <div><strong>El personal solo confirma</strong>Nada es oficial hasta que enfermería lo revisa y confirma.</div></li>
        </ol>
        <p class="hl7-nota" role="note">${HL7_NOTA}</p>
      </div>
  `
}

function _hl7MontarModal() {
  if (document.getElementById("hl7-modal")) return
  const ov = document.createElement("div")
  ov.id = "hl7-modal"
  ov.className = "hl7-overlay"
  ov.hidden = true
  ov.innerHTML = `
    <div class="hl7-modal" role="dialog" aria-modal="true" aria-labelledby="hl7-modal-titulo" aria-describedby="hl7-desc">
      <div class="hl7-modal-cab">
        <div>
          <span class="hl7-etiqueta">Próximamente</span>
          <h2 id="hl7-modal-titulo" class="hl7-titulo">Integración con máquinas AK 98</h2>
        </div>
        <button type="button" class="hl7-cerrar" data-hl7-cerrar aria-label="Cerrar">&times;</button>
      </div>
      ${_hl7CuerpoHTML("hl7")}
      <div class="hl7-pie">
        <button type="button" class="hl7-btn" data-hl7-cerrar>Entendido</button>
      </div>
    </div>`
  document.body.appendChild(ov)

  ov.addEventListener("click", e => {
    if (e.target === ov || e.target.closest("[data-hl7-cerrar]")) hl7CerrarProximamente()
  })
  ov.addEventListener("keydown", _hl7Teclado)

  // Degradación elegante: sin video → póster; sin póster → ilustración.
  const video = document.getElementById("hl7-video")
  const poster = document.getElementById("hl7-poster")
  video.addEventListener("error", _hl7SinVideo, true)  // también captura el error del <source>
  poster.addEventListener("error", () => {
    _hl7PosterFallo = true
    if (document.getElementById("hl7-video").hidden) _hl7SinVideo(true)
  })
}

let _hl7PosterFallo = false

function _hl7SinVideo(forzar = false) {
  const video = document.getElementById("hl7-video")
  if (!video || (video.hidden && forzar !== true)) return
  video.pause?.()
  video.hidden = true
  document.getElementById("hl7-poster").hidden = _hl7PosterFallo
  document.getElementById("hl7-ilustracion").hidden = !_hl7PosterFallo
}

function _hl7Enfocables(cont) {
  return [...cont.querySelectorAll('button, [href], input, select, textarea, video[controls], [tabindex]:not([tabindex="-1"])')]
    .filter(el => !el.disabled && !el.hidden && el.offsetParent !== null)
}

function _hl7Teclado(e) {
  if (e.key === "Escape") { e.preventDefault(); hl7CerrarProximamente(); return }
  if (e.key !== "Tab") return
  const items = _hl7Enfocables(document.querySelector("#hl7-modal .hl7-modal"))
  if (!items.length) return
  const primero = items[0], ultimo = items[items.length - 1]
  if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus() }
  else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus() }
}

function hl7AbrirProximamente() {
  _hl7MontarModal()
  const ov = document.getElementById("hl7-modal")
  _hl7FocoPrevio = document.activeElement
  ov.hidden = false
  document.getElementById("hl7-burbuja")?.setAttribute("aria-expanded", "true")

  const video = document.getElementById("hl7-video")
  if (!video.hidden) {
    if (!video.querySelector("source")) {       // el video se descarga solo al abrir el panel
      const src = document.createElement("source")
      src.src = HL7_VIDEO
      src.type = "video/mp4"
      src.addEventListener("error", _hl7SinVideo)
      video.appendChild(src)
      video.load()
    }
    const sinMovimiento = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    if (!sinMovimiento) {
      video.muted = true
      video.autoplay = true
      const p = video.play()
      if (p && p.catch) p.catch(() => {})       // autoplay bloqueado: quedan los controles
    }
  }
  ov.querySelector(".hl7-cerrar").focus()
}

function hl7CerrarProximamente() {
  const ov = document.getElementById("hl7-modal")
  if (!ov || ov.hidden) return
  document.getElementById("hl7-video")?.pause?.()
  ov.hidden = true
  document.getElementById("hl7-burbuja")?.setAttribute("aria-expanded", "false")
  if (_hl7FocoPrevio && _hl7FocoPrevio.focus) _hl7FocoPrevio.focus()
}

// ── Sección «Próximamente» del menú (R8): mismo contenido que la burbuja ─────
function renderProximamente() {
  G.sesion = null; G.registros = []
  G.vista = "proximamente"
  updateHeader()
  hl7CerrarProximamente()
  app().innerHTML = `
    <div class="max-w-3xl mx-auto">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-start justify-between mb-4">
          <div>
            <span class="hl7-etiqueta">Próximamente</span>
            <h2 class="text-xl font-bold text-blue-900">Integración con máquinas AK 98</h2>
          </div>
          <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Inicio</button>
        </div>
        ${_hl7CuerpoHTML("hl7v")}
      </div>
    </div>`
  const video = document.getElementById("hl7v-video")
  const poster = document.getElementById("hl7v-poster")
  const ilus = document.getElementById("hl7v-ilustracion")
  let posterFallo = false
  const sinVideo = () => { video.pause?.(); video.hidden = true; poster.hidden = posterFallo; ilus.hidden = !posterFallo }
  poster.addEventListener("error", () => { posterFallo = true; if (video.hidden) sinVideo() })
  video.addEventListener("error", sinVideo, true)
  const src = document.createElement("source")
  src.src = HL7_VIDEO
  src.type = "video/mp4"
  src.addEventListener("error", sinVideo)
  video.appendChild(src)
  video.load()
}

// ── Bandeja de la máquina (solo con HL7 habilitado) ─────────────────────────
function _hl7MontarBotonBandeja() {
  if (document.getElementById("hl7-bandeja-btn")) return
  const btn = document.createElement("button")
  btn.type = "button"
  btn.id = "hl7-bandeja-btn"
  btn.className = "hl7-burbuja hl7-bandeja-btn"
  btn.setAttribute("aria-label", "Bandeja de la máquina: borradores pendientes de confirmar")
  btn.title = "Bandeja de la máquina"
  btn.innerHTML = `<span class="hl7-burbuja-icono" aria-hidden="true">⇩</span>
    <span class="hl7-texto">Bandeja de la máquina</span><span id="hl7-bandeja-n" class="hl7-insignia" hidden>0</span>`
  btn.addEventListener("click", () => renderBandejaHL7())
  document.getElementById("hl7-flotantes").prepend(btn)
}

async function _hl7ActualizarContador() {
  try {
    const r = await fetch("/api/hl7/borradores")
    if (!r.ok) return
    const n = (await r.json()).length
    const el = document.getElementById("hl7-bandeja-n")
    if (el) { el.textContent = n; el.hidden = n === 0 }
  } catch { /* sin conexión: se reintenta en el próximo ciclo */ }
}

const _HL7_ETIQUETAS = {
  peso_entrada: ["PE", "kg"], peso_salida: ["PS", "kg"], uf_litros: ["UF", "L"], ktv: ["Kt/V", ""],
  frecuencia_cardiaca: ["FC", "lpm"], duracion_min: ["Dur.", "min"],
}

function _hl7Valores(v) {
  const partes = Object.entries(_HL7_ETIQUETAS)
    .filter(([k]) => v[k] != null)
    .map(([k, [et, u]]) => `${et} <b>${_hl7Esc(v[k])}</b>${u ? " " + u : ""}`)
  if (v.ta_sistolica != null) partes.splice(4, 0, `TA <b>${_hl7Esc(v.ta_sistolica)}/${_hl7Esc(v.ta_diastolica)}</b>`)
  let html = partes.join(" · ")
  if (v.alarmas?.length) html += `<div class="text-xs text-slate-500">Alarmas: ${v.alarmas.map(_hl7Esc).join(", ")}</div>`
  return html
}

function _hl7Banderas(bs) {
  return (bs || []).map(b =>
    `<span class="hl7-chip ${b.nivel === "alerta" ? "hl7-chip-alerta" : "hl7-chip-info"}" title="${_hl7Esc(b.mensaje)}">${_hl7Esc(b.mensaje)}</span>`
  ).join("")
}

let _hl7Pacientes = null

async function renderBandejaHL7() {
  if (!_hl7Estado.habilitado) return
  G.sesion = null; G.registros = []
  G.vista = "hl7"
  updateHeader()
  let borradores = []
  try { borradores = await apiGet("/api/hl7/borradores") } catch (e) { toast(e.message, "err"); return }
  if (!_hl7Pacientes && borradores.some(b => !b.paciente)) {
    try { _hl7Pacientes = await apiGet("/api/pacientes") } catch { _hl7Pacientes = [] }
  }

  const filas = borradores.map(b => {
    const p = b.paciente
    const quien = p
      ? `<div class="font-semibold">${_hl7Esc(p.nombre)}</div>
         <div class="text-xs text-slate-500">Cama ${displayCama(p.cama, p.estacion)} · ${_hl7Esc(p.cedula)}</div>`
      : `<div class="hl7-desc">Paciente sin identificar</div>
         <div class="text-xs text-slate-500">Id máquina: ${_hl7Esc(b.id_externo || "—")}</div>
         ${G.readonly ? "" : `<select id="hl7-pac-${b.id}" class="form-input form-select mt-1 hl7-select" aria-label="Paciente para el borrador ${b.id}">
           <option value="">Seleccione paciente…</option>
           ${(_hl7Pacientes || []).filter(x => x.activo !== false && (!b.turno || x.turno === b.turno))
             .map(x => `<option value="${x.id}">${_hl7Esc(x.nombre)} · cama ${displayCama(x.cama, x.estacion)}</option>`).join("")}
         </select>`}`
    const actual = b.registro_actual
    const enHoja = actual && (actual.peso_entrada != null || actual.peso_salida != null || actual.ktv != null)
      ? `<div class="text-xs text-slate-500 mt-1">En la hoja: PE ${fmtPeso(actual.peso_entrada)} · PS ${fmtPeso(actual.peso_salida)} · Kt/V ${actual.ktv ?? "—"}</div>` : ""
    const acciones = G.readonly ? `<span class="text-xs text-slate-400">Solo lectura</span>` : `
      <div class="flex gap-2">
        <button type="button" class="hl7-btn hl7-btn-ok" onclick="hl7Confirmar(${b.id})">Confirmar</button>
        <button type="button" class="hl7-btn hl7-btn-sec" onclick="hl7Descartar(${b.id})">Descartar</button>
      </div>`
    return `<tr>
      <td>${quien}</td>
      <td>${b.fecha ? fmtFecha(b.fecha) : "—"}<div class="text-xs text-slate-500">${TURNOS[b.turno] || "—"} · ${_hl7Esc(b.maquina || "")}</div></td>
      <td class="hl7-valores">${_hl7Valores(b.valores || {})}${enHoja}</td>
      <td>${_hl7Banderas(b.banderas)}</td>
      <td>${acciones}</td>
    </tr>`
  }).join("")

  app().innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-xl font-bold text-blue-900">Bandeja de la máquina</h2>
            <p class="text-slate-500 text-sm mt-0.5">Datos recibidos de las máquinas AK 98. Nada pasa a la hoja hasta que se confirme.</p>
          </div>
          <button onclick="goHome()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium">← Inicio</button>
        </div>
        ${borradores.length ? `<div class="overflow-x-auto"><table class="tbl-crud">
          <thead><tr><th>Paciente</th><th>Sesión</th><th>Valores de la máquina</th><th>Revisión</th><th></th></tr></thead>
          <tbody>${filas}</tbody></table></div>`
        : `<p class="text-slate-500 text-sm">No hay borradores pendientes.</p>`}
      </div>
    </div>`
  _hl7ActualizarContador()
}

async function hl7Confirmar(id) {
  const sel = document.getElementById(`hl7-pac-${id}`)
  const body = {}
  if (sel) {
    if (!sel.value) { toast("Seleccione el paciente antes de confirmar", "warn"); sel.focus(); return }
    body.paciente_id = Number(sel.value)
  }
  try {
    const r = await apiPost(`/api/hl7/borradores/${id}/confirmar`, body)
    if (r.conflictos?.length) {
      toast(`Confirmado. Se conservaron valores escritos a mano: ${r.conflictos.map(c => c.campo).join(", ")}`, "warn")
    } else toast("Confirmado en la hoja del día")
    renderBandejaHL7()
  } catch (e) { toast(e.message, "err") }
}

async function hl7Descartar(id) {
  const motivo = window.prompt("Motivo del descarte (opcional):", "")
  if (motivo === null) return
  try {
    await apiPost(`/api/hl7/borradores/${id}/descartar`, { motivo })
    toast("Borrador descartado")
    renderBandejaHL7()
  } catch (e) { toast(e.message, "err") }
}

// ── Inicio ───────────────────────────────────────────────────────────────────
async function iniciarHL7() {
  _hl7MontarBurbuja()
  try {
    const r = await fetch("/api/hl7/estado")
    if (r.ok) _hl7Estado = await r.json()
  } catch { _hl7Estado = { habilitado: false } }
  if (_hl7Estado.habilitado === true) {
    _hl7MontarBotonBandeja()
    _hl7ActualizarContador()
    setInterval(_hl7ActualizarContador, 60000)
  }
}
iniciarHL7()
