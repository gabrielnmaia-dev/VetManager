# Cria ListaEspera, AgendamentoRecorrente e HistoricoStatusAtendimento.
# Depende de atendimentos.0008 (para Atendimento.sala) e veterinarios.0004.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("veterinarios", "0004_modelos_agenda_base"),
        ("atendimentos", "0008_atendimento_sala_status_reagendamento"),
        ("pets", "0009_converter_especie_raca_para_fk"),
        ("tutores", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ListaEspera",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "is_deleted",
                    models.BooleanField(default=False),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="criado por",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="atualizado por",
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="excluído por",
                    ),
                ),
                (
                    "data_desejada",
                    models.DateField(),
                ),
                (
                    "horario_inicio_desejado",
                    models.TimeField(),
                ),
                (
                    "horario_fim_desejado",
                    models.TimeField(
                        blank=True,
                        null=True,
                        help_text="Horário limite aceitável.",
                    ),
                ),
                (
                    "observacoes",
                    models.TextField(blank=True),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
                (
                    "atendimento_gerado",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lista_espera_origem",
                        to="atendimentos.atendimento",
                    ),
                ),
                (
                    "pet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lista_espera",
                        to="pets.pet",
                    ),
                ),
                (
                    "profissional",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lista_espera",
                        to="veterinarios.profissional",
                    ),
                ),
                (
                    "tutor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lista_espera",
                        to="tutores.tutor",
                    ),
                ),
                (
                    "tipo_servico",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lista_espera",
                        to="veterinarios.tiposervico",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "verbose_name": "lista de espera",
                "verbose_name_plural": "listas de espera",
            },
        ),
        migrations.CreateModel(
            name="AgendamentoRecorrente",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "is_deleted",
                    models.BooleanField(default=False),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="criado por",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="atualizado por",
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="excluído por",
                    ),
                ),
                (
                    "duracao_minutos",
                    models.PositiveIntegerField(default=30),
                ),
                (
                    "dia_semana",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (0, "Segunda-feira"),
                            (1, "Terça-feira"),
                            (2, "Quarta-feira"),
                            (3, "Quinta-feira"),
                            (4, "Sexta-feira"),
                            (5, "Sábado"),
                            (6, "Domingo"),
                        ],
                    ),
                ),
                (
                    "hora_inicio",
                    models.TimeField(),
                ),
                (
                    "data_inicio",
                    models.DateField(),
                ),
                (
                    "data_fim",
                    models.DateField(
                        blank=True,
                        null=True,
                        help_text="Data final da recorrência (opcional).",
                    ),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
                (
                    "pet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agendamentos_recorrentes",
                        to="pets.pet",
                    ),
                ),
                (
                    "profissional",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agendamentos_recorrentes",
                        to="veterinarios.profissional",
                    ),
                ),
                (
                    "sala",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="agendamentos_recorrentes",
                        to="veterinarios.salaconsultorio",
                    ),
                ),
                (
                    "tipo_servico",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agendamentos_recorrentes",
                        to="veterinarios.tiposervico",
                    ),
                ),
                (
                    "tutor",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="agendamentos_recorrentes",
                        to="tutores.tutor",
                    ),
                ),
            ],
            options={
                "ordering": ["dia_semana", "hora_inicio"],
                "verbose_name": "agendamento recorrente",
                "verbose_name_plural": "agendamentos recorrentes",
            },
        ),
        migrations.CreateModel(
            name="HistoricoStatusAtendimento",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True),
                ),
                (
                    "is_deleted",
                    models.BooleanField(default=False),
                ),
                (
                    "deleted_at",
                    models.DateTimeField(blank=True, null=True),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="criado por",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="atualizado por",
                    ),
                ),
                (
                    "deleted_by",
                    models.ForeignKey(
                        blank=True,
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="excluído por",
                    ),
                ),
                (
                    "status_anterior",
                    models.CharField(blank=True, max_length=20),
                ),
                (
                    "status_novo",
                    models.CharField(max_length=20),
                ),
                (
                    "motivo",
                    models.CharField(blank=True, max_length=255),
                ),
                (
                    "data_operacao",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "atendimento",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="historico_status",
                        to="atendimentos.atendimento",
                    ),
                ),
                (
                    "usuario",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="mudancas_status_atendimento",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-data_operacao"],
                "verbose_name": "histórico de status",
                "verbose_name_plural": "históricos de status",
            },
        ),
    ]
