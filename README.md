<div align="center">

# 🐾 VetManager

**API REST para gerenciamento de clínicas veterinárias**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.x-092E20?style=flat&logo=django&logoColor=white)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/Django_REST_Framework-3.x-A30000?style=flat)](https://www.django-rest-framework.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat&logo=docker&logoColor=white)](https://docker.com)


Sistema completo para gerenciar atendimentos, pets, tutores e financeiro de clínicas veterinárias de pequeno e médio porte.

[Funcionalidades](#-funcionalidades) · [Tecnologias](#-tecnologias) · [Como rodar](#-como-rodar) · [Endpoints](#-endpoints-da-api) · [Estrutura](#-estrutura-do-projeto)

</div>

---

## 📋 Sobre o projeto

O **VetManager** nasceu da necessidade real de uma clínica veterinária de organizar sua rotina: agendamentos conflitantes, histórico clínico espalhado e controle financeiro manual. A API resolve isso de forma simples e extensível.

**Principais problemas que resolve:**
- Conflitos de horário na agenda dos veterinários
- Falta de histórico clínico centralizado dos pets
- Ausência de controle financeiro dos atendimentos
- Comunicação descentralizada com tutores

---

## ✨ Funcionalidades

### MVP (versão atual)
- ✅ Cadastro de tutores, pets e veterinários
- ✅ Agendamento com **validação de conflito de horários**
- ✅ Controle de status do atendimento (`Agendado → Confirmado → Em Andamento → Concluído → Cancelado`)
- ✅ Prontuário clínico com upload de anexos (exames, receitas)
- ✅ Controle de vacinas e vermifugação
- ✅ Financeiro básico com relatório de faturamento diário/mensal
- ✅ Dashboard com visão geral da agenda
- ✅ Autenticação JWT
- ✅ Documentação automática via Swagger

### Fase 2 (em planejamento)
- 🔜 Lembretes automáticos via WhatsApp (Evolution API)
- 🔜 App para tutores acompanharem agenda e histórico do pet
- 🔜 Controle de estoque de medicamentos
- 🔜 Integração com gateway de pagamento (Asaas / PagSeguro)

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|---|---|
| Backend | Django 5 + Django REST Framework |
| Autenticação | SimpleJWT |
| Documentação | drf-spectacular (Swagger / ReDoc) |
| Banco de dados | PostgreSQL 16 |
| Filtros | django-filter |
| Containers | Docker + Docker Compose |
| Automação | Makefile |
| Frontend (futuro) | React |

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

Edite o `.env` com suas configurações:

```env
SECRET_KEY=sua-secret-key-aqui
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

POSTGRES_DB=vetmanager
POSTGRES_USER=vetmanager_user
POSTGRES_PASSWORD=sua-senha-aqui
DATABASE_URL=postgres://vetmanager_user:sua-senha-aqui@db:5432/vetmanager
```

### 3. Suba os containers

```bash
make build
make up
```

### 4. Execute as migrations e crie o superusuário

```bash
make migrate
make createsuperuser
```

### 5. Acesse

| Serviço | URL |
|---|---|
| API | http://localhost:8000/api/ |
| Swagger | http://localhost:8000/api/schema/swagger-ui/ |
| ReDoc | http://localhost:8000/api/schema/redoc/ |
| Admin Django | http://localhost:8000/admin/ |

---

## ⚙️ Comandos Make

```bash
# Containers
make build           # Build das imagens
make up              # Sobe os serviços em background
make down            # Para e remove os containers
make restart         # Reinicia todos os serviços
make logs            # Exibe logs em tempo real

# Django
make migrate         # Aplica migrations
make makemigrations  # Gera novas migrations
make createsuperuser # Cria superusuário
make shell           # Django shell interativo
make collectstatic   # Coleta arquivos estáticos

# Qualidade de código
make test            # Roda os testes
make test-cov        # Testes com cobertura
make lint            # Verifica o código (ruff)
make format          # Formata o código (black + isort)

# Banco de dados
make psql            # Acessa o PostgreSQL
make backup          # Gera dump do banco
make reset-db        # Apaga e recria o banco ⚠️
```

---

## 🔌 Endpoints da API

### Autenticação
```
POST   /api/v1/token/           # Obter token JWT
POST   /api/v1/token/refresh/   # Renovar token
```

### Tutores
```
GET    /api/v1/tutores/         # Listar tutores (inclui pets aninhados na lista/retrieve)
POST   /api/v1/tutores/         # Criar tutor com pets (cascata) em 1 chamada
GET    /api/v1/tutores/{id}/    # Detalhe do tutor + pets
PUT    /api/v1/tutores/{id}/    # Atualizar tutor
PATCH  /api/v1/tutores/{id}/    # Atualizar parcial
DELETE /api/v1/tutores/{id}/    # Remover tutor
```

### Pets
```
GET    /api/v1/pets/            # Listar pets
POST   /api/v1/pets/            # Cadastrar pet
GET    /api/v1/pets/{id}/       # Detalhe do pet
PUT    /api/v1/pets/{id}/       # Atualizar pet
PATCH  /api/v1/pets/{id}/       # Atualizar parcial
DELETE /api/v1/pets/{id}/       # Remover pet
```

### Atendimentos
```
GET    /api/v1/atendimentos/           # Listar atendimentos
POST   /api/v1/atendimentos/           # Agendar atendimento (legado + novo: aceita profissional_id)
GET    /api/v1/atendimentos/{id}/      # Detalhe do atendimento
PUT    /api/v1/atendimentos/{id}/      # Atualizar atendimento
PATCH  /api/v1/atendimentos/{id}/      # Atualizar parcial
DELETE /api/v1/atendimentos/{id}/      # Remover atendimento
POST   /api/v1/atendimentos/rapido/     # Criar tutor+pet+atendimento em 1 chamada
```

### Outros
```
GET    /api/v1/dashboard/                     # Visão geral
GET    /api/v1/profissionais/                # Profissionais
GET    /api/v1/prontuarios/                  # Prontuários
GET    /api/v1/vacinas/                      # Vacinas
```

> Documentação completa e interativa disponível no Swagger em `/api/schema/swagger-ui/`

---

## 👥 Perfis e grupos (RBAC)

O acesso é controlado por grupos do Django. Eles são criados automaticamente
pela migration `accounts.0001_grupos_padrao` e podem ser garantidos a qualquer
momento com:

```bash
python manage.py setup_inicial   # ou: make prod-setup
```

| Grupo | Acesso |
|---|---|
| `admin` | total (superusuários também) |
| `veterinario` | agenda, tutores, pets, prontuários e vacinas |
| `recepcao` | agenda, tutores e pets; **sem acesso a prontuários** |

No `/admin`, associe cada usuário ao grupo correspondente em
*Usuários › grupos*. Os nomes precisam ser exatamente `admin`, `veterinario`
ou `recepcao` — são os mesmos devolvidos no claim `groups` do JWT.

---

## 🗂️ Estrutura do projeto

```
vetmanager/
├── 🐳 Dockerfile
├── 🐳 docker-compose.yml
├── 🐳 docker-compose.prod.yml
├── ⚙️  Makefile
├── 📄 .env.example
├── 📄 requirements.txt
├── 📄 manage.py
│
├── core/                    # Configurações do projeto
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   └── prod.py
│   ├── urls.py
│   └── wsgi.py
│
├── apps/
│   ├── tutores/             # Módulo de clientes
│   ├── pets/                # Módulo de pets
│   ├── veterinarios/        # Módulo de veterinários
│   ├── atendimentos/        # Módulo core — agenda e validação
│   ├── prontuario/          # Histórico clínico
│   ├── financeiro/          # Pagamentos e relatórios
│   └── dashboard/           # Visão geral
│
└── tests/                   # Testes automatizados
```

---

## 🧪 Testes

```bash
# Rodar todos os testes
make test

# Com relatório de cobertura
make test-cov
```

---

## 🤝 Contribuindo

1. Fork o projeto
2. Crie sua branch: `git checkout -b feature/minha-feature`
3. Commit suas mudanças: `git commit -m 'feat: adiciona minha feature'`
4. Push para a branch: `git push origin feature/minha-feature`
5. Abra um Pull Request

---

## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---


