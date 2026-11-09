from .base import *
import os
# pyrefly: ignore [missing-import]
import dj_database_url
from django.core.exceptions import ImproperlyConfigured

DEBUG = False

# Ambiente lógico: "production" (default) ou "staging".
# Em staging os defaults de domínio mudam e o HSTS fica desligado.
ENVIRONMENT = os.environ.get("ENVIRONMENT", "production").strip().lower()
IS_STAGING = ENVIRONMENT == "staging"

# --- Segredos obrigatórios --------------------------------------------
if not SECRET_KEY or SECRET_KEY.startswith("troque-") or len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "SECRET_KEY ausente ou fraca. Defina uma chave forte (>= 32 caracteres) no .env.prod."
    )

if not os.environ.get("DATABASE_URL"):
    raise ImproperlyConfigured("DATABASE_URL não definida no ambiente de produção.")

# --- Hosts / domínios -------------------------------------------------
# Domínio público da API (produção: Funnel; staging: subdomínio próprio).
_DEFAULT_FUNNEL_HOST = (
    "api-staging.seudominio.com" if IS_STAGING else "serverubunto.tail459c47.ts.net"
)
_DEFAULT_NETLIFY_ORIGIN = (
    "https://staging--vetmanager-letvet.netlify.app"
    if IS_STAGING
    else "https://vetmanager-letvet.netlify.app"
)
FUNNEL_HOST = os.environ.get("FUNNEL_HOST", _DEFAULT_FUNNEL_HOST)
# Origem do front no Netlify (usada no CSRF e liberada no CORS mais abaixo).
NETLIFY_ORIGIN = os.environ.get("NETLIFY_ORIGIN", _DEFAULT_NETLIFY_ORIGIN)

# ALLOWED_HOSTS = lista separada por vírgula (ex.: "1.2.3.4,meuapp.com").
# Mantém compatibilidade com RENDER_EXTERNAL_HOSTNAME caso volte ao Render.
# Os defaults abaixo garantem que o Funnel continue funcionando mesmo que a
# variável no .env.prod esteja incompleta. O host do Netlify entra também
# porque alguns proxies preservam o Host original em vez do host de destino.
_hosts = os.environ.get("ALLOWED_HOSTS") or os.environ.get(
    "RENDER_EXTERNAL_HOSTNAME", ""
)
_netlify_host = NETLIFY_ORIGIN.split("://", 1)[-1].split("/", 1)[0]
ALLOWED_HOSTS = sorted(
    {h.strip() for h in _hosts.split(",") if h.strip()}
    | {"localhost", "127.0.0.1", FUNNEL_HOST, _netlify_host}
)

# Permite publicar a API sob um prefixo (ex.: /staging-api) quando o proxy
# público monta o serviço em um subpath. Vazio/ausente = raiz.
FORCE_SCRIPT_NAME = os.environ.get("FORCE_SCRIPT_NAME") or None

# Necessário para login no /admin via HTTPS atrás de proxy (Nginx/Tailscale)
# e para o front no Netlify. Com o proxy /api do Netlify o navegador enxerga
# tudo como mesma origem, mas manter ambas as origens não atrapalha.
CSRF_TRUSTED_ORIGINS = sorted(
    set(env_list("CSRF_TRUSTED_ORIGINS"))
    | {NETLIFY_ORIGIN, f"https://{FUNNEL_HOST}"}
)

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
# Em produção o proxy /api do Netlify mantém tudo same-origin; ainda assim a
# origem exata fica liberada para clientes que chamem a API diretamente.
# Em staging o front pode chamar a API por URL absoluta (cross-origin), então
# liberamos também os deploys/previews do Netlify via regex.
_default_frontend = NETLIFY_ORIGIN
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = sorted(
    {
        o.strip()
        for o in os.environ.get(
            "CORS_ALLOWED_ORIGINS",
            os.environ.get("FRONTEND_URL", _default_frontend),
        ).split(",")
        if o.strip()
    }
    | {NETLIFY_ORIGIN}
)

# Aceita qualquer subdomínio de deploy do Netlify quando habilitado.
# O default é True apenas em staging; em produção continue exigindo a origem
# exata em CORS_ALLOWED_ORIGINS, a menos que CORS_ALLOW_NETLIFY_APP=True.
CORS_ALLOWED_ORIGIN_REGEXES = sorted(
    set(env_list("CORS_ALLOWED_ORIGIN_REGEXES"))
    | (
        {r"^https://[a-z0-9-]+\.netlify\.app$"}
        if env_bool("CORS_ALLOW_NETLIFY_APP", IS_STAGING)
        else set()
    )
)

# --- Segurança --------------------------------------------------------
# Headers aplicados sempre (não dependem de TLS).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
# Em staging cross-site (front Netlify -> API em outro domínio) use "None"
# junto com HTTPS/Secure. O default de produção continua "Lax".
SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
CSRF_COOKIE_SAMESITE = os.environ.get("CSRF_COOKIE_SAMESITE", "Lax")
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
    # HSTS longo é adequado à produção; em staging o default é 0 para não
    # "grudar" HSTS no subdomínio de testes. Pode ser sobrescrito por env.
    SECURE_HSTS_SECONDS = env_int(
        "SECURE_HSTS_SECONDS", 0 if IS_STAGING else 31536000
    )
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool(
        "SECURE_HSTS_INCLUDE_SUBDOMAINS", not IS_STAGING
    )
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", not IS_STAGING)

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
    # Dados operacionais da API nunca devem ser cacheados por navegador,
    # por proxy ou pelo service worker do PWA.
    "core.middleware.ApiNoStoreMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
