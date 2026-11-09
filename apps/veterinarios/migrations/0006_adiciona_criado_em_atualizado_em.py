# Adiciona criado_em/atualizado_em aos modelos do veterinarios que herdam
# BaseModel mas cujas tabelas não possuem essas colunas.

import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def preencher_criado_em(apps, schema_editor):
    now = django.utils.timezone.now()
    db_alias = schema_editor.connection.alias
    for model_name in [
        "veterinario",
        "tiposervico",
        "salaconsultorio",
        "horariotrabalho",
        "bloqueioagenda",
        "listaespera",
        "agendamentorecorrente",
    ]:
        model = apps.get_model("veterinarios", model_name)
        model.objects.using(db_alias).filter(
            criado_em__isnull=True
        ).update(criado_em=now, atualizado_em=now)


def desfazer(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("veterinarios", "0005_lista_espera_recorrente_historico"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="veterinario",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="veterinario",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tiposervico",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="tiposervico",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="salaconsultorio",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="salaconsultorio",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="horariotrabalho",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="horariotrabalho",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="bloqueioagenda",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="bloqueioagenda",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="listaespera",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="listaespera",
            name="atualizado_em",
            field=models.DateTimeField(
                auto_now=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="agendamentorecorrente",
            name="criado_em",
            field=models.DateTimeField(
                auto_now_add=True,
                default=django.utils.timezone.now,
                editable=False,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="agendamentorecorrente",
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
