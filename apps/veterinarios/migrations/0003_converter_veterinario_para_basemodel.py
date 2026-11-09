# Converte Veterinario para herdar BaseModel (id UUID PK, created_at, etc.)
# e remove primary_key=True do campo profissional.
#
# A conversão da PK é feita em etapas para preservar os dados e os vínculos
# existentes (ex.: prontuario.veterinario_id):
#
#   1. remove as FKs de outras tabelas que apontam para Veterinario;
#   2. cria a coluna id e copia profissional_id para ela — assim todos os
#      vínculos continuam válidos, sem reescrever as tabelas dependentes;
#   3. troca a PK de profissional_id para id e recria as FKs apontando para id.
#
# No PostgreSQL a troca é feita em SQL porque não é possível remover uma PK
# enquanto existir FK dependente. No SQLite (usado nos testes) as operações
# padrão do Django já cuidam do rebuild da tabela.

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.migrations.operations.base import Operation

# FKs dependentes capturadas durante a migração (tabela, nome, definição).
_FKS_DEPENDENTES = []


def _alter_field_op():
    return migrations.AlterField(
        model_name="veterinario",
        name="profissional",
        field=models.OneToOneField(
            on_delete=django.db.models.deletion.CASCADE,
            related_name="veterinario",
            to="veterinarios.profissional",
        ),
    )


def _add_id_field_op():
    return migrations.AddField(
        model_name="veterinario",
        name="id",
        field=models.UUIDField(
            default=uuid.uuid4,
            editable=False,
            primary_key=True,
            serialize=False,
        ),
    )


def _fks_para_veterinario(schema_editor):
    """Lista as FKs que referenciam veterinarios_veterinario."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE confrelid = 'veterinarios_veterinario'::regclass
              AND contype = 'f'
            """
        )
        return cursor.fetchall()


def remover_fks_dependentes(apps, schema_editor):
    """Remove FKs de outras tabelas que apontam para Veterinario."""
    if schema_editor.connection.vendor != "postgresql":
        return
    global _FKS_DEPENDENTES
    _FKS_DEPENDENTES = _fks_para_veterinario(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        for tabela, nome, _definicao in _FKS_DEPENDENTES:
            cursor.execute(f'ALTER TABLE {tabela} DROP CONSTRAINT "{nome}"')


def restaurar_fks_dependentes(apps, schema_editor):
    """Recria as FKs dependentes apontando para a nova PK (id)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for tabela, nome, definicao in _FKS_DEPENDENTES:
            nova = definicao.replace(
                "REFERENCES veterinarios_veterinario(profissional_id)",
                "REFERENCES veterinarios_veterinario(id)",
            )
            cursor.execute(f'ALTER TABLE {tabela} ADD CONSTRAINT "{nome}" {nova}')


def desfazer_restaurar_fks_dependentes(apps, schema_editor):
    """Reverso: captura e remove as FKs que apontam para Veterinario(id)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    global _FKS_DEPENDENTES
    _FKS_DEPENDENTES = _fks_para_veterinario(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        for tabela, nome, _definicao in _FKS_DEPENDENTES:
            cursor.execute(f'ALTER TABLE {tabela} DROP CONSTRAINT "{nome}"')


def desfazer_remover_fks_dependentes(apps, schema_editor):
    """Reverso: recria as FKs apontando para a PK antiga (profissional_id)."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        for tabela, nome, definicao in _FKS_DEPENDENTES:
            nova = definicao.replace(
                "REFERENCES veterinarios_veterinario(id)",
                "REFERENCES veterinarios_veterinario(profissional_id)",
            )
            cursor.execute(f'ALTER TABLE {tabela} ADD CONSTRAINT "{nome}" {nova}')


def _converter_pk_postgres(schema_editor):
    """Troca a PK no PostgreSQL preservando os vínculos existentes."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario ADD COLUMN IF NOT EXISTS id uuid"
        )
        # id = profissional_id mantém prontuários e demais FKs válidos.
        cursor.execute(
            "UPDATE veterinarios_veterinario SET id = profissional_id"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario ALTER COLUMN id SET NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "DROP CONSTRAINT IF EXISTS veterinarios_veterinario_pkey"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "ADD CONSTRAINT veterinarios_veterinario_pkey PRIMARY KEY (id)"
        )
        # profissional_id era a PK; agora precisa de UNIQUE próprio.
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "DROP CONSTRAINT IF EXISTS veterinarios_veterinario_profissional_id_key"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "ADD CONSTRAINT veterinarios_veterinario_profissional_id_key "
            "UNIQUE (profissional_id)"
        )


def _reverter_pk_postgres(schema_editor):
    """Reverso: volta a PK para profissional_id e remove id."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "DROP CONSTRAINT IF EXISTS veterinarios_veterinario_profissional_id_key"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "DROP CONSTRAINT IF EXISTS veterinarios_veterinario_pkey"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario "
            "ADD CONSTRAINT veterinarios_veterinario_pkey PRIMARY KEY (profissional_id)"
        )
        cursor.execute(
            "ALTER TABLE veterinarios_veterinario DROP COLUMN IF EXISTS id"
        )


class ConverterPKVeterinario(Operation):
    """Converte a PK de Veterinario em etapas seguras para os dois bancos."""

    reversible = True

    def state_forwards(self, app_label, state):
        _alter_field_op().state_forwards(app_label, state)
        _add_id_field_op().state_forwards(app_label, state)

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            _converter_pk_postgres(schema_editor)
            return
        # SQLite e demais bancos: operações padrão do Django.
        alter = _alter_field_op()
        add = _add_id_field_op()
        estado_alter = from_state.clone()
        alter.state_forwards(app_label, estado_alter)
        alter.database_forwards(app_label, schema_editor, from_state, estado_alter)
        add.database_forwards(app_label, schema_editor, estado_alter, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            _reverter_pk_postgres(schema_editor)
            return
        alter = _alter_field_op()
        add = _add_id_field_op()
        estado_alter = to_state.clone()
        alter.state_forwards(app_label, estado_alter)
        add.database_backwards(app_label, schema_editor, from_state, estado_alter)
        alter.database_backwards(app_label, schema_editor, estado_alter, to_state)

    def describe(self):
        return "Converte a PK de Veterinario para UUID (id)"

    def deconstruct(self):
        return (self.__class__.__name__, [], {})


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
        # 0. Remove FKs dependentes antes de mexer na PK (PostgreSQL).
        migrations.RunPython(
            remover_fks_dependentes,
            reverse_code=desfazer_remover_fks_dependentes,
        ),
        # 1-2. Troca a PK (profissional_id -> id), preservando os vínculos.
        migrations.SeparateDatabaseAndState(
            database_operations=[ConverterPKVeterinario()],
            state_operations=[_alter_field_op(), _add_id_field_op()],
        ),
        # 3. Recria as FKs dependentes apontando para id (PostgreSQL).
        migrations.RunPython(
            restaurar_fks_dependentes,
            reverse_code=desfazer_restaurar_fks_dependentes,
        ),
        # 4. Adiciona campos de auditoria e soft delete do BaseModel.
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
        # 5. Preenche created_at/updated_at para registros existentes.
        migrations.RunPython(
            preencher_campos_auditoria, reverse_code=desfazer
        ),
        # 6. Torna created_at/updated_at NOT NULL (sem default para novos).
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
