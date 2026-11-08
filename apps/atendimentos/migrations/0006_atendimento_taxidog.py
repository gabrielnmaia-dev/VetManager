# Adiciona o campo taxidog ao model Atendimento.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("atendimentos", "0005_preencher_profissional_atendimento"),
    ]

    operations = [
        migrations.AddField(
            model_name="atendimento",
            name="taxidog",
            field=models.BooleanField(default=False),
        ),
    ]
