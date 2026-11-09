# Cria modelos básicos de agenda sem dependência de atendimentos:
# TipoServico, SalaConsultorio, HorarioTrabalho, BloqueioAgenda.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("veterinarios", "0003_converter_veterinario_para_basemodel"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TipoServico",
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
                    "nome",
                    models.CharField(max_length=60, unique=True),
                ),
                (
                    "duracao_padrao_minutos",
                    models.PositiveIntegerField(
                        default=30,
                        help_text="Duração padrão em minutos.",
                    ),
                ),
                (
                    "intervalo_minutos",
                    models.PositiveIntegerField(
                        default=0,
                        help_text="Intervalo entre atendimentos deste tipo (minutos).",
                    ),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
            ],
            options={
                "ordering": ["nome"],
                "verbose_name": "tipo de serviço",
                "verbose_name_plural": "tipos de serviço",
            },
        ),
        migrations.CreateModel(
            name="SalaConsultorio",
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
                    "nome",
                    models.CharField(max_length=100, unique=True),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
            ],
            options={
                "ordering": ["nome"],
                "verbose_name": "sala",
                "verbose_name_plural": "salas",
            },
        ),
        migrations.CreateModel(
            name="HorarioTrabalho",
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
                    "hora_fim",
                    models.TimeField(),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
                (
                    "profissional",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="horarios_trabalho",
                        to="veterinarios.profissional",
                    ),
                ),
            ],
            options={
                "ordering": ["profissional", "dia_semana", "hora_inicio"],
                "unique_together": {("profissional", "dia_semana", "hora_inicio")},
                "verbose_name": "horário de trabalho",
                "verbose_name_plural": "horários de trabalho",
            },
        ),
        migrations.CreateModel(
            name="BloqueioAgenda",
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
                    "tipo",
                    models.CharField(
                        choices=[
                            ("feriado", "Feriado"),
                            ("folga", "Folga"),
                            ("ausencia", "Ausência"),
                            ("manutencao", "Manutenção"),
                            ("outro", "Outro"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "motivo",
                    models.CharField(blank=True, max_length=255),
                ),
                (
                    "data_inicio",
                    models.DateTimeField(),
                ),
                (
                    "data_fim",
                    models.DateTimeField(),
                ),
                (
                    "ativo",
                    models.BooleanField(default=True),
                ),
                (
                    "profissional",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bloqueios_agenda",
                        to="veterinarios.profissional",
                    ),
                ),
                (
                    "sala",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bloqueios_agenda",
                        to="veterinarios.salaconsultorio",
                    ),
                ),
            ],
            options={
                "ordering": ["data_inicio"],
                "verbose_name": "bloqueio de agenda",
                "verbose_name_plural": "bloqueios de agenda",
            },
        ),
    ]
