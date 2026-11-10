"""Testes do catálogo e da execução de procedimentos."""

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
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional

from . import services
from .models import (
    CategoriaProcedimento,
    ExecucaoProcedimento,
    MaterialPrevistoProcedimento,
    MaterialUtilizadoProcedimento,
    Procedimento,
)

User = get_user_model()

URL_CATEGORIAS = "/api/v1/categorias-procedimento/"
URL_PROCEDIMENTOS = "/api/v1/procedimentos/"
URL_EXECUCOES = "/api/v1/execucoes-procedimento/"


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


class BaseProcedimentoTestCase(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_proc", "admin")
        self.vet_user = fazer_usuario("vet_proc", "veterinario")
        self.rec = fazer_usuario("rec_proc", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.vet_user)

        self.tutor = Tutor.objects.create(
            nome="Tutor Procedimento", telefone="11 99999-1000"
        )
        self.outro_tutor = Tutor.objects.create(
            nome="Outro Tutor", telefone="11 98888-1000"
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
        self.auxiliar = Profissional.objects.create(
            nome="João Auxiliar", cargo=Profissional.Cargo.OUTRO
        )
        self.outro_profissional = Profissional.objects.create(
            nome="Dr. Bruno", cargo=Profissional.Cargo.VETERINARIO
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

        self.cat_medicamento = categoria_produto(
            CategoriaProduto.Tipo.MEDICAMENTO, "Medicamentos"
        )
        self.cat_material = categoria_produto(
            CategoriaProduto.Tipo.MATERIAL_CLINICO, "Materiais clínicos"
        )
        self.cat_comercial = categoria_produto(
            CategoriaProduto.Tipo.COMERCIAL, "Comercial"
        )
        self.produto = Produto.objects.create(
            nome="Dipirona 500 mg/ml",
            categoria=self.cat_medicamento,
            codigo_interno="MED-PROC-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.ML,
            principio_ativo="Dipirona sódica",
            concentracao="500 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
        )
        self.produto_material = Produto.objects.create(
            nome="Seringa 5 ml",
            categoria=self.cat_material,
            codigo_interno="MAT-PROC-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.UNIDADE,
        )
        self.produto_comercial = Produto.objects.create(
            nome="Ração premium",
            categoria=self.cat_comercial,
            codigo_interno="COM-PROC-001",
            tipo_estoque=Produto.TipoEstoque.COMERCIAL,
            unidade_medida=Produto.UnidadeMedida.PACOTE,
        )
        self.lote = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-PROC-1",
            quantidade_inicial=Decimal("20"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )
        self.lote_material = estoque_services.criar_lote(
            produto=self.produto_material,
            numero_lote="LOTE-MAT-PROC-1",
            quantidade_inicial=Decimal("10"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )
        self.lote_vencido = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-PROC-VENCIDO",
            quantidade_inicial=Decimal("5"),
            data_validade=timezone.localdate() - timedelta(days=1),
            usuario=self.admin,
        )
        self.lote_comercial = estoque_services.criar_lote(
            produto=self.produto_comercial,
            numero_lote="LOTE-COM-PROC-1",
            quantidade_inicial=Decimal("5"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.admin,
        )

        self.categoria = CategoriaProcedimento.objects.create(
            nome="Exames", descricao="Exames ambulatoriais"
        )
        self.procedimento = Procedimento.objects.create(
            nome="Ultrassonografia abdominal",
            categoria=self.categoria,
            tipo=Procedimento.Tipo.CLINICO,
            descricao="Avaliação abdominal",
            duracao_estimada_minutos=30,
        )
        MaterialPrevistoProcedimento.objects.create(
            procedimento=self.procedimento,
            produto=self.produto_material,
            quantidade_prevista=Decimal("1"),
        )

    def payload_procedimento(self, **extra):
        dados = {
            "nome": "Curativo simples",
            "categoria": str(self.categoria.id),
            "tipo": Procedimento.Tipo.AMBULATORIAL,
            "descricao": "Limpeza e curativo",
            "duracao_estimada_minutos": 20,
            "ativo": True,
            "materiais_previstos": [
                {
                    "produto": str(self.produto_material.id),
                    "quantidade_prevista": "2",
                }
            ],
        }
        dados.update(extra)
        return dados

    def payload_execucao(self, **extra):
        dados = {
            "pet": str(self.pet.id),
            "atendimento": str(self.atendimento.id),
            "procedimento": str(self.procedimento.id),
            "profissional": str(self.profissional.id),
            "equipe": [str(self.auxiliar.id)],
            "observacoes": "Execução de teste",
            "resultado": "Concluído sem alterações",
            "intercorrencias": "Nenhuma",
            "materiais": [
                {
                    "produto": str(self.produto_material.id),
                    "lote": str(self.lote_material.id),
                    "quantidade": "2",
                }
            ],
            "chave_idempotencia": "exec-teste-1",
        }
        dados.update(extra)
        return dados

    def criar_execucao(self, **extra):
        resp = self.client.post(
            URL_EXECUCOES, self.payload_execucao(**extra), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        return ExecucaoProcedimento.objects.get(pk=resp.data["id"])


class CatalogoTests(BaseProcedimentoTestCase):
    def test_cria_categoria_e_procedimento_com_materiais_previstos(self):
        resp = self.client.post(
            URL_CATEGORIAS,
            {"nome": "Cirurgias", "descricao": "Procedimentos cirúrgicos"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        categoria_id = resp.data["id"]

        resp = self.client.post(
            URL_PROCEDIMENTOS,
            self.payload_procedimento(categoria=categoria_id),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        procedimento = Procedimento.objects.get(pk=resp.data["id"])
        self.assertEqual(procedimento.created_by_id, self.vet_user.id)
        self.assertEqual(str(procedimento.categoria_id), categoria_id)
        self.assertEqual(procedimento.materiais_previstos.count(), 1)
        self.assertEqual(
            procedimento.materiais_previstos.first().quantidade_prevista,
            Decimal("2.000"),
        )

    def test_nome_de_procedimento_unico_ignora_maiusculas(self):
        resp = self.client.post(
            URL_PROCEDIMENTOS,
            self.payload_procedimento(nome="ultrassonografia ABDOMINAL"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("nome", resp.data)

    def test_atualizacao_sincroniza_materiais_previstos(self):
        resp = self.client.patch(
            f"{URL_PROCEDIMENTOS}{self.procedimento.id}/",
            {
                "materiais_previstos": [
                    {
                        "produto": str(self.produto.id),
                        "quantidade_prevista": "1.5",
                    },
                    {
                        "produto": str(self.produto_material.id),
                        "quantidade_prevista": "3",
                    },
                ]
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.procedimento.refresh_from_db()
        self.assertEqual(self.procedimento.materiais_previstos.count(), 2)
        self.assertTrue(
            self.procedimento.materiais_previstos.filter(
                produto=self.produto
            ).exists()
        )
        # O material antigo foi removido logicamente, não apagado.
        self.assertTrue(
            MaterialPrevistoProcedimento.all_objects.filter(
                procedimento=self.procedimento,
                produto=self.produto_material,
                is_deleted=True,
            ).exists()
        )

    def test_material_previsto_duplicado_retorna_erro(self):
        resp = self.client.post(
            URL_PROCEDIMENTOS,
            self.payload_procedimento(
                materiais_previstos=[
                    {
                        "produto": str(self.produto_material.id),
                        "quantidade_prevista": "1",
                    },
                    {
                        "produto": str(self.produto_material.id),
                        "quantidade_prevista": "2",
                    },
                ]
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("materiais_previstos", resp.data)

    def test_recepcao_le_catalogo_mas_nao_cria(self):
        self.client.force_authenticate(self.rec)
        resp = self.client.get(URL_PROCEDIMENTOS)
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            URL_PROCEDIMENTOS, self.payload_procedimento(), format="json"
        )
        self.assertEqual(resp.status_code, 403)

    def test_usuario_anonimo_nao_acessa_catalogo(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get(URL_PROCEDIMENTOS)
        self.assertEqual(resp.status_code, 401)


class ExecucaoTests(BaseProcedimentoTestCase):
    def test_execucao_registra_relacionamentos_e_equipe(self):
        resp = self.client.post(
            URL_EXECUCOES, self.payload_execucao(), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)

        execucao = ExecucaoProcedimento.objects.get(pk=resp.data["id"])
        self.assertEqual(execucao.pet_id, self.pet.id)
        self.assertEqual(execucao.atendimento_id, self.atendimento.id)
        self.assertEqual(execucao.procedimento_id, self.procedimento.id)
        self.assertEqual(execucao.profissional_id, self.profissional.id)
        self.assertEqual(execucao.created_by_id, self.vet_user.id)
        self.assertEqual(
            list(execucao.equipe.values_list("id", flat=True)),
            [self.auxiliar.id],
        )
        self.assertEqual(execucao.resultado, "Concluído sem alterações")
        self.assertEqual(execucao.intercorrencias, "Nenhuma")

    def test_execucao_deriva_animal_do_atendimento(self):
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                pet=None,
                chave_idempotencia="deriva-pet",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(str(resp.data["pet"]), str(self.pet.id))

    def test_execucao_com_atendimento_de_outro_animal_retorna_erro(self):
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                pet=str(self.pet.id),
                atendimento=str(self.atendimento_outro_pet.id),
                chave_idempotencia="pet-divergente",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("atendimento", resp.data)

    def test_execucao_consome_materiais_e_estoque(self):
        execucao = self.criar_execucao(chave_idempotencia="consumo-1")
        material = execucao.materiais.get()
        self.assertIsNotNone(material.movimentacao_id)
        self.assertEqual(material.quantidade, Decimal("2.000"))
        self.assertEqual(
            material.movimentacao.tipo,
            MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        )
        self.assertEqual(material.movimentacao.quantidade, Decimal("2"))
        self.assertEqual(material.movimentacao.saldo_anterior, Decimal("10"))
        self.assertEqual(material.movimentacao.saldo_posterior, Decimal("8"))
        self.assertEqual(
            material.movimentacao.atendimento_id, self.atendimento.id
        )
        self.lote_material.refresh_from_db()
        self.assertEqual(self.lote_material.quantidade_atual, Decimal("8"))

    def test_execucao_sem_materiais_nao_movimenta_estoque(self):
        antes = MovimentacaoEstoque.objects.count()
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                materiais=[], chave_idempotencia="sem-materiais"
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(MovimentacaoEstoque.objects.count(), antes)

    def test_execucao_com_lote_vencido_nao_persiste_nada(self):
        antes = ExecucaoProcedimento.objects.count()
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                materiais=[
                    {
                        "produto": str(self.produto.id),
                        "lote": str(self.lote_vencido.id),
                        "quantidade": "1",
                    }
                ],
                chave_idempotencia="lote-vencido",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(ExecucaoProcedimento.objects.count(), antes)
        self.lote_vencido.refresh_from_db()
        self.assertEqual(self.lote_vencido.quantidade_atual, Decimal("5"))

    def test_execucao_com_saldo_insuficiente_nao_persiste_nada(self):
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                materiais=[
                    {
                        "produto": str(self.produto.id),
                        "lote": str(self.lote.id),
                        "quantidade": "999",
                    }
                ],
                chave_idempotencia="sem-saldo",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            ExecucaoProcedimento.objects.filter(
                chave_idempotencia="sem-saldo"
            ).exists()
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("20"))

    def test_execucao_com_lote_de_outro_produto_retorna_erro(self):
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                materiais=[
                    {
                        "produto": str(self.produto.id),
                        "lote": str(self.lote_material.id),
                        "quantidade": "1",
                    }
                ],
                chave_idempotencia="lote-divergente",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("materiais", resp.data)

    def test_execucao_com_produto_comercial_retorna_erro(self):
        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(
                materiais=[
                    {
                        "produto": str(self.produto_comercial.id),
                        "lote": str(self.lote_comercial.id),
                        "quantidade": "1",
                    }
                ],
                chave_idempotencia="comercial",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("materiais", resp.data)

    def test_procedimento_inativo_nao_pode_ser_executado(self):
        self.procedimento.ativo = False
        self.procedimento.save()
        resp = self.client.post(
            URL_EXECUCOES, self.payload_execucao(), format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("procedimento", resp.data)

    def test_chave_idempotente_nao_duplica_execucao_nem_consumo(self):
        resp1 = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(chave_idempotencia="idempotente-proc"),
            format="json",
        )
        resp2 = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(chave_idempotencia="idempotente-proc"),
            format="json",
        )
        self.assertEqual(resp1.status_code, 201, resp1.data)
        self.assertEqual(resp2.status_code, 201, resp2.data)
        self.assertEqual(resp1.data["id"], resp2.data["id"])
        self.assertEqual(
            ExecucaoProcedimento.objects.filter(
                chave_idempotencia="idempotente-proc"
            ).count(),
            1,
        )
        self.assertEqual(
            MovimentacaoEstoque.objects.filter(
                tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO
            ).count(),
            1,
        )
        self.assertEqual(
            AuditLog.objects.filter(
                entidade="procedimentos.execucaoprocedimento",
                entidade_id=resp1.data["id"],
                acao=AuditLog.Acao.CRIACAO,
            ).count(),
            1,
        )
        self.lote_material.refresh_from_db()
        self.assertEqual(self.lote_material.quantidade_atual, Decimal("8"))

    def test_chave_idempotente_unica_no_banco(self):
        execucao = self.criar_execucao(chave_idempotencia="unica-proc")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ExecucaoProcedimento.objects.create(
                    pet=self.pet,
                    atendimento=self.atendimento,
                    procedimento=self.procedimento,
                    profissional=self.profissional,
                    chave_idempotencia=execucao.chave_idempotencia,
                )

    def test_recepcao_lista_historico_mas_nao_executa(self):
        self.criar_execucao(chave_idempotencia="lista-recepcao")
        self.client.force_authenticate(self.rec)
        resp = self.client.get(URL_EXECUCOES)
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            URL_EXECUCOES,
            self.payload_execucao(chave_idempotencia="recepcao-proc"),
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_historico_filtra_por_animal_e_procedimento(self):
        self.criar_execucao(chave_idempotencia="hist-1")
        resp = self.client.get(
            URL_EXECUCOES,
            {"pet": str(self.pet.id), "procedimento": str(self.procedimento.id)},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)


class CancelamentoTests(BaseProcedimentoTestCase):
    def test_cancelamento_gera_devolucao_e_preserva_historico(self):
        execucao = self.criar_execucao(chave_idempotencia="cancelar-1")
        material = execucao.materiais.get()
        mov_original = material.movimentacao

        resp = self.client.post(
            f"{URL_EXECUCOES}{execucao.id}/cancelar/",
            {"motivo": "Material registrado em duplicidade"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        execucao.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(
            execucao.status, ExecucaoProcedimento.Status.CANCELADA
        )
        self.assertEqual(
            execucao.motivo_cancelamento, "Material registrado em duplicidade"
        )
        self.assertIsNotNone(execucao.cancelada_em)
        self.assertEqual(execucao.cancelada_por_id, self.vet_user.id)
        self.assertIsNotNone(material.estorno_movimentacao_id)
        self.assertTrue(
            MovimentacaoEstoque.objects.filter(pk=mov_original.pk).exists()
        )
        estorno = material.estorno_movimentacao
        self.assertEqual(estorno.tipo, MovimentacaoEstoque.Tipo.DEVOLUCAO)
        self.assertEqual(estorno.quantidade, Decimal("2"))
        self.assertEqual(estorno.direcao, MovimentacaoEstoque.Direcao.ENTRADA)
        self.lote_material.refresh_from_db()
        self.assertEqual(self.lote_material.quantidade_atual, Decimal("10"))

        auditorias = AuditLog.objects.filter(
            entidade="procedimentos.execucaoprocedimento",
            entidade_id=str(execucao.id),
        )
        self.assertTrue(auditorias.filter(acao=AuditLog.Acao.CRIACAO).exists())
        self.assertTrue(
            auditorias.filter(
                acao=AuditLog.Acao.ATUALIZACAO,
                justificativa="Material registrado em duplicidade",
            ).exists()
        )

    def test_cancelamento_exige_motivo(self):
        execucao = self.criar_execucao(chave_idempotencia="cancelar-sem-motivo")
        resp = self.client.post(
            f"{URL_EXECUCOES}{execucao.id}/cancelar/",
            {},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("motivo", resp.data)
        self.lote_material.refresh_from_db()
        self.assertEqual(self.lote_material.quantidade_atual, Decimal("8"))

    def test_cancelamento_duplicado_nao_estorna_duas_vezes(self):
        execucao = self.criar_execucao(chave_idempotencia="cancelar-duplo")
        for _ in range(2):
            resp = self.client.post(
                f"{URL_EXECUCOES}{execucao.id}/cancelar/",
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
        self.lote_material.refresh_from_db()
        self.assertEqual(self.lote_material.quantidade_atual, Decimal("10"))

    def test_recepcao_nao_cancela_execucao(self):
        execucao = self.criar_execucao(chave_idempotencia="cancelar-recepcao")
        self.client.force_authenticate(self.rec)
        resp = self.client.post(
            f"{URL_EXECUCOES}{execucao.id}/cancelar/",
            {"motivo": "Tentativa"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)


class ServicoProcedimentoTests(BaseProcedimentoTestCase):
    def test_servico_reaproveita_execucao_existente(self):
        primeira, criada = services.registrar_execucao(
            procedimento=self.procedimento,
            atendimento=self.atendimento,
            profissional=self.profissional,
            materiais=[],
            chave_idempotencia="servico-idempotente",
            usuario=self.vet_user,
        )
        self.assertTrue(criada)
        segunda, criada = services.registrar_execucao(
            procedimento=self.procedimento,
            atendimento=self.atendimento,
            profissional=self.profissional,
            materiais=[],
            chave_idempotencia="servico-idempotente",
            usuario=self.vet_user,
        )
        self.assertFalse(criada)
        self.assertEqual(primeira.pk, segunda.pk)

    def test_servico_nao_permite_procedimento_inativo(self):
        self.procedimento.ativo = False
        self.procedimento.save()
        with self.assertRaises(DRFValidationError):
            services.registrar_execucao(
                procedimento=self.procedimento,
                atendimento=self.atendimento,
                profissional=self.profissional,
                usuario=self.vet_user,
            )


@skipIf(
    connection.vendor == "sqlite",
    "Concorrência real é validada no PostgreSQL; SQLite serializa escritas.",
)
class ConcorrenciaProcedimentoTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.vet_user = fazer_usuario("vet_proc_conc", "veterinario")
        self.tutor = Tutor.objects.create(
            nome="Tutor Concorrência", telefone="11 97777-1000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Thor", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dra. Concorrência", cargo=Profissional.Cargo.VETERINARIO
        )
        self.atendimento = Atendimento.objects.create(
            pet=self.pet,
            profissional=self.profissional,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
            data_hora_inicio=timezone.now(),
            status=Atendimento.Status.REALIZADO,
        )
        self.categoria = CategoriaProcedimento.objects.create(nome="Conc")
        self.procedimento = Procedimento.objects.create(
            nome="Procedimento Concorrência",
            categoria=self.categoria,
        )
        self.categoria_produto = categoria_produto(
            CategoriaProduto.Tipo.MATERIAL_CLINICO, "Materiais clínicos"
        )
        self.produto = Produto.objects.create(
            nome="Material Concorrência",
            categoria=self.categoria_produto,
            codigo_interno="MAT-CONC-PROC-1",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.UNIDADE,
        )
        self.lote = estoque_services.criar_lote(
            produto=self.produto,
            numero_lote="LOTE-CONC-PROC-1",
            quantidade_inicial=Decimal("10"),
            data_validade=timezone.localdate() + timedelta(days=180),
            usuario=self.vet_user,
        )

    def _executar(self, chave, barreira):
        close_old_connections()
        barreira.wait()
        try:
            execucao, criada = services.registrar_execucao(
                procedimento=Procedimento.objects.get(pk=self.procedimento.pk),
                atendimento=Atendimento.objects.get(pk=self.atendimento.pk),
                profissional=Profissional.objects.get(pk=self.profissional.pk),
                materiais=[
                    {
                        "produto": Produto.objects.get(pk=self.produto.pk),
                        "lote": Lote.objects.get(pk=self.lote.pk),
                        "quantidade": Decimal("6"),
                    }
                ],
                chave_idempotencia=chave,
                usuario=self.vet_user,
            )
            return ("ok", execucao.pk, criada)
        except DRFValidationError as exc:
            return ("erro", exc.detail)
        finally:
            close_old_connections()

    def test_duas_execucoes_concorrentes_nao_deixam_saldo_negativo(self):
        barreira = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [
                executor.submit(self._executar, chave, barreira)
                for chave in ("conc-proc-1", "conc-proc-2")
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

    def test_duas_requisicoes_com_mesma_chave_criam_uma_execucao(self):
        barreira = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futuros = [
                executor.submit(self._executar, "conc-proc-mesma", barreira)
                for _ in range(2)
            ]
            resultados = [futuro.result() for futuro in futuros]

        ids = {resultado[1] for resultado in resultados if resultado[0] == "ok"}
        self.assertEqual(len(ids), 1)
        self.assertEqual(
            ExecucaoProcedimento.objects.filter(
                chave_idempotencia="conc-proc-mesma"
            ).count(),
            1,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("4"))
