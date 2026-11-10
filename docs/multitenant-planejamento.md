# Planejamento Multiempresa / SaaS (Prompt 23)

**Status:** planejamento e arquitetura apenas.  
**NÃO** implementar migração estrutural nem alterar o modelo de dados antes de aprovação do produto.  
O sistema VetManager é atualmente **single-tenant** (uma clínica por instalação/banco).

---

## 1. Contexto e decisão arquitetural

O VetManager hoje é single-tenant: todos os registros pertencem implicitamente a
a única clínica instalada. Não há campo de clínica/unidade nos modelos, e o
isolamento entre clínicas não existe.

Para suportar várias clínicas (SaaS), avaliamos três estratégias de isolamento
de banco:

| Estratégia | Descrição | Vantagem | Desvantagem |
|------------|-----------|----------|-------------|
| **Banco por clínica** | Cada clínica tem seu próprio banco PostgreSQL | Isolamento físico total; backup/restore por clínica simples | Alto custo operacional; migrations replicadas; difícil de escalar para muitas clínicas |
| **Schema por clínica** | Um banco, um schema PostgreSQL por clínica | Bom isolamento lógico; backup por schema possível | Complexidade de migrations e conexões; limites de schema |
| **Tabela compartilhada + `clinica_id`** | Uma tabela por modelo com coluna `clinica_id` (row-level) | Simples de operar; migrations únicas; escala para muitas clínicas | Requer isolamento rigoroso no backend (RLS + query automática) |

**Decisão proposta:** tabela compartilhada com coluna `clinica_id` + Row Level Security (RLS) no PostgreSQL para isolamento em duas camadas (aplicação e banco). Esse modelo equilibra simplicidade operacional com isolamento de dados.

---

## 2. Modelo de dados proposto

Novas entidades:

### Clinica
Uma clínica (pessoa jurídica/estabelecimento) contratante do SaaS.

| Campo | Tipo | Observação |
|-------|------|------------|
| id | UUID PK | |
| nome | string | Nome fantasia / razão social |
| cnpj | string, único | CNPJ da clínica |
| email | string | Contato principal |
| telefone | string | |
| endereco | string | |
| ativo | boolean | Clínica pode ser desativada (suspensão de plano) |
| plano | string | Plano de assinatura (ex.: básico, profissional) |
| created_at / updated_at | timestamp | |
| created_by | FK usuário | Usuário da plataforma que cadastrou |

### Unidade
Uma unidade física pertencente a uma clínica (filial, unidade de atendimento).

| Campo | Tipo | Observação |
|-------|------|------------|
| id | UUID PK | |
| clinica | FK Clinica | Obrigatório |
| nome | string | Ex.: "Unidade Centro" |
| endereco | string | |
| telefone | string | |
| ativo | boolean | |
| created_at / updated_at | timestamp | |

### Vínculo Usuário–Clínica (UsuarioClinica)
Um usuário pode pertencer a uma ou mais clínicas, com papel diferente em cada uma.

| Campo | Tipo | Observação |
|-------|------|------------|
| id | UUID PK | |
| usuario | FK User | Obrigatório |
| clinica | FK Clinica | Obrigatório |
| papel | string | admin_clinica, veterinario, recepcao, financeiro |
| unidades | M2M Unidade | Unidades às quais o usuário tem acesso dentro da clínica |
| ativo | boolean | Vínculo pode ser desativado sem desativar o usuário |
| created_at | timestamp | |

**Regras:**
* Um usuário sem vínculo ativo a nenhuma clínica não acessa o SPA interno.
* Um usuário pode ser `admin_plataforma` (acesso a todas as clínicas) ou
  `admin_clinica` (gerencia só suas clínicas).
* Papéis são por clínica: o mesmo usuário pode ser `veterinário` na clínica A e
  `recepção` na clínica B.

### Associação `clinica_id` nos modelos existentes

Adicionar `clinica = models.ForeignKey(Clinica, ...)` a:
* Tutor, Pet, Profissional, Veterinario
* Atendimento, Prontuario, Vacina, Vermifugacao, MedicaoVital
* Estoque, Produto, Lote, MovimentacaoEstoque, Inventario
* ContaReceber, Parcela, Pagamento, AplicacaoPagamento, Caixa, MovimentacaoCaixa
* Servico, CategoriaServico, Orcamento, ServicoRealizado
* Prescricao, ItemPrescricao
* Documento, Notificacao (portal)
* SolicitacaoAgendamento

Quando aplicável, também associar `unidade` (Unidade) para isolamento dentro da
clínica (ex.: estoque por unidade, agenda por unidade).

Registros já existentes (single-tenant) serão associados a uma **Clínica inicial**
durante a migração (seção 5).

---

## 3. Estratégia de isolamento

### 3.1 Backend (aplicação)

* Todo ViewSet que lida com modelos associados a clínica filtra automaticamente
  por `clinica` do usuário da requisição (middleware de tenant ou `get_queryset`).
* Nenhum endpoint aceita `clinica` no payload de escrita: a clínica é inferida
  do usuário autenticado.
* Filtros por `clinica_id` em query strings são ignorados/rejeitados quando não
  pertencem ao usuário (evita enumeração).
* O middleware de tenant define `request.clinica` (ou `request.clinicas`) a
  partir dos vínculos do usuário; views usam esse valor.

### 3.2 Banco (PostgreSQL RLS)

* Habilitar Row Level Security nas tabelas associadas a clínica.
* Política: `USING (clinica_id = current_setting('app.clinica_id', true)::uuid)`.
* Definir `app.clinica_id` no início de cada requisição (via `SET LOCAL` dentro
  da transação da request) para que o próprio PostgreSQL impeça acesso cruzado.
* Superusuário e migrations estão isentos da RLS (bypassrls) para administração.

Isso garante isolamento mesmo que haja falha no filtro da aplicação.

---

## 4. Usuários e papéis

| Tipo | Escopo | Pode |
|------|--------|------|
| Admin plataforma | Todas as clínicas | Criar clínicas, gerenciar usuários plataforma, ver métricas globais |
| Admin clínica | Suas clínicas | Gerenciar usuários, unidades, papéis, plano da clínica |
| Veterinário | Clínica + unidades | Prontuários, prescrições, atendimentos de suas unidades |
| Recepção | Clínica + unidades | Agendamentos, orçamentos, caixa, contas a receber |
| Financeiro | Clínica | Contas a pagar/receber, relatórios financeiros |

* Usuário pertence a 1..N clínicas (muitos-para-muitos via `UsuarioClinica`).
* Papel é por clínica.
* Permissões por unidade (opcional, mais granular).

---

## 5. Estratégia de migração (single-tenant → multi-tenant)

Objetivo: migrar todos os registros atuais para uma **Clínica inicial** para que
não haja registros sem tenant.

Passos:

1. Criar modelo `Clinica`, `Unidade`, `UsuarioClinica` e as migrações.
2. Rodar `setup_inicial` (ou migration de dados) que cria:
   - Uma `Clinica` inicial a partir dos dados da clínica atual (nome, CNPJ,
     endereço, telefone definidos no `.env` ou defaults).
   - Uma `Unidade` inicial (sede) vinculada à clínica.
   - Vínculo `UsuarioClinica` para todos os usuários existentes como
     `admin_clinica` da clínica inicial (ou papel que já possuíam).
3. Adicionar `clinica_id` (NOT NULL com default da clínica inicial) a todos os
   modelos existentes; popular registros atuais com o ID da clínica inicial.
4. Validar que não há registros com `clinica_id` NULL (`__check_no_tenantless`).
5. Ativar RLS e o filtro de tenant no backend.
6. Manter compatibilidade: enquanto houver instalações single-tenant, o campo
   `clinica` é preenchido automaticamente; nenhuma quebra para o deployment atual.

Não deixar registros sem tenant: toda migration de dados inclui checagem de
`clinica_id IS NULL` e falha se houver.

---

## 6. Riscos

| Risco | Impacto | Mitigação |
|-------|---------|-----------|
| Vazamento de dados entre clínicas (falha de filtro) | Alto | RLS no banco como segunda camada; testes de acesso cruzado |
| Complexidade de migrations com dados existentes | Médio | Migration de dados em etapas, backup antes, rollback testado |
| Performance de consultas com `clinica_id` | Médio | Índices compostos `(clinica_id, ...)` nas colunas filtradas |
| Usuário com papel inconsistente entre clínicas | Baixo | Papel armazenado por vínculo usuário-clínica, não no usuário global |
| Backup/restore por clínica mais complexo | Médio | Dump filtrado por `clinica_id` ou backup por schema se necessário |

---

## 7. Testes de isolamento

Para cada recurso clínico (tutor, pet, prontuario, estoque, financeiro):
* Criar registros de duas clínicas diferentes.
* Autenticar como usuário da clínica A.
* Tentar acessar (listar/detalhar/editar/excluir) registro da clínica B.
* Esperar 403 ou 404 (não vazar o registro), nunca 200 com dados da clínica B.
* Testar também via query string `?clinica_id=<id da clínica B>` — deve ser ignorado ou rejeitado.

---

## 8. Plano de implantação (após aprovação)

1. Apresentar este documento ao produto e obter aprovação da arquitetura.
2. Criar branches `feat/multitenant-*` para modelos, migrations e isolamento.
3. Implementar `Clinica`/`Unidade`/`UsuarioClinica` + migration de dados para clínica inicial.
4. Adicionar `clinica_id` aos modelos existentes e popular registros atuais.
5. Implementar filtro de tenant no backend + RLS.
6. Escrever testes de acesso cruzado.
7. Revisão de segurança e homologação.
8. Implantar em staging e validar com dados reais de uma clínica.
9. Somente então liberar multi-clínica para novos clientes.

**A migração estrutural só é executada após aprovação explícita do produto.**
