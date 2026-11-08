<div align="center">

# 🐾 VetManager

**API REST para gerenciamento de clínicas veterinárias**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5%2B-092E20?style=flat&logo=django&logoColor=white)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/Django_REST_Framework-3.x-A30000?style=flat)](https://www.django-rest-framework.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat&logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat&logo=docker&logoColor=white)](https://docker.com)

Backend para gestão de tutores, pets, profissionais, agenda, prontuários e vacinas,
com autenticação JWT em cookies `httpOnly`, controle de acesso por grupos e uma
camada de proteção contra abuso (rate limiting e bloqueio de login).

[Funcionalidades](#-funcionalidades) · [Tecnologias](#-tecnologias) · [Como rodar](#-como-rodar) · [Autenticação](#-autenticação-e-segurança) · [Endpoints](#-endpoints-da-api) · [Deploy](#-deploy)

</div>

---

## 📋 Sobre o projeto

O **VetManager** centraliza a rotina de uma clínica veterinária em uma API REST:
cadastro de tutores e pets, profissionais, agendamento de atendimentos com
validação de conflito de horário, prontuário clínico, registro de vacinas e um
dashboard com a visão geral do dia.

O projeto foi pensado para ser consumido por um frontend separado (React/Vite),
mas também pode ser usado diretamente via cURL, Swagger ou qualquer cliente HTTP.

**Principais problemas que resolve:**

- Conflitos de horário na agenda dos profissionais
- Histórico clínico centralizado por pet
- Cadastro rápido de tutor + pet + atendimento em uma única chamada
- Acesso controlado a dados clínicos (prontuários e vacinas)
- Autenticação segura sem expor tokens ao JavaScript do navegador

> **Estado atual:** o núcleo de cadastros, agenda, prontuário, vacinas e dashboard
> está implementado. Módulo financeiro, estoque e integrações externas estão no
> roadmap e **ainda não fazem parte da API**.

---

## ✨ Funcionalidades

### Implementado

- ✅ Autenticação JWT com `access`/`refresh`, rotação e blacklist
- ✅ Tokens entregues em cookies `httpOnly` (e também no corpo da resposta)
- ✅ Login compatível com `Authorization: Bearer` para clientes e Swagger
- ✅ Logout com revogação do refresh token e limpeza dos cookies
- ✅ Perfil do usuário e troca de senha (exige a senha atual)
- ✅ Cadastro de tutores com pets aninhados em cascata
- ✅ Cadastro de pets com vínculo ao tutor e filtro por tutor
- ✅ Cadastro de profissionais (veterinário, tosador, banhista, outro)
- ✅ Dados de veterinário (CRMV e especialidade) vinculados ao profissional
- ✅ Agendamento com **validação de conflito de horário por profissional**
- ✅ Atendimento rápido: tutor, pet e atendimento em uma única transação
- ✅ Prontuário clínico com peso, temperatura, diagnóstico, prescrição e retorno
- ✅ Vacinas por pet, opcionalmente vinculadas a um prontuário
- ✅ Dashboard com atendimentos do dia, pendentes, total de pets e tutores
- ✅ Busca e filtros nos principais recursos
- ✅ Paginação padronizada (20 itens por página)
- ✅ RBAC por grupos do Django (`admin`, `veterinario`, `recepcao`)
- ✅ Rate limiting por IP/usuário e bloqueio temporário após falhas de login
- ✅ Documentação automática com Swagger, ReDoc e schema OpenAPI
- ✅ Ambiente Docker de desenvolvimento isolado da produção
- ✅ Scripts de backup, restauração e backup pré-migration

### Roadmap

- 🔜 Módulo financeiro (pagamentos, faturamento diário/mensal e relatórios)
- 🔜 Controle de estoque de medicamentos
- 🔜 Lembretes automáticos via WhatsApp (Evolution API)
- 🔜 Aplicativo/web para tutores acompanharem agenda e histórico do pet
- 🔜 Integração com gateway de pagamento (Asaas / PagSeguro)
- 🔜 Relatórios clínicos e exportações

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12 |
| Framework | Django 5+ (`django>=5.0`) |
| API | Django REST Framework 3.15+ |
| Autenticação | SimpleJWT (cookies `httpOnly` + Bearer) |
| Documentação | drf-spectacular (Swagger / ReDoc / OpenAPI) |
| Banco de dados | PostgreSQL 16 (SQLite nos testes locais) |
| Cache / throttling | Redis 7 (LocMemCache como fallback) |
| Filtros | django-filter + SearchFilter |
| CORS | django-cors-headers |
| Servidor de produção | Gunicorn |
| Arquivos estáticos | WhiteNoise |
| Containers | Docker + Docker Compose |
| Automação | Makefile |
| Frontend | React/Vite (repositório separado) |

---

## 🧱 Arquitetura e modelo de dados

O backend segue a estrutura padrão do Django, com as configurações separadas por
ambiente e as regras de negócio concentradas em `services.py` quando envolvem
mais de um objeto.

- `core/settings/base.py`: configuração comum, DRF, JWT, RBAC, throttling e cache
- `core/settings/dev.py`: PostgreSQL do Docker, `DEBUG=True`, mídia local
- `core/settings/prod.py`: segurança, `DATABASE_URL`, WhiteNoise, CORS e HSTS
- `core/settings/test.py`: SQLite e cache local para testes fora do Docker
- `api/v1/router.py`: registro central dos `ViewSets`
- `apps/*/services.py`: transações e validações de negócio
- `apps/accounts/*`: autenticação, permissões, throttles, lockout e grupos

### Relacionamentos principais

| Origem | Relação | Destino |
|---|---|---|
| `Tutor` | 1:N | `Pet` |
| `Pet` | 1:N | `Atendimento` |
| `Pet` | 1:N | `Prontuario` |
| `Pet` | 1:N | `Vacina` |
| `Profissional` | 1:N | `Atendimento` |
| `Profissional` | 1:1 | `Veterinario` (CRMV/especialidade) |
| `Atendimento` | 1:1 (opcional) | `Prontuario` |
| `Prontuario` | 1:N | `Vacina` |

Os modelos de domínio que herdam `BaseModel` (tutores, pets, profissionais,
atendimentos e prontuários) usam **UUID** como chave primária. `Vacina` usa o
`id` inteiro padrão do Django. Os relacionamentos de tutores, pets,
profissionais e atendimentos usam `PROTECT`: antes de excluir um registro, é
preciso remover ou realocar os dependentes.

---

## 🚀 Como rodar

### Pré-requisitos

- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/)
- [Make](https://www.gnu.org/software/make/)

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/vetmanager.git
cd vetmanager
```

### 2. Configure as variáveis de ambiente

```bash
cp .env.example .env
```

Edite o `.env` e ajuste pelo menos:

```env
SECRET_KEY=troque-por-uma-secret-key-segura
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,web

POSTGRES_DB=vetmanager
POSTGRES_USER=vetmanager_user
POSTGRES_PASSWORD=troque-esta-senha
DATABASE_URL=postgres://vetmanager_user:troque-esta-senha@db:5432/vetmanager

REDIS_URL=redis://redis:6379/1
```

> No ambiente de desenvolvimento o Django usa `core.settings.dev` e lê
> `POSTGRES_DB`, `POSTGRES_USER` e `POSTGRES_PASSWORD`. A `DATABASE_URL` é
> obrigatória em produção.

### 3. Suba os containers

```bash
make build
make up
```

O compose de desenvolvimento sobe:

- `web`: Django com auto-reload em `http://localhost:8000`
- `db`: PostgreSQL 16
- `redis`: Redis 7

O projeto usa o nome `vetmanager-dev` e um volume próprio, então um
`docker compose down -v` no desenvolvimento **não apaga** o banco de produção.

### 4. Aplique as migrations e crie o superusuário

```bash
make migrate
make createsuperuser
```

Opcionalmente, garanta os grupos padrão e crie os usuários iniciais definidos no
`.env` (`DJANGO_SUPERUSER_*` e `DJANGO_RECEPCAO_*`):

```bash
docker compose exec web python manage.py setup_inicial
```

### 5. Acesse

| Serviço | URL |
|---|---|
| API (raiz do `v1`) | http://localhost:8000/api/v1/ |
| Swagger | http://localhost:8000/api/schema/swagger-ui/ |
| ReDoc | http://localhost:8000/api/schema/redoc/ |
| Schema OpenAPI | http://localhost:8000/api/schema/ |
| Admin Django | http://localhost:8000/admin/ |

---

## ⚙️ Variáveis de ambiente

### Django e banco

| Variável | Padrão / observação |
|---|---|
| `SECRET_KEY` | Obrigatória em produção; use uma chave com 32+ caracteres |
| `DEBUG` | `True` no `.env.example`; em produção o `prod.py` força `False` |
| `ALLOWED_HOSTS` | Lista separada por vírgula |
| `DATABASE_URL` | Obrigatória em produção (`postgres://...`) |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | Usadas pelo compose e pelo ambiente de desenvolvimento |
| `REDIS_URL` | Cache compartilhado para throttling e lockout |
| `DB_CONN_MAX_AGE` | Tempo de reutilização de conexão (padrão `60`) |
| `DB_STATEMENT_TIMEOUT_MS` | Timeout de queries em produção (padrão `15000`) |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` | Limite de payload (padrão `5 MiB`) |

### Segurança e autenticação

| Variável | Padrão / observação |
|---|---|
| `JWT_ACCESS_MINUTES` | `30` minutos |
| `JWT_REFRESH_DAYS` | `1` dia |
| `JWT_COOKIE_SECURE` | `True` por padrão |
| `JWT_COOKIE_SAMESITE` | `Lax` por padrão |
| `JWT_COOKIE_DOMAIN` | Vazio = cookie host-only (recomendado) |
| `LOGIN_MAX_ATTEMPTS` | `5` falhas por usuário + IP |
| `LOGIN_IP_MAX_ATTEMPTS` | `200` falhas por IP |
| `LOGIN_WINDOW_SECONDS` | `900` (15 minutos) |
| `LOGIN_LOCKOUT_SECONDS` | `900` (15 minutos) |
| `NUM_PROXIES` | Nº de proxies confiáveis para ler `X-Forwarded-For` |
| `FRONTEND_URL` | Origem liberada no CORS (padrão `http://localhost:5173`) |
| `CSRF_TRUSTED_ORIGINS` | Origens extras confiáveis em produção |
| `USE_HTTPS` | Ativa redirect SSL, cookies seguros e HSTS |
| `API_DOCS_PUBLIC` | `True` libera Swagger/ReDoc publicamente em produção |

### Throttling

| Variável | Padrão |
|---|---|
| `THROTTLE_ANON` | `30/min` |
| `THROTTLE_USER_BURST` | `120/min` |
| `THROTTLE_USER_SUSTAINED` | `3000/hour` |
| `THROTTLE_LOGIN` | `10/min` |
| `THROTTLE_TOKEN_REFRESH` | `30/min` |
| `THROTTLE_TOKEN_LOGOUT` | `20/min` |
| `THROTTLE_ALTERAR_SENHA` | `5/min` |

### Usuários iniciais

| Variável | Função |
|---|---|
| `DJANGO_SUPERUSER_USERNAME` | Cria o superusuário no `setup_inicial` |
| `DJANGO_SUPERUSER_PASSWORD` | Senha do superusuário |
| `DJANGO_SUPERUSER_EMAIL` | E-mail do superusuário |
| `DJANGO_RECEPCAO_USERNAME` | Cria um usuário no grupo `recepcao` (opcional) |
| `DJANGO_RECEPCAO_PASSWORD` | Senha do usuário de recepção |
| `DJANGO_RECEPCAO_EMAIL` | E-mail do usuário de recepção |

### Deploy

| Variável | Padrão / observação |
|---|---|
| `FUNNEL_HOST` | Host público do Tailscale Funnel |
| `NETLIFY_ORIGIN` | Origem do frontend no Netlify |
| `CORS_ALLOWED_ORIGINS` | Lista de origens permitidas em produção |

---

## 🧰 Comandos Make

### Desenvolvimento

```bash
make build            # Build das imagens
make up               # Sobe os serviços em background
make down             # Para e remove os containers
make restart          # Reinicia todos os serviços
make logs             # Exibe logs em tempo real

make migrate          # Aplica migrations
make migrations       # Gera novas migrations (makemigrations)
make createsuperuser  # Cria superusuário interativo
make shell            # Django shell interativo

make test             # Roda os testes
make lint             # Verifica o código com ruff
make format           # Formata com black + isort

make psql             # Abre o psql no banco de desenvolvimento
make reset-db         # Apaga e recria o banco de DEV (pede confirmação) ⚠️
```

### Produção

Os alvos abaixo usam `docker-compose.prod.yml`:

```bash
make prod-build       # Build das imagens de produção
make prod-up          # Sobe os serviços
make prod-down        # Derruba os serviços
make prod-logs        # Logs em tempo real
make prod-migrate     # Aplica migrations
make prod-superuser   # Cria superusuário
make prod-setup       # Garante grupos e usuários iniciais

make prod-backup      # Gera um dump manual do banco
make prod-restore FILE=backups/vetmanager_AAAAMMDD_HHMMSS.sql.gz
```

> ⚠️ O `docker-compose.prod.yml` **não está versionado neste repositório**. Os
> alvos `prod-*` e os scripts de backup/restore esperam esse arquivo no servidor
> de produção. O compose de desenvolvimento (`docker-compose.yml`) funciona
> normalmente sem ele.

---

## 🔐 Autenticação e segurança

### Login

```http
POST /api/v1/token/
Content-Type: application/json

{
  "username": "admin",
  "password": "sua-senha"
}
```

A resposta contém `access`, `refresh` e os dados básicos do usuário (`id`,
`username`, `groups`, `is_staff`). O backend também define os cookies
`httpOnly` **access** e **refresh**.

```bash
curl -i -c cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"sua-senha"}' \
  http://localhost:8000/api/v1/token/
```

Depois, o navegador autentica automaticamente pelas próximas requisições:

```bash
curl -b cookies.txt http://localhost:8000/api/v1/dashboard/
```

Para clientes que preferem header (Swagger, cURL, integrações):

```bash
curl -H "Authorization: Bearer <access>" \
  http://localhost:8000/api/v1/dashboard/
```

### Tokens e sessão

- `access` expira em **30 minutos** por padrão.
- `refresh` expira em **1 dia** por padrão.
- O refresh token é rotacionado a cada renovação.
- O refresh token antigo é colocado na blacklist após a rotação.
- O logout remove os cookies e revoga o refresh token.
- A troca de senha revoga todos os refresh tokens anteriores do usuário e
  devolve um novo par `access`/`refresh`.

### Endpoints de autenticação e perfil

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/api/v1/token/` | Login (JWT + cookies) |
| `POST` | `/api/v1/token/refresh/` | Renova o access (lê o refresh do body ou do cookie) |
| `POST` | `/api/v1/token/logout/` | Logout, blacklist e limpeza dos cookies |
| `GET` | `/api/v1/perfil/` | Dados do usuário logado |
| `PUT` | `/api/v1/perfil/` | Atualiza nome, sobrenome e e-mail |
| `PATCH` | `/api/v1/perfil/` | Atualização parcial do perfil |
| `POST` | `/api/v1/perfil/alterar-senha/` | Troca de senha (exige a senha atual) |

`username`, grupos e permissões são **somente leitura** — são gerenciados no
`/admin`. A troca de senha envia:

```json
{
  "senha_atual": "senha-antiga-123",
  "nova_senha": "senha-nova-456",
  "confirmar_nova_senha": "senha-nova-456"
}
```

A nova senha passa pelos `AUTH_PASSWORD_VALIDATORS` (mínimo de **10
caracteres**, senha comum, numérica e similaridade com o usuário). A senha atual
incorreta, a confirmação divergente e a repetição da senha atual são rejeitadas.

### Perfis e permissões (RBAC)

Os grupos são criados pela migration `accounts.0001_grupos_padrao` e garantidos
pelo comando `setup_inicial`:

```bash
python manage.py setup_inicial   # ou: make prod-setup
```

| Grupo | Acesso |
|---|---|
| `admin` | Todos os recursos, incluindo prontuários e vacinas |
| `veterinario` | Prontuários e vacinas + demais recursos autenticados |
| `recepcao` | Agenda, tutores, pets, profissionais e dashboard; **sem prontuários/vacinas** |
| sem grupo | Acessa apenas recursos sem `role_policy`; não acessa prontuários/vacinas |

- Superusuários têm acesso total independentemente do grupo.
- Estar no grupo `admin` **não** concede acesso ao `/admin` do Django; para isso
  o usuário precisa de `is_staff` ou `is_superuser`.
- Os nomes precisam ser exatamente `admin`, `veterinario` e `recepcao` — são os
  mesmos devolvidos no claim `groups` do JWT.

### Proteções contra abuso

- **Rate limiting** por IP anônimo e por usuário autenticado.
- **Login** limitado por usuário informado (não apenas por IP), evitando que
  um pico de logins bloqueie a clínica inteira atrás do proxy.
- **Bloqueio temporário** após tentativas falhas, tanto no login JWT quanto no
  `/admin` (backend `LockoutModelBackend`).
- **Limite de payload** e de campos por requisição.
- Em produção: `X-Frame-Options: DENY`, `nosniff`, HSTS opcional, redirect SSL
  opcional e tratamento genérico de erros 500 sem stack trace.
- Swagger/ReDoc ficam restritos a staff por padrão em produção
  (`API_DOCS_PUBLIC=False`).

---

## 🔌 Endpoints da API

### Convenções

- Base: `http://localhost:8000/api/v1/`
- Todos os endpoints exigem autenticação, exceto login e refresh.
- Tutores, pets, profissionais, atendimentos e prontuários usam **UUID**;
  vacinas usam `id` inteiro.
- Datas/horas usam ISO 8601 (ex.: `2026-10-20T09:00:00Z`).
- Listagens são paginadas em **20 itens**:

```json
{
  "count": 42,
  "next": "http://localhost:8000/api/v1/pets/?page=2",
  "previous": null,
  "results": []
}
```

- Parâmetros comuns: `?search=` e `?page=` (os ViewSets atuais habilitam
  `SearchFilter`; filtros específicos estão listados em cada recurso).
- Em produção a API responde apenas JSON (sem Browsable API).

### Tutores

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/tutores/` | Lista tutores com pets aninhados |
| `POST` | `/api/v1/tutores/` | Cria tutor (com pets opcionais em cascata) |
| `GET` | `/api/v1/tutores/{id}/` | Detalhe do tutor + pets |
| `PUT` | `/api/v1/tutores/{id}/` | Atualiza tutor |
| `PATCH` | `/api/v1/tutores/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/tutores/{id}/` | Remove tutor |

- Busca: `nome`, `telefone`, `cpf`
- No `POST`, o campo `pets` é uma lista opcional.
- A criação de tutor + pets roda em uma única transação.

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/tutores/ \
  -H "Content-Type: application/json" \
  -d '{
    "nome": "Joana Reis",
    "telefone": "11 91111-1111",
    "email": "joana@example.com",
    "pets": [
      {"nome": "Rex", "especie": "Cão", "raca": "Labrador", "sexo": "M"}
    ]
  }'
```

### Pets

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/pets/` | Lista pets |
| `POST` | `/api/v1/pets/` | Cadastra pet (exige `tutor`) |
| `GET` | `/api/v1/pets/{id}/` | Detalhe do pet |
| `PUT` | `/api/v1/pets/{id}/` | Atualiza pet |
| `PATCH` | `/api/v1/pets/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/pets/{id}/` | Remove pet |

- Filtro: `?tutor={uuid}`
- Busca: `nome`, `especie`, `raca`, `tutor__nome`
- Campos: `nome`, `especie`, `raca`, `cor`, `sexo`, `castrado`, `vermifugado`,
  `data_nascimento`, `observacoes`

### Profissionais

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/profissionais/` | Lista profissionais |
| `POST` | `/api/v1/profissionais/` | Cadastra profissional |
| `GET` | `/api/v1/profissionais/{id}/` | Detalhe do profissional |
| `PUT` | `/api/v1/profissionais/{id}/` | Atualiza profissional |
| `PATCH` | `/api/v1/profissionais/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/profissionais/{id}/` | Remove profissional |

- Busca: `nome`, `cargo`
- Cargos: `Veterinário`, `tosador`, `banhista`, `Outro`
- A resposta inclui o bloco `veterinario` (`crmv`, `especialidade`) quando
  existir.

### Atendimentos

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/atendimentos/` | Lista atendimentos |
| `POST` | `/api/v1/atendimentos/` | Agenda atendimento |
| `GET` | `/api/v1/atendimentos/{id}/` | Detalhe |
| `PUT` | `/api/v1/atendimentos/{id}/` | Atualiza |
| `PATCH` | `/api/v1/atendimentos/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/atendimentos/{id}/` | Remove |
| `POST` | `/api/v1/atendimentos/rapido/` | Cria tutor/pet/atendimento em 1 chamada |

- Filtros: `?pet={uuid}`, `?profissional={uuid}`, `?status=...`,
  `?data_inicio=AAAA-MM-DD`, `?data_fim=AAAA-MM-DD`
- Busca: `pet__nome`, `pet__tutor__nome`, `profissional__nome`,
  `nome_profissional`
- Para o profissional, envie `profissional_id` (preferencial) ou
  `nome_profissional` (compatibilidade legada). Pelo menos um é obrigatório.
- Tipos de serviço: `consulta`, `retorno`, `vacina`, `banho`, `tosa`,
  `banho_e_tosa`, `banho_e_tosa_higienica`
- Status: `agendado`, `confirmado`, `realizado`, `cancelado`, `faltou`

#### Regra de conflito de horário

O backend considera o intervalo `[data_hora_inicio, data_hora_inicio + duracao)`.

- Dois atendimentos do **mesmo profissional** não podem se sobrepor.
- Atendimentos **cancelados** não geram conflito.
- Horários adjacentes são permitidos (um termina quando o outro começa).
- Na edição, o próprio atendimento é ignorado na verificação.
- Registros legados sem FK de profissional não entram na verificação.
- A resposta de conflito é `400` com a chave `data_hora_inicio` e mensagem em
  português.

#### Atendimento rápido

`POST /api/v1/atendimentos/rapido/` cria tudo em uma única transação:

- Exatamente **um** entre `tutor_id` e `tutor`
- Exatamente **um** entre `pet_id` e `pet`
- Pelo menos **um** entre `profissional_id` e `nome_profissional`
- O `pet_id` informado precisa pertencer ao tutor informado
- Qualquer falha desfaz tutor, pet e atendimento criados na chamada

```bash
curl -b cookies.txt -X POST http://localhost:8000/api/v1/atendimentos/rapido/ \
  -H "Content-Type: application/json" \
  -d '{
    "tutor": {"nome": "Joana Reis", "telefone": "11 91111-1111"},
    "pet": {"nome": "Rex", "especie": "Cão", "raca": "Labrador"},
    "profissional_id": "00000000-0000-0000-0000-000000000000",
    "tipo_servico": "consulta",
    "data_hora_inicio": "2026-10-20T09:00:00Z",
    "duracao_minutos": 30,
    "queixa": "Vômitos desde ontem"
  }'
```

### Prontuários

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/prontuarios/` | Lista prontuários |
| `POST` | `/api/v1/prontuarios/` | Cria prontuário |
| `GET` | `/api/v1/prontuarios/{id}/` | Detalhe |
| `PUT` | `/api/v1/prontuarios/{id}/` | Atualiza |
| `PATCH` | `/api/v1/prontuarios/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/prontuarios/{id}/` | Remove |

- Acesso restrito a `admin` e `veterinario` (superusuário sempre pode).
- Filtro: `?pet={uuid}`
- Busca: `pet__nome`, `diagnostico`
- Campos: `atendimento`, `pet`, `veterinario`, `data_consulta`, `peso`,
  `temperatura`, `diagnostico`, `observacoes`, `prescricao`,
  `retorno_recomendado`
- A resposta inclui `vacinas` aninhadas e os nomes de pet/veterinário.

### Vacinas

| Método | Endpoint | Descrição |
|---|---|---|
| `GET` | `/api/v1/vacinas/` | Lista vacinas |
| `POST` | `/api/v1/vacinas/` | Registra vacina |
| `GET` | `/api/v1/vacinas/{id}/` | Detalhe |
| `PUT` | `/api/v1/vacinas/{id}/` | Atualiza |
| `PATCH` | `/api/v1/vacinas/{id}/` | Atualiza parcialmente |
| `DELETE` | `/api/v1/vacinas/{id}/` | Remove |

- Acesso restrito a `admin` e `veterinario`.
- Filtro: `?pet={uuid}`
- Busca: `nome_vacina`, `pet__nome`
- Campos: `pet`, `prontuario` (opcional), `nome_vacina`, `data_aplicacao`,
  `data_retorno`, `observacoes`

### Dashboard

```http
GET /api/v1/dashboard/
```

Resposta:

```json
{
  "usuario": "admin",
  "perfil": "admin",
  "atendimentos_hoje": 8,
  "atendimentos_pendentes": 3,
  "total_pets": 120,
  "total_tutores": 87
}
```

### Códigos de resposta

| Código | Significado |
|---|---|
| `200` | Sucesso |
| `201` | Criado |
| `204` | Removido |
| `400` | Dados inválidos / conflito de horário |
| `401` | Token ausente, inválido ou expirado |
| `403` | Sem permissão para o recurso |
| `404` | Recurso não encontrado |
| `429` | Limite de requisições excedido |
| `500` | Erro interno (mensagem genérica em produção) |

---

## 🧪 Testes e qualidade

### Com Docker

```bash
make test
make lint
make format
```

### Sem Docker (SQLite)

O settings `core.settings.test` usa SQLite e cache local, permitindo rodar a
suíte fora do container:

```bash
DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py test
```

A suíte cobre, entre outros pontos:

- criação dos grupos padrão e idempotência do `setup_inicial`
- login JWT e claim de grupos
- permissões de prontuários por perfil
- perfil e troca de senha (incluindo revogação de refresh tokens)
- cadastro de tutor com pets em cascata e rollback
- atendimento rápido (ids, cascata, validações e rollback)
- conflito de horário (sobreposição, adjacência, cancelados e edição)
- endpoints legados de atendimento
- busca e filtros dos recursos

---

## 🚢 Deploy

### Render (build.sh + procfile)

O repositório inclui os arquivos usados em deploy estilo Render:

```bash
./build.sh
```

O script instala dependências, roda `collectstatic`, aplica migrations e executa
`setup_inicial`. O `procfile` inicia o Gunicorn:

```text
web: gunicorn core.wsgi:application --bind 0.0.0.0:$PORT
```

### Docker de produção

O fluxo esperado é:

```text
navegador → nginx → gunicorn (web) → PostgreSQL
                              ↘ Redis
```

- `deploy/entrypoint.sh` faz backup do banco antes de migrations pendentes,
  aplica migrations, coleta estáticos e garante grupos/usuários iniciais.
- `deploy/nginx.conf` serve o SPA, faz proxy de `/api/` e `/admin/`, e entrega
  `/static/` e `/media/`.
- `deploy/backup_db.sh` gera dumps comprimidos em `backups/` e mantém retenção.
- `deploy/restore_db.sh` gera um backup de segurança e restaura um dump com
  confirmação explícita.

> O arquivo `docker-compose.prod.yml` é necessário para os comandos `prod-*`,
> mas não está versionado neste repositório. Mantenha-o no servidor de produção
> com as variáveis e volumes adequados.

### Netlify + Tailscale Funnel

Arquitetura usada pelo frontend:

```text
navegador → Netlify (/api/* como proxy) → Tailscale Funnel → nginx → gunicorn
```

Assim o navegador enxerga frontend e API na **mesma origem** (`*.netlify.app`),
o que torna os cookies `httpOnly` first-party e funcionais no Safari/Chrome do
celular.

- O `netlify.toml` incluído redireciona `/api/*` para o host do Funnel antes do
  fallback do SPA.
- O frontend deve usar `VITE_API_URL=/api/v1` (caminho relativo).
- `core/settings/prod.py` adiciona o host do Funnel em `ALLOWED_HOSTS` e as
  origens do Netlify/Funnel em `CSRF_TRUSTED_ORIGINS`.
- Os cookies JWT usam `SameSite=Lax` por padrão (`JWT_COOKIE_SAMESITE`).
- O Funnel termina o TLS e repassa `X-Forwarded-Proto: https`
  (`SECURE_PROXY_SSL_HEADER`).
- Com `USE_HTTPS=True`, o Django ativa redirect SSL, cookies seguros e HSTS.

Teste rápido de disponibilidade:

```bash
curl -i https://serverubunto.tail459c47.ts.net/api/v1/   # 401 = API viva
curl -i https://vetmanager-letvet.netlify.app/api/v1/    # 401 = proxy OK
```

### Backup e restauração

```bash
# Backup manual
make prod-backup

# Restaurar um dump (pede confirmação e gera backup de segurança antes)
make prod-restore FILE=backups/vetmanager_20261105_120000.sql.gz
```

- Dumps diários são mantidos por **30 dias** (`RETAIN_DAYS`).
- Os **10 últimos** backups pré-migration são preservados
  (`KEEP_PRE_MIGRATION`).
- O entrypoint aborta o start se o backup pré-migration falhar.

---

## 🗂️ Estrutura do projeto

```text
VetManager/
├── 🐳 Dockerfile
├── 🐳 docker-compose.yml
├── ⚙️  Makefile
├── 📄 .env.example
├── 📄 requirements.txt
├── 📄 manage.py
├── 📄 build.sh
├── 📄 procfile
├── 📄 netlify.toml
├── 📄 schema.yml
│
├── api/
│   └── v1/
│       └── router.py              # Registro dos ViewSets
│
├── core/
│   ├── settings/
│   │   ├── base.py                # DRF, JWT, RBAC, cache, throttling
│   │   ├── dev.py                 # PostgreSQL local + DEBUG
│   │   ├── prod.py                # Segurança e DATABASE_URL
│   │   └── test.py                # SQLite para testes
│   ├── exceptions.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── apps/
│   ├── accounts/                  # Auth, perfil, grupos, lockout, throttles
│   ├── atendimentos/              # Agenda + conflito + atendimento rápido
│   ├── base/                      # BaseModel (UUID) e utilitários
│   ├── dashboard/                 # Visão geral
│   ├── pets/                      # Pets
│   ├── prontuario/                # Prontuários e vacinas
│   ├── tutores/                   # Tutores + cadastro em cascata
│   └── veterinarios/              # Profissionais e veterinários
│
└── deploy/
    ├── backup_db.sh
    ├── entrypoint.sh
    ├── nginx.conf
    └── restore_db.sh
```

---

## 🤝 Contribuindo

1. Faça um fork do projeto
2. Crie uma branch: `git checkout -b feature/minha-feature`
3. Faça suas alterações e rode `make lint` e `make test`
4. Commit: `git commit -m 'feat: adiciona minha feature'`
5. Push: `git push origin feature/minha-feature`
6. Abra um Pull Request

Ao alterar modelos, não esqueça de rodar:

```bash
make migrations
make migrate
```

E, se alterar endpoints, atualize o schema OpenAPI:

```bash
docker compose exec web python manage.py spectacular --file schema.yml
```

---

## 📄 Licença

Este projeto está sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para
mais detalhes.

---

<div align="center">

Feito para simplificar a rotina de clínicas veterinárias 🐶🐱

</div>
