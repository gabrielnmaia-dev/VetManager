"""Testes da internação veterinária (admissão, ocupação, evolução e alta)."""

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
from apps.documentos.models import DocumentoClinico, TipoDocumento
from apps.estoque import services as estoque_services
from apps.estoque.models import (
    CategoriaProduto,
    Lote,
    MovimentacaoEstoque,
    Produto,
)
from apps.pets.models import Especie, Pet
from apps.prescricao.models import ItemPrescricao, Prescricao
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

from . import services
from .models import (
    AdministracaoMedicamentoInternacao,
    CuidadoInternacao,
    EvolucaoInternacao,
    Internacao,
    Leito,
    OcupacaoLeito,
)

User = get_user_model()

URL_LEITOS = "/api/v1/leitos/"
URL_INTERNACOES = "/api/v1/internacoes/"
URL_OCUPACOES = "/api/v1/ocupacoes-leito/"
URL_EVOLUCOES = "/api/v1/evolucoes-internacao/"
URL_CUIDADOS = "/api/v1/cuidados-internacao/"
URL_ADMINISTRACOES = "/api/v1/administracoes-internacao/"
URL_CENTRAL = "/api/v1/internacao/central/"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


def categoria_produto(tipo, nome):
    categoria = CategoriaProduto.objects.filter(tipo=tipo).first()
    if categoria is None:
        categoria = CategoriaProduto.objects.create(nome=nome, tipo=tipo)
    return categoria


class BaseInternacaoTestCase(TestCase):
    def setUp(self):
        cache.clear()  # evita throttling acumulado entre testes
        self.admin = fazer_usuario("admin_intern", "admin")
        self.vet_user = fazer_usuario("vet_intern", "veterinario")
        self.rec = fazer_usuario("rec_intern", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.vet_user)

        self.tutor = Tutor.objects.create(
            nome="Tutor Internação", telefone="11 99999-2000"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor Internação", telefone="11 98888-2000"
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
        self.outro_profissional = Profissional.objects.create(
            nome="Dr. Bruno", cargo=Profissional.Cargo.VETERINARIO
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional, crmv="CRMV-INT-1"
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
            nome_profissional=self.profissional.nome,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )

        self.leito = Leito.objects.create(
            nome="Leito 01", tipo=Leito.Tipo.CLINICO, capacidade=1
        )
        self.leito2 = Leito.objects.create(
            nome="Leito 02", tipo=Leito.Tipo.CLINICO, capacidade=1
        )

        categoria = categoria_produto(
            CategoriaProduto.Tipo.MEDICAMENTO, "Medicamentos"
        )
        self.produto = Produto.objects.create(
            nome="Dipirona 500 mg/ml",
            categoria=categoria,
            codigo_interno="MED-INT-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.ML,
            principio_ativo="Dipirona sódica",
            concentracao="500 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
        )
        self.lote = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-INT-1",
            quantidade_inicial=Decimal("20"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )

        self.prescricao = Prescricao.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            atendimento=self.atendimento,
        )
        self.item = ItemPrescricao.objects.create(
            prescricao=self.prescricao,
            produto=self.produto,
            dose="1 ml",
            frequencia="12h",
            duracao="3 dias",
            quantidade_prescrita=Decimal("10"),
        )

    def tearDown(self):
        cache.clear()  # não deixa o throttle da internação vazar para outros apps

    # --- helpers ---------------------------------------------------------

    def payload_admissao(self, **extra):
        dados = {
            "pet": str(self.pet.id),
            "atendimento_origem": str(self.atendimento.id),
            "leito": str(self.leito.id),
            "profissional_responsavel": str(self.profissional.id),
            "motivo_internacao": "Desidratação e anorexia",
            "diagnostico_inicial": "Gastroenterite",
            "estado_clinico": Internacao.EstadoClinico.GRAVE,
            "observacoes": "Paciente agitado",
        }
        dados.update(extra)
        return dados

    def admitir(self, **extra):
        resp = self.client.post(
            URL_INTERNACOES, self.payload_admissao(**extra), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return Internacao.objects.get(pk=resp.data["id"])

    def dar_alta(self, internacao, **extra):
        dados = {
            "profissional_alta": str(self.profissional.id),
            "condicao_alta": "Estável",
            "orientacoes_tutor": "Retornar em 7 dias",
            "resumo_internacao": "Evoluiu bem",
        }
        dados.update(extra)
        return self.client.post(
            f"{URL_INTERNACOES}{internacao.pk}/alta/", dados, format="json"
        )


class AdmissaoTests(BaseInternacaoTestCase):
    def test_admissao_cria_internacao_e_ocupa_leito(self):
        internacao = self.admitir(chave_idempotencia="adm-1")

        self.assertEqual(internacao.status, Internacao.Status.INTERNADO)
        self.assertEqual(internacao.leito, self.leito)
        self.assertEqual(internacao.pet, self.pet)
        self.assertEqual(internacao.created_by, self.vet_user)
        self.assertTrue(internacao.ativa)

        ocupacao = OcupacaoLeito.objects.get(internacao=internacao)
        self.assertEqual(ocupacao.leito, self.leito)
        self.assertIsNone(ocupacao.data_saida)
        self.assertEqual(self.leito.ocupados, 1)
        self.assertFalse(self.leito.disponivel)

        log = AuditLog.objects.filter(
            entidade__endswith="internacao", acao=AuditLog.Acao.CRIACAO
        ).first()
        self.assertIsNotNone(log)

    def test_impede_duas_internacoes_ativas_do_mesmo_animal(self):
        self.admitir()
        resp = self.client.post(
            URL_INTERNACOES,
            self.payload_admissao(leito=str(self.leito2.id)),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("pet", resp.data)

    def test_impede_admissao_em_leito_lotado(self):
        self.admitir()
        resp = self.client.post(
            URL_INTERNACOES,
            self.payload_admissao(
                pet=str(self.outro_pet.id),
                atendimento_origem=str(self.atendimento_outro_pet.id),
                leito=str(self.leito.id),
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("leito", resp.data)

    def test_leito_com_capacidade_dois_aceita_segundo_paciente(self):
        self.leito.capacidade = 2
        self.leito.save(update_fields=["capacidade"])
        self.admitir()
        resp = self.client.post(
            URL_INTERNACOES,
            self.payload_admissao(
                pet=str(self.outro_pet.id),
                atendimento_origem=str(self.atendimento_outro_pet.id),
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(self.leito.ocupados, 2)
        self.assertFalse(self.leito.disponivel)

    def test_atendimento_de_outro_animal_e_rejeitado(self):
        resp = self.client.post(
            URL_INTERNACOES,
            self.payload_admissao(
                atendimento_origem=str(self.atendimento_outro_pet.id)
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("atendimento_origem", resp.data)

    def test_chave_de_idempotencia_nao_duplica_admissao(self):
        internacao = self.admitir(chave_idempotencia="adm-idem")
        resp = self.client.post(
            URL_INTERNACOES,
            self.payload_admissao(
                chave_idempotencia="adm-idem", leito=str(self.leito2.id)
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["id"], str(internacao.id))
        self.assertEqual(Internacao.objects.count(), 1)
        self.assertEqual(OcupacaoLeito.objects.count(), 1)

    def test_leito_inativo_nao_recebe_internacao(self):
        self.leito.situacao = Leito.Situacao.MANUTENCAO
        self.leito.save(update_fields=["situacao"])
        resp = self.client.post(
            URL_INTERNACOES, self.payload_admissao(), format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("leito", resp.data)

    def test_recepcao_pode_listar_mas_nao_admitir(self):
        self.client.force_authenticate(self.rec)
        self.assertEqual(
            self.client.get(URL_INTERNACOES).status_code, 200
        )
        resp = self.client.post(
            URL_INTERNACOES, self.payload_admissao(), format="json"
        )
        self.assertEqual(resp.status_code, 403, resp.data)

    def test_atualizacao_nao_altera_leito_diretamente(self):
        internacao = self.admitir()
        resp = self.client.patch(
            f"{URL_INTERNACOES}{internacao.pk}/",
            {"leito": str(self.leito2.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("leito", resp.data)

    def test_atualizacao_de_estado_clinico(self):
        internacao = self.admitir()
        resp = self.client.patch(
            f"{URL_INTERNACOES}{internacao.pk}/",
            {"estado_clinico": Internacao.EstadoClinico.ESTAVEL},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        internacao.refresh_from_db()
        self.assertEqual(
            internacao.estado_clinico, Internacao.EstadoClinico.ESTAVEL
        )


class LeitoTests(BaseInternacaoTestCase):
    def test_cadastro_e_disponibilidade_de_leito(self):
        resp = self.client.post(
            URL_LEITOS,
            {
                "nome": "Leito UTI 01",
                "tipo": Leito.Tipo.UTI,
                "capacidade": 1,
                "situacao": Leito.Situacao.ATIVO,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertTrue(resp.data["disponivel"])
        self.assertEqual(resp.data["situacao_operacional"], "disponivel")
        self.assertEqual(resp.data["ocupados"], 0)

    def test_endpoint_disponiveis_exclui_leito_ocupado(self):
        self.admitir()
        resp = self.client.get(f"{URL_LEITOS}disponiveis/")
        self.assertEqual(resp.status_code, 200, resp.data)
        nomes = [leito["nome"] for leito in resp.data["results"]]
        self.assertNotIn(self.leito.nome, nomes)
        self.assertIn(self.leito2.nome, nomes)

    def test_historico_de_ocupacao_do_leito(self):
        internacao = self.admitir()
        self.dar_alta(internacao)
        resp = self.client.get(f"{URL_LEITOS}{self.leito.pk}/historico/")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(len(resp.data), 1)
        self.assertIsNotNone(resp.data[0]["data_saida"])

    def test_recepcao_nao_cadastra_leito(self):
        self.client.force_authenticate(self.rec)
        resp = self.client.post(
            URL_LEITOS, {"nome": "Leito X", "capacidade": 1}, format="json"
        )
        self.assertEqual(resp.status_code, 403, resp.data)


class TransferenciaTests(BaseInternacaoTestCase):
    def test_transferencia_encerra_ocupacao_e_abre_outra(self):
        internacao = self.admitir()
        resp = self.client.post(
            f"{URL_INTERNACOES}{internacao.pk}/transferir/",
            {"novo_leito": str(self.leito2.id), "motivo": "Necessidade de UTI"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        internacao.refresh_from_db()
        self.assertEqual(internacao.leito, self.leito2)
        antiga = OcupacaoLeito.objects.get(
            internacao=internacao, leito=self.leito
        )
        nova = OcupacaoLeito.objects.get(
            internacao=internacao, leito=self.leito2
        )
        self.assertIsNotNone(antiga.data_saida)
        self.assertEqual(antiga.motivo_saida, "Necessidade de UTI")
        self.assertIsNone(nova.data_saida)
        self.assertEqual(self.leito.ocupados, 0)
        self.assertEqual(self.leito2.ocupados, 1)
        self.assertTrue(self.leito.disponivel)

    def test_transferencia_para_leito_lotado_falha(self):
        internacao = self.admitir()
        outro = Internacao.objects.create(
            pet=self.outro_pet,
            leito=self.leito2,
            profissional_responsavel=self.profissional,
            motivo_internacao="Observação",
        )
        OcupacaoLeito.objects.create(
            internacao=outro, leito=self.leito2, data_entrada=timezone.now()
        )
        resp = self.client.post(
            f"{URL_INTERNACOES}{internacao.pk}/transferir/",
            {"novo_leito": str(self.leito2.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("leito", resp.data)

    def test_transferencia_para_mesmo_leito_falha(self):
        internacao = self.admitir()
        resp = self.client.post(
            f"{URL_INTERNACOES}{internacao.pk}/transferir/",
            {"novo_leito": str(self.leito.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_historico_de_ocupacao_mantem_duas_etapas(self):
        internacao = self.admitir()
        self.client.post(
            f"{URL_INTERNACOES}{internacao.pk}/transferir/",
            {"novo_leito": str(self.leito2.id)},
            format="json",
        )
        resp = self.client.get(
            URL_OCUPACOES, {"internacao": str(internacao.pk)}
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["count"], 2)


class EvolucaoTests(BaseInternacaoTestCase):
    def payload_evolucao(self, internacao, **extra):
        dados = {
            "internacao": str(internacao.id),
            "profissional": str(self.profissional.id),
            "evolucao_clinica": "Paciente mais ativo e hidratado.",
            "observacoes": "Aceitou alimentação",
            "intercorrencias": "Nenhuma",
            "temperatura": "38.5",
            "frequencia_cardiaca": 110,
            "frequencia_respiratoria": 30,
            "saturacao": 98,
            "peso": "12.40",
        }
        dados.update(extra)
        return dados

    def test_registra_evolucao_com_sinais_vitais(self):
        internacao = self.admitir()
        resp = self.client.post(
            URL_EVOLUCOES,
            self.payload_evolucao(internacao),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        evolucao = EvolucaoInternacao.objects.get(pk=resp.data["id"])
        self.assertEqual(evolucao.internacao, internacao)
        self.assertEqual(evolucao.created_by, self.vet_user)
        self.assertEqual(evolucao.temperatura, Decimal("38.5"))
        self.assertEqual(evolucao.saturacao, 98)

    def test_evolucao_nao_sobrescreve_anterior(self):
        internacao = self.admitir()
        primeira = self.client.post(
            URL_EVOLUCOES,
            self.payload_evolucao(internacao, evolucao_clinica="Primeira"),
            format="json",
        ).data
        segunda = self.client.post(
            URL_EVOLUCOES,
            self.payload_evolucao(internacao, evolucao_clinica="Segunda"),
            format="json",
        ).data
        self.assertNotEqual(primeira["id"], segunda["id"])
        self.assertEqual(
            EvolucaoInternacao.objects.filter(internacao=internacao).count(), 2
        )
        antiga = EvolucaoInternacao.objects.get(pk=primeira["id"])
        self.assertEqual(antiga.evolucao_clinica, "Primeira")

    def test_evolucao_nao_pode_ser_editada_nem_excluida(self):
        internacao = self.admitir()
        criada = self.client.post(
            URL_EVOLUCOES, self.payload_evolucao(internacao), format="json"
        ).data
        url = f"{URL_EVOLUCOES}{criada['id']}/"
        self.assertEqual(
            self.client.patch(url, {"evolucao_clinica": "x"}, format="json").status_code,
            405,
        )
        self.assertEqual(self.client.delete(url).status_code, 405)

    def test_saturacao_invalida_e_rejeitada(self):
        internacao = self.admitir()
        resp = self.client.post(
            URL_EVOLUCOES,
            self.payload_evolucao(internacao, saturacao=150),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("saturacao", resp.data)

    def test_internacao_encerrada_nao_recebe_evolucao(self):
        internacao = self.admitir()
        self.dar_alta(internacao)
        resp = self.client.post(
            URL_EVOLUCOES, self.payload_evolucao(internacao), format="json"
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_listagem_por_internacao(self):
        internacao = self.admitir()
        self.client.post(
            URL_EVOLUCOES, self.payload_evolucao(internacao), format="json"
        )
        resp = self.client.get(
            URL_EVOLUCOES, {"internacao": str(internacao.pk)}
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["count"], 1)


class CuidadoTests(BaseInternacaoTestCase):
    def test_registra_cuidados_de_rotina(self):
        internacao = self.admitir()
        for tipo in (
            CuidadoInternacao.Tipo.ALIMENTACAO,
            CuidadoInternacao.Tipo.HIDRATACAO,
            CuidadoInternacao.Tipo.MONITORAMENTO,
            CuidadoInternacao.Tipo.ENFERMAGEM,
        ):
            resp = self.client.post(
                URL_CUIDADOS,
                {
                    "internacao": str(internacao.id),
                    "tipo": tipo,
                    "descricao": f"Cuidado {tipo}",
                    "profissional": str(self.profissional.id),
                },
                format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            CuidadoInternacao.objects.filter(internacao=internacao).count(), 4
        )

    def test_tipo_de_cuidado_invalido_e_rejeitado(self):
        internacao = self.admitir()
        resp = self.client.post(
            URL_CUIDADOS,
            {
                "internacao": str(internacao.id),
                "tipo": "cirurgia",
                "descricao": "x",
                "profissional": str(self.profissional.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_cuidado_nao_pode_ser_editado(self):
        internacao = self.admitir()
        criada = self.client.post(
            URL_CUIDADOS,
            {
                "internacao": str(internacao.id),
                "tipo": CuidadoInternacao.Tipo.ALIMENTACAO,
                "descricao": "Ração úmida",
                "profissional": str(self.profissional.id),
            },
            format="json",
        ).data
        url = f"{URL_CUIDADOS}{criada['id']}/"
        self.assertEqual(
            self.client.patch(url, {"descricao": "x"}, format="json").status_code,
            405,
        )
        self.assertEqual(self.client.delete(url).status_code, 405)


class AdministracaoTests(BaseInternacaoTestCase):
    def payload_administracao(self, internacao, **extra):
        dados = {
            "internacao": str(internacao.id),
            "item_prescricao": str(self.item.id),
            "lote": str(self.lote.id),
            "profissional": str(self.profissional.id),
            "quantidade": "2",
            "observacoes": "Administrado sem intercorrências",
            "chave_idempotencia": "adm-med-1",
        }
        dados.update(extra)
        return dados

    def test_administracao_baixa_estoque_e_registra_autoria(self):
        internacao = self.admitir()
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        administracao = AdministracaoMedicamentoInternacao.objects.get(
            pk=resp.data["id"]
        )
        self.assertEqual(administracao.status, AdministracaoMedicamentoInternacao.Status.ATIVA)
        self.assertEqual(administracao.pet, self.pet)
        self.assertEqual(administracao.prescricao, self.prescricao)
        self.assertEqual(administracao.dose, "1 ml")
        self.assertEqual(administracao.created_by, self.vet_user)

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("18.000"))
        movimentacao = administracao.movimentacao
        self.assertEqual(
            movimentacao.tipo, MovimentacaoEstoque.Tipo.CONSUMO_CLINICO
        )
        self.assertEqual(movimentacao.quantidade, Decimal("2.000"))
        self.assertEqual(movimentacao.saldo_posterior, Decimal("18.000"))
        self.assertEqual(movimentacao.created_by, self.vet_user)

    def test_administracao_idempotente_nao_baixa_duas_vezes(self):
        internacao = self.admitir()
        self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        )
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(
            AdministracaoMedicamentoInternacao.objects.count(), 1
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("18.000"))

    def test_cancelamento_devolve_estoque_e_preserva_historico(self):
        internacao = self.admitir()
        criada = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        ).data
        resp = self.client.post(
            f"{URL_ADMINISTRACOES}{criada['id']}/cancelar/",
            {"motivo": "Medicamento derramado"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        administracao = AdministracaoMedicamentoInternacao.objects.get(
            pk=criada["id"]
        )
        self.assertEqual(
            administracao.status,
            AdministracaoMedicamentoInternacao.Status.CANCELADA,
        )
        self.assertIsNotNone(administracao.movimentacao)
        self.assertIsNotNone(administracao.estorno_movimentacao)
        self.assertEqual(administracao.cancelada_por, self.vet_user)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("20.000"))

        resp = self.client.post(
            f"{URL_ADMINISTRACOES}{criada['id']}/cancelar/",
            {"motivo": "Duplicado"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_cancelamento_exige_motivo(self):
        internacao = self.admitir()
        criada = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        ).data
        resp = self.client.post(
            f"{URL_ADMINISTRACOES}{criada['id']}/cancelar/",
            {"motivo": ""},
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_produto_comercial_nao_pode_ser_administrado(self):
        categoria = categoria_produto(
            CategoriaProduto.Tipo.COMERCIAL, "Comercial"
        )
        produto = Produto.objects.create(
            nome="Ração",
            categoria=categoria,
            codigo_interno="COM-INT-1",
            tipo_estoque=Produto.TipoEstoque.COMERCIAL,
            unidade_medida=Produto.UnidadeMedida.PACOTE,
        )
        lote = estoque_services.criar_lote(
            produto=produto,
            numero_lote="LOTE-COM-INT",
            quantidade_inicial=Decimal("5"),
            data_validade=timezone.localdate() + timedelta(days=90),
            usuario=self.admin,
        )
        internacao = self.admitir()
        resp = self.client.post(
            URL_ADMINISTRACOES,
            {
                "internacao": str(internacao.id),
                "produto": str(produto.id),
                "lote": str(lote.id),
                "profissional": str(self.profissional.id),
                "quantidade": "1",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("produto", resp.data)

    def test_item_de_prescricao_de_outro_animal_e_rejeitado(self):
        internacao = self.admitir()
        outra_prescricao = Prescricao.objects.create(
            pet=self.outro_pet,
            veterinario=self.veterinario,
        )
        item = ItemPrescricao.objects.create(
            prescricao=outra_prescricao,
            produto=self.produto,
            dose="0,5 ml",
            quantidade_prescrita=Decimal("3"),
        )
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(
                internacao, item_prescricao=str(item.id)
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("item_prescricao", resp.data)

    def test_administracao_em_internacao_encerrada_falha(self):
        internacao = self.admitir()
        self.dar_alta(internacao)
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(internacao),
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)


class AltaTests(BaseInternacaoTestCase):
    def test_alta_encerra_internacao_e_libera_leito(self):
        internacao = self.admitir()
        resp = self.dar_alta(
            internacao,
            prescricoes=[str(self.prescricao.id)],
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        internacao.refresh_from_db()
        self.assertEqual(internacao.status, Internacao.Status.ALTA)
        self.assertIsNotNone(internacao.data_hora_alta)
        self.assertEqual(internacao.profissional_alta, self.profissional)
        self.assertEqual(internacao.condicao_alta, "Estável")
        self.assertEqual(internacao.orientacoes_tutor, "Retornar em 7 dias")
        self.assertEqual(internacao.resumo_internacao, "Evoluiu bem")
        self.assertEqual(
            list(internacao.prescricoes.all()), [self.prescricao]
        )

        self.assertFalse(
            OcupacaoLeito.objects.filter(
                internacao=internacao, data_saida__isnull=True
            ).exists()
        )
        self.assertEqual(self.leito.ocupados, 0)
        self.assertTrue(self.leito.disponivel)

    def test_alta_associa_documentos_do_mesmo_animal(self):
        internacao = self.admitir()
        documento = DocumentoClinico.objects.create(
            pet=self.pet,
            tipo=TipoDocumento.OUTRO,
            nome_original="alta.pdf",
            nome_interno="interno-alta.pdf",
            caminho_arquivo="documentos/interno-alta.pdf",
            tamanho=123,
        )
        resp = self.dar_alta(internacao, documentos=[str(documento.id)])
        self.assertEqual(resp.status_code, 200, resp.data)
        internacao.refresh_from_db()
        self.assertEqual(list(internacao.documentos.all()), [documento])

    def test_alta_com_prescricao_de_outro_animal_falha(self):
        internacao = self.admitir()
        outra = Prescricao.objects.create(
            pet=self.outro_pet, veterinario=self.veterinario
        )
        resp = self.dar_alta(internacao, prescricoes=[str(outra.id)])
        self.assertEqual(resp.status_code, 400, resp.data)
        self.assertIn("prescricoes", resp.data)

    def test_nao_permite_alta_duplicada(self):
        internacao = self.admitir()
        self.assertEqual(self.dar_alta(internacao).status_code, 200)
        resp = self.dar_alta(internacao)
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_nao_permite_evolucao_apos_alta(self):
        internacao = self.admitir()
        self.dar_alta(internacao)
        resp = self.client.post(
            URL_EVOLUCOES,
            {
                "internacao": str(internacao.id),
                "profissional": str(self.profissional.id),
                "evolucao_clinica": "Tarde",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400, resp.data)

    def test_recepcao_nao_registra_alta(self):
        internacao = self.admitir()
        self.client.force_authenticate(self.rec)
        resp = self.dar_alta(internacao)
        self.assertEqual(resp.status_code, 403, resp.data)


class CentralTests(BaseInternacaoTestCase):
    def test_central_agrega_leitos_internados_e_pendencias(self):
        internacao = self.admitir()
        resp = self.client.get(URL_CENTRAL)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data["resumo"]["internados"], 1)
        self.assertEqual(resp.data["resumo"]["leitos_ocupados"], 1)
        self.assertEqual(
            [item["id"] for item in resp.data["internados"]],
            [str(internacao.id)],
        )
        self.assertEqual(len(resp.data["prescricoes_pendentes"]), 1)
        pendente = resp.data["prescricoes_pendentes"][0]["itens"][0]
        self.assertEqual(pendente["quantidade_pendente"], "10.000")

    def test_central_reflete_administracao_e_alta(self):
        internacao = self.admitir()
        self.client.post(
            URL_ADMINISTRACOES,
            {
                "internacao": str(internacao.id),
                "item_prescricao": str(self.item.id),
                "lote": str(self.lote.id),
                "profissional": str(self.profissional.id),
                "quantidade": "4",
            },
            format="json",
        )
        resp = self.client.get(URL_CENTRAL)
        pendente = resp.data["prescricoes_pendentes"][0]["itens"][0]
        self.assertEqual(pendente["quantidade_pendente"], "6.000")
        self.assertEqual(len(resp.data["administracoes_hoje"]), 1)

        self.dar_alta(internacao)
        resp = self.client.get(URL_CENTRAL)
        self.assertEqual(resp.data["resumo"]["internados"], 0)
        self.assertEqual(resp.data["resumo"]["leitos_ocupados"], 0)
        self.assertTrue(resp.data["leitos"][0]["disponivel"])

    def test_central_exige_autenticacao(self):
        self.client.force_authenticate(None)
        resp = self.client.get(URL_CENTRAL)
        self.assertIn(resp.status_code, (401, 403))


class ServicoTests(BaseInternacaoTestCase):
    def test_servico_rejeita_leito_ausente(self):
        with self.assertRaises(Exception):
            services.admitir_paciente(
                pet=self.pet,
                leito=None,
                profissional_responsavel=self.profissional,
                motivo_internacao="Teste",
            )

    def test_idempotencia_transferencia_e_alta_no_servico(self):
        internacao, criada = services.admitir_paciente(
            pet=self.pet,
            leito=self.leito,
            profissional_responsavel=self.profissional,
            motivo_internacao="Teste",
            chave_idempotencia="svc-1",
            usuario=self.vet_user,
        )
        self.assertTrue(criada)
        repetida, criada = services.admitir_paciente(
            pet=self.pet,
            leito=self.leito2,
            profissional_responsavel=self.profissional,
            motivo_internacao="Teste",
            chave_idempotencia="svc-1",
            usuario=self.vet_user,
        )
        self.assertFalse(criada)
        self.assertEqual(repetida.pk, internacao.pk)

        services.transferir_internacao(
            internacao_id=internacao.pk,
            novo_leito=self.leito2,
            usuario=self.vet_user,
        )
        internacao.refresh_from_db()
        self.assertEqual(internacao.leito, self.leito2)

        services.dar_alta(
            internacao_id=internacao.pk,
            profissional_alta=self.outro_profissional,
            usuario=self.vet_user,
        )
        internacao.refresh_from_db()
        self.assertEqual(internacao.status, Internacao.Status.ALTA)
        self.assertEqual(
            internacao.profissional_alta, self.outro_profissional
        )
