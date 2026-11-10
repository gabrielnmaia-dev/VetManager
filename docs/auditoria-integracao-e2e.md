# Auditoria de integração ponta a ponta e relatório (Prompt 24)

**Status:** relatório de auditoria apenas.  
**NÃO** foram implementadas novas funcionalidades nem integrações externas sem autorização.  
Este documento audita os pontos de integração existentes do VetManager e aponta lacunas, riscos e recomendações.

---

## 1. Escopo da auditoria

Foram auditadas as integrações ponta a ponta dos seguintes domínios:

| Domínio | Implementado? | Fonte |
|---------|---------------|-------|
| Autenticação interna (JWT, cookies, refresh, logout) | Sim | `apps.accounts` |
| Autenticação do portal do tutor (cookies próprias, claim `tipo="portal"`) | Sim | `apps.portal` |
| Convites e vínculo User–Tutor do portal | Sim | `apps.portal` |
| Recuperação/redefinição de senha (portal) | Sim | `apps.portal` |
| Solicitação de agendamento pelo portal (não cria `Atendimento`) | Sim | `apps.portal` + `SolicitacaoAgendamento` |
| Documentos, prescrições e vacinas liberadas no portal | Sim | flag `liberado_portal` |
| Financeiro: contas a receber, parcelas, pagamentos, caixa | Sim | `apps.financeiro` |
| Catálogo de serviços, orçamentos, serviços realizados | Sim | `apps.servicos` |
| Prontuário, vacinas, vermifugações | Sim | `apps.prontuario` |
| Estoque, movimentações, lotes | Sim | `apps.estoque` |
| Auditoria (snapshots de criação/atualização/exclusão) | Sim | `apps.auditoria` |
| Integração externa Softcom | Não (apenas descoberta) | `docs/integracoes/softcom-descoberta.md` |
| E-mail de recuperação/notificações | Não implementado (referenciado) | — |

---

## 2. Auditoria ponta a ponta por domínio

### 2.1 Autenticação interna

**Fluxo verificado:**
1. `POST /api/v1/token/` valida credenciais e define cookies `access`/`refresh` (httpOnly).
2. `POST /api/v1/token/refresh/` rotaciona o refresh token (o anterior entra na blacklist).
3. `POST /api/v1/token/logout/` revoga o refresh token da sessão.
4. `JWTCookieAuthentication` recusa tokens com claim `tipo="portal"` (o portal não abre a API interna).
5. CSRF double-submit exigido em operações que alteram estado quando o token vem do cookie.

**Resultado:** fluxo completo e coerente. Testes de backend cobrem login, refresh, logout e revogação (483 testes passando).

### 2.2 Portal do tutor (isolado)

**Fluxo verificado:**
1. Convite gerado internamente (apenas a clínica pode convidar) — tutor não se vincula arbitrariamente.
2. `POST /api/v1/portal/convites/resgatar/` cria o usuário do tutor com aceite obrigatório da política de privacidade.
3. `POST /api/v1/portal/auth/login/` define cookies `portal_access`/`portal_refresh` (nomes distintos dos internos).
4. `PortalJWTCookieAuthentication` exige claim `tipo="portal"` e sessão não revogada.
5. O tutor só enxerga seus próprios pets, agendamentos, notificações e documentos com `liberado_portal`.
6. Solicitação de agendamento cria `SolicitacaoAgendamento` pendente, nunca um `Atendimento` direto.
7. Refresh token com rotação, revogação por sessão e blacklist.

**Resultado:** isolamento por objeto funcionando; a API interna rejeita tokens de portal e vice-versa. Testes do portal cobrem login, autenticação, rotas protegidas e pets.

### 2.3 Financeiro

**Fluxo verificado:**
1. Uma conta a receber tem parcelas; um pagamento pode cobrir várias parcelas via `AplicacaoPagamento`.
2. Estorno não apaga o pagamento (gera nova movimentação, histórico imutável).
3. Caixa aberto recebe entradas automaticamente; ajustes de caixa restritos a admin.
4. Formas de pagamento padrão criadas por migration de dados e configuráveis por admin.
5. Painéis: `/financeiro`, `/financeiro/contas`, `/financeiro/caixa`, `/financeiro/relatorios`.

**Resultado:** integridade transacional e idempotência respeitadas. Testes de backend cobrem financeiro (30 testes).

### 2.4 Catálogo de serviços e orçamentos

**Fluxo verificado:**
1. Serviço tem preço e desconto; desconto acima do limite exige admin + motivo.
2. Orçamento: aprovação/recusa/histórico/conversão; conversão só para admin/veterinário; recepção pode criar/aprovar/recusar.
3. Conversão de orçamento gera serviço realizado e consome estoque; cancelamento devolve estoque.

**Resultado:** coerente com as regras de negócio. Testes de backend cobrem serviços (24 testes) e orçamento está dentro do financeiro.

### 2.5 Auditoria

**Fluxo verificado:**
1. `AuditModelViewSetMixin` registra criação/atualização/exclusão com usuário, justificativa e snapshot.
2. Campos sensíveis (`observacoes`, `prescricao`) são excluídos do snapshot padrão (`audit_exclude`).
3. Soft delete mantém histórico imutável; restauração e hard delete são possíveis.

**Resultado:** trilha de auditoria presente nos apps que herdam o mixin. Testes de backend cobrem base (soft delete, autoria).

---

## 3. Integrações externas — status

### Softcom (descoberta apenas)

Conforme `docs/integracoes/softcom-descoberta.md`:
- Fase 1 (descoberta) e Fase 2 (relatório) concluídas.
- Fase 3 (implementação) **não iniciada**: ausência de confirmação do produto/base contratado e de credenciais de homologação autorizadas.
- A documentação pública da `api-agenda` parece pertencer à retaguarda de suporte da Softcom, não ao ERP veterinário da clínica. Não há endpoints para pets, prontuário, agenda veterinária, estoque ou emissão fiscal.
- **Não implementar integração com Softcom sem confirmação do produto/base e credenciais autorizadas.** Usar mocks/homologação, nunca dados reais.

### E-mail (recuperação de senha)

O fluxo de recuperação de senha do portal gera um token de uso único, mas o envio por e-mail depende de um provedor de e-mail ainda não configurado. Até que seja configurado, o token é gerado mas não entregue automaticamente.

---

## 4. Lacunas e riscos identificados

| # | Lacuna / risco | Severidade | Recomendação |
|---|----------------|------------|--------------|
| 1 | Integração Softcom não implementada (sem credenciais autorizadas) | Alta | Aguardar confirmação do produto/base; implementar somente em homologação com mocks |
| 2 | Envio de e-mail de recuperação não configurado | Média | Configurar SMTP/serviço de e-mail; testar entrega em homologação |
| 3 | Nenhum webhook consumido (Softcom ou outro) | Baixa | Se houver integração futura, validar assinatura de webhook e idempotência |
| 4 | Backup de arquivos clínicos (`media/`) depende do container web estar up | Média | Garantir que o volume de media seja incluído no backup e restaurado junto com o banco |

---

## 5. Evidências de teste

- Backend: 483 testes passando (4 ignorados), banco SQLite, `core.settings.test`, `makemigrations --check --dry-run` OK.
- Frontend: 33 testes passando (Vitest + Testing Library + jsdom), `npm run lint` OK, `npm run build` OK.
- CI: workflows `.github/workflows/ci.yml` em ambos os repositórios (checks, migrations, testes, lint, build).
- Testes de isolamento do portal: tokens de portal vs. interna são rejeitados mutuamente.

---

## 6. Conclusão

As integrações internas (autenticação, portal do tutor, financeiro, catálogo, orçamentos, prontuário, estoque e auditoria) estão implementadas e cobertas por testes automatizados, com isolamento por objeto respeitado.

A única integração externa mapeada (Softcom) está na fase de descoberta e **não deve ser implementada** sem confirmação do produto/base da clínica e credenciais de homologação autorizadas, conforme o previsto no Prompt 19.

Não foram implementadas novas funcionalidades sem autorização neste relatório.
