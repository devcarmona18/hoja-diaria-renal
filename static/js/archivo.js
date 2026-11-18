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
