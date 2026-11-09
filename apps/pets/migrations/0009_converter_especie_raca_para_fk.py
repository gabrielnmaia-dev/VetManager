# Converte Pet.especie e Pet.raca de CharField para FK nos catálogos.
#
# NOTA: Esta migration pressupõe que a tabela pets_pet está vazia (ambiente de
# teste) ou que os dados já foram preparados. Em produção com dados existentes,
# é necessário um passo adicional de migração de dados antes de aplicar a
# alteração de tipo de campo.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pets", "0008_especie_raca_historico"),
    ]

    operations = [
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
        migrations.AlterField(
            model_name="pet",
            name="raca",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pets",
                to="pets.raca",
                verbose_name="raça",
            ),
        ),
    ]
