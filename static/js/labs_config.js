/* ============================================================
   labs_config.js — R13: rangos de laboratorio, médicos y Teams
   Depende de: app.js, laboratorios.js
   ============================================================ */

async function renderLabConfig() {
  G.vista = "labconfig"
  updateHeader()
  let rangos, medicos, est
  try {
    ;[rangos, medicos, est] = await Promise.all([
      apiGet("/api/labs/rangos"), apiGet("/api/labs/medicos"), apiGet("/api/labs/notificaciones/estado")])
  } catch (e) { toast(e.message, "err"); return }

  const num = v => (v == null ? "" : v)
  const filasRangos = rangos.map(r => `<tr>
      <td class="text-left font-medium">${escHtml(r.etiqueta)} ${r.personalizado ? `<span class="badge-mes abierto">personalizado</span>` : ""}</td>
      <td class="text-xs text-slate-600">${escHtml(r.unidad || "—")}</td>
      ${["minimo", "maximo", "muy_alto"].map(k => `<td><input class="rango-input" type="number" step="any" min="0"
          id="rg-${r.tipo}-${k}" value="${num(r[k])}" aria-label="${escHtml(r.etiqueta)}: ${k.replace("_", " ")}" /></td>`).join("")}
      <td class="whitespace-nowrap">
        <button class="solo-admin bg-blue-800 hover:bg-blue-700 text-white text-xs px-2 py-1 rounded font-semibold btn-foco" onclick="labCfgGuardarRango('${r.tipo}')">Guardar</button>
        ${r.personalizado ? `<button class="solo-admin bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs px-2 py-1 rounded font-semibold btn-foco" onclick="labCfgRestablecer('${r.tipo}')">Restablecer</button>` : ""}
      </td></tr>`).join("")

  const filasMedicos = medicos.map(m => `<tr>
      <td class="text-left font-medium">${escHtml(m.nombre)}</td>
      <td><input class="rango-input" style="width:5em" id="md-ini-${m.id}" value="${escHtml(m.iniciales)}" maxlength="10" aria-label="Iniciales de ${escHtml(m.nombre)}" /></td>
      <td class="text-left"><input class="rango-input" type="url" id="md-url-${m.id}" autocomplete="off"
            placeholder="${m.tiene_webhook ? "Configurado: " + escHtml(m.webhook_enmascarado) + " (escriba otro para cambiarlo)" : "https://…logic.azure.com/…"}"
            aria-label="Webhook de Teams de ${escHtml(m.nombre)}" /></td>
      <td class="text-xs">${m.tiene_webhook ? (m.webhook_valido ? "Webhook válido" : "Webhook no permitido") : "Sin webhook"}</td>
      <td class="whitespace-nowrap">
        <button class="solo-admin bg-blue-800 hover:bg-blue-700 text-white text-xs px-2 py-1 rounded font-semibold btn-foco" onclick="labCfgGuardarMedico(${m.id})">Guardar</button>
        ${m.tiene_webhook ? `<button class="solo-admin bg-slate-100 hover:bg-slate-200 text-slate-800 text-xs px-2 py-1 rounded font-semibold btn-foco" onclick="labCfgQuitarWebhook(${m.id})">Quitar webhook</button>` : ""}
      </td></tr>`).join("")

  app().innerHTML = `
    <div class="max-w-6xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
          <div><h2 class="text-xl font-bold text-blue-900">Laboratorios — Rangos y notificaciones</h2>
            <p class="text-slate-500 text-sm">Solo el administrador puede cambiar estos valores.</p></div>
          <button onclick="renderLabPanel()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">← Panel</button>
        </div>

        <h3 class="font-semibold text-slate-800 mb-1">Rangos por examen</h3>
        <p class="text-xs text-slate-600 mb-2">Bajo: por debajo del mínimo · Normal: entre mínimo y máximo · Alto: sobre el máximo · Muy alto: sobre el último umbral. Deje vacío un límite que no aplique.</p>
        <div class="overflow-x-auto rounded-xl border border-slate-200 mb-6">
          <table class="tbl-stats w-full"><thead><tr><th class="text-left">Examen</th><th>Unidad</th><th>Mínimo</th><th>Máximo</th><th>Muy alto</th><th></th></tr></thead>
            <tbody>${filasRangos}</tbody></table></div>

        <h3 class="font-semibold text-slate-800 mb-1">Médicos tratantes y Microsoft Teams</h3>
        <div class="hoja-aviso ${est.enabled ? "cerrada" : "abierta"}" role="status">
          Notificaciones por Teams: <strong>${est.enabled ? "ACTIVADAS" : "APAGADAS"}</strong>
          ${est.enabled ? "" : " (TEAMS_ENABLED=false: no se envía nada)"} · Días de envío del mes: <strong>${est.dias_envio.join(" y ") || "—"}</strong>
          · Token del trabajo programado: ${est.token_configurado ? "configurado" : "no configurado"}.
          Los pacientes se identifican solo por iniciales.
        </div>
        <div class="overflow-x-auto rounded-xl border border-slate-200 mb-3">
          <table class="tbl-stats w-full"><thead><tr><th class="text-left">Médico</th><th>Iniciales</th><th class="text-left">Webhook de Teams</th><th>Estado</th><th></th></tr></thead>
            <tbody>${filasMedicos || `<tr><td colspan="5" class="py-6 text-slate-500">No hay médicos registrados en los pacientes.</td></tr>`}</tbody></table></div>
        <div class="flex flex-wrap gap-2">
          <button onclick="labCfgVistaPrevia()" class="solo-admin bg-slate-100 hover:bg-slate-200 text-slate-800 text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco">Vista previa del reporte</button>
          <button onclick="labCfgEnviar()" ${est.enabled ? "" : "disabled"} class="solo-admin bg-blue-800 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm px-3 py-1.5 rounded-lg font-semibold btn-foco"
            title="${est.enabled ? "Envía ahora a los médicos con webhook" : "Active TEAMS_ENABLED para poder enviar"}">Enviar ahora</button>
        </div>
        ${est.ultimos_envios.length ? `<p class="text-xs text-slate-600 mt-3">Últimos envíos: ${est.ultimos_envios.map(e =>
          `${fmtFecha(e.fecha)} · ${e.pacientes} pac. · ${e.estado}${e.detalle ? " (" + escHtml(e.detalle) + ")" : ""}`).join(" — ")}</p>` : ""}
      </div>
    </div>`
}

async function labCfgGuardarRango(tipo) {
  const v = k => { const x = $(`rg-${tipo}-${k}`).value; return x === "" ? null : parseFloat(x) }
  try {
    await apiPut(`/api/labs/rangos/${tipo}`, { minimo: v("minimo"), maximo: v("maximo"), muy_alto: v("muy_alto") })
    toast("Rango guardado"); renderLabConfig()
  } catch (e) { toast(e.message, "err") }
}

async function labCfgRestablecer(tipo) {
  try { await apiDelete(`/api/labs/rangos/${tipo}`); toast("Rango restablecido"); renderLabConfig() }
  catch (e) { toast(e.message, "err") }
}

async function labCfgGuardarMedico(id) {
  const cuerpo = { iniciales: $(`md-ini-${id}`).value }
  const url = $(`md-url-${id}`).value.trim()
  if (url) cuerpo.teams_webhook_url = url
  try { await apiPut(`/api/labs/medicos/${id}`, cuerpo); toast("Médico guardado"); renderLabConfig() }
  catch (e) { toast(e.message, "err") }
}

async function labCfgQuitarWebhook(id) {
  try { await apiPut(`/api/labs/medicos/${id}`, { teams_webhook_url: "" }); toast("Webhook quitado"); renderLabConfig() }
  catch (e) { toast(e.message, "err") }
}

async function labCfgVistaPrevia() {
  let d
  try { d = await apiGet("/api/labs/notificaciones/vista-previa") } catch (e) { toast(e.message, "err"); return }
  const cuerpo = d.reportes.length ? d.reportes.map(r => `
      <section class="mb-3"><h4 class="font-semibold text-sm text-slate-800">${escHtml(r.medico)} · ${r.total_pacientes} paciente(s)
        <span class="text-xs font-normal text-slate-600">${r.tiene_webhook ? "con webhook" : "sin webhook"}</span></h4>
        <ul class="text-xs text-slate-700 list-disc ml-5">${r.pacientes.slice(0, 40).map(p => `<li><strong>${escHtml(p.iniciales)}</strong>: ${p.hallazgos.map(h =>
          `${escHtml(h.etiqueta)} ${h.valor} ${escHtml(h.unidad)} (${ESTADO_LAB[h.estado].txt.toLowerCase()})`).join("; ")}</li>`).join("")}</ul></section>`).join("")
    : `<p class="text-sm text-slate-600">Ningún paciente activo tiene resultados fuera de rango.</p>`
  openModal("Vista previa del reporte (no se envía nada)",
    `<div class="max-h-96 overflow-y-auto">${cuerpo}</div>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cerrar</button>`, { ancho: true })
}

async function labCfgEnviar() {
  if (!confirm("¿Enviar ahora el reporte a los médicos que tienen webhook configurado?")) return
  try {
    const r = await apiPost("/api/labs/notificaciones/enviar", { forzar: true })
    toast(`Enviados: ${r.enviados.length} · omitidos: ${r.omitidos.length}`, r.enviados.length ? "ok" : "warn")
    renderLabConfig()
  } catch (e) { toast(e.message, "err") }
}
