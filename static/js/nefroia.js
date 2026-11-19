/* ============================================================
   nefroia.js — R9: apartado «IA» = NefroIA integrado (SSO)
   ------------------------------------------------------------
   Reemplaza el antiguo módulo IA (que enviaba el nombre del paciente a un
   modelo). Hoja Diaria NO envía datos de pacientes: solo pide al servidor
   una URL de acceso de un solo uso (token firmado con la identidad del
   usuario, vida ≤ 2 min) y la carga en un iframe. Si NefroIA no está
   configurado, se muestra una tarjeta informativa y no se hace ninguna
   llamada saliente.
   ============================================================ */

function _nefroiaCabecera(conBoton) {
  return `
    <div class="nefroia-cabecera">
      <div>
        <h2 class="text-lg font-bold text-indigo-900"><span aria-hidden="true">🤖</span> IA · NefroIA</h2>
        <p class="text-xs text-slate-500">Asistente de apoyo a la decisión para enfermería renal. No diagnostica ni prescribe.
          No escribas nombres, cédulas ni otros datos que identifiquen a pacientes.</p>
      </div>
      ${conBoton ? `<button type="button" class="nefroia-btn" onclick="abrirNefroIAPestana()"
          title="Útil si tu navegador bloquea cookies de terceros (algunos móviles)">↗ Abrir en pestaña nueva</button>` : ""}
    </div>`
}

function _nefroiaTarjeta(titulo, texto, extra = "", estado = "error") {
  return `
    <div class="max-w-2xl mx-auto mt-6">
      <div class="bg-white rounded-2xl shadow-xl p-6" role="status" data-nefroia-estado="${estado}">
        ${_nefroiaCabecera(false)}
        <div class="nefroia-aviso mt-4">
          <p class="font-semibold text-slate-700">${escHtml(titulo)}</p>
          <p class="text-sm text-slate-500 mt-1">${texto}</p>
          ${extra}
        </div>
      </div>
    </div>`
}

async function renderIA() {
  G.vista = "ia"
  updateHeader()

  if (!G.me.nefroia_configurado) {
    app().innerHTML = _nefroiaTarjeta(
      "NefroIA no está configurado todavía",
      "El administrador debe definir <code>NEFROIA_URL</code> y <code>NEFROIA_SSO_SECRET</code> en el servidor " +
      "(ver <code>docs/integracion-nefroia.md</code>). Mientras tanto, este apartado no se conecta a ningún servicio externo.",
      "", "no-configurado")
    return
  }

  app().innerHTML = `
    <section class="nefroia-panel" aria-label="NefroIA">
      ${_nefroiaCabecera(true)}
      <div class="nefroia-marco-wrap">
        <p id="nefroia-cargando" class="nefroia-cargando">Conectando con NefroIA…</p>
        <iframe id="nefroia-frame" class="nefroia-marco" title="NefroIA — asistente de IA"
          referrerpolicy="no-referrer" allow="clipboard-write"
          sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"></iframe>
      </div>
      <p class="text-xs text-slate-400 mt-2">¿No carga o pide iniciar sesión? Algunos navegadores (sobre todo en el celular)
        bloquean las cookies dentro de otra página: usa «Abrir en pestaña nueva».</p>
    </section>`

  try {
    const { url } = await apiGet("/api/nefroia/sso")
    const frame = $("nefroia-frame")
    if (!frame) return                       // el usuario ya salió del apartado
    frame.addEventListener("load", () => $("nefroia-cargando")?.remove(), { once: true })
    frame.src = url                          // un solo uso: se pide uno nuevo cada vez
  } catch (e) {
    app().innerHTML = _nefroiaTarjeta("No se pudo abrir NefroIA", escHtml(e.message || "Error desconocido"),
      `<button type="button" class="nefroia-btn mt-3" onclick="renderIA()">Reintentar</button>`)
  }
}

/** Mismo SSO pero en una pestaña de primer nivel (sin cookies de terceros). */
function abrirNefroIAPestana() {
  window.open("/api/nefroia/abrir", "_blank", "noopener")
}
