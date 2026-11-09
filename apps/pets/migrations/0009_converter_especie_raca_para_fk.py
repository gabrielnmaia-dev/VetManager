# Converte Pet.especie e Pet.raca de CharField para FK nos catálogos.
#
# Etapas:
#   1. cria colunas temporárias especie_fk/raca_fk (FKs anuláveis);
#   2. cria/associa Especie e Raca a partir dos valores de texto existentes;
#   3. remove as colunas de texto antigas e renomeia as FKs para os nomes
#      definitivos;
#   4. torna especie obrigatória.
#
# A migração preserva os dados: cada valor distinto vira um item de catálogo.
# A comparação ignora caixa, acentos e espaços extras para evitar duplicatas
# do tipo "Cão"/"cao". O texto original do primeiro registro é mantido como
# nome de exibição.
#
# A reversão copia os nomes dos catálogos de volta para os campos de texto.
# Para isso, os campos antigos passam temporariamente a aceitar nulos antes de
# serem removidos: assim a reversão consegue recriá-los, popular e só então
# restaurar o NOT NULL.

import unicodedata

import django.db.models.deletion
from django.db import migrations, models


def _normalizar(valor):
    """Remove espaços extras e mantém o texto de exibição."""
    return " ".join((valor or "").split())


def _chave(valor):
    """Chave de comparação sem caixa, acentos ou espaços extras."""
    texto = unicodedata.normalize("NFKD", _normalizar(valor))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.casefold()


def _liberar_triggers(schema_editor):
    """Libera eventos de trigger adiados no PostgreSQL.

    Sem isso, alterar tabelas que receberam inserts/updates na mesma
    transação falha com "pending trigger events".
    """
    if schema_editor.connection.vendor == "postgresql":
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def migrar_dados(apps, schema_editor):
    """Cria catálogos e associa cada pet à espécie/raça correspondente."""
    Pet = apps.get_model("pets", "Pet")
    Especie = apps.get_model("pets", "Especie")
    Raca = apps.get_model("pets", "Raca")
    db_alias = schema_editor.connection.alias

    cache_especies = {}
    cache_racas = {}

    for pet in Pet.objects.using(db_alias).all().order_by("id"):
        nome_especie = _normalizar(pet.especie) or "Não informado"
        chave_especie = _chave(nome_especie)

        especie = cache_especies.get(chave_especie)
        if especie is None:
            especie = (
                Especie.objects.using(db_alias)
                .filter(nome__iexact=nome_especie)
                .first()
            )
            if especie is None:
                especie = Especie.objects.using(db_alias).create(
                    nome=nome_especie, ativo=True
                )
            cache_especies[chave_especie] = especie

        pet.especie_fk_id = especie.id

        nome_raca = _normalizar(pet.raca)
        if nome_raca:
            chave_raca = (chave_especie, _chave(nome_raca))
            raca = cache_racas.get(chave_raca)
            if raca is None:
                raca = (
                    Raca.objects.using(db_alias)
                    .filter(especie=especie, nome__iexact=nome_raca)
                    .first()
                )
                if raca is None:
                    raca = Raca.objects.using(db_alias).create(
                        especie=especie, nome=nome_raca, ativo=True
                    )
                cache_racas[chave_raca] = raca
            pet.raca_fk_id = raca.id

        pet.save(using=db_alias, update_fields=["especie_fk", "raca_fk"])

    _liberar_triggers(schema_editor)


def reverter_dados(apps, schema_editor):
    """Reverso: copia os nomes dos catálogos de volta para os campos de texto."""
    Pet = apps.get_model("pets", "Pet")
    db_alias = schema_editor.connection.alias

    pets = Pet.objects.using(db_alias).select_related("especie_fk", "raca_fk")
    for pet in pets:
        pet.especie = pet.especie_fk.nome if pet.especie_fk_id else ""
        pet.raca = pet.raca_fk.nome if pet.raca_fk_id else ""
        pet.save(using=db_alias, update_fields=["especie", "raca"])

    _liberar_triggers(schema_editor)


class Migration(migrations.Migration):

    dependencies = [
        ("pets", "0008_especie_raca_historico"),
    ]

    operations = [
        # 1. Colunas temporárias de FK (anuláveis enquanto migram os dados).
        migrations.AddField(
            model_name="pet",
            name="especie_fk",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pets",
                to="pets.especie",
                verbose_name="espécie",
            ),
        ),
        migrations.AddField(
            model_name="pet",
            name="raca_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pets",
                to="pets.raca",
                verbose_name="raça",
            ),
        ),
        # 2. Campos de texto passam a aceitar nulo (necessário para a reversão).
        migrations.AlterField(
            model_name="pet",
            name="especie",
            field=models.CharField(max_length=50, null=True),
        ),
        migrations.AlterField(
            model_name="pet",
            name="raca",
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        # 3. Converte os valores de texto existentes em registros de catálogo.
        migrations.RunPython(migrar_dados, reverse_code=reverter_dados),
        # 4. Remove as colunas de texto e promove as FKs aos nomes definitivos.
        migrations.RemoveField(model_name="pet", name="especie"),
        migrations.RemoveField(model_name="pet", name="raca"),
        migrations.RenameField(
            model_name="pet", old_name="especie_fk", new_name="especie"
        ),
        migrations.RenameField(
            model_name="pet", old_name="raca_fk", new_name="raca"
        ),
        # 5. Espécie passa a ser obrigatória.
        migrations.AlterField(
            model_name="pet",
            name="especie",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pets",
                to="pets.especie",
                verbose_name="espécie",
            ),
        ),
    ]
