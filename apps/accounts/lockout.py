"""
Bloqueio de login por força bruta (usado pelo LockoutModelBackend).

Contadores ficam no cache padrão (Redis em produção, para que sejam
compartilhados entre os workers do Gunicorn). Duas chaves são usadas:

- usuário + IP: bloqueia tentativas repetidas contra a mesma conta;
- somente IP: bloqueia "password spraying" (muitas contas a partir do mesmo IP).
"""

import hashlib
import logging

from django.conf import settings
from django.core.cache import cache
from rest_framework.settings import api_settings

logger = logging.getLogger("vetmanager.security")

_DEFAULTS = {
    "MAX_ATTEMPTS": 5,
    "IP_MAX_ATTEMPTS": 20,
    "WINDOW_SECONDS": 15 * 60,
    "LOCKOUT_SECONDS": 15 * 60,
}


def _conf(key):
    return getattr(settings, "LOGIN_LOCKOUT", {}).get(key, _DEFAULTS[key])


def get_client_ip(request):
    """IP do cliente respeitando NUM_PROXIES (mesma lógica do throttling do DRF)."""
    if request is None:
        return None
    meta = getattr(request, "META", {})
    remote_addr = meta.get("REMOTE_ADDR")
    xff = meta.get("HTTP_X_FORWARDED_FOR")
    num_proxies = api_settings.NUM_PROXIES

    if num_proxies is not None:
        if num_proxies == 0 or not xff:
            return remote_addr
        addrs = [a.strip() for a in xff.split(",") if a.strip()]
        if not addrs:
            return remote_addr
        return addrs[-min(num_proxies, len(addrs))]
    return remote_addr


def _hash(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _user_key(username, ip):
    return f"lockout:user:{_hash(f'{(username or '').strip().lower()}|{ip}')}"


def _ip_key(ip):
    return f"lockout:ip:{_hash(ip)}"


def _locked_key(key):
    return f"{key}:locked"


def is_locked(username, ip):
    keys = [_user_key(username, ip)]
    if ip:
        keys.append(_ip_key(ip))
    return any(cache.get(_locked_key(k)) for k in keys)


def _incr(key):
    window = _conf("WINDOW_SECONDS")
    # add() só cria se não existir, preservando o início da janela.
    if cache.add(key, 1, timeout=window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # A chave expirou entre o add() e o incr().
        cache.set(key, 1, timeout=window)
        return 1


def register_failure(username, ip):
    lockout_seconds = _conf("LOCKOUT_SECONDS")

    user_key = _user_key(username, ip)
    if _incr(user_key) >= _conf("MAX_ATTEMPTS"):
        cache.set(_locked_key(user_key), True, timeout=lockout_seconds)
        cache.delete(user_key)
        logger.warning("Login bloqueado (usuário+IP): user=%r ip=%s", username, ip)

    if ip:
        ip_key = _ip_key(ip)
        if _incr(ip_key) >= _conf("IP_MAX_ATTEMPTS"):
            cache.set(_locked_key(ip_key), True, timeout=lockout_seconds)
            cache.delete(ip_key)
            logger.warning("Login bloqueado (IP): ip=%s", ip)


def reset(username, ip):
    """Zera o contador usuário+IP após login bem-sucedido."""
    cache.delete(_user_key(username, ip))
