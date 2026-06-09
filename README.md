<div align="center">

# 🐾 VetManager

**API REST para gerenciamento de clínicas veterinárias**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![Django](https://img.shields.io/badge/Django-5.x-092E20?style=flat&logo=django&logoColor=white)](https://djangoproject.com)
[![DRF](https://img.shields.io/badge/Django_REST_Framework-3.x-A30000?style=flat)](https://www.django-rest-framework.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat&logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

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
POST   /api/token/           # Obter token JWT
POST   /api/token/refresh/   # Renovar token
```

### Tutores
```
GET    /api/tutores/         # Listar tutores
POST   /api/tutores/         # Criar tutor
GET    /api/tutores/{id}/    # Detalhe do tutor
PUT    /api/tutores/{id}/    # Atualizar tutor
DELETE /api/tutores/{id}/    # Remover tutor
```

### Pets
```
GET    /api/pets/            # Listar pets
POST   /api/pets/            # Cadastrar pet
GET    /api/pets/{id}/       # Detalhe do pet
PUT    /api/pets/{id}/       # Atualizar pet
```

### Atendimentos
```
GET    /api/atendimentos/           # Listar atendimentos
POST   /api/atendimentos/           # Agendar atendimento
GET    /api/atendimentos/{id}/      # Detalhe do atendimento
PUT    /api/atendimentos/{id}/      # Atualizar atendimento
GET    /api/agenda/disponivel/      # Horários disponíveis
```

### Outros
```
GET    /api/dashboard/                     # Visão geral
GET    /api/relatorios/faturamento/        # Relatório financeiro
GET    /api/prontuario/{pet_id}/           # Histórico do pet
```

> Documentação completa e interativa disponível no Swagger em `/api/schema/swagger-ui/`

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

<div align="center">
  Feito com ❤️ · <a href="https://github.com/seu-usuario">@seu-usuario</a>
</div>
