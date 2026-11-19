"""
R9 — Token de inicio de sesión único (SSO) hacia NefroIA.

JWT compacto HS256 firmado con NEFROIA_SSO_SECRET (secreto compartido con
NefroIA), de vida corta (≤ 2 min) y de un solo uso (jti). Solo lleva la
identidad del usuario de Hoja Diaria y su rol: NUNCA datos de pacientes.

Claims: iss="hoja-diaria-renal", aud="nefroia", sub, role (admin|demo), name,
iat, exp, jti. Ver docs/integracion-nefroia.md.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import config

ISSUER = "hoja-diaria-renal"
AUDIENCE = "nefroia"
ROLES = ("admin", "demo")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def firmar(claims: dict, secreto: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64url(json.dumps(claims, separators=(",", ":"), ensure_ascii=False).encode())
    firma = hmac.new(secreto.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(firma)}"


def emitir_token(sub: str, rol: str, nombre: str, *, ahora: float | None = None) -> str:
    """Token firmado para `sub`. Falla si la integración no está configurada."""
    if not config.NEFROIA_ENABLED:
        raise RuntimeError("NefroIA no está configurado")
    if rol not in ROLES:
        raise ValueError(f"rol no válido: {rol}")
    iat = int(ahora if ahora is not None else time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": sub,
        "role": rol,
        "name": nombre[:100],
        "iat": iat,
        "exp": iat + config.NEFROIA_TOKEN_TTL,
        "jti": secrets.token_urlsafe(18),
    }
    return firmar(claims, config.NEFROIA_SSO_SECRET)


def url_sso(token: str, *, embed: bool) -> str:
    """URL de entrada de NefroIA: /sso?token=…&embed=1&lang=es."""
    query = urlencode({"token": token, "embed": "1" if embed else "0", "lang": "es"})
    return f"{config.NEFROIA_URL}/sso?{query}"


def origen_nefroia() -> str:
    """Esquema + host (+ puerto) de NEFROIA_URL, para CSP frame-src."""
    partes = config.NEFROIA_URL.split("/")
    return "/".join(partes[:3]) if len(partes) >= 3 else ""
