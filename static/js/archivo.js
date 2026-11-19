/* ============================================================
   archivo.js — R13: lista de pacientes archivados
   El paciente archivado sale de listas, hojas, programación y pedidos.
   Aquí aparece ARCHIVO_DIAS días (180 por defecto) y se puede restaurar (admin); después sale
   solo de esta lista: sus sesiones, labs y asistencia nunca se borran.
   Depende de: app.js, crud.js
   ============================================================ */

let _archivados = []

async function renderArchivados() {
  G.vista = "archivados"
  updateHeader()
  let d
  try { d = await apiGet("/api/pacientes/archivados") } catch (e) { toast(e.message, "err"); return }

  _archivados = d.pacientes
  const rows = d.pacientes.map(p => `<tr>
      <td class="text-left font-medium">${escHtml(p.nombre)}</td>
      <td class="text-xs text-slate-600">${escHtml(p.cedula)}</td>
      <td class="text-xs text-slate-600">${TURNOS[p.turno] || p.turno}</td>
      <td class="text-left text-xs">${escHtml(p.motivo) || "—"}</td>
      <td class="text-xs">${fmtFecha(p.archivado_en.slice(0, 10))}</td>
      <td class="text-xs"><strong>${p.dias_restantes}</strong> día${p.dias_restantes === 1 ? "" : "s"}</td>
      <td class="whitespace-nowrap">
        <button onclick="renderLabs(${p.id}, _nombreArchivado(${p.id}))" class="bg-purple-100 hover:bg-purple-200 text-purple-800 text-xs px-2 py-1 rounded font-medium btn-foco">Labs</button>
        <button onclick="archivoRestaurar(${p.id})" class="solo-admin bg-emerald-100 hover:bg-emerald-200 text-emerald-800 text-xs px-2 py-1 rounded font-medium btn-foco">Restaurar</button>
      </td></tr>`).join("")

  app().innerHTML = `
    <div class="max-w-5xl mx-auto space-y-4">
      <div class="bg-white rounded-2xl shadow-xl p-6">
        <div class="flex flex-wrap items-center justify-between gap-2 mb-4">
          <div><h2 class="text-xl font-bold text-blue-900">Pacientes archivados</h2>
            <p class="text-slate-500 text-sm">Se listan ${d.archivo_dias} días desde el archivo y se pueden restaurar en ese plazo.</p></div>
          <button onclick="renderCRUD()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">← Pacientes</button>
        </div>
        <form onsubmit="event.preventDefault(); archivoBuscarCedula()" class="flex flex-wrap items-end gap-2 mb-3" role="search">
          <label class="text-xs text-slate-600">Buscar por cédula (incluye archivados que ya salieron de la lista)
            <input id="arch-cedula" type="search" inputmode="numeric" autocomplete="off" minlength="3"
              class="block mt-1 border border-slate-300 rounded-lg px-3 py-1.5 text-sm w-56" placeholder="Cédula" /></label>
          <button type="submit" class="bg-blue-800 hover:bg-blue-700 text-white text-sm px-3 py-1.5 rounded-lg font-medium btn-foco">Buscar</button>
        </form>
        <div id="arch-resultados" class="mb-4" aria-live="polite"></div>
        <div class="overflow-x-auto rounded-xl border border-slate-200">
          <table class="tbl-stats w-full"><thead><tr><th class="text-left">Paciente</th><th>Cédula</th><th>Turno</th><th class="text-left">Motivo</th>
            <th>Archivado</th><th>Sale de la lista en</th><th></th></tr></thead>
            <tbody>${rows || `<tr><td colspan="7" class="py-8 text-center text-slate-500">No hay pacientes archivados.</td></tr>`}</tbody></table>
        </div>
        <p class="text-xs text-slate-500 mt-2">Pasado el plazo el paciente deja de aparecer aquí, pero sus sesiones, laboratorios y asistencia se conservan
          y siguen visibles en Historial y Estadísticas.</p>
      </div>
    </div>`
}

function _nombreArchivado(id) { return (_archivados.find(p => p.id === id) || {}).nombre || "Paciente" }

function archivoRestaurar(id) {
  const nombre = _nombreArchivado(id)
  openModal("Restaurar paciente",
    `<p class="text-sm text-slate-700"><strong>${escHtml(nombre)}</strong> volverá a las listas, hojas y programación de su turno y cama.</p>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cancelar</button>
     <button onclick="_archivoConfirmarRestaurar(${id})" class="bg-emerald-700 hover:bg-emerald-800 text-white px-4 py-2 rounded-lg text-sm font-semibold btn-foco">Restaurar</button>`)
}

async function _archivoConfirmarRestaurar(id) {
  closeModal()
  try { await apiPost(`/api/pacientes/${id}/restaurar`, {}); toast("Paciente restaurado"); renderArchivados() }
  catch (e) { toast(e.message, "err") }
}

// ── Reactivar (sin límite de tiempo; solo admin; queda auditado) ─────────────
let _archBuscados = []

async function archivoBuscarCedula() {
  const ced = ($("arch-cedula").value || "").trim()
  const caja = $("arch-resultados")
  if (ced.length < 3) { caja.innerHTML = `<p class="text-xs text-slate-500">Escriba al menos 3 caracteres de la cédula.</p>`; return }
  let d
  try { d = await apiGet(`/api/pacientes/archivados/buscar?cedula=${encodeURIComponent(ced)}`) } catch (e) { toast(e.message, "err"); return }
  _archBuscados = d.pacientes
  caja.innerHTML = d.pacientes.length ? `
    <div class="overflow-x-auto rounded-xl border border-amber-200 bg-amber-50/40">
      <table class="tbl-stats w-full" id="arch-tabla-busqueda"><thead><tr><th class="text-left">Paciente</th><th>Cédula</th><th>Archivado</th><th>Estado</th><th></th></tr></thead>
      <tbody>${d.pacientes.map(p => `<tr data-pid="${p.id}">
        <td class="text-left font-medium">${escHtml(p.nombre)}</td>
        <td class="text-xs">${escHtml(p.cedula)}</td>
        <td class="text-xs">${fmtFecha(p.archivado_en.slice(0, 10))}</td>
        <td class="text-xs">${p.en_ventana ? "En la lista" : "Fuera de la lista"}</td>
        <td><button onclick="archivoOfrecerReactivar(_archBuscados.find(x => x.id === ${p.id}))"
          class="solo-admin bg-emerald-100 hover:bg-emerald-200 text-emerald-800 text-xs px-2 py-1 rounded font-medium btn-foco">Reactivar</button></td>
      </tr>`).join("")}</tbody></table></div>`
    : `<p class="text-xs text-slate-500">Ningún paciente archivado con esa cédula.</p>`
}

function archivoOfrecerReactivar(p) {
  if (!p) return
  openModal("Reactivar paciente archivado",
    `<p class="text-sm text-slate-700">La cédula <strong>${escHtml(p.cedula)}</strong> es de
       <strong>${escHtml(p.nombre)}</strong>, archivado el ${fmtFecha(p.archivado_en.slice(0, 10))}${p.motivo ? ` (${escHtml(p.motivo)})` : ""}.</p>
     <p class="text-sm text-slate-700 mt-2">Al reactivarlo vuelve a las listas, hojas y programación con sus datos anteriores
       y su historial completo; revise turno, cama y prescripción después.</p>
     <label class="block text-xs text-slate-600 mt-3">Motivo (opcional)
       <input id="arch-react-motivo" maxlength="300" class="block w-full mt-1 border border-slate-300 rounded-lg px-3 py-1.5 text-sm" placeholder="Reingreso a la unidad" /></label>`,
    `<button onclick="closeModal()" class="bg-slate-100 hover:bg-slate-200 text-slate-700 px-4 py-2 rounded-lg text-sm font-medium btn-foco">Cancelar</button>
     <button onclick="_archivoConfirmarReactivar(${p.id})" class="solo-admin bg-emerald-700 hover:bg-emerald-800 text-white px-4 py-2 rounded-lg text-sm font-semibold btn-foco">Reactivar paciente archivado</button>`)
}

async function _archivoConfirmarReactivar(id) {
  const motivo = ($("arch-react-motivo")?.value || "").trim() || null
  closeModal()
  try {
    const r = await apiPost(`/api/pacientes/${id}/reactivar`, { motivo })
    toast(`Paciente reactivado: ${r.nombre}`)
    await crudEditarPorId(r.id, r.turno)
  } catch (e) { toast(e.message, "err") }
}
