"""Testes do financeiro: contas, pagamentos, parcelamento, caixa e relatórios."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.atendimentos.models import Atendimento
from apps.auditoria.models import AuditLog
from apps.pets.models import Especie, Pet
from apps.servicos.models import CategoriaServico, Servico, ServicoRealizado
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

from .models import (
    Caixa,
    ContaReceber,
    FormaPagamento,
    HistoricoContaReceber,
    MovimentacaoCaixa,
    Pagamento,
    ParcelaContaReceber,
)

User = get_user_model()

URL_FORMAS = "/api/v1/formas-pagamento/"
URL_CONTAS = "/api/v1/contas-receber/"
URL_PARCELAS = "/api/v1/parcelas-conta-receber/"
URL_PAGAMENTOS = "/api/v1/pagamentos/"
URL_CAIXAS = "/api/v1/caixas/"
URL_MOVIMENTACOES = "/api/v1/movimentacoes-caixa/"
URL_DASHBOARD = "/api/v1/financeiro/dashboard/"
URL_RECEITA_PERIODO = "/api/v1/financeiro/receita-periodo/"
URL_RECEITA_SERVICO = "/api/v1/financeiro/receita-servico/"
URL_RECEBIMENTOS = "/api/v1/financeiro/recebimentos/"
URL_PENDENTES = "/api/v1/financeiro/contas-pendentes/"
URL_INADIMPLENCIA = "/api/v1/financeiro/inadimplencia/"
URL_FLUXO = "/api/v1/financeiro/fluxo-caixa/"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class BaseFinanceiroTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = fazer_usuario("admin_fin", "admin")
        self.vet = fazer_usuario("vet_fin", "veterinario")
        self.rec = fazer_usuario("rec_fin", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.rec)

        self.tutor = Tutor.objects.create(
            nome="Tutor Financeiro", telefone="11 97777-1000"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor Financeiro", telefone="11 97777-2000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Bolt", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dr. Caixa", cargo=Profissional.Cargo.VETERINARIO
        )
        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.profissional,
            nome_profissional=self.profissional.nome,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )

        self.dinheiro, _ = FormaPagamento.objects.get_or_create(
            nome="Dinheiro",
            defaults={"tipo": FormaPagamento.Tipo.DINHEIRO},
        )
        self.pix, _ = FormaPagamento.objects.get_or_create(
            nome="Pix", defaults={"tipo": FormaPagamento.Tipo.PIX}
        )

    def tearDown(self):
        cache.clear()

    def dados_conta(self, **extras):
        dados = {
            "tutor": str(self.tutor.pk),
            "atendimento": str(self.atendimento.pk),
            "descricao": "Consulta e exames",
            "valor": "100.00",
            "data_emissao": timezone.localdate().isoformat(),
            "vencimento": (timezone.localdate() + timedelta(days=10)).isoformat(),
            "numero_parcelas": 1,
        }
        dados.update(extras)
        return dados

    def criar_conta(self, **extras):
        resposta = self.client.post(URL_CONTAS, self.dados_conta(**extras), format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        return resposta.data

    def pagar(self, conta_id, valor, **extras):
        dados = {
            "conta": str(conta_id),
            "forma_pagamento": str(self.dinheiro.pk),
            "valor": valor,
        }
        chave = extras.pop("chave_idempotencia", None)
        if chave:
            dados["chave_idempotencia"] = chave
        dados.update(extras)
        return self.client.post(URL_PAGAMENTOS, dados, format="json")


class ContaReceberTests(BaseFinanceiroTestCase):
    def test_recepcao_cria_conta_e_parcelamento_divide_valor(self):
        conta = self.criar_conta(numero_parcelas=3)
        self.assertEqual(Decimal(conta["valor"]), Decimal("100.00"))
        self.assertEqual(Decimal(conta["saldo"]), Decimal("100.00"))
        self.assertEqual(conta["status"], "aberta")
        self.assertEqual(len(conta["parcelas"]), 3)
        valores = [Decimal(p["valor"]) for p in conta["parcelas"]]
        self.assertEqual(valores, [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])
        self.assertEqual(sum(valores), Decimal("100.00"))
        self.assertEqual(len(conta["historico"]), 1)
        self.assertTrue(
            AuditLog.objects.filter(
                entidade="financeiro.contareceber", entidade_id=str(conta["id"])
            ).exists()
        )

    def test_parcelas_entrada_precisam_somar_o_valor(self):
        resposta = self.client.post(
            URL_CONTAS,
            self.dados_conta(
                parcelas_entrada=[
                    {"vencimento": timezone.localdate().isoformat(), "valor": "40.00"},
                    {"vencimento": timezone.localdate().isoformat(), "valor": "50.00"},
                ]
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("parcelas_entrada", resposta.data)

    def test_veterinario_nao_cria_conta_mas_consulta(self):
        self.client.force_authenticate(self.vet)
        resposta = self.client.post(URL_CONTAS, self.dados_conta(), format="json")
        self.assertEqual(resposta.status_code, 403)
        consulta = self.client.get(URL_CONTAS)
        self.assertEqual(consulta.status_code, 200)

    def test_idempotencia_nao_duplica_conta(self):
        dados = self.dados_conta(chave_idempotencia="conta-unica-1")
        primeira = self.client.post(URL_CONTAS, dados, format="json")
        segunda = self.client.post(URL_CONTAS, dados, format="json")
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(
            ContaReceber.objects.filter(chave_idempotencia="conta-unica-1").count(), 1
        )

    def test_tutor_derivado_do_atendimento(self):
        resposta = self.client.post(
            URL_CONTAS,
            {
                "atendimento": str(self.atendimento.pk),
                "descricao": "Serviço avulso",
                "valor": "80.00",
                "vencimento": (timezone.localdate() + timedelta(days=5)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(str(resposta.data["tutor"]), str(self.tutor.pk))

    def test_cancelamento_bloqueado_com_pagamento_confirmado(self):
        conta = self.criar_conta()
        self.pagar(conta["id"], "10.00")
        self.client.force_authenticate(self.admin)
        resposta = self.client.post(
            f"{URL_CONTAS}{conta['id']}/cancelar/",
            {"motivo": "Duplicidade."},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)

        pagamento = Pagamento.objects.get(conta_id=conta["id"])
        self.client.post(
            f"{URL_PAGAMENTOS}{pagamento.pk}/estornar/",
            {"motivo": "Estorno para cancelar."},
            format="json",
        )
        cancelada = self.client.post(
            f"{URL_CONTAS}{conta['id']}/cancelar/",
            {"motivo": "Duplicidade."},
            format="json",
        )
        self.assertEqual(cancelada.status_code, 200, cancelada.data)
        self.assertEqual(cancelada.data["status"], "cancelada")
        self.assertEqual(Decimal(cancelada.data["saldo"]), Decimal("0.00"))

    def test_cancelamento_restrito_a_admin(self):
        conta = self.criar_conta()
        resposta = self.client.post(
            f"{URL_CONTAS}{conta['id']}/cancelar/", {"motivo": "Teste."}, format="json"
        )
        self.assertEqual(resposta.status_code, 403)

    def test_historico_endpoint_lista_eventos(self):
        conta = self.criar_conta()
        self.pagar(conta["id"], "30.00")
        resposta = self.client.get(f"{URL_CONTAS}{conta['id']}/historico/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.data), 2)
        self.assertEqual(
            [item["status_novo"] for item in resposta.data], ["aberta", "parcial"]
        )

    def test_filtro_status_vencida(self):
        conta = self.criar_conta(
            vencimento=(timezone.localdate() - timedelta(days=3)).isoformat()
        )
        resposta = self.client.get(URL_CONTAS, {"status": "vencida"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)
        self.assertEqual(resposta.data["results"][0]["id"], conta["id"])
        self.assertTrue(resposta.data["results"][0]["vencida"])


class PagamentoTests(BaseFinanceiroTestCase):
    def test_pagamento_parcial_e_total_atualiza_saldos(self):
        conta = self.criar_conta(numero_parcelas=2)
        parcial = self.pagar(conta["id"], "25.00")
        self.assertEqual(parcial.status_code, 201, parcial.data)
        atualizada = ContaReceber.objects.get(pk=conta["id"])
        self.assertEqual(atualizada.status, ContaReceber.Status.PARCIAL)
        self.assertEqual(atualizada.valor_pago, Decimal("25.00"))
        self.assertEqual(atualizada.saldo, Decimal("75.00"))
        primeira = atualizada.parcelas.order_by("numero").first()
        self.assertEqual(primeira.valor_pago, Decimal("25.00"))
        self.assertEqual(primeira.saldo, Decimal("25.00"))
        self.assertEqual(primeira.status, ParcelaContaReceber.Status.PARCIAL)

        total = self.pagar(conta["id"], "75.00")
        self.assertEqual(total.status_code, 201, total.data)
        quitada = ContaReceber.objects.get(pk=conta["id"])
        self.assertEqual(quitada.status, ContaReceber.Status.PAGA)
        self.assertEqual(quitada.saldo, Decimal("0.00"))
        self.assertEqual(quitada.valor_pago, Decimal("100.00"))
        self.assertEqual(
            quitada.parcelas.filter(status=ParcelaContaReceber.Status.PAGA).count(), 2
        )

    def test_pagamento_nao_pode_exceder_saldo(self):
        conta = self.criar_conta()
        resposta = self.pagar(conta["id"], "150.00")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("valor", resposta.data)
        self.assertEqual(Pagamento.objects.count(), 0)

    def test_pagamento_em_parcela_especifica(self):
        conta = self.criar_conta(numero_parcelas=2)
        parcelas = ParcelaContaReceber.objects.filter(conta_id=conta["id"]).order_by(
            "numero"
        )
        segunda = parcelas[1]
        resposta = self.pagar(conta["id"], "50.00", parcela=str(segunda.pk))
        self.assertEqual(resposta.status_code, 201, resposta.data)
        segunda.refresh_from_db()
        primeira = parcelas[0]
        primeira.refresh_from_db()
        self.assertEqual(segunda.valor_pago, Decimal("50.00"))
        self.assertEqual(primeira.valor_pago, Decimal("0.00"))

    def test_idempotencia_nao_duplica_pagamento(self):
        conta = self.criar_conta()
        primeira = self.pagar(
            conta["id"], "20.00", chave_idempotencia="pagamento-unico-1"
        )
        segunda = self.pagar(
            conta["id"], "20.00", chave_idempotencia="pagamento-unico-1"
        )
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(
            Pagamento.objects.filter(chave_idempotencia="pagamento-unico-1").count(), 1
        )
        conta_db = ContaReceber.objects.get(pk=conta["id"])
        self.assertEqual(conta_db.valor_pago, Decimal("20.00"))

    def test_estorno_preserva_pagamento_e_devolve_saldo(self):
        conta = self.criar_conta()
        pagamento = self.pagar(conta["id"], "40.00").data
        self.client.force_authenticate(self.admin)
        resposta = self.client.post(
            f"{URL_PAGAMENTOS}{pagamento['id']}/estornar/",
            {"motivo": "Cobrança indevida."},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["status"], "estornado")
        self.assertEqual(resposta.data["motivo_estorno"], "Cobrança indevida.")

        registro = Pagamento.objects.get(pk=pagamento["id"])
        self.assertEqual(registro.status, Pagamento.Status.ESTORNADO)
        self.assertIsNotNone(registro.estornado_em)
        conta_db = ContaReceber.objects.get(pk=conta["id"])
        self.assertEqual(conta_db.status, ContaReceber.Status.ABERTA)
        self.assertEqual(conta_db.saldo, Decimal("100.00"))
        self.assertTrue(
            HistoricoContaReceber.objects.filter(
                conta_id=conta["id"], status_novo="aberta"
            ).exists()
        )

        repetido = self.client.post(
            f"{URL_PAGAMENTOS}{pagamento['id']}/estornar/",
            {"motivo": "De novo."},
            format="json",
        )
        self.assertEqual(repetido.status_code, 400)

    def test_estorno_restrito_a_admin(self):
        conta = self.criar_conta()
        pagamento = self.pagar(conta["id"], "10.00").data
        resposta = self.client.post(
            f"{URL_PAGAMENTOS}{pagamento['id']}/estornar/",
            {"motivo": "Teste."},
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_veterinario_nao_registra_pagamento(self):
        conta = self.criar_conta()
        self.client.force_authenticate(self.vet)
        resposta = self.pagar(conta["id"], "10.00")
        self.assertEqual(resposta.status_code, 403)

    def test_pagamento_gera_entrada_automatica_no_caixa_aberto(self):
        caixa = self.client.post(
            URL_CAIXAS,
            {"descricao": "Caixa manhã", "valor_abertura": "50.00"},
            format="json",
        )
        self.assertEqual(caixa.status_code, 201, caixa.data)
        conta = self.criar_conta()
        pagamento = self.pagar(conta["id"], "30.00")
        self.assertEqual(pagamento.status_code, 201, pagamento.data)

        movimentacao = MovimentacaoCaixa.objects.get(pagamento_id=pagamento.data["id"])
        self.assertEqual(movimentacao.tipo, MovimentacaoCaixa.Tipo.ENTRADA)
        self.assertEqual(movimentacao.valor, Decimal("30.00"))
        self.assertEqual(str(movimentacao.caixa_id), str(caixa.data["id"]))

        resumo = self.client.get(f"{URL_CAIXAS}{caixa.data['id']}/")
        self.assertEqual(Decimal(resumo.data["resumo"]["saldo_sistema"]), Decimal("80.00"))


class CaixaTests(BaseFinanceiroTestCase):
    def abrir_caixa(self, **extras):
        dados = {"descricao": "Caixa teste", "valor_abertura": "100.00"}
        dados.update(extras)
        resposta = self.client.post(URL_CAIXAS, dados, format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        return resposta.data

    def test_nao_permite_dois_caixas_abertos(self):
        self.abrir_caixa()
        resposta = self.client.post(
            URL_CAIXAS,
            {"descricao": "Outro caixa", "valor_abertura": "0.00"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)

    def test_movimentacoes_e_fechamento_calculam_diferenca(self):
        caixa = self.abrir_caixa()
        entrada = self.client.post(
            URL_MOVIMENTACOES,
            {
                "caixa": caixa["id"],
                "tipo": "entrada",
                "valor": "200.00",
                "descricao": "Venda de balcão",
                "forma_pagamento": str(self.dinheiro.pk),
            },
            format="json",
        )
        self.assertEqual(entrada.status_code, 201, entrada.data)
        saida = self.client.post(
            URL_MOVIMENTACOES,
            {
                "caixa": caixa["id"],
                "tipo": "saida",
                "valor": "50.00",
                "descricao": "Compra de material",
            },
            format="json",
        )
        self.assertEqual(saida.status_code, 201, saida.data)

        detalhe = self.client.get(f"{URL_CAIXAS}{caixa['id']}/")
        self.assertEqual(Decimal(detalhe.data["resumo"]["saldo_sistema"]), Decimal("250.00"))

        fechamento = self.client.post(
            f"{URL_CAIXAS}{caixa['id']}/fechar/",
            {"valor_fechamento_informado": "245.00", "observacoes": "Faltou troco."},
            format="json",
        )
        self.assertEqual(fechamento.status_code, 200, fechamento.data)
        self.assertEqual(fechamento.data["status"], "fechado")
        self.assertEqual(Decimal(fechamento.data["valor_fechamento_sistema"]), Decimal("250.00"))
        self.assertEqual(Decimal(fechamento.data["diferenca"]), Decimal("-5.00"))

        repetido = self.client.post(
            f"{URL_CAIXAS}{caixa['id']}/fechar/",
            {"valor_fechamento_informado": "250.00"},
            format="json",
        )
        self.assertEqual(repetido.status_code, 400)

    def test_ajuste_restrito_a_admin(self):
        caixa = self.abrir_caixa()
        resposta = self.client.post(
            URL_MOVIMENTACOES,
            {
                "caixa": caixa["id"],
                "tipo": "ajuste",
                "valor": "-10.00",
                "descricao": "Correção de troco",
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

        self.client.force_authenticate(self.admin)
        ajuste = self.client.post(
            URL_MOVIMENTACOES,
            {
                "caixa": caixa["id"],
                "tipo": "ajuste",
                "valor": "-10.00",
                "descricao": "Correção de troco",
            },
            format="json",
        )
        self.assertEqual(ajuste.status_code, 201, ajuste.data)
        self.assertEqual(
            MovimentacaoCaixa.objects.get(pk=ajuste.data["id"]).valor,
            Decimal("-10.00"),
        )

    def test_movimentacao_bloqueada_em_caixa_fechado(self):
        caixa = self.abrir_caixa()
        self.client.post(
            f"{URL_CAIXAS}{caixa['id']}/fechar/",
            {"valor_fechamento_informado": "100.00"},
            format="json",
        )
        resposta = self.client.post(
            URL_MOVIMENTACOES,
            {
                "caixa": caixa["id"],
                "tipo": "entrada",
                "valor": "10.00",
                "descricao": "Tentativa",
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)

    def test_idempotencia_caixa(self):
        dados = {
            "descricao": "Caixa idempotente",
            "valor_abertura": "10.00",
            "chave_idempotencia": "caixa-unico-1",
        }
        primeira = self.client.post(URL_CAIXAS, dados, format="json")
        segunda = self.client.post(URL_CAIXAS, dados, format="json")
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(Caixa.objects.count(), 1)


class RelatorioFinanceiroTests(BaseFinanceiroTestCase):
    def setUp(self):
        super().setUp()
        self.caixa = Caixa.objects.create(
            descricao="Caixa relatórios",
            valor_abertura=Decimal("0.00"),
            status=Caixa.Status.ABERTO,
        )

    def test_dashboard_consolida_recebimentos_e_inadimplencia(self):
        paga = self.criar_conta(valor="60.00")
        self.pagar(paga["id"], "60.00")
        self.criar_conta(
            valor="40.00",
            descricao="Conta vencida",
            vencimento=(timezone.localdate() - timedelta(days=4)).isoformat(),
        )

        resposta = self.client.get(URL_DASHBOARD)
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(Decimal(resposta.data["recebido_mes"]["total"]), Decimal("60.00"))
        self.assertEqual(resposta.data["contas_abertas"]["quantidade"], 1)
        self.assertEqual(resposta.data["inadimplencia"]["quantidade"], 1)
        self.assertEqual(Decimal(resposta.data["inadimplencia"]["saldo"]), Decimal("40.00"))
        self.assertEqual(len(resposta.data["ultimos_pagamentos"]), 1)
        self.assertIsNotNone(resposta.data["caixa_aberto"])

    def test_receita_por_periodo_e_recebimentos_por_forma(self):
        conta = self.criar_conta(valor="90.00")
        self.pagar(conta["id"], "40.00")
        self.pagar(conta["id"], "50.00", forma_pagamento=str(self.pix.pk))

        hoje = timezone.localdate().isoformat()
        periodo = self.client.get(URL_RECEITA_PERIODO, {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(periodo.status_code, 200, periodo.data)
        self.assertEqual(Decimal(periodo.data["total"]), Decimal("90.00"))
        self.assertEqual(periodo.data["quantidade"], 2)

        formas = self.client.get(URL_RECEBIMENTOS, {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(formas.status_code, 200, formas.data)
        self.assertEqual(Decimal(formas.data["total"]), Decimal("90.00"))
        nomes = {linha["nome"]: Decimal(linha["total"]) for linha in formas.data["linhas"]}
        self.assertEqual(nomes["Dinheiro"], Decimal("40.00"))
        self.assertEqual(nomes["Pix"], Decimal("50.00"))

    def test_receita_por_servico(self):
        categoria = CategoriaServico.objects.create(nome="Consultas fin")
        servico = Servico.objects.create(
            nome="Consulta financeira", categoria=categoria, preco_base=Decimal("80.00")
        )
        ServicoRealizado.objects.create(
            atendimento=self.atendimento,
            pet=self.pet,
            servico=servico,
            profissional=self.profissional,
            quantidade=Decimal("1.000"),
            valor_unitario=Decimal("80.00"),
            valor_total=Decimal("80.00"),
            data_hora=timezone.now(),
        )
        resposta = self.client.get(URL_RECEITA_SERVICO)
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(Decimal(resposta.data["total"]), Decimal("80.00"))
        self.assertEqual(resposta.data["linhas"][0]["nome"], "Consulta financeira")

    def test_contas_pendentes_e_inadimplencia(self):
        self.criar_conta(valor="30.00", descricao="Pendente futura")
        self.criar_conta(
            valor="20.00",
            descricao="Pendente vencida",
            vencimento=(timezone.localdate() - timedelta(days=2)).isoformat(),
        )
        pendentes = self.client.get(URL_PENDENTES)
        self.assertEqual(pendentes.status_code, 200, pendentes.data)
        self.assertEqual(pendentes.data["quantidade"], 2)
        self.assertEqual(Decimal(pendentes.data["total"]), Decimal("50.00"))

        inadimplencia = self.client.get(URL_INADIMPLENCIA)
        self.assertEqual(inadimplencia.status_code, 200, inadimplencia.data)
        self.assertEqual(inadimplencia.data["quantidade"], 1)
        self.assertEqual(Decimal(inadimplencia.data["total"]), Decimal("20.00"))

    def test_fluxo_de_caixa(self):
        MovimentacaoCaixa.objects.create(
            caixa=self.caixa,
            tipo=MovimentacaoCaixa.Tipo.ENTRADA,
            valor=Decimal("100.00"),
            descricao="Entrada",
        )
        MovimentacaoCaixa.objects.create(
            caixa=self.caixa,
            tipo=MovimentacaoCaixa.Tipo.SAIDA,
            valor=Decimal("30.00"),
            descricao="Saída",
        )
        hoje = timezone.localdate().isoformat()
        resposta = self.client.get(URL_FLUXO, {"data_inicio": hoje, "data_fim": hoje})
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(Decimal(resposta.data["entradas"]), Decimal("100.00"))
        self.assertEqual(Decimal(resposta.data["saidas"]), Decimal("30.00"))
        self.assertEqual(Decimal(resposta.data["saldo"]), Decimal("70.00"))

    def test_relatorios_restritos_a_usuarios_autenticados_do_perfil(self):
        self.client.force_authenticate(None)
        resposta = self.client.get(URL_DASHBOARD)
        self.assertIn(resposta.status_code, (401, 403))


class FormaPagamentoTests(BaseFinanceiroTestCase):
    def test_formas_padrao_foram_carregadas(self):
        nomes = set(FormaPagamento.objects.values_list("nome", flat=True))
        self.assertIn("Dinheiro", nomes)
        self.assertIn("Pix", nomes)
        self.assertIn("Cartão de crédito", nomes)

    def test_somente_admin_configura_formas(self):
        resposta = self.client.post(
            URL_FORMAS,
            {"nome": "Cripto", "tipo": "outros"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

        self.client.force_authenticate(self.admin)
        criada = self.client.post(
            URL_FORMAS,
            {"nome": "Cripto", "tipo": "outros"},
            format="json",
        )
        self.assertEqual(criada.status_code, 201, criada.data)

        duplicada = self.client.post(
            URL_FORMAS,
            {"nome": "cripto", "tipo": "outros"},
            format="json",
        )
        self.assertEqual(duplicada.status_code, 400)
