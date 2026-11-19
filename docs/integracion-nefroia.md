# Integración Hoja Diaria Renal ↔ NefroIA (R9)

El apartado **«IA»** de Hoja Diaria Renal muestra **NefroIA** (asistente de IA para enfermería renal) dentro de la propia app, con **inicio de sesión único (SSO)**. Sustituye al antiguo módulo «IA Clínica», que enviaba el nombre y el historial del paciente a un modelo de lenguaje: ese módulo se eliminó por completo.

> Este documento es idéntico en los dos repositorios (`hoja-diaria-renal` y `nefroia`).

## 1. Qué datos viajan

| Dato | ¿Sale de Hoja Diaria? |
| --- | --- |
| Nombre, cédula, historial, laboratorios o cualquier dato de pacientes | **No, nunca.** Hoja Diaria no llama a NefroIA ni a ningún modelo. |
| Identidad del usuario (usuario, rol, nombre visible) | Sí, dentro de un token firmado que el **navegador** entrega a NefroIA. |

Lo que la enfermera escriba dentro de NefroIA pasa por sus guardarraíles (redacción de datos personales antes de guardar o enviar al modelo). La interfaz recuerda no escribir datos que identifiquen a pacientes.

## 2. Arquitectura

```mermaid
sequenceDiagram
  participant N as Navegador (enfermera)
  participant H as Hoja Diaria (FastAPI)
  participant I as NefroIA (Next.js)
  N->>H: Abre «IA» (cookie de sesión de Hoja Diaria)
  H-->>N: GET /api/nefroia/sso → URL con token HS256 (≤ 2 min, jti único)
  N->>I: iframe: GET /sso?token=…&embed=1&lang=es
  I->>I: Verifica firma, exp, iss/aud, claims; consume jti (un solo uso)
  I->>I: Crea o vincula el usuario "hdr:<sub>" e inicia sesión (Auth.js, JWT)
  I-->>N: 303 /sso/check (Set-Cookie SameSite=None; Secure)
  N->>I: /sso/check → ¿llegó la cookie? sí: chat · no: aviso «abre en pestaña nueva»
```

- **Iframe** (`embed=1`): diseño compacto (barra lateral plegada, sin logotipo duplicado); el aviso de apoyo a la decisión se mantiene.
- **«Abrir en pestaña nueva»**: `GET /api/nefroia/abrir` en Hoja Diaria genera un token nuevo y redirige (303) a `NEFROIA_URL/sso?token=…&embed=0`. Es el mismo flujo pero de primer nivel, para navegadores (sobre todo móviles) que bloquean cookies de terceros dentro del iframe.
- Cada vez que se abre el apartado se pide un token nuevo; los tokens no se guardan.

## 3. El token

JWT compacto **HS256** firmado con el secreto compartido `NEFROIA_SSO_SECRET`.

```json
{ "alg": "HS256", "typ": "JWT" }
{
  "iss": "hoja-diaria-renal",
  "aud": "nefroia",
  "sub": "admin",              // usuario de Hoja Diaria; demo: "demo-<12 hex>" por sesión
  "role": "admin",             // "admin" | "demo"
  "name": "admin",
  "iat": 1795000000,
  "exp": 1795000060,           // NEFROIA_TOKEN_TTL (60 s por defecto, máx. 120)
  "jti": "…"                   // aleatorio, 24 caracteres base64url
}
```

Validación en NefroIA (`lib/sso/token.ts`, sin dependencias):

1. Secreto configurado y de **≥ 32 caracteres**; si no, **se rechaza todo** (`/sso` responde 404).
2. Cabecera `alg` exactamente `HS256` (se rechazan `none`, `HS512`, etc.) y sin `crit`.
3. Firma HMAC-SHA256 comparada en **tiempo constante** antes de leer ningún claim.
4. `iss = hoja-diaria-renal`, `aud = nefroia`.
5. `exp` vigente (5 s de tolerancia de reloj), `iat`/`nbf` no futuros, y `exp − iat ≤ 120 s`.
6. `sub` con formato acotado (`[A-Za-z0-9._@-]`, ≤ 60), `role ∈ {admin, demo}`, `jti` de 16–128 caracteres.
7. **Un solo uso**: el `jti` se consume en Redis (`SET NX PX`) si `REDIS_URL` está disponible; si no, en la tabla `sso_token_use` (PostgreSQL, `INSERT … ON CONFLICT DO NOTHING`, filas purgadas al caducar); como último respaldo, en memoria del proceso.

## 4. Usuarios y permisos en NefroIA

| Rol en Hoja Diaria | Usuario NefroIA | Tipo de sesión | Límites |
| --- | --- | --- | --- |
| `admin` | `hdr:<usuario>` | `hdr` | Como un usuario registrado (`RATE_LIMIT_USER_MESSAGES_PER_HOUR`, 60/h). |
| `demo` | `hdr:demo-<id>` (uno por visitante, no comparten chats) | `hdr-demo` | `RATE_LIMIT_SSO_DEMO_MESSAGES_PER_HOUR` (5/h), **sin subir ni borrar protocolos** y **sin adjuntar archivos** (403 en la API, controles ocultos en la interfaz). |

- Las cuentas `hdr:` tienen una contraseña aleatoria nunca revelada y el inicio de sesión con correo/contraseña las rechaza explícitamente; tampoco se pueden registrar (no son correos válidos).
- La sesión de NefroIA iniciada por SSO dura **8 h** (igual que la de Hoja Diaria); después vuelve a entrar desde Hoja Diaria.
- Si Hoja Diaria tiene el login desactivado (sin `APP_USER`/`APP_PASSWORD`, solo desarrollo) **no emite tokens** (403): todo el mundo sería «admin».

## 5. Propiedades de seguridad

- **Clickjacking**: NefroIA envía en todas las respuestas `Content-Security-Policy: frame-ancestors <HOJA_DIARIA_ORIGIN>`; sin configuración, `frame-ancestors 'none'`. No se usa `X-Frame-Options`. `HOJA_DIARIA_ORIGIN` se valida (solo `http(s)://host[:puerto]`, sin comodines, rutas ni caracteres que permitan inyectar directivas).
- **Cookies en el iframe**: con el modo integrado activo (secreto + origen), las cookies de Auth.js, de idioma y de modo integrado son `SameSite=None; Secure` (requiere HTTPS; `localhost` se acepta en desarrollo). Sin modo integrado siguen siendo `Lax`.
- **CSRF**: como `SameSite=None` deja pasar cookies en peticiones de otros sitios, el `proxy.ts` de NefroIA rechaza (403) toda petición `POST/PUT/PATCH/DELETE` cuyo `Origin` no sea el propio.
- **Fuga del token**: el token va en la URL solo un instante; `/sso` responde `Cache-Control: no-store` y `Referrer-Policy: no-referrer` y redirige a `/sso/check` (sin token). El iframe usa `referrerpolicy="no-referrer"` y `sandbox` sin `allow-top-navigation`. Aunque se filtrara, caduca en ≤ 2 min y ya está consumido.
- **Login CSRF / inicio forzado**: `/api/nefroia/abrir` solo acepta navegaciones `Sec-Fetch-Site: same-origin|none`.
- **Sin datos de pacientes**: el token solo contiene la identidad del usuario (probado en `tests/test_r9_nefroia.py`).
- **Interruptor**: sin `NEFROIA_URL` o sin `NEFROIA_SSO_SECRET` (≥ 32) Hoja Diaria muestra «NefroIA no está configurado todavía», `/api/nefroia/sso` y `/abrir` responden 404 y no se emite ningún token.

## 6. Variables de entorno

### Hoja Diaria Renal (Render, servicio `hoja-diaria-renal`)

| Variable | Valor |
| --- | --- |
| `NEFROIA_URL` | URL pública de NefroIA, sin barra final (p. ej. `https://nefroia.onrender.com`). `sync: false`. |
| `NEFROIA_SSO_SECRET` | Secreto compartido (≥ 32 caracteres): `python -c "import secrets; print(secrets.token_urlsafe(48))"`. `sync: false`. |
| `NEFROIA_TOKEN_TTL` | Opcional, segundos de vida del token (60 por defecto, máx. 120). |

### NefroIA

| Variable | Valor |
| --- | --- |
| `NEFROIA_SSO_SECRET` | **El mismo valor** que en Hoja Diaria. |
| `HOJA_DIARIA_ORIGIN` | Origen exacto de Hoja Diaria (p. ej. `https://hoja-diaria-renal.onrender.com`). |
| `RATE_LIMIT_SSO_DEMO_MESSAGES_PER_HOUR` | Opcional (5 por defecto). |
| `AUTH_URL`, `NEXT_PUBLIC_APP_URL` | URL pública de NefroIA (HTTPS). |

Rotación del secreto: cambia el valor en los dos servicios a la vez; los tokens en vuelo (≤ 2 min) dejarán de valer.

## 7. Archivos

**Hoja Diaria Renal**: `config.py` (variables e interruptor), `services/nefroia_sso.py` (firma del token), `routers/nefroia.py` (`/api/nefroia/estado`, `/sso`, `/abrir`), `static/js/nefroia.js` y `static/css/nefroia.css` (apartado «IA»), `MENU_INICIO` en `static/js/app.js` (IA tras EPO/Fe, antes de «Pedido de insumos»; «Próximamente» sigue al final), `tests/test_r9_nefroia.py`. Eliminados: `routers/ia.py`, `static/js/ia.js`, el botón «IA» por paciente y la dependencia `anthropic`.

**NefroIA**: `lib/sso/config.ts`, `lib/sso/token.ts`, `lib/sso/replay.ts`, `lib/sso/server.ts`, `lib/sso/pages.ts`, `lib/sso/embed.ts`, `app/(auth)/sso/route.ts`, `app/(auth)/sso/check/route.ts`, proveedor `hoja-diaria` en `app/(auth)/auth.ts`, `proxy.ts` (CSP y Origin), `lib/ai/entitlements.ts`, migración `0005_sso_hoja_diaria.sql` (tabla `sso_token_use`), `tests/unit/sso.test.ts`, `tests/e2e/sso-embed.test.ts`.

## 8. Pruebas

- Hoja Diaria: `python -m pytest` (`tests/test_r9_nefroia.py`: claims, firma, caducidad, rol demo, interruptor apagado, sin datos de pacientes, endpoints antiguos eliminados, orden del menú).
- NefroIA: `pnpm test:unit` (`tests/unit/sso.test.ts`: firma incorrecta, `alg` no permitido, vencido, `iss`/`aud` erróneos, vida > 2 min, claims mal formados, reutilización, CSP y cookies) y `pnpm test:e2e` (`tests/e2e/sso-embed.test.ts`: una página local en `127.0.0.1:3901` hace de Hoja Diaria y enmarca NefroIA con un token válido; el chat responde dentro del iframe; un origen no autorizado queda bloqueado por `frame-ancestors`; tokens reutilizados, vencidos o falsificados se rechazan; el rol demo no puede subir protocolos).

## 9. Despliegue pendiente

1. Crear el servicio web de NefroIA en Render (imagen Docker del repositorio, healthcheck `/ping`) con PostgreSQL gestionado (Neon, con la extensión `pgvector` para HNSW; sin ella funciona con ranking exacto) y aplicar migraciones (`pnpm db:migrate` o el target `migrate`).
2. Definir en NefroIA `AUTH_SECRET`, `POSTGRES_URL`, `ANTHROPIC_API_KEY` (u otro proveedor), `AUTH_URL`/`NEXT_PUBLIC_APP_URL`, `NEFROIA_SSO_SECRET` y `HOJA_DIARIA_ORIGIN`; opcionalmente `REDIS_URL` y S3.
3. Definir en Hoja Diaria `NEFROIA_URL` y el mismo `NEFROIA_SSO_SECRET`, y redesplegar.
4. Comprobar: abrir «IA» en Hoja Diaria (escritorio y móvil) y «Abrir en pestaña nueva».
