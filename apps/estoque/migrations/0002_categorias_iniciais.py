"""Semeia as categorias básicas do catálogo de produtos."""

from django.db import migrations

CATEGORIAS = [
    ("Medicamentos", "medicamento", "Medicamentos e itens para prescrição."),
    ("Materiais clínicos", "material_clinico", "Materiais usados em atendimentos e procedimentos."),
    ("Vacinas", "vacina", "Vacinas e imunobiológicos."),
    ("Produtos de consumo", "consumo", "Itens de consumo interno da clínica."),
    ("Produtos comerciais", "comercial", "Produtos para venda ao tutor."),
]


def criar_categorias(apps, schema_editor):
    CategoriaProduto = apps.get_model("estoque", "CategoriaProduto")
    for nome, tipo, descricao in CATEGORIAS:
        if not CategoriaProduto.objects.filter(nome__iexact=nome).exists():
            CategoriaProduto.objects.create(
                nome=nome,
                tipo=tipo,
                descricao=descricao,
                ativo=True,
            )


def remover_categorias(apps, schema_editor):
    CategoriaProduto = apps.get_model("estoque", "CategoriaProduto")
    for nome, _, _ in CATEGORIAS:
        categoria = CategoriaProduto.objects.filter(nome__iexact=nome).first()
        if categoria is not None and not categoria.produtos.exists():
            categoria.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("estoque", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(criar_categorias, remover_categorias),
    ]
