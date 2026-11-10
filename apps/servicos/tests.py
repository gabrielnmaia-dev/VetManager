"""Testes de serviços, preços e orçamentos.

Cobrem cálculos no backend, limite de desconto, permissões, transições de
status, histórico, conversão em serviços realizados e idempotência.
"""

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
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

from .models import (
    CategoriaServico,
    HistoricoOrcamento,
    Orcamento,
    Servico,
    ServicoRealizado,
)

User = get_user_model()

URL_CATEGORIAS = "/api/v1/categorias-servico/"
URL_SERVICOS = "/api/v1/servicos/"
URL_ORCAMENTOS = "/api/v1/orcamentos/"
URL_REALIZADOS = "/api/v1/servicos-realizados/"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class BaseServicoTestCase(TestCase):
    def setUp(self):
        cache.clear()  # evita throttling acumulado entre testes
        self.admin = fazer_usuario("admin_serv", "admin")
        self.vet_user = fazer_usuario("vet_serv", "veterinario")
        self.rec = fazer_usuario("rec_serv", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.vet_user)

        self.tutor = Tutor.objects.create(
            nome="Tutor Serviço", telefone="11 99999-3000"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor Serviço", telefone="11 98888-3000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex", especie=self.especie
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.outro_tutor, nome="Mia", especie=self.especie
        )

        self.profissional = Profissional.objects.create(
            nome="Dra. Ana", cargo=Profissional.Cargo.VETERINARIO
        )
        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.profissional,
            nome_profissional=self.profissional.nome,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )
        self.atendimento_outro_pet = Atendimento.objects.create(
            pet=self.outro_pet,
            profissional=self.profissional,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )

        self.categoria = CategoriaServico.objects.create(nome="Consultas")
        self.servico = Servico.objects.create(
            nome="Consulta clínica",
            categoria=self.categoria,
            preco_base=Decimal("100.00"),
            duracao_estimada_minutos=30,
            permite_desconto=True,
            desconto_maximo_percentual=Decimal("10.00"),
        )
        self.servico_sem_desconto = Servico.objects.create(
            nome="Vacinação",
            categoria=self.categoria,
            preco_base=Decimal("50.00"),
            permite_desconto=False,
            desconto_maximo_percentual=Decimal("0.00"),
        )

    def tearDown(self):
        cache.clear()

    def dados_orcamento(self, **extras):
        dados = {
            "tutor": str(self.tutor.pk),
            "pet": str(self.pet.pk),
            "atendimento": str(self.atendimento.pk),
            "profissional": str(self.profissional.pk),
            "validade": (timezone.localdate() + timedelta(days=10)).isoformat(),
            "itens": [
                {
                    "servico": str(self.servico.pk),
                    "quantidade": "2",
                    "valor_unitario": "100.00",
                    "desconto": "10.00",
                },
                {
                    "servico": str(self.servico_sem_desconto.pk),
                    "quantidade": "1",
                    "valor_unitario": "50.00",
                },
            ],
        }
        dados.update(extras)
        return dados

    def criar_orcamento(self, **extras):
        resposta = self.client.post(
            URL_ORCAMENTOS, self.dados_orcamento(**extras), format="json"
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        return resposta.data


class CatalogoServicoTests(BaseServicoTestCase):
    def test_recepcao_consulta_mas_nao_cria_servico(self):
        self.client.force_authenticate(self.rec)
        resposta = self.client.get(URL_SERVICOS)
        self.assertEqual(resposta.status_code, 200)

        resposta = self.client.post(
            URL_SERVICOS,
            {
                "nome": "Banho",
                "categoria": str(self.categoria.pk),
                "preco_base": "70.00",
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_veterinario_cria_servico_e_duplicidade_e_bloqueada(self):
        resposta = self.client.post(
            URL_SERVICOS,
            {
                "nome": "Banho medicamentoso",
                "categoria": str(self.categoria.pk),
                "preco_base": "80.00",
                "duracao_estimada_minutos": 45,
                "situacao": "ativo",
                "regras": "Avaliação prévia do animal.",
                "permite_desconto": True,
                "desconto_maximo_percentual": "5.00",
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(resposta.data["preco_base"], "80.00")

        duplicado = self.client.post(
            URL_SERVICOS,
            {
                "nome": "banho MEDICAMENTOSO",
                "categoria": str(self.categoria.pk),
                "preco_base": "80.00",
            },
            format="json",
        )
        self.assertEqual(duplicado.status_code, 400)
        self.assertIn("nome", duplicado.data)

    def test_preco_negativo_e_desconto_invalido_sao_rejeitados(self):
        resposta = self.client.post(
            URL_SERVICOS,
            {
                "nome": "Serviço inválido",
                "categoria": str(self.categoria.pk),
                "preco_base": "-1.00",
                "desconto_maximo_percentual": "120.00",
            },
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("preco_base", resposta.data)

    def test_categoria_duplicada_e_rejeitada(self):
        resposta = self.client.post(
            URL_CATEGORIAS,
            {"nome": "consultas"},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("nome", resposta.data)


class ServicoRealizadoTests(BaseServicoTestCase):
    def payload(self, **extras):
        dados = {
            "atendimento": str(self.atendimento.pk),
            "pet": str(self.pet.pk),
            "servico": str(self.servico.pk),
            "profissional": str(self.profissional.pk),
            "quantidade": "2",
            "valor_unitario": "100.00",
            "desconto": "10.00",
            "chave_idempotencia": "servico-realizado-1",
        }
        dados.update(extras)
        return dados

    def test_calcula_total_no_backend(self):
        resposta = self.client.post(URL_REALIZADOS, self.payload(), format="json")
        self.assertEqual(resposta.status_code, 201, resposta.data)
        self.assertEqual(Decimal(resposta.data["valor_total"]), Decimal("190.00"))
        self.assertEqual(
            resposta.data["desconto_autorizado_por_nome"], self.vet_user.username
        )
        registro = ServicoRealizado.objects.get(pk=resposta.data["id"])
        self.assertEqual(registro.valor_total, Decimal("190.00"))
        self.assertTrue(
            AuditLog.objects.filter(
                entidade="servicos.servicorealizado",
                entidade_id=str(registro.pk),
            ).exists()
        )

    def test_desconto_acima_do_limite_exige_admin_e_motivo(self):
        # 10,5% em um serviço com limite de 10% (base de 200,00).
        resposta = self.client.post(
            URL_REALIZADOS,
            self.payload(
                desconto="21.00",
                chave_idempotencia="servico-realizado-limite",
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("desconto", resposta.data)

        self.client.force_authenticate(self.admin)
        sem_motivo = self.client.post(
            URL_REALIZADOS,
            self.payload(
                desconto="21.00",
                chave_idempotencia="servico-realizado-admin-1",
            ),
            format="json",
        )
        self.assertEqual(sem_motivo.status_code, 400)
        self.assertIn("desconto_motivo", sem_motivo.data)

        com_motivo = self.client.post(
            URL_REALIZADOS,
            self.payload(
                desconto="21.00",
                desconto_motivo="Cortesia autorizada pela direção.",
                chave_idempotencia="servico-realizado-admin-2",
            ),
            format="json",
        )
        self.assertEqual(com_motivo.status_code, 201, com_motivo.data)
        self.assertEqual(
            Decimal(com_motivo.data["valor_total"]), Decimal("179.00")
        )

    def test_servico_sem_desconto_rejeita_desconto(self):
        resposta = self.client.post(
            URL_REALIZADOS,
            self.payload(
                servico=str(self.servico_sem_desconto.pk),
                valor_unitario="50.00",
                quantidade="1",
                desconto="5.00",
                chave_idempotencia="servico-sem-desconto",
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("desconto", resposta.data)

    def test_atendimento_de_outro_animal_e_rejeitado(self):
        resposta = self.client.post(
            URL_REALIZADOS,
            self.payload(
                atendimento=str(self.atendimento_outro_pet.pk),
                chave_idempotencia="servico-outro-pet",
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("atendimento", resposta.data)

    def test_recepcao_nao_registra_servico_realizado(self):
        self.client.force_authenticate(self.rec)
        resposta = self.client.post(
            URL_REALIZADOS,
            self.payload(chave_idempotencia="servico-rec"),
            format="json",
        )
        self.assertEqual(resposta.status_code, 403)

    def test_idempotencia_nao_duplica_registro(self):
        primeira = self.client.post(URL_REALIZADOS, self.payload(), format="json")
        segunda = self.client.post(URL_REALIZADOS, self.payload(), format="json")
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(
            ServicoRealizado.objects.filter(
                chave_idempotencia="servico-realizado-1"
            ).count(),
            1,
        )

    def test_filtro_por_data(self):
        self.client.post(URL_REALIZADOS, self.payload(), format="json")
        hoje = timezone.localdate().isoformat()
        resposta = self.client.get(
            URL_REALIZADOS, {"data_inicio": hoje, "data_fim": hoje}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["count"], 1)


class OrcamentoTests(BaseServicoTestCase):
    def test_calcula_totais_e_registra_historico(self):
        orcamento = self.criar_orcamento()
        self.assertEqual(Decimal(orcamento["subtotal"]), Decimal("250.00"))
        self.assertEqual(Decimal(orcamento["valor_desconto"]), Decimal("10.00"))
        self.assertEqual(Decimal(orcamento["valor_total"]), Decimal("240.00"))
        self.assertEqual(orcamento["status"], "rascunho")
        self.assertEqual(orcamento["itens_count"], 2)

        historico = HistoricoOrcamento.objects.filter(
            orcamento_id=orcamento["id"]
        )
        self.assertEqual(historico.count(), 1)
        self.assertEqual(historico.first().status_novo, "rascunho")

    def test_item_repetido_e_rejeitado(self):
        dados = self.dados_orcamento()
        dados["itens"] = [
            {
                "servico": str(self.servico.pk),
                "quantidade": "1",
                "valor_unitario": "100.00",
            },
            {
                "servico": str(self.servico.pk),
                "quantidade": "1",
                "valor_unitario": "100.00",
            },
        ]
        resposta = self.client.post(URL_ORCAMENTOS, dados, format="json")
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("itens", resposta.data)

    def test_validade_no_passado_e_rejeitada(self):
        resposta = self.client.post(
            URL_ORCAMENTOS,
            self.dados_orcamento(
                validade=(timezone.localdate() - timedelta(days=1)).isoformat()
            ),
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("validade", resposta.data)

    def test_aprovacao_registra_status_e_historico(self):
        orcamento = self.criar_orcamento()
        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["status"], "aprovado")
        self.assertIsNotNone(resposta.data["aprovado_em"])
        historico = HistoricoOrcamento.objects.filter(
            orcamento_id=orcamento["id"]
        ).order_by("created_at")
        self.assertEqual(historico.count(), 2)
        self.assertEqual(historico.last().status_novo, "aprovado")
        self.assertEqual(historico.last().usuario, self.vet_user)

    def test_recusa_exige_motivo_e_registra(self):
        orcamento = self.criar_orcamento()
        sem_motivo = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/recusar/", {}, format="json"
        )
        self.assertEqual(sem_motivo.status_code, 400)

        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/recusar/",
            {"motivo": "Valor acima do esperado."},
            format="json",
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["status"], "recusado")
        self.assertEqual(
            resposta.data["motivo_recusa"], "Valor acima do esperado."
        )

    def test_orcamento_aprovado_nao_pode_ser_editado(self):
        orcamento = self.criar_orcamento()
        self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        resposta = self.client.patch(
            f"{URL_ORCAMENTOS}{orcamento['id']}/",
            {"observacoes": "Tentativa de alteração."},
            format="json",
        )
        self.assertEqual(resposta.status_code, 400)

    def test_orcamento_vencido_nao_pode_ser_aprovado(self):
        orcamento = self.criar_orcamento()
        Orcamento.objects.filter(pk=orcamento["id"]).update(
            validade=timezone.localdate() - timedelta(days=1)
        )
        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("validade", resposta.data)

    def test_recepcao_cria_e_aprova_mas_nao_converte(self):
        self.client.force_authenticate(self.rec)
        orcamento = self.criar_orcamento()
        aprovado = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        self.assertEqual(aprovado.status_code, 200, aprovado.data)

        conversao = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/", {}, format="json"
        )
        self.assertEqual(conversao.status_code, 403)

    def test_conversao_cria_servicos_realizados_e_e_idempotente(self):
        orcamento = self.criar_orcamento()
        self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/", {}, format="json"
        )
        self.assertEqual(resposta.status_code, 200, resposta.data)
        self.assertEqual(resposta.data["status"], "convertido")
        self.assertEqual(
            ServicoRealizado.objects.filter(
                orcamento_item__orcamento_id=orcamento["id"]
            ).count(),
            2,
        )
        realizados = ServicoRealizado.objects.filter(
            orcamento_item__orcamento_id=orcamento["id"]
        ).order_by("created_at")
        valores = sorted(registro.valor_total for registro in realizados)
        self.assertEqual(valores, [Decimal("50.00"), Decimal("190.00")])

        repetida = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/", {}, format="json"
        )
        self.assertEqual(repetida.status_code, 200)
        self.assertEqual(
            ServicoRealizado.objects.filter(
                orcamento_item__orcamento_id=orcamento["id"]
            ).count(),
            2,
        )

    def test_conversao_sem_atendimento_falha(self):
        orcamento = self.criar_orcamento(atendimento=None)
        self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/", {}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)
        self.assertIn("atendimento", resposta.data)

        com_atendimento = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/",
            {"atendimento": str(self.atendimento.pk)},
            format="json",
        )
        self.assertEqual(com_atendimento.status_code, 200, com_atendimento.data)

    def test_conversao_de_orcamento_nao_aprovado_falha(self):
        orcamento = self.criar_orcamento()
        resposta = self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/converter/", {}, format="json"
        )
        self.assertEqual(resposta.status_code, 400)

    def test_historico_endpoint_lista_transicoes(self):
        orcamento = self.criar_orcamento()
        self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/enviar/", {}, format="json"
        )
        self.client.post(
            f"{URL_ORCAMENTOS}{orcamento['id']}/aprovar/", {}, format="json"
        )
        resposta = self.client.get(
            f"{URL_ORCAMENTOS}{orcamento['id']}/historico/"
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.data), 3)
        self.assertEqual(
            [item["status_novo"] for item in resposta.data],
            ["rascunho", "enviado", "aprovado"],
        )

    def test_idempotencia_nao_duplica_orcamento(self):
        dados = self.dados_orcamento(chave_idempotencia="orcamento-unico")
        primeira = self.client.post(URL_ORCAMENTOS, dados, format="json")
        segunda = self.client.post(URL_ORCAMENTOS, dados, format="json")
        self.assertEqual(primeira.status_code, 201)
        self.assertEqual(segunda.status_code, 201)
        self.assertEqual(primeira.data["id"], segunda.data["id"])
        self.assertEqual(
            Orcamento.objects.filter(
                chave_idempotencia="orcamento-unico"
            ).count(),
            1,
        )
