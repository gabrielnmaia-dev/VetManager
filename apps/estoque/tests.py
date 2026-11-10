"""Testes do catálogo de produtos, medicamentos e categorias."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from rest_framework.test import APIClient

from apps.auditoria.models import AuditLog

from .models import CategoriaProduto, Produto

User = get_user_model()

URL_CATEGORIAS = "/api/v1/categorias-produto/"
URL_PRODUTOS = "/api/v1/produtos/"


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class BaseCatalogoTestCase(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_catalogo", "admin")
        self.vet = fazer_usuario("vet_catalogo", "veterinario")
        self.rec = fazer_usuario("rec_catalogo", "recepcao")
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

        self.cat_medicamento = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.MEDICAMENTO
        )
        self.cat_material = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.MATERIAL_CLINICO
        )
        self.cat_comercial = CategoriaProduto.objects.get(
            tipo=CategoriaProduto.Tipo.COMERCIAL
        )

    def payload_produto(self, **kwargs):
        dados = {
            "nome": "Produto de teste",
            "categoria": str(self.cat_material.id),
            "codigo_interno": "COD-001",
            "tipo_estoque": Produto.TipoEstoque.CLINICO,
            "unidade_medida": Produto.UnidadeMedida.UNIDADE,
        }
        dados.update(kwargs)
        return dados

    def payload_medicamento(self, **kwargs):
        dados = {
            "nome": "Medicamento de teste",
            "categoria": str(self.cat_medicamento.id),
            "codigo_interno": "MED-001",
            "tipo_estoque": Produto.TipoEstoque.CLINICO,
            "unidade_medida": Produto.UnidadeMedida.ML,
            "principio_ativo": "Princípio ativo informado pela clínica",
            "concentracao": "10 mg/ml",
            "forma_farmaceutica": Produto.FormaFarmaceutica.SOLUCAO,
            "unidade_dispensacao": Produto.UnidadeDispensacao.ML,
            "apresentacao": "Frasco de 100 ml",
        }
        dados.update(kwargs)
        return dados


class CategoriaProdutoTests(BaseCatalogoTestCase):
    def test_categorias_iniciais_foram_semeadas(self):
        self.assertEqual(CategoriaProduto.objects.count(), 5)
        tipos = set(
            CategoriaProduto.objects.values_list("tipo", flat=True)
        )
        self.assertEqual(
            tipos,
            {
                CategoriaProduto.Tipo.MEDICAMENTO,
                CategoriaProduto.Tipo.MATERIAL_CLINICO,
                CategoriaProduto.Tipo.VACINA,
                CategoriaProduto.Tipo.CONSUMO,
                CategoriaProduto.Tipo.COMERCIAL,
            },
        )

    def test_listar_categorias_para_recepcao(self):
        self.client.force_authenticate(self.rec)
        resp = self.client.get(URL_CATEGORIAS)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 5)

    def test_criar_categoria_como_veterinario(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            URL_CATEGORIAS,
            {"nome": "Antiparasitários", "tipo": "medicamento"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(
            CategoriaProduto.objects.filter(nome="Antiparasitários").exists()
        )

    def test_nome_de_categoria_duplicado_ignora_caixa(self):
        resp = self.client.post(
            URL_CATEGORIAS,
            {"nome": "medicamentos", "tipo": "medicamento"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("nome", resp.data)

    def test_recepcao_nao_pode_criar_categoria(self):
        self.client.force_authenticate(self.rec)
        resp = self.client.post(
            URL_CATEGORIAS,
            {"nome": "Nova categoria", "tipo": "consumo"},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_nao_excluir_categoria_com_produto(self):
        self.client.post(
            URL_PRODUTOS,
            self.payload_produto(categoria=str(self.cat_material.id)),
            format="json",
        )
        resp = self.client.delete(f"{URL_CATEGORIAS}{self.cat_material.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("detail", resp.data)
        self.assertTrue(
            CategoriaProduto.objects.filter(pk=self.cat_material.pk).exists()
        )


class ProdutoValidationTests(BaseCatalogoTestCase):
    def test_cadastrar_produto_simples(self):
        resp = self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        self.assertEqual(resp.status_code, 201, resp.data)
        produto = Produto.objects.get(codigo_interno="COD-001")
        self.assertFalse(produto.is_medicamento)
        self.assertEqual(produto.categoria_id, self.cat_material.id)

    def test_medicamento_exige_campos_farmaceuticos(self):
        dados = self.payload_medicamento(
            principio_ativo="",
            concentracao="",
            forma_farmaceutica="",
            unidade_dispensacao="",
        )
        resp = self.client.post(URL_PRODUTOS, dados, format="json")
        self.assertEqual(resp.status_code, 400)
        for campo in (
            "principio_ativo",
            "concentracao",
            "forma_farmaceutica",
            "unidade_dispensacao",
        ):
            self.assertIn(campo, resp.data)

    def test_cadastrar_medicamento_completo(self):
        resp = self.client.post(
            URL_PRODUTOS, self.payload_medicamento(), format="json"
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        produto = Produto.objects.get(codigo_interno="MED-001")
        self.assertTrue(produto.is_medicamento)
        self.assertEqual(produto.principio_ativo, "Princípio ativo informado pela clínica")
        self.assertTrue(resp.data["is_medicamento"])

    def test_codigo_interno_duplicado_ignora_caixa(self):
        self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        resp = self.client.post(
            URL_PRODUTOS,
            self.payload_produto(nome="Outro produto", codigo_interno="cod-001"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("codigo_interno", resp.data)

    def test_codigo_barras_duplicado(self):
        self.client.post(
            URL_PRODUTOS,
            self.payload_produto(codigo_barras="7891234567890"),
            format="json",
        )
        resp = self.client.post(
            URL_PRODUTOS,
            self.payload_produto(
                nome="Outro produto",
                codigo_interno="COD-002",
                codigo_barras="7891234567890",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("codigo_barras", resp.data)

    def test_codigo_barras_vazio_pode_repetir(self):
        for i in range(2):
            resp = self.client.post(
                URL_PRODUTOS,
                self.payload_produto(
                    nome=f"Produto {i}", codigo_interno=f"COD-{i}", codigo_barras=""
                ),
                format="json",
            )
            self.assertEqual(resp.status_code, 201, resp.data)

    def test_produto_em_categoria_inativa(self):
        categoria = CategoriaProduto.objects.create(
            nome="Categoria inativa", tipo="consumo", ativo=False
        )
        resp = self.client.post(
            URL_PRODUTOS,
            self.payload_produto(categoria=str(categoria.id)),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("categoria", resp.data)

    def test_editar_produto_para_categoria_de_medicamento(self):
        criado = self.client.post(
            URL_PRODUTOS, self.payload_produto(), format="json"
        )
        resp = self.client.patch(
            f"{URL_PRODUTOS}{criado.data['id']}/",
            {"categoria": str(self.cat_medicamento.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("principio_ativo", resp.data)

    def test_editar_produto_para_outra_categoria_inativa(self):
        criado = self.client.post(
            URL_PRODUTOS, self.payload_produto(), format="json"
        )
        inativa = CategoriaProduto.objects.create(
            nome="Outra categoria inativa", tipo="consumo", ativo=False
        )
        resp = self.client.patch(
            f"{URL_PRODUTOS}{criado.data['id']}/",
            {"categoria": str(inativa.id)},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("categoria", resp.data)

    def test_editar_produto_mantendo_categoria_inativada(self):
        criado = self.client.post(
            URL_PRODUTOS, self.payload_produto(), format="json"
        )
        self.cat_material.ativo = False
        self.cat_material.save(update_fields=["ativo"])
        resp = self.client.patch(
            f"{URL_PRODUTOS}{criado.data['id']}/",
            {"nome": "Produto renomeado"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_codigo_reaproveitavel_apos_exclusao_logica(self):
        criado = self.client.post(
            URL_PRODUTOS, self.payload_produto(), format="json"
        )
        resp = self.client.delete(f"{URL_PRODUTOS}{criado.data['id']}/")
        self.assertEqual(resp.status_code, 204)
        recriado = self.client.post(
            URL_PRODUTOS, self.payload_produto(), format="json"
        )
        self.assertEqual(recriado.status_code, 201, recriado.data)


class ProdutoConsultaTests(BaseCatalogoTestCase):
    def setUp(self):
        super().setUp()
        self.p1 = Produto.objects.create(
            nome="Dipirona veterinária",
            categoria=self.cat_medicamento,
            codigo_interno="MED-100",
            principio_ativo="Dipirona",
            concentracao="500 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
            tipo_estoque=Produto.TipoEstoque.CLINICO,
        )
        self.p2 = Produto.objects.create(
            nome="Shampoo neutro",
            categoria=self.cat_comercial,
            codigo_interno="COM-100",
            tipo_estoque=Produto.TipoEstoque.COMERCIAL,
        )
        self.p3 = Produto.objects.create(
            nome="Produto inativo",
            categoria=self.cat_comercial,
            codigo_interno="COM-200",
            tipo_estoque=Produto.TipoEstoque.COMERCIAL,
            ativo=False,
        )

    def test_busca_por_principio_ativo(self):
        resp = self.client.get(URL_PRODUTOS, {"search": "Dipirona"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["codigo_interno"], "MED-100")

    def test_filtro_por_categoria_e_tipo_de_estoque(self):
        resp = self.client.get(
            URL_PRODUTOS,
            {"categoria": str(self.cat_comercial.id), "tipo_estoque": "comercial"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)

    def test_filtro_por_situacao(self):
        resp = self.client.get(URL_PRODUTOS, {"ativo": "false"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["codigo_interno"], "COM-200")

    def test_action_ativos_exclui_inativos(self):
        resp = self.client.get(f"{URL_PRODUTOS}ativos/")
        self.assertEqual(resp.status_code, 200)
        codigos = {item["codigo_interno"] for item in resp.data}
        self.assertIn("MED-100", codigos)
        self.assertIn("COM-100", codigos)
        self.assertNotIn("COM-200", codigos)

    def test_action_medicamentos(self):
        resp = self.client.get(f"{URL_PRODUTOS}medicamentos/")
        self.assertEqual(resp.status_code, 200)
        codigos = {item["codigo_interno"] for item in resp.data}
        self.assertEqual(codigos, {"MED-100"})


class ProdutoPermissaoTests(BaseCatalogoTestCase):
    def test_recepcao_pode_listar_mas_nao_criar(self):
        self.client.force_authenticate(self.rec)
        self.assertEqual(self.client.get(URL_PRODUTOS).status_code, 200)
        resp = self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_pode_criar_e_excluir(self):
        self.client.force_authenticate(self.vet)
        criado = self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        self.assertEqual(criado.status_code, 201, criado.data)
        resp = self.client.delete(f"{URL_PRODUTOS}{criado.data['id']}/")
        self.assertEqual(resp.status_code, 204)

    def test_usuario_anonimo_nao_acessa(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL_PRODUTOS).status_code, 401)
        resp = self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        self.assertEqual(resp.status_code, 401)

    def test_criacao_registra_auditoria(self):
        criado = self.client.post(URL_PRODUTOS, self.payload_produto(), format="json")
        self.assertEqual(criado.status_code, 201)
        self.assertTrue(
            AuditLog.objects.filter(
                entidade="estoque.produto",
                entidade_id=criado.data["id"],
                acao=AuditLog.Acao.CRIACAO,
                usuario=self.admin,
            ).exists()
        )


# ---------------------------------------------------------------------------
# Estoque clínico: saldo, FEFO, lotes, movimentações, inventário e alertas.
# ---------------------------------------------------------------------------

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

from . import services
from .models import Fornecedor, Inventario, ItemInventario, Lote, MovimentacaoEstoque

URL_LOTES = "/api/v1/lotes/"
URL_FORNECEDORES = "/api/v1/fornecedores/"
URL_MOVIMENTACOES = "/api/v1/movimentacoes-estoque/"
URL_INVENTARIOS = "/api/v1/inventarios/"
URL_ITENS_INVENTARIO = "/api/v1/itens-inventario/"
URL_ESTOQUE_DASHBOARD = "/api/v1/estoque/dashboard/"
URL_ESTOQUE_ALERTAS = "/api/v1/estoque/alertas/"


class BaseEstoqueTestCase(BaseCatalogoTestCase):
    def setUp(self):
        super().setUp()
        self.produto = Produto.objects.create(
            nome="Dipirona 500 mg/ml",
            categoria=self.cat_medicamento,
            codigo_interno="MED-EST-001",
            tipo_estoque=Produto.TipoEstoque.CLINICO,
            unidade_medida=Produto.UnidadeMedida.ML,
            principio_ativo="Dipirona sódica",
            concentracao="500 mg/ml",
            forma_farmaceutica=Produto.FormaFarmaceutica.SOLUCAO,
            unidade_dispensacao=Produto.UnidadeDispensacao.ML,
            estoque_minimo=Decimal("5"),
        )
        self.fornecedor = Fornecedor.objects.create(
            nome="Fornecedor Central",
            cnpj="12.345.678/0001-10",
        )
        self.lote = self.criar_lote("L-001", "10", validade_dias=180)

    def criar_lote(
        self,
        numero,
        quantidade="0",
        validade_dias=180,
        *,
        produto=None,
        usuario=None,
        **kwargs,
    ):
        validade = (
            None
            if validade_dias is None
            else timezone.localdate() + timedelta(days=validade_dias)
        )
        return services.criar_lote(
            produto=produto or self.produto,
            numero_lote=numero,
            quantidade_inicial=Decimal(quantidade),
            data_validade=validade,
            fornecedor=kwargs.pop("fornecedor", self.fornecedor),
            usuario=usuario or self.admin,
            **kwargs,
        )

    def criar_produto(self, codigo, *, tipo_estoque=Produto.TipoEstoque.CLINICO, **kwargs):
        dados = {
            "nome": f"Produto {codigo}",
            "categoria": self.cat_material,
            "codigo_interno": codigo,
            "tipo_estoque": tipo_estoque,
            "unidade_medida": Produto.UnidadeMedida.UNIDADE,
        }
        dados.update(kwargs)
        return Produto.objects.create(**dados)


class MovimentacaoEstoqueServiceTests(BaseEstoqueTestCase):
    def test_criar_lote_com_saldo_inicial_registra_entrada(self):
        mov = MovimentacaoEstoque.objects.get(lote=self.lote)
        self.assertEqual(mov.tipo, MovimentacaoEstoque.Tipo.ENTRADA)
        self.assertEqual(mov.quantidade, Decimal("10"))
        self.assertEqual(mov.saldo_anterior, Decimal("0"))
        self.assertEqual(mov.saldo_posterior, Decimal("10"))
        self.assertEqual(self.lote.quantidade_atual, Decimal("10"))

    def test_criar_lote_sem_saldo_nao_gera_movimentacao(self):
        lote = self.criar_lote("L-ZERO", "0")
        self.assertEqual(lote.quantidade_atual, Decimal("0"))
        self.assertFalse(lote.movimentacoes.exists())

    def test_entrada_soma_saldo_e_registra_saldos(self):
        mov = services.registrar_entrada(
            produto=self.produto,
            lote=self.lote,
            quantidade=Decimal("5"),
            usuario=self.vet,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("15"))
        self.assertEqual(mov.saldo_anterior, Decimal("10"))
        self.assertEqual(mov.saldo_posterior, Decimal("15"))
        self.assertEqual(mov.created_by, self.vet)

    def test_saida_com_lote_explicito_baixa_saldo(self):
        movs = services.registrar_saida(
            produto=self.produto,
            lote=self.lote,
            quantidade=Decimal("3"),
            usuario=self.vet,
        )
        self.lote.refresh_from_db()
        self.assertEqual(len(movs), 1)
        self.assertEqual(self.lote.quantidade_atual, Decimal("7"))
        self.assertEqual(movs[0].saldo_anterior, Decimal("10"))
        self.assertEqual(movs[0].saldo_posterior, Decimal("7"))

    def test_saida_sem_lote_aplica_fefo(self):
        produto = self.criar_produto("FEFO-001")
        lote_longe = self.criar_lote(
            "FEFO-LONGE", "5", validade_dias=120, produto=produto
        )
        lote_perto = self.criar_lote(
            "FEFO-PERTO", "4", validade_dias=10, produto=produto
        )
        lote_sem_validade = self.criar_lote(
            "FEFO-SEM", "5", validade_dias=None, produto=produto
        )

        movs = services.registrar_saida(
            produto=produto,
            quantidade=Decimal("6"),
            usuario=self.vet,
        )

        self.assertEqual(len(movs), 2)
        self.assertEqual(movs[0].lote_id, lote_perto.id)
        self.assertEqual(movs[0].quantidade, Decimal("4"))
        self.assertEqual(movs[1].lote_id, lote_longe.id)
        self.assertEqual(movs[1].quantidade, Decimal("2"))
        lote_perto.refresh_from_db()
        lote_longe.refresh_from_db()
        lote_sem_validade.refresh_from_db()
        self.assertEqual(lote_perto.quantidade_atual, Decimal("0"))
        self.assertEqual(lote_longe.quantidade_atual, Decimal("3"))
        self.assertEqual(lote_sem_validade.quantidade_atual, Decimal("5"))

    def test_saida_sem_saldo_suficiente_faz_rollback_total(self):
        antes = MovimentacaoEstoque.objects.count()
        with self.assertRaises(DRFValidationError):
            services.registrar_saida(
                produto=self.produto,
                quantidade=Decimal("999"),
                usuario=self.vet,
            )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("10"))
        self.assertEqual(MovimentacaoEstoque.objects.count(), antes)

    def test_lote_vencido_nao_permite_saida_nem_consumo(self):
        vencido = self.criar_lote("L-VENC", "3", validade_dias=-2)
        for tipo in (
            MovimentacaoEstoque.Tipo.SAIDA,
            MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        ):
            with self.assertRaises(DRFValidationError):
                services.registrar_saida(
                    produto=self.produto,
                    lote=vencido,
                    quantidade=Decimal("1"),
                    tipo=tipo,
                    usuario=self.vet,
                )
        vencido.refresh_from_db()
        self.assertEqual(vencido.quantidade_atual, Decimal("3"))

    def test_lote_vencido_pode_ser_baixado_por_vencimento(self):
        vencido = self.criar_lote("L-VENC2", "3", validade_dias=-2)
        services.registrar_saida(
            produto=self.produto,
            lote=vencido,
            quantidade=Decimal("3"),
            tipo=MovimentacaoEstoque.Tipo.VENCIMENTO,
            usuario=self.vet,
        )
        vencido.refresh_from_db()
        self.assertEqual(vencido.quantidade_atual, Decimal("0"))

    def test_fefo_ignora_lote_vencido(self):
        produto = self.criar_produto("FEFO-VENC")
        self.criar_lote("VENC", "9", validade_dias=-1, produto=produto)
        valido = self.criar_lote("VALIDO", "4", validade_dias=60, produto=produto)

        movs = services.registrar_saida(
            produto=produto, quantidade=Decimal("4"), usuario=self.vet
        )
        self.assertEqual(len(movs), 1)
        self.assertEqual(movs[0].lote_id, valido.id)

    def test_ajuste_exige_motivo(self):
        with self.assertRaises(DRFValidationError):
            services.registrar_ajuste(
                produto=self.produto,
                lote=self.lote,
                quantidade=Decimal("1"),
                direcao=MovimentacaoEstoque.Direcao.SAIDA,
                motivo="   ",
                usuario=self.vet,
            )

    def test_ajuste_de_entrada_e_saida(self):
        services.registrar_ajuste(
            produto=self.produto,
            lote=self.lote,
            quantidade=Decimal("2"),
            direcao=MovimentacaoEstoque.Direcao.ENTRADA,
            motivo="Correção de contagem",
            usuario=self.vet,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("12"))

        services.registrar_ajuste(
            produto=self.produto,
            lote=self.lote,
            quantidade=Decimal("5"),
            direcao=MovimentacaoEstoque.Direcao.SAIDA,
            motivo="Correção de contagem",
            usuario=self.vet,
        )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("7"))

    def test_ajuste_nao_deixa_saldo_negativo(self):
        with self.assertRaises(DRFValidationError):
            services.registrar_ajuste(
                produto=self.produto,
                lote=self.lote,
                quantidade=Decimal("11"),
                direcao=MovimentacaoEstoque.Direcao.SAIDA,
                motivo="Ajuste indevido",
                usuario=self.vet,
            )
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("10"))

    def test_produto_sem_controle_de_estoque_nao_movimenta(self):
        produto = self.criar_produto("SEM-CTRL", controla_estoque=False)
        lote = Lote.objects.create(
            produto=produto,
            numero_lote="SEM-1",
            quantidade_inicial=Decimal("0"),
            quantidade_atual=Decimal("0"),
        )
        with self.assertRaises(DRFValidationError):
            services.registrar_entrada(
                produto=produto,
                lote=lote,
                quantidade=Decimal("1"),
                usuario=self.vet,
            )


class MovimentacaoImutavelTests(BaseEstoqueTestCase):
    def test_movimentacao_nao_pode_ser_alterada(self):
        mov = MovimentacaoEstoque.objects.get(lote=self.lote)
        mov.quantidade = Decimal("1")
        with self.assertRaises(DjangoValidationError):
            mov.save()

    def test_movimentacao_nao_pode_ser_excluida(self):
        mov = MovimentacaoEstoque.objects.get(lote=self.lote)
        with self.assertRaises(DjangoValidationError):
            mov.delete()
        with self.assertRaises(DjangoValidationError):
            mov.soft_delete(user=self.admin)
        with self.assertRaises(DjangoValidationError):
            mov.hard_delete()

    def test_api_nao_permite_editar_ou_excluir_movimentacao(self):
        mov = MovimentacaoEstoque.objects.get(lote=self.lote)
        self.client.force_authenticate(self.admin)
        # O viewset é somente leitura; a política de papéis barra antes mesmo
        # do roteamento do método (403) e, se não barrasse, seria 405.
        resp = self.client.put(
            f"{URL_MOVIMENTACOES}{mov.id}/", {}, format="json"
        )
        self.assertIn(resp.status_code, (403, 405))
        resp = self.client.delete(f"{URL_MOVIMENTACOES}{mov.id}/")
        self.assertIn(resp.status_code, (403, 405))


class InventarioTests(BaseEstoqueTestCase):
    def test_abrir_inventario_congela_saldo_dos_lotes(self):
        inv = services.abrir_inventario(
            tipo_estoque=Produto.TipoEstoque.CLINICO, usuario=self.admin
        )
        item = ItemInventario.objects.get(inventario=inv, lote=self.lote)
        self.assertEqual(item.quantidade_sistema, Decimal("10"))
        self.assertEqual(item.quantidade_contada, Decimal("10"))
        self.assertEqual(inv.status, Inventario.Status.ABERTO)

    def test_finalizar_inventario_aplica_ajuste_e_movimentacao(self):
        inv = services.abrir_inventario(
            tipo_estoque=Produto.TipoEstoque.CLINICO, usuario=self.admin
        )
        item = ItemInventario.objects.get(inventario=inv, lote=self.lote)
        item.quantidade_contada = Decimal("7")
        item.save(user=self.admin)

        inv = services.finalizar_inventario(inventario_id=inv.id, usuario=self.vet)

        self.lote.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("7"))
        self.assertEqual(inv.status, Inventario.Status.FINALIZADO)
        self.assertEqual(inv.finalizado_por, self.vet)
        self.assertIsNotNone(inv.finalizado_em)
        self.assertIsNotNone(item.movimentacao_id)
        self.assertEqual(item.diferenca, Decimal("-3"))
        mov = item.movimentacao
        self.assertEqual(mov.tipo, MovimentacaoEstoque.Tipo.AJUSTE)
        self.assertEqual(mov.direcao, MovimentacaoEstoque.Direcao.SAIDA)
        self.assertEqual(mov.quantidade, Decimal("3"))

    def test_inventario_recalcula_saldo_na_finalizacao(self):
        inv = services.abrir_inventario(
            tipo_estoque=Produto.TipoEstoque.CLINICO, usuario=self.admin
        )
        services.registrar_saida(
            produto=self.produto,
            lote=self.lote,
            quantidade=Decimal("4"),
            usuario=self.vet,
        )
        item = ItemInventario.objects.get(inventario=inv, lote=self.lote)
        item.quantidade_contada = Decimal("6")
        item.save(user=self.admin)

        services.finalizar_inventario(inventario_id=inv.id, usuario=self.vet)

        self.lote.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(item.quantidade_sistema, Decimal("6"))
        self.assertEqual(item.diferenca, Decimal("0"))
        self.assertIsNone(item.movimentacao_id)
        self.assertEqual(self.lote.quantidade_atual, Decimal("6"))

    def test_inventario_finalizado_nao_pode_ser_finalizado_de_novo(self):
        inv = services.abrir_inventario(
            tipo_estoque=Produto.TipoEstoque.CLINICO, usuario=self.admin
        )
        services.finalizar_inventario(inventario_id=inv.id, usuario=self.admin)
        with self.assertRaises(DRFValidationError):
            services.finalizar_inventario(inventario_id=inv.id, usuario=self.admin)

    def test_cancelar_inventario_aberto(self):
        inv = services.abrir_inventario(
            tipo_estoque=Produto.TipoEstoque.CLINICO, usuario=self.admin
        )
        inv = services.cancelar_inventario(inventario_id=inv.id, usuario=self.admin)
        self.assertEqual(inv.status, Inventario.Status.CANCELADO)
        with self.assertRaises(DRFValidationError):
            services.finalizar_inventario(inventario_id=inv.id, usuario=self.admin)

    def test_inventario_api_cria_lista_e_finaliza(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            URL_INVENTARIOS,
            {"tipo_estoque": Produto.TipoEstoque.CLINICO, "observacoes": "Mensal"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        inv_id = resp.data["id"]

        item = ItemInventario.objects.get(inventario_id=inv_id, lote=self.lote)
        resp = self.client.patch(
            f"{URL_ITENS_INVENTARIO}{item.id}/",
            {"quantidade_contada": "8"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)

        resp = self.client.post(f"{URL_INVENTARIOS}{inv_id}/finalizar/", {}, format="json")
        self.assertEqual(resp.status_code, 200, resp.data)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("8"))


class AlertaEstoqueTests(BaseEstoqueTestCase):
    def test_alerta_de_estoque_minimo(self):
        produto = self.criar_produto("MIN-001", estoque_minimo=Decimal("5"))
        self.criar_lote("MIN-L1", "2", produto=produto)
        alertas = services.alertas_estoque()
        ids = [item["id"] for item in alertas["estoque_minimo"]]
        self.assertIn(str(produto.id), ids)
        item = next(i for i in alertas["estoque_minimo"] if i["id"] == str(produto.id))
        self.assertEqual(item["saldo_total"], Decimal("2"))
        self.assertEqual(item["faltando"], Decimal("3"))

    def test_produto_com_saldo_acima_do_minimo_nao_alerta(self):
        alertas = services.alertas_estoque()
        ids = [item["id"] for item in alertas["estoque_minimo"]]
        self.assertNotIn(str(self.produto.id), ids)

    def test_alerta_de_lotes_vencidos_e_vencendo(self):
        vencido = self.criar_lote("AL-VENC", "1", validade_dias=-1)
        vencendo = self.criar_lote("AL-PROX", "1", validade_dias=10)
        alertas = services.alertas_estoque()
        ids_vencidos = [item["id"] for item in alertas["lotes_vencidos"]]
        ids_vencendo = [item["id"] for item in alertas["lotes_vencendo"]]
        self.assertIn(str(vencido.id), ids_vencidos)
        self.assertIn(str(vencendo.id), ids_vencendo)
        self.assertEqual(alertas["totais"]["lotes_vencidos"], 1)
        self.assertEqual(alertas["totais"]["lotes_vencendo"], 1)

    def test_lote_sem_validade_nao_entra_nos_alertas_de_validade(self):
        sem_validade = self.criar_lote("AL-SEM", "1", validade_dias=None)
        alertas = services.alertas_estoque()
        ids = [
            item["id"]
            for item in alertas["lotes_vencidos"] + alertas["lotes_vencendo"]
        ]
        self.assertNotIn(str(sem_validade.id), ids)

    def test_dashboard_consolida_clinico_e_comercial(self):
        comercial = self.criar_produto(
            "COM-001", tipo_estoque=Produto.TipoEstoque.COMERCIAL
        )
        self.criar_lote("COM-L1", "3", produto=comercial)
        resumo = services.resumo_estoque()
        self.assertGreaterEqual(
            resumo["por_tipo"][Produto.TipoEstoque.CLINICO]["quantidade"],
            Decimal("10"),
        )
        self.assertEqual(
            resumo["por_tipo"][Produto.TipoEstoque.COMERCIAL]["quantidade"],
            Decimal("3"),
        )
        self.assertTrue(resumo["movimentacoes_recentes"])


class EstoquePermissoesTests(BaseEstoqueTestCase):
    def test_recepcao_le_estoque_mas_nao_movimenta(self):
        self.client.force_authenticate(self.rec)
        self.assertEqual(self.client.get(URL_LOTES).status_code, 200)
        self.assertEqual(self.client.get(URL_MOVIMENTACOES).status_code, 200)
        self.assertEqual(self.client.get(URL_ESTOQUE_DASHBOARD).status_code, 200)
        self.assertEqual(self.client.get(URL_ESTOQUE_ALERTAS).status_code, 200)
        resp = self.client.post(
            f"{URL_MOVIMENTACOES}entrada/",
            {
                "produto": str(self.produto.id),
                "lote": str(self.lote.id),
                "quantidade": "1",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_veterinario_pode_registrar_entrada_e_saida(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            f"{URL_MOVIMENTACOES}entrada/",
            {
                "produto": str(self.produto.id),
                "lote": str(self.lote.id),
                "quantidade": "2",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data["tipo"], MovimentacaoEstoque.Tipo.ENTRADA)

        resp = self.client.post(
            f"{URL_MOVIMENTACOES}saida/",
            {
                "produto": str(self.produto.id),
                "quantidade": "5",
                "tipo": MovimentacaoEstoque.Tipo.SAIDA,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(len(resp.data), 1)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("7"))

    def test_usuario_anonimo_nao_acessa_estoque(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(URL_LOTES).status_code, 401)
        self.assertEqual(self.client.get(URL_ESTOQUE_DASHBOARD).status_code, 401)

    def test_quantidade_atual_e_somente_leitura_na_api(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.patch(
            f"{URL_LOTES}{self.lote.id}/",
            {"quantidade_atual": "999", "fabricante": "Novo fabricante"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.quantidade_atual, Decimal("10"))
        self.assertEqual(self.lote.fabricante, "Novo fabricante")

    def test_nao_exclui_lote_com_saldo(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.delete(f"{URL_LOTES}{self.lote.id}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Lote.objects.filter(pk=self.lote.pk).exists())

    def test_api_cria_lote_com_saldo_inicial(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            URL_LOTES,
            {
                "produto": str(self.produto.id),
                "numero_lote": "L-API-1",
                "data_validade": str(timezone.localdate() + timedelta(days=90)),
                "quantidade_inicial": "6",
                "custo_aquisicao": "1.50",
                "fornecedor": str(self.fornecedor.id),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        lote = Lote.objects.get(pk=resp.data["id"])
        self.assertEqual(lote.quantidade_atual, Decimal("6"))
        self.assertEqual(
            lote.movimentacoes.get().tipo, MovimentacaoEstoque.Tipo.ENTRADA
        )

    def test_api_impede_numero_de_lote_duplicado_no_produto(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            URL_LOTES,
            {
                "produto": str(self.produto.id),
                "numero_lote": "l-001",
                "data_validade": str(timezone.localdate() + timedelta(days=90)),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("numero_lote", resp.data)

    def test_fornecedor_crud_e_cnpj_duplicado(self):
        self.client.force_authenticate(self.vet)
        resp = self.client.post(
            URL_FORNECEDORES,
            {"nome": "Fornecedor Novo", "cnpj": "98.765.432/0001-10"},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.data)
        duplicado = self.client.post(
            URL_FORNECEDORES,
            {"nome": "Outro", "cnpj": "98.765.432/0001-10"},
            format="json",
        )
        self.assertEqual(duplicado.status_code, 400)
        self.assertIn("cnpj", duplicado.data)
