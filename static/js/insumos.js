/* ============================================================
   insumos.js — Pedido de insumos (R5/R6)
   Depende de: app.js (G, $, app, apiGet/apiPost/apiPut/apiDelete, escHtml, toast…)
   Lógica en el servidor: routers/insumos.py · services/insumos.py
   ============================================================ */

const INS_SECCIONES = [
  { id: "pedido",     titulo: "Pedido",       sub: "Sesiones del próximo día de diálisis", cls: "ins-sec-pedido" },
  { id: "adicional",  titulo: "Adicionales",  sub: "Pacientes adicionales que llegaron hoy (van en el pedido de hoy)", cls: "ins-sec-adicional" },
  { id: "devolucion", titulo: "Devoluciones", sub: "Pedidos para hoy: no asistieron y sin peso de entrada", cls: "ins-sec-devolucion" },
  { id: "revisar",    titulo: "Revisar",      sub: "Datos que no cuadran: no suman en los totales", cls: "ins-sec-revisar" },
]

let _ins = { fecha: null, turno: "", estacion: 0, datos: null }

/** Fecha local AAAA-MM-DD (toISOString daría la fecha UTC: en la noche ya sería mañana). */
function _insHoyLocal() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function _insQuery() {
  const q = new URLSearchParams({ fecha: _ins.fecha })
  if (_ins.turno) q.set("turno", _ins.turno)
  if (_ins.estacion) q.set("estacion", _ins.estacion)
  return q.toString()
}

async function renderInsumos(fecha = null) {
  G.vista = "insumos"
  updateHeader()
  _ins.fecha = fecha || _ins.fecha || _insHoyLocal()
  app().innerHTML = `<div class="max-w-6xl mx-auto"><div class="bg-white rounded-2xl shadow-xl p-6 text-slate-500 text-sm">Calculando pedido…</div></div>`
  try {
    _ins.datos = await apiGet(`/api/insumos/pedido?${_insQuery()}`)
  } catch (e) {
    toast(e.message, "err")
    app().innerHTML = `<div class="max-w-6xl mx-auto"><div class="bg-white rounded-2xl shadow-xl p-6">
      <p class="prog-alerta">${escHtml(e.message)}</p>
      <button onclick="_ins.fecha=null;renderInsumos()" class="prog-btn mt-3">Volver a hoy</button>
      <button onclick="goHome()" class="prog-btn mt-3">← Inicio</button></div></div>`
    return
  }
  _insPintar()
}

function _insFiltrar(turno, estacion) {
  _ins.turno = turno; _ins.estacion = estacion
  renderInsumos()
}

function _insChips(opciones, actual, onclick) {
  return opciones.map(o => `<button type="button" onclick="${onclick(o.v)}" aria-pressed="${o.v === actual}"
      class="ins-chip ${o.v === actual ? "ins-chip-on" : ""}">${escHtml(o.l)}</button>`).join("")
}

function _insItemsHTML(items) {
  if (!items.length) return `<span class="text-slate-400 text-xs">—</span>`
  return items.map(i => `<span class="ins-item" title="${escHtml(i.nombre + (i.detalle ? " · " + i.detalle : ""))}">
    <strong>${i.cantidad}×</strong> ${escHtml(i.nombre)}${i.detalle ? ` <span class="ins-item-det">${escHtml(i.detalle)}</span>` : ""}</span>`).join("")
}

function _insAvisosHTML(f) {
  return (f.alertas || []).map(a => `<span class="ins-alerta">⚠ ${escHtml(a)}</span>`).join(" ")
}

function _insTablaSeccion(sec, filas) {
  const conMotivo = sec.id !== "pedido"
  if (!filas.length) {
    return `<p class="text-sm text-slate-400 px-1 py-2">Sin pacientes en esta sección${_ins.turno || _ins.estacion ? " (con el filtro actual)" : ""}.</p>`
  }
  const rows = filas.map(f => `
    <tr class="${f.estacion ? "row-est-" + f.estacion : ""}">
      <td class="font-mono text-xs text-center">${f.cama_global ?? "—"}</td>
      <td class="text-xs text-center">${f.turno ? escHtml(f.turno) : "—"}</td>
      <td><span class="font-medium">${escHtml(f.nombre)}</span>
        <span class="pac-subtxt">${escHtml(f.cedula || "")}${f.tipo && !["base", "adicional"].includes(f.tipo) ? " · cambio de un día" : ""}</span></td>
      <td class="text-xs">${escHtml(f.acceso)}</td>
      ${conMotivo ? `<td class="text-xs">${escHtml(f.motivo || "")}</td>` : ""}
      <td>${_insItemsHTML(f.items)} ${_insAvisosHTML(sec.id === "revisar" ? { alertas: [] } : f)}</td>
    </tr>`).join("")
  return `<div class="overflow-x-auto rounded-xl border border-slate-200">
    <table class="tbl-crud ins-tabla">
      <thead><tr>
        <th class="w-10">Cama</th><th class="w-10">Turno</th><th>Paciente</th><th class="w-40">Acceso</th>
        ${conMotivo ? `<th class="w-48">Motivo</th>` : ""}<th>Insumos${sec.id === "revisar" ? " (no suman)" : ""}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`
}

function _insTotalesHTML(t) {
  const filas = {}
  const orden = []
  for (const s of ["pedido", "adicional", "devolucion", "neto"]) {
    for (const i of t[s]) {
      if (!filas[i.codigo]) { filas[i.codigo] = { nombre: i.nombre, unidad: i.unidad, detalle: i.detalle }; orden.push(i.codigo) }
      filas[i.codigo][s] = i.cantidad
    }
  }
  if (!orden.length) return `<p class="text-sm text-slate-400">Sin insumos.</p>`
  const n = v => v ? v : `<span class="text-slate-300">0</span>`
  return `<div class="overflow-x-auto rounded-xl border border-slate-200">
    <table class="tbl-crud ins-tabla ins-totales">
      <thead><tr><th>Insumo</th><th class="w-24">Unidad</th>
        <th class="w-20 text-right">Pedido</th><th class="w-24 text-right">Adicionales</th>
        <th class="w-24 text-right">Devolución</th><th class="w-20 text-right" title="Pedido + adicionales − devoluciones">Neto</th></tr></thead>
      <tbody>${orden.map(c => { const f = filas[c]; return `<tr>
        <td>${escHtml(f.nombre)}${f.detalle ? ` <span class="ins-item-det">${escHtml(f.detalle)}</span>` : ""}</td>
        <td class="text-xs text-slate-500">${escHtml(f.unidad)}</td>
        <td class="text-right font-mono">${n(f.pedido)}</td><td class="text-right font-mono">${n(f.adicional)}</td>
        <td class="text-right font-mono">${n(f.devolucion)}</td><td class="text-right font-mono font-bold">${n(f.neto)}</td></tr>` }).join("")}
      </tbody>
    </table></div>`
}

function _insPintar() {
  const d = _ins.datos
  const conf = d.confirmado
  const turnos = [{ v: "", l: "Todos" }, ...["M", "T", "N"].map(t => ({ v: t, l: TURNOS[t] }))]
  const ests = [{ v: 0, l: "Todas" }, ...[1, 2, 3].map(e => ({ v: e, l: `Est. ${e} ${EST_LABEL[e]}` }))]
  const filtroTxt = [_ins.turno ? `Turno ${TURNOS[_ins.turno]}` : "", _ins.estacion ? `Estación ${_ins.estacion}` : ""].filter(Boolean).join(" · ")
  const origen = d.origen_devoluciones || {}
  const pend = d.pendientes || []
  const prev = d.adicionales_previstos || []
  const nov = d.novedades || []
  const cuenta = s => d.secciones[s].length

  const estado = conf
    ? `<span class="ins-estado ins-estado-ok">CONFIRMADO / ENVIADO</span>
       <span class="text-xs text-slate-500">${escHtml(conf.por || "")} · ${escHtml((conf.en || "").replace("T", " "))}</span>`
    : `<span class="ins-estado ins-estado-borrador">BORRADOR</span>
       <span class="text-xs text-slate-500">se recalcula hasta confirmarlo</span>`

  app().innerHTML = `
  <div class="max-w-6xl mx-auto space-y-4 ins-pagina">
    <div class="bg-white rounded-2xl shadow-xl p-6 print-section">
      <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 class="text-xl font-bold text-blue-900">Pedido de insumos</h2>
          <p class="text-slate-600 text-sm mt-0.5">
            Pedido del <strong class="capitalize">${escHtml(d.dia_pedido)}</strong> ${fmtFecha(d.fecha_pedido)}
            → sesiones del <strong class="capitalize">${escHtml(d.dia_sesiones)}</strong> ${fmtFecha(d.fecha_sesiones)}
            ${filtroTxt ? ` · <span class="text-blue-800">${escHtml(filtroTxt)}</span>` : ""}
          </p>
          <div class="flex flex-wrap items-center gap-2 mt-1">${estado}</div>
        </div>
        <div class="flex flex-wrap gap-2 no-print">
          <button onclick="window.print()" class="prog-btn">🖨 Imprimir</button>
          <a href="/api/insumos/pedido.csv?${_insQuery()}" class="prog-btn ins-link" download>⬇ CSV</a>
          <button onclick="renderInsumosReglas()" class="prog-btn">Reglas</button>
          ${conf
            ? `<button onclick="_insAnular()" class="solo-admin prog-btn ins-btn-peligro">Anular confirmación</button>`
            : `<button onclick="_insConfirmar()" class="solo-admin ins-btn-confirmar">Confirmar / Enviar</button>`}
          <button onclick="goHome()" class="prog-btn">← Inicio</button>
        </div>
      </div>

      <div class="flex flex-wrap items-end gap-4 mb-4 no-print">
        <div>
          <label class="form-label" for="ins-fecha">Fecha del pedido</label>
          <input id="ins-fecha" type="date" class="form-input ins-fecha" value="${d.fecha_pedido}"
            onchange="if(this.value) renderInsumos(this.value)" />
        </div>
        <div><span class="form-label">Turno</span><div class="flex gap-1" role="group" aria-label="Filtrar por turno">
          ${_insChips(turnos, _ins.turno, v => `_insFiltrar('${v}', ${_ins.estacion})`)}</div></div>
        <div><span class="form-label">Estación</span><div class="flex gap-1" role="group" aria-label="Filtrar por estación">
          ${_insChips(ests, _ins.estacion, v => `_insFiltrar('${_ins.turno}', ${v})`)}</div></div>
      </div>

      <div class="ins-avisos text-sm">
        <p class="prog-aviso">Devoluciones y revisión: lo pedido para hoy sale
          ${origen.tipo === "confirmado"
            ? `del pedido confirmado el ${fmtFecha(origen.fecha_pedido)}.`
            : `de la hoja de hoy recalculada (no hay pedido confirmado que cubra el ${fmtFecha(d.fecha_pedido)}).`}
          ${pend.length ? ` <strong>${pend.length}</strong> pendiente${pend.length > 1 ? "s" : ""} (hoja sin abrir, asistencia sin marcar o adicional sin llegar).` : ""}
        </p>
        ${pend.length ? `<details class="no-print ins-detalles"><summary>Ver pendientes</summary>
          <ul class="ins-lista">${pend.map(p => `<li>${escHtml(p.nombre)} · ${TURNOS[p.turno] || ""} — ${escHtml(p.motivo)}</li>`).join("")}</ul></details>` : ""}
        ${prev.length ? `<p class="text-xs text-slate-500">Adicionales previstos para el ${fmtFecha(d.fecha_sesiones)} (se piden el día que lleguen):
          ${prev.map(p => escHtml(p.nombre)).join(", ")}</p>` : ""}
        ${conf && nov.length ? `<div class="prog-alerta"><strong>Novedades posteriores a la confirmación</strong> (no están en el pedido enviado):
          <ul class="ins-lista">${nov.map(n => `<li>${n.seccion === "adicional" ? "Adicional" : "Devolución"}: ${escHtml(n.nombre)} — ${escHtml(n.motivo || "")}</li>`).join("")}</ul></div>` : ""}
      </div>
    </div>

    <div class="bg-white rounded-2xl shadow-xl p-6 print-section">
      <h3 class="ins-h3">Totales por insumo</h3>
      ${_insTotalesHTML(d.totales)}
    </div>

    ${INS_SECCIONES.map(s => `
    <section class="bg-white rounded-2xl shadow-xl p-6 ${s.cls}" aria-labelledby="ins-h-${s.id}">
      <h3 id="ins-h-${s.id}" class="ins-h3">${s.titulo} <span class="ins-cuenta">${cuenta(s.id)}</span></h3>
      <p class="text-xs text-slate-500 mb-3">${s.sub}${s.id === "adicional" ? " · Para un adicional de un solo día marque «Adic.» en su fila de la hoja diaria." : ""}</p>
      ${_insTablaSeccion(s, d.secciones[s.id])}
    </section>`).join("")}

    <div class="ins-firmas print-only">
      <div>Elaboró</div><div>Revisó</div><div>Recibió</div>
    </div>
  </div>`
}

async function _insConfirmar() {
  if (!confirm("¿Confirmar y enviar el pedido?\nSe guarda una foto: aunque después se editen pacientes o reglas, este pedido no cambia.")) return
  try {
    await apiPost("/api/insumos/pedido/confirmar", { fecha: _ins.datos.fecha_pedido })
    toast("Pedido confirmado")
    renderInsumos()
  } catch (e) { toast(e.message, "err") }
}

async function _insAnular() {
  if (!confirm("¿Anular la confirmación?\nEl pedido vuelve a borrador y se recalcula con los datos actuales.")) return
  try {
    await apiDelete(`/api/insumos/pedido/${_ins.datos.fecha_pedido}`)
    toast("Confirmación anulada", "warn")
    renderInsumos()
  } catch (e) { toast(e.message, "err") }
}

// ── Reglas ────────────────────────────────────────────────────────────────────

function _insCondTxt(si) {
  if (!si) return ""
  const p = []
  if (si.acceso) p.push(si.acceso.join(" o "))
  if (si.sitio) p.push("sitio " + si.sitio.join(" o "))
  if (si.estado_fav) p.push("FAV " + si.estado_fav.join(" o "))
  if (si.turno) p.push("turno " + si.turno.map(t => TURNOS[t] || t).join(" o "))
  if (si.dia_semana) p.push(si.dia_semana.join(" o "))
  if (si.citrato_o_heparina_sodica === true) p.push("con citrato o heparina sódica")
  if (si.citrato_o_heparina_sodica === false) p.push("sin citrato ni heparina sódica")
  if (si.citrato != null) p.push(si.citrato ? "con citrato" : "sin citrato")
  if (si.heparina_sodica != null) p.push(si.heparina_sodica ? "con heparina sódica" : "sin heparina sódica")
  return p.join(" · ")
}

function _insCantTxt(c) {
  if (typeof c === "number") return String(c)
  return c.map(k => { const t = _insCondTxt(k.si); return t ? `${k.cantidad} si ${t}` : `si no ${k.cantidad}` }).join("; ")
}

async function renderInsumosReglas() {
  G.vista = "insumos-reglas"
  updateHeader()
  let r
  try { r = await apiGet("/api/insumos/reglas") } catch (e) { toast(e.message, "err"); return }
  const R = r.reglas
  const filas = R.reglas.map(x => {
    const ins = R.insumos[x.insumo] || {}
    return `<tr><td>${escHtml(ins.nombre || x.insumo)} <span class="pac-subtxt">${escHtml(x.insumo)}</span></td>
      <td class="text-xs">${escHtml(_insCondTxt(x.si)) || "siempre"}</td>
      <td class="text-xs">${escHtml(_insCantTxt(x.cantidad))} ${escHtml(ins.unidad || "")}${ins.detalle ? ` <span class="ins-item-det">${escHtml(ins.detalle)}</span>` : ""}</td></tr>`
  }).join("")
  const ro = G.readonly ? "readonly" : ""
  app().innerHTML = `
  <div class="max-w-5xl mx-auto space-y-4">
    <div class="bg-white rounded-2xl shadow-xl p-6">
      <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 class="text-xl font-bold text-blue-900">Reglas del pedido de insumos</h2>
          <p class="text-slate-500 text-sm mt-0.5">${r.origen === "personalizadas"
            ? `Personalizadas · ${escHtml(r.actualizado_por || "")} ${escHtml((r.actualizado_en || "").replace("T", " "))}`
            : "Predeterminadas (services/insumos_reglas.json)"} · versión ${R.version}</p>
        </div>
        <div class="flex gap-2">
          <button onclick="renderInsumos()" class="prog-btn">← Pedido</button>
          <button onclick="goHome()" class="prog-btn">Inicio</button>
        </div>
      </div>
      <p class="text-xs text-slate-500 mb-2">Por cada sesión del paciente. Sin calibre o sin filtro no se adivina: aparece el aviso «${escHtml(R.faltantes?.calibre || "Calibre faltante")}» / «${escHtml(R.faltantes?.filtro || "Filtro faltante")}».</p>
      <div class="overflow-x-auto rounded-xl border border-slate-200">
        <table class="tbl-crud ins-tabla"><thead><tr><th>Insumo</th><th>Cuándo</th><th>Cantidad</th></tr></thead>
        <tbody>${filas}</tbody></table>
      </div>
    </div>
    <div class="bg-white rounded-2xl shadow-xl p-6">
      <h3 class="ins-h3">Editar (JSON)</h3>
      <p class="text-xs text-slate-500 mb-2">Formato en docs/insumos.md. Se valida al guardar; si hay un error no se cambia nada.</p>
      <label class="sr-only" for="ins-json">Reglas en JSON</label>
      <textarea id="ins-json" class="form-input ins-json" spellcheck="false" ${ro}>${escHtml(JSON.stringify(R, null, 2))}</textarea>
      <p id="ins-json-error" class="prog-alerta mt-2 hidden" role="alert"></p>
      <div class="flex gap-2 mt-3 solo-admin">
        <button onclick="_insGuardarReglas()" class="ins-btn-confirmar">Guardar reglas</button>
        ${r.origen === "personalizadas" ? `<button onclick="_insRestaurarReglas()" class="prog-btn ins-btn-peligro">Restaurar predeterminadas</button>` : ""}
      </div>
    </div>
  </div>`
}

async function _insGuardarReglas() {
  const err = $("ins-json-error")
  err.classList.add("hidden")
  let datos
  try { datos = JSON.parse($("ins-json").value) } catch (e) {
    err.textContent = "JSON inválido: " + e.message; err.classList.remove("hidden"); return
  }
  try {
    await apiPut("/api/insumos/reglas", datos)
    toast("Reglas guardadas")
    renderInsumosReglas()
  } catch (e) { err.textContent = e.message; err.classList.remove("hidden") }
}

async function _insRestaurarReglas() {
  if (!confirm("¿Volver a las reglas predeterminadas? Se pierden los cambios guardados.")) return
  try { await apiDelete("/api/insumos/reglas"); toast("Reglas predeterminadas"); renderInsumosReglas() }
  catch (e) { toast(e.message, "err") }
}
