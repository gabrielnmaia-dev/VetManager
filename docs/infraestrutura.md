# Infraestrutura operacional (Prompt 22)

Documenta logs estruturados, healthchecks, monitoramento, backup/restauração e
revisão de segurança do VetManager.

## 1. Logs estruturados

Cada evento de log é emitido como uma única linha JSON com os campos:

| Campo | Descrição |
|-------|-----------|
| `timestamp` | Data/hora UTC (ISO 8601) |
| `nivel` | Nível do log (`INFO`, `WARNING`, `ERROR`, ...) |
| `servico` | Nome do serviço (`vetmanager-api`) |
| `logger` | Nome do logger Django |
| `mensagem` | Texto da mensagem (sem segredos) |
| `request_id` | Identificador da requisição (quando aplicável) |
| `usuario_id` | ID do usuário autenticado (quando aplicável) |
| `operacao` / `rota` / `metodo` / `status_code` / `duracao_ms` | Contexto da requisição HTTP |
| `erro` | Tipo e mensagem da exceção (quando houver) |

### Regras de segurança (sem dados sensíveis)

* Nunca registra-se `request.body`, `request.headers` inteiros, senhas, tokens
  (JWT, refresh, portal_access, portal_refresh) ou strings de conexão.
* Padrões de segredo que apareçam em mensagens de terceiros são redigidos
  automaticamente (`[REDACTED]`).
* O campo `extra` aceita apenas uma lista fechada de chaves (`operacao`,
  `metodo`, `rota`, `status_code`, `duracao_ms`, `lentidao`, `erro_tipo`,
  `erro_mensagem`, `servico_externo`, `tarefa`, `resultado`, `tentativa`),
  evitando vazamento acidental de dados clínicos.

### Formato e nível

* `LOG_FORMAT=json` (padrão) ou `texto` (desenvolvimento local).
* `LOG_LEVEL=INFO` (padrão).
* `LOG_INCLUDE_TRACEBACK=1` inclui o stack trace no JSON (somente depuração).

Os middlewares envolvem toda a pilha de requisição para capturar o request id e
a duração total (`core.middleware.RequestContextMiddleware`,
`core.middleware.AccessLogMiddleware`). `ApiNoStoreMiddleware` impede cache de
respostas da API.

## 2. Healthchecks

Endpoints Django (sem autenticação/throttling), funcionam mesmo com a API
degradada:

| Endpoint | O que verifica | Código |
|----------|----------------|--------|
| `/health/` | Liveness: o processo Django responde | 200 |
| `/health/ready/` | Readiness: banco, cache/Redis, worker, armazenamento | 200 / 503 |
| `/health/metrics/` | Contadores operacionais (falhas, 500s, lentidão) | 200 |

Verificações de readiness:

* `backend` — processo responde (sempre `ok`).
* `database` — `SELECT 1` no PostgreSQL.
* `cache` — `set`/`get` no Redis quando configurado; `nao_configurado` com
  LocMem.
* `worker` — `nao_configurado` enquanto não houver Celery/RQ (não finge um
  worker saudável).
* `storage` — `MEDIA_ROOT` aceita escrita/leitura e tem espaço livre mínimo
  (`HEALTH_MIN_FREE_BYTES`, padrão 100 MB).

Uma instância só recebe tráfego quando nenhuma verificação está em `erro`.

## 3. Monitoramento

O `AccessLogMiddleware` identifica, por requisição:

* **Falhas** — exceções não tratadas (log `ERROR`, contador `total_failures`).
* **Erros 500** — respostas com status >= 500 (contador `erros_500`).
* **Lentidão** — requisições acima de `ACCESS_LOG_SLOW_MS` (padrão 1000 ms;
  contador `lentidao`).
* **Falhas de comunicação externa** — `incrementar_falha_externa(servico)`
  (contador `falhas_externas`, por serviço: `softcom`, `email`, `sms`).

Os contadores ficam no cache padrão (LocMem dev/test, Redis produção) e são
expostos por `/health/metrics/` em JSON:

```json
{
  "total_failures": 0,
  "erros_500": 0,
  "lentidao": 0,
  "falhas_externas": { "total": 0, "por_servico": {} },
  "janela_segundos": 300,
  "timestamp": 1731234567
}
```

Para alertas em produção, colete `/health/metrics/` periodicamente e dispare
quando `erros_500` ou `total_failures` crescerem no período, ou quando
qualquer verificação de `/health/ready/` retornar `erro` (HTTP 503).

## 4. Backup

Scripts em `deploy/`:

* `backup_db.sh` — dump comprimido do PostgreSQL (`pg_dump`) + arquivo dos
  documentos clínicos (`media/`). Retenção de 30 dias para dumps diários e 10
  para pré-migration. Serializa execuções concorrentes com `flock`.
* `restore_db.sh` — sobrescreve o banco de produção após confirmação
  explícita (`CONFIRMAR`) e gera um dump de segurança do estado atual antes
  de restaurar.

### Entrypoint de produção

Antes de aplicar migrations pendentes, `deploy/entrypoint.sh` gera um dump
pré-migration e aborta o start se o backup falhar.

### Estratégia

* Banco: dump SQL comprimido (`--clean --if-exists --no-owner --no-privileges`).
* Arquivos clínicos: `tar.gz` de `media/`.
* Retenção: 30 dias (diários), 10 (pré-migration).
* Nunca exponha `MEDIA_ROOT` diretamente na web; os arquivos são servidos
  apenas via endpoint autenticado.

## 5. Restauração

Procedimento seguro (produção):

```bash
# 1. Confirme que tem o arquivo de dump válido
gzip -t backups/vetmanager_YYYYMMDD_HHMMSS.sql.gz

# 2. Restaure (gera backup de segurança do estado atual automaticamente)
./deploy/restore_db.sh backups/vetmanager_YYYYMMDD_HHMMSS.sql.gz
```

O `restore_db.sh`:

1. Pede confirmação explícita (`CONFIRMAR`).
2. Gera um dump de segurança do estado atual (`pre_migration_*.sql.gz`).
3. Para o container web (evita conexões durante o restore).
4. Aplica o dump com `psql -v ON_ERROR_STOP=1`.
5. Sobe o container web.

> **Não considere backup válido sem testar sua restauração.** Valide o dump
> em ambiente de homologação antes de confiar nele para produção.

## 6. Revisão de segurança

| Item | Configuração |
|------|--------------|
| Nginx | Termina TLS; `X-Forwarded-Proto` confiável; `client_max_body_size 20M`; `/media/` não exposto diretamente |
| TLS | Habilitado no domínio/Tailscale; `USE_HTTPS=true` ativa HSTS (produção) |
| Cookies | `HttpOnly`, `SameSite=Lax`; `Secure` quando HTTPS; nomes separados: `access`/`refresh` (interno) e `portal_access`/`portal_refresh` (portal) |
| CORS | `CORS_ALLOW_ALL_ORIGINS = False`; origens explícitas; regex Netlify apenas em staging |
| ALLOWED_HOSTS | Lista explícita de hosts; `localhost`/`127.0.0.1` incluídos |
| Arquivos privados | `MEDIA_ROOT` servido apenas via endpoint autenticado; nunca exposto diretamente |
| Segredos | `SECRET_KEY` obrigatória e forte (>= 32 chars); nunca commitar `.env*` (exceto `*.example`) |
| Limites de upload | `DATA_UPLOAD_MAX_MEMORY_SIZE` (padrão 5 MB); `client_max_body_size 20M` no Nginx |

## 7. Testes

Valide healthchecks, backup e restauração em ambiente seguro (homologação),
nunca diretamente na produção sem planejamento.

Suíte de backend (SQLite): `DJANGO_SETTINGS_MODULE=core.settings.test python manage.py test`.
Suíte de frontend: `npm test` (Vitest + Testing Library).
CI: `.github/workflows/ci.yml` em cada repositório (checks, migrations, testes,
lint, build).
