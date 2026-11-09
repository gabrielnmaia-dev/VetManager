# Converte Veterinario para herdar BaseModel (id UUID PK, created_at, etc.)
# e remove primary_key=True do campo profissional.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


def preencher_campos_auditoria(apps, schema_editor):
    """Preenche created_at/updated_at para registros existentes."""
    Veterinario = apps.get_model("veterinarios", "Veterinario")
    db_alias = schema_editor.connection.alias
    agora = "2026-01-01 00:00:00+00:00"
    Veterinario.objects.using(db_alias).filter(
        created_at__isnull=True
    ).update(created_at=agora, updated_at=agora)


def desfazer(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("veterinarios", "0002_alter_profissional_managers_profissional_created_by_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Remove primary_key=True do campo profissional.
        migrations.AlterField(
            model_name="veterinario",
            name="profissional",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="veterinario",
                to="veterinarios.profissional",
            ),
        ),
        # 2. Adiciona id como UUID primary key.
        migrations.AddField(
            model_name="veterinario",
            name="id",
            field=models.UUIDField(
                default=uuid.uuid4, editable=False, primary_key=True, serialize=False
            ),
        ),
        # 3. Adiciona campos de auditoria e soft delete do BaseModel.
        migrations.AddField(
            model_name="veterinario",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="updated_at",
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="is_deleted",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="deleted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="criado por",
            ),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="atualizado por",
            ),
        ),
        migrations.AddField(
            model_name="veterinario",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="excluído por",
            ),
        ),
        # 4. Preenche created_at/updated_at para registros existentes.
        migrations.RunPython(
            preencher_campos_auditoria, reverse_code=desfazer
        ),
        # 5. Torna created_at/updated_at NOT NULL (sem default para novos).
        migrations.AlterField(
            model_name="veterinario",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True),
        ),
        migrations.AlterField(
            model_name="veterinario",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
    ]
