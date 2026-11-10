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
