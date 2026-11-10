"""Formas de pagamento padrão.

A clínica pode editar/inativar estas formas depois, mas o sistema já nasce
operacional para registrar dinheiro, Pix, cartões e transferência.
"""

from django.db import migrations

FORMAS = [
    ("Dinheiro", "dinheiro", False),
    ("Pix", "pix", False),
    ("Cartão de crédito", "cartao_credito", True),
    ("Cartão de débito", "cartao_debito", False),
    ("Transferência", "transferencia", False),
    ("Cheque", "cheque", False),
    ("Outros", "outros", False),
]


def criar_formas(apps, schema_editor):
    FormaPagamento = apps.get_model("financeiro", "FormaPagamento")
    for nome, tipo, permite_parcelamento in FORMAS:
        FormaPagamento.objects.get_or_create(
            nome=nome,
            defaults={
                "tipo": tipo,
                "ativo": True,
                "permite_parcelamento": permite_parcelamento,
            },
        )


def remover_formas(apps, schema_editor):
    FormaPagamento = apps.get_model("financeiro", "FormaPagamento")
    FormaPagamento.objects.filter(nome__in=[nome for nome, _, _ in FORMAS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("financeiro", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(criar_formas, remover_formas),
    ]
