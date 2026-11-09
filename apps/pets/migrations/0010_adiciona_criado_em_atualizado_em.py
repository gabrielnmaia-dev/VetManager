# Adiciona criado_em/atualizado_em a Especie e Raca.

import django.utils.timezone
from django.db import migrations, models


def preencher_criado_em(apps, schema_editor):
    now = django.utils.timezone.now()
    db_alias = schema_editor.connection.alias
    for model_name in ["especie", "raca"]:
        model = apps.get_model("pets", model_name)
        model.objects.using(db_alias).filter(
            criado_em__isnull=True
        ).update(criado_em=now, atualizado_em=now)


def desfazer(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pets", "0009_converter_especie_raca_para_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="especie",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="especie",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="raca",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="raca",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.RunPython(
            preencher_criado_em, reverse_code=desfazer
        ),
    ]
