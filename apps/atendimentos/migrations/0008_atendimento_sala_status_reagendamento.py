# Adiciona sala, controle de status e reagendamento ao Atendimento.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atendimentos", "0007_alter_atendimento_managers_atendimento_created_by_and_more"),
        ("veterinarios", "0004_modelos_agenda_base"),
    ]

    operations = [
        # Campo sala (FK para SalaConsultorio).
        migrations.AddField(
            model_name="atendimento",
            name="sala",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="atendimentos",
                to="veterinarios.salaconsultorio",
                verbose_name="sala",
            ),
        ),
        # Motivo de cancelamento.
        migrations.AddField(
            model_name="atendimento",
            name="motivo_cancelamento",
            field=models.CharField(blank=True, max_length=255),
        ),
        # Data de confirmação.
        migrations.AddField(
            model_name="atendimento",
            name="data_confirmacao",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Data de cancelamento.
        migrations.AddField(
            model_name="atendimento",
            name="data_cancelamento",
            field=models.DateTimeField(blank=True, null=True),
        ),
        # Reagendado de (self-referencing FK).
        migrations.AddField(
            model_name="atendimento",
            name="reagendado_de",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="reagendamentos",
                to="atendimentos.atendimento",
                verbose_name="reagendado de",
            ),
        ),
        # Torna nome_profissional opcional (blank=True).
        migrations.AlterField(
            model_name="atendimento",
            name="nome_profissional",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
