# Descoberta de integração — Softcom

**Status:** Fase 1 (descoberta) e Fase 2 (relatório) concluídas. **Fase 3 (implementação) não iniciada** por ausência de acesso autorizado e de confirmação do produto/base contratado pela clínica.

**Data da análise:** 10/11/2026
**Responsável:** auditoria técnica do VetManager
**Escopo:** avaliar a viabilidade de integrar o VetManager com o Softcom sem presumir APIs, credenciais ou endpoints.

---

## 1. Identificação do fornecedor e do produto

As buscas públicas levam a **Softcom Tecnologia** (softcomtecnologia.com.br), fornecedora de software de gestão. A documentação oficial encontrada descreve a **api-agenda**, uma API REST sobre o banco **BaseSoftcom**:

- Documentação: <https://doc.softcom.cloud>
- Base URL documentada: `https://api.softcom.cloud/v1`
- OpenAPI publicado em `https://doc.softcom.cloud/openapi/{clientes,comercial,rh,tickets,notificacoes,admin,monitoria}.json`
- Contato técnico declarado na documentação: `soft.nocode@softcomtecnologia.com.br`

O health check público respondeu em 10/11/2026 (sem autenticação e sem dados de clientes):

```json
{
  "status": "ok",
  "basesoftcom": "up",
  "authdb": "up",
  "meuSoftcomDb": "up",
  "timestamp": "2026-11-10T15:52:59.637Z",
  "deployment": { "version": 1, "backgroundJobsEnabled": false }
}
```

### Ressalva importante de identificação

A documentação encontrada cobre a **retaguarda de suporte da própria Softcom** (clientes da Softcom, ocorrências/tickets, RH, comercial e notificações internas). Ela **não** descreve o ERP operacional de uma clínica veterinária.

A Softcom também comercializa solução para pet shop/clínica veterinária (vídeo público "Software para PetShop — Softcom Tecnologia"), mas **não foi localizada documentação pública de API para essa vertical**.

Portanto, antes de qualquer implementação é obrigatório confirmar:

1. Qual produto/base a clínica usa (BaseSoftcom, Softcom Pet/Vet ou outro).
2. Se a `api-agenda` expõe os dados desse tenant ou apenas a base de suporte da Softcom.
3. Se existe uma API distinta para a vertical veterinária.

Sem essa confirmação, qualquer integração correria o risco de ser construída contra o sistema errado.

---

## 2. Autenticação, limites e segurança

| Item | O que a documentação informa |
| --- | --- |
| API Key | Header `x-api-key`, destinada a sistemas/integrações externas. A chave tem **escopos** por seção (RH, Clientes, Tickets). |
| Login JWT | `POST /v1/auth/login` com e-mail + senha do colaborador retorna `accessToken` (2 h) e `refreshToken`. |
| Refresh | `POST /v1/auth/refresh`, com **rotação** do refresh token (o anterior é invalidado). |
| Logout | `POST /v1/auth/logout`, revoga o refresh token. Idempotente. |
| Master key | Header `x-master-key` para `/v1/admin/*` (criação/revogação de API keys). Uso interno. |
| Rate limit | **100 req/min por rota**; login **10/min**. Cota individual por usuário/chave; pode ser configurada por API key. Excesso retorna `429` com `Retry-After`. |
| Erros | `400` payload inválido, `401` chave/token ausente ou inválido, `404` recurso inexistente, `429` limite excedido. |
| Transporte | HTTPS em `api.softcom.cloud`. |
| Chave em texto plano | Retornada apenas na criação; não pode ser recuperada depois. |

**Observação:** a chave `x-master-key` não deve ser usada pelo VetManager. A integração deve operar com uma API key de escopo mínimo ou com um usuário de integração dedicado.

---

## 3. Recursos efetivamente documentados

Legenda de direção: **R** = leitura, **W** = escrita.

### 3.1 Clientes

| Recurso | Métodos/paths documentados | Direção | Relevância para o VetManager |
| --- | --- | --- | --- |
| Listar clientes | `GET /v1/clientes` (paginação, filtros `id`, `cnpj`, `nome`, `cidade`, `uf`, `bairro`, `partnerId`, `incluirDesativados`) | R | Possível origem de tutores, se a base for a da clínica |
| Detalhar cliente | `GET /v1/clientes/{id}` | R | Complemento cadastral |
| Contatos | `GET /v1/clientes/{id}/contatos` | R | Contatos do tutor |
| Financeiro | `GET /v1/clientes/{id}/financeiro` | R | Boletos/parcelas (`Bloquetes`): vencimento, valor, pago, data/valor pago |
| Questionários | `GET/POST /v1/clientes/{id}/questionarios` | R/W | Satisfação/NPS — sem uso clínico |
| Auditoria | `GET /v1/clientes/{id}/auditoria` | R | Trilha de alterações do cadastro |
| Compras | `GET /v1/compras` (filtros por cliente, consultor, programa e período) | R | Itens vendidos (`Vendas_Itens`), sem catálogo nem estoque |
| Campanhas | CRUD em `/v1/clientes/{id}/campanhas` | R/W | Marketing |
| Oportunidades | Listar/criar em `/v1/clientes/{id}/oportunidades` | R/W | Comercial |
| Checklists | CRUD em `/v1/clientes/{id}/checklists` | R/W | Onboarding |
| URLs de produto | CRUD em `/v1/clientes/{id}/produtos-urls` | R/W | Acessos de produto |
| Acesso remoto | CRUD em `/v1/clientes/{id}/acesso-remoto` | R/W | Suporte |
| RFCs | Listar/detalhar/editar em `/v1/clientes/{id}/rfcs` | R/W | Histórico de alterações |
| Reajustes | Listar renovações e marcar como enviadas | R/W | Cobrança |

**Não há endpoint documentado para criar ou editar cliente** — apenas listagem, detalhe e sub-recursos.

### 3.2 Financeiro

| Recurso | Descrição | Direção |
| --- | --- | --- |
| Financeiro do cliente | Boletos/parcelas da tabela `Bloquetes` | R |
| PIX em aberto | View `vw_squad_innovation_boletos_pix_aberto` | R |
| PDF de boleto | Geração a partir da parcela | R |
| Boleto combinado de renovação | PDF único com todas as parcelas do cliente | R |
| Clientes devedores | Parcelas vencendo/vencidas, paginado | R |

Não há documentação para **registrar pagamento, dar baixa, estornar, cancelar cobrança ou criar parcela**.

### 3.3 Tickets (ocorrências)

| Recurso | Descrição | Direção |
| --- | --- | --- |
| Abrir ticket | `POST /v1/tickets` (motivo obrigatório; `clienteId` associa o cadastro) | W |
| Iniciar/finalizar | `/v1/tickets/{id}/iniciar`, `/finalizar` | W |
| Editar | `PATCH /v1/tickets/{id}` | W |
| Listar/detalhar | Por cliente, por técnico e por id | R |
| FAQ/Scripts | Buscar subgrupos, árvore de perguntas, processar respostas | R |
| FAQ | Busca na base de conhecimento | R |

**Atenção:** o "ticket" é uma ocorrência de suporte na tabela legada `Agenda` do BaseSoftcom. **Não é agendamento veterinário** e não deve ser mapeado para `Atendimento`.

### 3.4 Comercial e RH

| Seção | Recursos documentados | Direção |
| --- | --- | --- |
| Comercial | Cadastros, parceiros/franquias, contatos, acompanhamentos, painel de atendimentos, busca de cliente, atividades | R/W |
| RH | Colaboradores e dezenas de sub-recursos (cargos, setores, férias, exames, plantões, PDVs, permissões, objetivos, feedbacks, aniversariantes, busca) | R/W |
| Empresas/PDV | Listar, criar e detalhar PDVs (`Vendas_Pdv`) | R/W |
| Notificações | Listar, detalhar e marcar comunicado como lido | R/W |
| Admin | Listar/criar/revogar API keys, definir flag admin e rate limit próprio | R/W |

### 3.5 Formatos e convenções

- JSON em todas as respostas.
- Listagens paginadas em `{ data, pagination }`, com `page` (base 1), `pageSize` (máx. 200) e metadados (`totalRecords`, `totalPages`, `hasNextPage` etc.).
- Datas em ISO 8601; campos `date` podem vir à meia-noite UTC.
- Valores monetários são numéricos (não strings formatadas).
- A documentação alerta para particularidades do schema legado: campos nulos, datas-base `1899-12-30` em horários antigos e horários gravados em BRT.
- Changelog ativo (última entrada em 03/06/2026), sem política de depreciação publicada.

---

## 4. Recursos indisponíveis ou não documentados

Não foram encontrados na documentação oficial:

- Cadastro de **pets**, espécie/raça, peso, microchip.
- **Prontuário**, evoluções, prescrições, exames, internação.
- **Vacinas** e vermifugações.
- **Agenda veterinária**, agendamentos, lista de espera, bloqueios.
- **Catálogo de produtos**, lotes, validade, inventário e movimentações de estoque.
- **Criação de venda/serviço**; existe apenas leitura de compras.
- **Emissão fiscal** (NF-e, NFC-e, NFS-e) ou consulta de notas.
- **Webhooks** ou streaming de eventos.
- **Idempotência** em operações de escrita (nenhum header/chave documentado).
- **Ambiente de homologação/sandbox**; o OpenAPI lista apenas produção (`api.softcom.cloud`) e desenvolvimento local (`localhost:3000`).
- **Exportação em massa** ou endpoint de sincronização incremental com watermark.
- **SLA, limites por tenant e política de retenção**.

---

## 5. Dados necessários para uma integração

Caso o fornecedor confirme que a API expõe a base da clínica, seriam necessários:

1. **Credenciais autorizadas** de homologação (API key com escopo mínimo ou usuário de integração), entregues por canal seguro.
2. **Identificação do tenant/base** e da URL correspondente.
3. **Confirmação por escrito** do escopo permitido: somente leitura ou também escrita.
4. **Contrato/LGPD**: base legal, finalidade, minimização, retenção, subprocessadores e procedimento de incidente.
5. **Documento de mapeamento** entre entidades, com responsáveis de negócio por cada campo.
6. **Amostra de payloads** homologados (sem dados reais) para validar contratos.

### Mapeamento preliminar (somente se confirmado)

| VetManager | Softcom documentado | Direção | Observação |
| --- | --- | --- | --- |
| `Tutor` | `Cliente` | R | Sem endpoint de criação/edição de cliente na documentação |
| `Pet` | — | — | Não disponível |
| `ContaReceber` | `Bloquete`/parcela | R | Leitura de vencimento, valor e status de pagamento |
| `Pagamento` | Campos `pago`, `dataPagamento`, `valorPago` | R | Sem escrita/baixa |
| `Produto`/estoque | Item de `Compra` | R | Não há catálogo nem saldo |
| `ServicoRealizado`/venda | Item de `Compra` | R | Sem criação de venda |
| Fiscal | — | — | Não disponível |
| `Atendimento` | `Ticket` | — | **Não mapear**: ticket é suporte, não atendimento clínico |

---

## 6. Riscos

| Risco | Severidade | Mitigação |
| --- | --- | --- |
| Integrar contra o produto/base errado | **Alta** | Gate de confirmação do fornecedor antes de escrever código |
| API documentada ser a retaguarda da Softcom, não o ERP da clínica | **Alta** | Validar com o fornecedor e com uma amostra de dados autorizada |
| Uso de produção sem sandbox | **Alta** | Exigir homologação; se inexistente, começar somente leitura e com dados mascarados |
| Duplicidade em `POST` (sem idempotência documentada) | **Alta** | Chave de idempotência local, deduplicação e `outbox`; nunca repetir escrita cegamente |
| Rate limit (100/min por rota, 10/min no login) | Média | Backoff exponencial, respeito a `Retry-After`, fila e circuit breaker |
| Gestão de JWT (2 h) e refresh rotativo | Média | Renovação centralizada, armazenamento seguro, nunca logar tokens |
| Schema legado com nulos e datas inconsistentes | Média | Normalização defensiva e validação por contrato |
| Escopo excessivo de API key / uso de master key | **Alta** | Chave dedicada de escopo mínimo; master key proibida no VetManager |
| Exposição de dados pessoais em logs | **Alta** | Logs estruturados sem PII/tokens; mascaramento e auditoria |
| Ausência de webhooks | Média | Sincronização por polling com janela e watermark |
| Acoplamento e mudanças sem política de depreciação | Média | Camada anticorrupção, contrato versionado e testes de contrato |

---

## 7. Estratégia de integração recomendada

### Fase 0 — Confirmação (bloqueante)

- Confirmar produto/base e existência de API para a vertical veterinária.
- Obter credenciais de homologação e autorização escrita de escopo.
- Formalizar LGPD e mapeamento de dados.

### Fase 1 — Somente leitura, atrás de feature flag

- Criar app isolado `apps/integracoes/softcom/` com:
  - cliente HTTP com timeout, retry/backoff e circuit breaker;
  - autenticação por API key (sem master key);
  - contratos/serializers de entrada e saída;
  - mapeadores para `Tutor` e leitura financeira;
  - tabela de vínculo externo (`VinculoExterno`) e log de execução (`ExecucaoSincronizacao`);
  - comando de sincronização manual e dry-run.
- Nenhuma escrita, nenhum webhook e nenhuma chamada em testes automatizados.

### Fase 2 — Escrita controlada (se autorizada)

- Apenas tickets de suporte, se houver caso de uso real.
- `outbox` transacional, chave de idempotência local, deduplicação e confirmação de estado antes de repetir.
- Feature flag desligada por padrão; habilitação por ambiente.

### Fase 3 — Sincronização e monitoramento

- Janela incremental com watermark, limite de páginas e locks.
- Métricas: latência, erros por código, 429, itens sincronizados e divergências.
- Alertas e painel operacional.
- Logs estruturados sem PII, com `request_id` e correlação.

### Fase 4 — Testes

- Mocks HTTP (ex.: `respx`) e fixtures derivadas do OpenAPI.
- Testes de contrato, retry, 429, timeout, 401 e payload inválido.
- Nenhum dado real; nenhuma alteração externa em CI.

**Dependência técnica:** o projeto não possui cliente HTTP dedicado (`httpx`/`requests`) em `requirements.txt`. A inclusão de dependência deve passar por revisão, assim como a definição de onde a sincronização roda (hoje não há Celery; apenas Redis está disponível).

---

## 8. Critérios de aceite para iniciar a Fase 3

- [ ] Fornecedor confirmou por escrito qual produto/base a clínica usa.
- [ ] Existe API documentada para os dados necessários (tutor, financeiro, estoque e/ou fiscal).
- [ ] Credenciais de homologação recebidas por canal seguro.
- [ ] Escopo de leitura/escrita aprovado e registrado.
- [ ] Base legal e DPIA/LGPD aprovados.
- [ ] Mapeamento de campos validado com amostras sem dados reais.
- [ ] Rate limits e política de retry acordados.
- [ ] Feature flag e plano de rollback definidos.

Enquanto os critérios acima não forem atendidos, a integração permanece **não implementada por decisão técnica**, e não por falta de esforço.

---

## 9. Conclusão

- Existe documentação pública real, versionada e com OpenAPI para a **api-agenda** da Softcom.
- A API cobre **clientes, financeiro (leitura), tickets de suporte, comercial, RH e notificações**.
- A API **não cobre** o núcleo clínico veterinário, estoque, vendas, fiscal, webhooks ou idempotência.
- O escopo documentado sugere que a API é a retaguarda da Softcom, e não necessariamente o ERP da clínica.
- **Nenhuma chamada autenticada foi feita, nenhum dado real foi acessado e nenhum código de integração foi criado.**
- Recomendação: **não implementar** até a confirmação do produto/base e a obtenção de acesso autorizado em homologação.

---

## Anexos — fontes consultadas

- Introdução: <https://doc.softcom.cloud>
- Índice completo: <https://doc.softcom.cloud/llms.txt>
- Autenticação: <https://doc.softcom.cloud/authentication.md>
- Quick start: <https://doc.softcom.cloud/quickstart.md>
- Changelog: <https://doc.softcom.cloud/changelog.md>
- OpenAPI de clientes: <https://doc.softcom.cloud/openapi/clientes.json>
- Listar clientes: <https://doc.softcom.cloud/api-reference/clientes/listar-clientes.md>
- Financeiro do cliente: <https://doc.softcom.cloud/api-reference/clientes--financeiro/listar-financeiro-do-cliente.md>
- Compras: <https://doc.softcom.cloud/api-reference/clientes--compras/listar-compras.md>
- Abrir ticket: <https://doc.softcom.cloud/api-reference/tickets/abrir-ticket.md>
- Health check público: <https://api.softcom.cloud/health>
- SDK comunitário em PHP (referência de autenticação): <https://github.com/softcomtecnologia/softcom-api-php>
- Integração fiscal via SIEG (exige contato com o suporte Softcom): <https://integracoes.sieg.com/outros-sistemas/docs/softcom>
