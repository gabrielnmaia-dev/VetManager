from .base import *
import os
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

# --- Segredos obrigatórios --------------------------------------------
if not SECRET_KEY or SECRET_KEY.startswith("troque-") or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "SECRET_KEY ausente ou fraca. Defina uma chave forte (>= 32 caracteres) no .env.prod."
    )

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL não definida no ambiente de produção.")

# --- Hosts / domínios -------------------------------------------------
# ALLOWED_HOSTS = lista separada por vírgula (ex.: "1.2.3.4,meuapp.com").
# Mantém compatibilidade com RENDER_EXTERNAL_HOSTNAME caso volte ao Render.
_hosts = os.environ.get("ALLOWED_HOSTS") or os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME", ""
)
ALLOWED_HOSTS = [h.strip() for h in _hosts.split(",") if h.strip()]

# Necessário para login no /admin via HTTPS atrás de proxy (Nginx/Tailscale).
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# --- Arquivos estáticos ----------------------------------------------
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATIC_URL = "/static/"

# --- Arquivos de mídia (uploads) -------------------------------------
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# --- Banco de dados ---------------------------------------------------
DATABASES = {
    "default": dj_database_url.parse(
        os.environ["DATABASE_URL"],
        conn_max_age=env_int("DB_CONN_MAX_AGE", 60),
        conn_health_checks=True,
    )
}
# Evita queries "penduradas" consumindo conexões (mitigação de DoS).
if DATABASES["default"].get("ENGINE", "").endswith("postgresql"):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"].setdefault(
        "options", f"-c statement_timeout={env_int('DB_STATEMENT_TIMEOUT_MS', 15000)}"
    )

# --- Cache ------------------------------------------------------------
# Definido em base.py a partir de REDIS_URL. Em produção o Redis é
# fortemente recomendado para que throttling e bloqueio de login sejam
# compartilhados entre os workers do Gunicorn.
if not os.environ.get("REDIS_URL"):
    import warnings

    warnings.warn(
        "REDIS_URL não definida: throttling/bloqueio de login usarão cache local "
        "por processo (menos eficaz com vários workers).",
        RuntimeWarning,
    )

# --- CORS (frontend no Netlify) ---------------------------------------
_default_frontend = "https://vetmanager-letvet.netlify.app"
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        os.environ.get("FRONTEND_URL", _default_frontend),
    ).split(",")
    if o.strip()
]

# --- Segurança --------------------------------------------------------
# Headers aplicados sempre (não dependem de TLS).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True

# O TLS será terminado pelo Tailscale (serve). Confiamos no header
# X-Forwarded-Proto (definido pelo Tailscale/nginx) para o Django reconhecer
# que a requisição original chegou por HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Defina USE_HTTPS=True quando o acesso HTTPS for de ponta a ponta (domínio/Tailscale).
if env_bool("USE_HTTPS"):
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# --- DRF ---------------------------------------------------------------
# Throttling, JWT e RBAC são configurados em base.py.
# Atrás do Nginx existe 1 proxy confiável. Se houver outro na frente
# (ex.: Tailscale serve repassando X-Forwarded-For), use NUM_PROXIES=2.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "NUM_PROXIES": env_int("NUM_PROXIES", 1),
    # Em produção a API só responde JSON (sem a Browsable API).
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

# Documentação (Swagger/ReDoc): por padrão só para staff logado no /admin.
if not env_bool("API_DOCS_PUBLIC"):
    SPECTACULAR_SETTINGS = {
        **SPECTACULAR_SETTINGS,
        "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAdminUser"],
        "SERVE_AUTHENTICATION": [
            "rest_framework.authentication.SessionAuthentication",
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        ],
    }

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
