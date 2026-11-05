/* ============================================================
   ia.js — Fase 4: IA Clínica  (consulta sobre historial)
   Depende de: app.js, crud.js
   ============================================================ */

let _iaPacId       = null
let _iaPacNombre   = ""
let _iaChatHistory = []    // { role: "user"|"assistant", text: "..." }
let _iaEnviando    = false

// ── Entrada principal ─────────────────────────────────────────────────────────

async function renderIA(pacienteId = null, pacienteNombre = null) {
  G.vista = "ia"
  _iaPacId     = pacienteId
  _iaPacNombre = pacienteNombre || ""
  _iaChatHistory = []
  updateHeader()

  let status
  try { status = await apiGet("/api/ia/status") }
  catch (e) { toast(e.message, "err"); return }

  if (!status.configured) {
    _renderIASetup()
  } else if (!_iaPacId) {
    _renderIASeleccionPaciente()
  } else {
    _renderIAChat()
  }
}

// ── Vista: configurar clave API ───────────────────────────────────────────────

function _renderIASetup() {
  app().innerHTML = `
    <div class="max-w-lg mx-auto mt-10">
      <div class="bg-white rounded-2xl shadow-xl p-8">
        <div class="text-center mb-6">
          <div class="inline-flex items-center justify-center w-14 h-14 bg-indigo-100 rounded-full mb-2">
            <span class="text-3xl">🤖</span>
          </div>
          <h2 class="text-xl font-bold text-blue-900">Configurar IA Clínica (Fase 4)</h2>
          <p class="text-slate-500 text-sm mt-1">
            Ingrese su clave de API de Anthropic para activar la consulta IA.<br/>
            La clave se guarda localmente en el servidor (ia_config.json).
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-sm font-semibold text-slate-600 mb-1">Clave API de Anthropic</label>
            <input id="ia-key-input" type="password" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm
              focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono"
              placeholder="sk-ant-api03-..." />
            <p class="text-xs text-slate-400 mt-1">
              Obtenga su clave en console.anthropic.com → API Keys
            </p>
          </div>
          <button onclick="_iaGuardarConfig()"
            class="w-full bg-indigo-700 hover:bg-indigo-600 text-white font-bold py-3 rounded-xl text-sm">
            Guardar y activar IA
          </button>
          <div id="ia-setup-err" class="text-red-600 text-sm hidden"></div>
        </div>

        <div class="mt-6 bg-amber-50 border border-amber-200 rounded-xl p-4 text-xs text-amber-800">
          <strong>Nota de privacidad:</strong> Al usar esta función, el historial clínico del paciente
          (datos ficticios en modo desarrollo) se envía a la API de Anthropic para generar la respuesta.
          No use datos reales hasta contar con aprobación institucional.
        </div>

        <div class="mt-4 text-center">
          <button onclick="goHome()" class="text-slate-400 hover:text-slate-600 text-sm underline">← Volver al inicio</button>
        </div>
      </div>
    </div>
  `
}

async function _iaGuardarConfig() {
  const key = $("ia-key-input")?.value.trim()
  const err = $("ia-setup-err")
  if (!key) { err.textContent = "Ingrese la clave API"; err.classList.remove("hidden"); return }
  err.classList.add("hidden")
  try {
    await apiPost("/api/ia/config", { api_key: key })
    toast("IA configurada correctamente")
    _renderIASeleccionPaciente()
  } catch (e) {
    err.textContent = e.message; err.classList.remove("hidden")
  }
}

// ── Vista: selección de paciente (cuando se entra desde dashboard) ─────────────

async function _renderIASeleccionPaciente() {
  let pacientes = []
  try { pacientes = await apiGet("/api/pacientes?activo=true") } catch (e) { toast(e.message, "err"); return }

  // Agrupar por turno y estación
  const byTurno = { M: [], T: [], N: [] }
  pacientes.forEach(p => byTurno[p.turno]?.push(p))

  const turnoSections = ["M","T","N"].map(t => {
    if (!byTurno[t].length) return ""
    const opts = byTurno[t]
      .sort((a, b) => a.estacion - b.estacion || a.cama - b.cama)
      .map(p => `<option value="${p.id}">${displayCama(p.cama,p.estacion)} · ${p.nombre}</option>`)
      .join("")
    return `<optgroup label="${TURNOS[t]}">${opts}</optgroup>`
  }).join("")

  app().innerHTML = `
    <div class="max-w-lg mx-auto mt-10">
      <div class="bg-white rounded-2xl shadow-xl p-8">
        <div class="text-center mb-6">
          <span class="text-4xl">🤖</span>
          <h2 class="text-xl font-bold text-blue-900 mt-2">IA Clínica — Seleccione paciente</h2>
          <p class="text-slate-500 text-sm mt-1">Elija un paciente para consultar su historial</p>
        </div>
        <div class="space-y-4">
          <div>
            <label class="block text-sm font-semibold text-slate-600 mb-1">Paciente</label>
            <select id="ia-pac-sel" class="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm
              focus:outline-none focus:ring-2 focus:ring-indigo-500">
              <option value="">— Seleccione —</option>
              ${turnoSections}
            </select>
          </div>
          <button onclick="_iaIrPaciente()"
            class="w-full bg-indigo-700 hover:bg-indigo-600 text-white font-bold py-3 rounded-xl text-sm">
            Abrir consulta IA →
          </button>
        </div>
        <div class="mt-4 text-center flex gap-4 justify-center">
          <button onclick="goHome()" class="text-slate-400 hover:text-slate-600 text-sm underline">← Inicio</button>
          <button onclick="_renderIASetup()" class="text-indigo-400 hover:text-indigo-600 text-sm underline">Cambiar clave API</button>
        </div>
      </div>
    </div>
  `
}

function _iaIrPaciente() {
  const sel = $("ia-pac-sel")
  const id  = parseInt(sel?.value)
  if (!id) { toast("Seleccione un paciente", "warn"); return }
  const opt = sel.options[sel.selectedIndex]
  _iaPacId     = id
  _iaPacNombre = opt.text.split(" · ").slice(1).join(" · ") || opt.text
  _iaChatHistory = []
  _renderIAChat()
}

// ── Vista: chat ───────────────────────────────────────────────────────────────

function _renderIAChat() {
  app().innerHTML = `
    <div class="max-w-3xl mx-auto flex flex-col" style="height:calc(100vh - 80px)">
      <div class="bg-white rounded-2xl shadow-xl flex flex-col overflow-hidden flex-1">

        <!-- Header chat -->
        <div class="flex items-center gap-3 px-5 py-3 border-b border-slate-200 bg-indigo-50">
          <span class="text-2xl">🤖</span>
          <div class="flex-1 min-w-0">
            <h2 class="font-bold text-indigo-900 text-sm leading-tight">IA Clínica — ${_iaPacNombre}</h2>
            <p class="text-indigo-600 text-xs">Consulta sobre historial · Solo datos ficticios</p>
          </div>
          <div class="flex gap-2 flex-shrink-0">
            <button onclick="_iaChatHistory=[]; _renderIAChat()" title="Nueva conversación"
              class="text-indigo-400 hover:text-indigo-700 text-xs px-2 py-1 rounded border border-indigo-200 hover:bg-indigo-100">
              Nueva conv.
            </button>
            <button onclick="_renderIASeleccionPaciente()"
              class="text-slate-400 hover:text-slate-600 text-xs px-2 py-1 rounded border border-slate-200 hover:bg-slate-100">
              Cambiar paciente
            </button>
            <button onclick="goHome()"
              class="text-slate-400 hover:text-slate-600 text-xs px-2 py-1 rounded border border-slate-200 hover:bg-slate-100">
              ← Inicio
            </button>
          </div>
        </div>

        <!-- Mensajes -->
        <div id="ia-msgs" class="flex-1 overflow-y-auto px-5 py-4 space-y-4 bg-slate-50">
          ${_iaChatHistory.length === 0 ? `
            <div class="text-center py-8 text-slate-400">
              <p class="text-4xl mb-2">💬</p>
              <p class="font-medium text-slate-500 text-sm mb-1">Haga una pregunta sobre el paciente</p>
              <p class="text-xs">Ejemplos de preguntas:</p>
              <div class="flex flex-wrap gap-2 justify-center mt-2">
                ${[
                  "¿Cuál es la tendencia de la Hb en los últimos 3 meses?",
                  "¿Cuándo fue la última hospitalización?",
                  "¿Cómo ha variado el peso seco?",
                  "¿Cuál es el promedio de Kt/V reciente?",
                  "Resumen clínico del paciente",
                ].map(q => `<button class="text-xs bg-white border border-indigo-200 text-indigo-600 px-2 py-1 rounded-full hover:bg-indigo-50"
                  onclick="$('ia-input').value='${q.replace(/'/g, "\\'")}'; _iaEnviar()">${q}</button>`).join("")}
              </div>
            </div>` : _iaMsgsHTML()}
        </div>

        <!-- Input -->
        <div class="border-t border-slate-200 px-4 py-3 bg-white">
          <div class="flex gap-2">
            <textarea id="ia-input" rows="2"
              class="flex-1 border border-slate-300 rounded-xl px-3 py-2 text-sm resize-none
                focus:outline-none focus:ring-2 focus:ring-indigo-500"
              placeholder="Escriba su pregunta clínica aquí…"
              onkeydown="if(event.key==='Enter' && !event.shiftKey){event.preventDefault(); _iaEnviar()}"></textarea>
            <button onclick="_iaEnviar()" id="ia-btn-send"
              class="bg-indigo-700 hover:bg-indigo-600 text-white px-4 py-2 rounded-xl font-semibold text-sm self-end">
              Enviar
            </button>
          </div>
          <p class="text-xs text-slate-400 mt-1">Enter para enviar · Shift+Enter para nueva línea</p>
        </div>
      </div>
    </div>
  `
}

function _iaMsgsHTML() {
  return _iaChatHistory.map(m => {
    const isUser = m.role === "user"
    return `<div class="flex ${isUser ? "justify-end" : "justify-start"}">
      <div class="max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed
        ${isUser
          ? "bg-indigo-700 text-white rounded-br-sm"
          : "bg-white border border-slate-200 text-slate-800 rounded-bl-sm shadow-sm"}">
        ${isUser ? _escapeHTML(m.text) : _markdownSimple(m.text)}
      </div>
    </div>`
  }).join("") + (_iaEnviando ? `
    <div class="flex justify-start">
      <div class="bg-white border border-slate-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
        <span class="ia-typing-dots">
          <span></span><span></span><span></span>
        </span>
      </div>
    </div>` : "")
}

function _escapeHTML(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
}

function _markdownSimple(text) {
  // Soporte básico: **bold**, *italic*, listas con guión, saltos de línea
  return _escapeHTML(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^- (.+)$/gm, "• $1")
    .replace(/\n/g, "<br/>")
}

async function _iaEnviar() {
  if (_iaEnviando) return
  const input = $("ia-input")
  const pregunta = input?.value.trim()
  if (!pregunta) return

  input.value = ""
  _iaChatHistory.push({ role: "user", text: pregunta })
  _iaEnviando = true
  _renderMsgsOnly()

  try {
    const res = await apiPost("/api/ia/consulta", {
      paciente_id: _iaPacId,
      pregunta,
      historial: _iaChatHistory.slice(0, -1),  // historial sin la pregunta actual
    })
    _iaChatHistory.push({ role: "assistant", text: res.respuesta })
  } catch (e) {
    _iaChatHistory.push({ role: "assistant", text: `⚠️ Error: ${e.message}` })
  } finally {
    _iaEnviando = false
    _renderMsgsOnly()
    // Auto-scroll al final
    const msgs = $("ia-msgs")
    if (msgs) msgs.scrollTop = msgs.scrollHeight
  }
}

function _renderMsgsOnly() {
  const el = $("ia-msgs")
  if (!el) return
  if (_iaChatHistory.length === 0) {
    _renderIAChat()  // volver al estado inicial
    return
  }
  el.innerHTML = _iaMsgsHTML()
  el.scrollTop = el.scrollHeight
  const btn = $("ia-btn-send")
  if (btn) btn.disabled = _iaEnviando
}
