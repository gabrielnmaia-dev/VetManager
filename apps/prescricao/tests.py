"""Testes da integração prescrição ↔ estoque clínico."""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest import skipIf

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.atendimentos.models import Atendimento
from apps.auditoria.models import AuditLog
from apps.estoque import services as estoque_services
from apps.estoque.models import (
    CategoriaProduto,
    Lote,
    MovimentacaoEstoque,
    Produto,
)
from apps.pets.models import Especie, Pet
from apps.prontuario.models import Prontuario
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

from . import services
from .models import (
    AdministracaoMedicamento,
    ItemPrescricao,
    Prescricao,
)

User = get_user_model()

URL_PRESCRICOES = "/api/v1/prescricoes/"
URL_ADMINISTRACOES = "/api/v1/administracoes-medicamento/"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class BasePrescricaoTestCase(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_presc", "admin")
        self.vet_user = fazer_usuario("vet_presc", "veterinario")
        self.rec = fazer_usuario("rec_presc", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.vet_user)

        self.tutor = Tutor.objects.create(
            nome="Tutor Prescrição", telefone="11 99999-0000"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor", telefone="11 98888-0000"
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
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional,
            crmv="CRMV-PRESC-1",
            especialidade="Clínica",
        )
        self.outro_profissional = Profissional.objects.create(
            nome="Dr. Bruno", cargo=Profissional.Cargo.VETERINARIO
        )
        self.outro_veterinario = Veterinario.objects.create(
            profissional=self.outro_profissional,
            crmv="CRMV-PRESC-2",
        )

        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.profissional,
            nome_profissional=self.profissional.nome,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )
        self.prontuario = Prontuario.objects.create(
            atendimento=self.atendimento,
            pet=self.pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
            diagnostico="Otite",
        )
        self.prontuario_outro_pet = Prontuario.objects.create(
            pet=self.outro_pet,
            veterinario=self.veterinario,
            data_consulta=timezone.now(),
            diagnostico="Dermatite",
        )

        self.cat_medicamento = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.MEDICAMENTO
        )
        self.cat_material = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.MATERIAL_CLINICO
        )
        self.produto = Produto.objects.create(
            nome="Dipirona 500 mg/ml",
            categoria=self.cat_medicamento,
            codigo_interno="MED-PRESC-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.ML,
            principio_ativo="Dipirona sódica",
            concentracao="500 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
            estoque_minimo=Decimal("5"),
        )
        self.produto_material = Produto.objects.create(
            nome="Seringa 5 ml",
            categoria=self.cat_material,
            codigo_interno="MAT-PRESC-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.UNIDADE,
        )
        self.lote = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-PRESC-1",
            quantidade_inicial=Decimal("20"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )
        self.lote_vencido = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-VENCIDO",
            quantidade_inicial=Decimal("5"),
            data_validade=timezone.localdate() - timedelta(days=1),
            usuario=self.admin,
        )
        self.lote_material = estoque_services.criar_lote(
            produto=self.produto_material,
            numero_lote="LOTE-MAT-1",
            quantidade_inicial=Decimal("10"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )

        self.prescricao = Prescricao.objects.create(
            prontuario=self.prontuario,
            atendimento=self.atendimento,
            pet=self.pet,
            veterinario=self.veterinario,
            data_prescricao=timezone.now(),
            created_by=self.vet_user,
        )
        self.item = ItemPrescricao.objects.create(
            prescricao=self.prescricao,
            produto=self.produto,
            dose="1 ml",
            via="oral",
            frequencia="8/8h",
            duracao="5 dias",
            quantidade_prescrita=Decimal("10"),
            created_by=self.vet_user,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def payload_prescricao(self, **extra):
        dados = {
            "prontuario": str(self.prontuario.id),
            "pet": str(self.pet.id),
            "veterinario": str(self.veterinario.id),
            "atendimento": str(self.atendimento.id),
            "observacoes": "Prescrição de teste",
            "itens": [
                {
                    "produto": str(self.produto.id),
                    "dose": "1 ml",
                    "via": "oral",
                    "frequencia": "8/8h",
                    "duracao": "5 dias",
                    "quantidade_prescrita": "10",
                }
            ],
        }
        dados.update(extra)
        return dados

    def payload_administracao(self, **extra):
        dados = {
            "item_prescricao": str(self.item.id),
            "lote": str(self.lote.id),
            "quantidade": "2",
            "chave_idempotencia": "adm-teste-1",
        }
        dados.update(extra)
        return dados

    def criar_administracao(self, **extra):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(**extra),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return AdministracaoMedicamento.objects.get(pk=resp.data["id"])


class PrescricaoTests(BasePrescricaoTestCase):
    def test_prescricao_criada_nao_movimenta_estoque(self):
        antes = MovimentacaoEstoque.objects.count()
        saldo_antes = self.lote.quantidade_atual

        resp = self.client.post(
            URL_PRESCRICOES, self.payload_prescricao(), format="json"
        )

        self.assertEqual(resp.status_code, 201, resp.data)
        prescricao = Prescricao.objects.get(pk=resp.data["id"])
        self.assertEqual(prescricao.status, Prescricao.Status.ATIVA)
        self.assertEqual(prescricao.itens.count(), 1)
        self.assertEqual(MovimentacaoEstoque.objects.count(), antes)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, saldo_antes)

    def test_prescricao_sem_itens_retorna_erro(self):
        resp = self.client.post(
            URL_PRESCRICOES,
            self.payload_prescricao(itens=[]),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("itens", resp.data)

    def test_prescricao_exige_medicamento_do_catalogo(self):
        dados = self.payload_prescricao()
        dados["itens"][0]["produto"] = str(self.produto_material.id)
        resp = self.client.post(URL_PRESCRICOES, dados, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("itens", resp.data)
        self.assertFalse(
            Prescricao.objects.filter(observacoes="Prescrição de teste").exists()
        )

    def test_prescricao_com_prontuario_de_outro_animal_retorna_erro(self):
        resp = self.client.post(
            URL_PRESCRICOES,
            self.payload_prescricao(prontuario=str(self.prontuario_outro_pet.id)),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("prontuario", resp.data)

    def test_recepcao_pode_listar_mas_nao_criar_prescricao(self):
        self.client.force_authenticate(self.rec)
        resp = self.client.get(URL_PRESCRICOES)
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            URL_PRESCRICOES, self.payload_prescricao(), format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_usuario_anonimo_nao_acessa_prescricoes(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(URL_PRESCRICOES)
        self.assertEqual(resp.status_code, 401)


class AdministracaoTests(BasePrescricaoTestCase):
    def test_administracao_gera_consumo_clinico_e_baixa(self):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        administracao = AdministracaoMedicamento.objects.get(pk=resp.data["id"])
        self.assertIsNotNone(administracao.movimentacao_id)
        self.assertEqual(administracao.pet_id, self.pet.id)
        self.assertEqual(administracao.produto_id, self.produto.id)
        self.assertEqual(administracao.lote_id, self.lote.id)
        self.assertEqual(administracao.prescricao_id, self.prescricao.id)
        self.assertEqual(administracao.profissional_id, self.profissional.id)
        self.assertEqual(administracao.atendimento_id, self.atendimento.id)
        self.assertEqual(administracao.dose, "1 ml")
        self.assertEqual(administracao.via, "oral")

        mov = administracao.movimentacao
        self.assertEqual(mov.tipo, MovimentacaoEstoque.Tipo.CONSUMO_CLINICO)
        self.assertEqual(mov.quantidade, Decimal("2"))
        self.assertEqual(mov.saldo_anterior, Decimal("20"))
        self.assertEqual(mov.saldo_posterior, Decimal("18"))
        self.assertEqual(mov.atendimento_id, self.atendimento.id)

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("18"))

    def test_consumo_sem_prescricao_vinculado_ao_atendimento(self):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            {
                "pet": str(self.pet.id),
                "produto": str(self.produto.id),
                "lote": str(self.lote.id),
                "atendimento": str(self.atendimento.id),
                "profissional": str(self.profissional.id),
                "quantidade": "1.5",
                "dose": "1,5 ml",
                "via": "intramuscular",
                "chave_idempotencia": "consumo-avulso",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        administracao = AdministracaoMedicamento.objects.get(pk=resp.data["id"])
        self.assertIsNone(administracao.item_prescricao_id)
        self.assertIsNone(administracao.prescricao_id)
        self.assertEqual(administracao.quantidade, Decimal("1.500"))
        self.assertEqual(
            administracao.movimentacao.tipo,
            MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        )

    def test_administracao_sem_saldo_nao_persiste_nada(self):
        antes = AdministracaoMedicamento.objects.count()
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(quantidade="999", chave_idempotencia="sem-saldo"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AdministracaoMedicamento.objects.count(), antes)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("20"))

    def test_administracao_com_lote_vencido_nao_baixa(self):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(
                lote=str(self.lote_vencido.id),
                chave_idempotencia="lote-vencido",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.lote_vencido.refresh_from_db()
        self.assertEqual(self.lote_vencido.quantidade_atual, Decimal("5"))
        self.assertFalse(
            AdministracaoMedicamento.objects.filter(
                chave_idempotencia="lote-vencido"
            ).exists()
        )

    def test_administracao_com_lote_de_outro_produto_retorna_erro(self):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(
                lote=str(self.lote_material.id),
                chave_idempotencia="lote-divergente",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("lote", resp.data)

    def test_administracao_com_pet_divergente_retorna_erro(self):
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(
                pet=str(self.outro_pet.id),
                chave_idempotencia="pet-divergente",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("pet", resp.data)

    def test_chave_idempotente_nao_duplica_administracao_nem_movimentacao(self):
        resp1 = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(chave_idempotencia="idempotente-1"),
            format="json",
        )
        resp2 = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(chave_idempotencia="idempotente-1"),
            format="json",
        )
        self.assertEqual(resp1.status_code, 201, resp1.data)
        self.assertEqual(resp2.status_code, 201, resp2.data)
        self.assertEqual(resp1.data["id"], resp2.data["id"])
        self.assertEqual(
            AdministracaoMedicamento.objects.filter(
                chave_idempotencia="idempotente-1"
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entidade="prescricao.administracaomedicamento",
                entidade_id=resp1.data["id"],
                acao=AuditLog.Acao.CRIACAO,
            ).count(),
            1,
        )
        self.assertEqual(
            MovimentacaoEstoque.objects.filter(
                tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO
            ).count(),
            1,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("18"))

    def test_chave_idempotente_unica_no_banco(self):
        administracao = self.criar_administracao(chave_idempotencia="unica-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AdministracaoMedicamento.objects.create(
                    pet=self.pet,
                    produto=self.produto,
                    lote=self.lote,
                    profissional=self.profissional,
                    quantidade=Decimal("1"),
                    chave_idempotencia=administracao.chave_idempotencia,
                )

    def test_recepcao_pode_listar_mas_nao_administrar(self):
        self.criar_administracao(chave_idempotencia="listar-recepcao")
        self.client.force_authenticate(self.rec)
        resp = self.client.get(URL_ADMINISTRACOES)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(chave_idempotencia="recepcao"),
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class EstornoTests(BasePrescricaoTestCase):
    def test_cancelamento_gera_devolucao_e_preserva_historico(self):
        administracao = self.criar_administracao(chave_idempotencia="estorno-1")
        mov_original = administracao.movimentacao

        resp = self.client.post(
            f"{URL_ADMINISTRACOES}{administracao.id}/cancelar/",
            {"motivo": "Dose registrada em duplicidade"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        administracao.refresh_from_db()
        self.assertEqual(
            administracao.status, AdministracaoMedicamento.Status.CANCELADA
        )
        self.assertEqual(
            administracao.motivo_cancelamento, "Dose registrada em duplicidade"
        )
        self.assertIsNotNone(administracao.estorno_movimentacao_id)
        self.assertIsNotNone(administracao.cancelada_em)
        self.assertEqual(administracao.cancelada_por_id, self.vet_user.id)

        # A movimentação original continua existindo e imutável.
        self.assertTrue(
            MovimentacaoEstoque.objects.filter(pk=mov_original.pk).exists()
        )
        estorno = administracao.estorno_movimentacao
        self.assertEqual(estorno.tipo, MovimentacaoEstoque.Tipo.DEVOLUCAO)
        self.assertEqual(estorno.quantidade, Decimal("2"))
        self.assertEqual(estorno.direcao, MovimentacaoEstoque.Direcao.ENTRADA)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("20"))

        auditorias = AuditLog.objects.filter(
            entidade="prescricao.administracaomedicamento",
            entidade_id=str(administracao.id),
        )
        self.assertTrue(
            auditorias.filter(acao=AuditLog.Acao.CRIACAO).exists()
        )
        self.assertTrue(
            auditorias.filter(
                acao=AuditLog.Acao.ATUALIZACAO,
                justificativa="Dose registrada em duplicidade",
            ).exists()
        )

    def test_cancelamento_exige_motivo(self):
        administracao = self.criar_administracao(chave_idempotencia="estorno-sem-motivo")
        resp = self.client.post(
            f"{URL_ADMINISTRACOES}{administracao.id}/cancelar/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("motivo", resp.data)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("18"))

    def test_cancelamento_duplicado_nao_estorna_duas_vezes(self):
        administracao = self.criar_administracao(chave_idempotencia="estorno-duplo")
        for _ in range(2):
            resp = self.client.post(
                f"{URL_ADMINISTRACOES}{administracao.id}/cancelar/",
                {"motivo": "Teste de duplicidade"},
                format="json",
            )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            MovimentacaoEstoque.objects.filter(
                tipo=MovimentacaoEstoque.Tipo.DEVOLUCAO
            ).count(),
            1,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("20"))

    def test_prescricao_cancelada_bloqueia_nova_administracao(self):
        resp = self.client.post(
            f"{URL_PRESCRICOES}{self.prescricao.id}/cancelar/",
            {"motivo": "Prescrição substituída"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        resp = self.client.post(
            URL_ADMINISTRACOES,
            self.payload_administracao(chave_idempotencia="presc-cancelada"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("item_prescricao", resp.data)

    def test_prescricao_com_administracao_ativa_nao_pode_ser_cancelada(self):
        self.criar_administracao(chave_idempotencia="bloqueia-cancelamento")
        resp = self.client.post(
            f"{URL_PRESCRICOES}{self.prescricao.id}/cancelar/",
            {"motivo": "Tentativa de cancelamento"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.data)
        self.prescricao.refresh_from_db()
        self.assertEqual(self.prescricao.status, Prescricao.Status.ATIVA)

    def test_prescricao_cancelada_sem_administracao_nao_mexe_estoque(self):
        saldo_antes = self.lote.quantidade_atual
        resp = self.client.post(
            f"{URL_PRESCRICOES}{self.prescricao.id}/cancelar/",
            {"motivo": "Erro de digitação"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.prescricao.refresh_from_db()
        self.assertEqual(self.prescricao.status, Prescricao.Status.CANCELADA)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, saldo_antes)


class ServicoAdministracaoTests(BasePrescricaoTestCase):
    def test_servico_reaproveita_administracao_existente(self):
        primeira, criada = services.registrar_administracao(
            item_prescricao=self.item,
            lote=self.lote,
            quantidade=Decimal("1"),
            chave_idempotencia="servico-idempotente",
            usuario=self.vet_user,
        )
        self.assertTrue(criada)
        segunda, criada = services.registrar_administracao(
            item_prescricao=self.item,
            lote=self.lote,
            quantidade=Decimal("1"),
            chave_idempotencia="servico-idempotente",
            usuario=self.vet_user,
        )
        self.assertFalse(criada)
        self.assertEqual(primeira.pk, segunda.pk)
        self.assertEqual(
            MovimentacaoEstoque.objects.filter(
                tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO
            ).count(),
            1,
        )

    def test_servico_nao_permite_item_de_prescricao_cancelada(self):
        services.cancelar_prescricao(
            prescricao_id=self.prescricao.pk,
            motivo="Cancelada",
            usuario=self.vet_user,
        )
        with self.assertRaises(DRFValidationError):
            services.registrar_administracao(
                item_prescricao=self.item,
                lote=self.lote,
                quantidade=Decimal("1"),
                usuario=self.vet_user,
            )


@skipIf(
    connection.vendor == "sqlite",
    "Concorrência real é validada no PostgreSQL; SQLite serializa escritas.",
)
class ConcorrenciaAdministracaoTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.vet_user = fazer_usuario("vet_concorrencia", "veterinario")
        self.tutor = Tutor.objects.create(
            nome="Tutor Concorrência", telefone="11 97777-0000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Thor", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dra. Concorrência", cargo=Profissional.Cargo.VETERINARIO
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional, crmv="CRMV-CONC-1"
        )
        self.categoria = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.MEDICAMENTO
        )
        self.produto = Produto.objects.create(
            nome="Medicamento Concorrência",
            categoria=self.categoria,
            codigo_interno="MED-CONC-1",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.ML,
            principio_ativo="Teste",
            concentracao="1 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
        )
        self.lote = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-CONC-1",
            quantidade_inicial=Decimal("10"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.vet_user,
        )
        self.prescricao = Prescricao.objects.create(
            pet=self.pet,
            veterinario=self.veterinario,
            data_prescricao=timezone.now(),
        )
        self.item = ItemPrescricao.objects.create(
            prescricao=self.prescricao,
            produto=self.produto,
            dose="1 ml",
            quantidade_prescrita=Decimal("10"),
        )

    def _administrar(self, chave, barreira):
        close_old_connections()
        barreira.wait()
        try:
            administracao, criada = services.registrar_administracao(
                item_prescricao=ItemPrescricao.objects.get(pk=self.item.pk),
                lote=Lote.objects.get(pk=self.lote.pk),
                quantidade=Decimal("6"),
                chave_idempotencia=chave,
                usuario=self.vet_user,
            )
            return ("ok", administracao.pk, criada)
        except DRFValidationError as exc:
            return ("erro", exc.detail)
        finally:
            close_old_connections()

    def test_duas_administracoes_concorrentes_nao_deixam_saldo_negativo(self):
        barreira = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [
                executor.submit(self._administrar, chave, barreira)
                for chave in ("conc-1", "conc-2")
            ]
            resultados = [futuro.result() for futuro in futuros]

        self.assertEqual(
            sum(1 for resultado in resultados if resultado[0] == "erro"), 1
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("4"))
        self.assertEqual(
            MovimentacaoEstoque.objects.filter(
                tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO
            ).count(),
            1,
        )

    def test_duas_requisicoes_com_mesma_chave_criam_uma_administracao(self):
        barreira = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [
                executor.submit(self._administrar, "conc-mesma", barreira)
                for _ in range(2)
            ]
            resultados = [futuro.result() for futuro in futuros]

        ids = {resultado[1] for resultado in resultados if resultado[0] == "ok"}
        self.assertEqual(len(ids), 1)
        self.assertEqual(
            AdministracaoMedicamento.objects.filter(
                chave_idempotencia="conc-mesma"
            ).count(),
            1,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("4"))
