"""Data migration: casa Atendimento.nome_profissional com Profissional existente.

Regras do casamento:
- comparação sem caixa e com espaços colapsados
  ("  Dr.  Ana " == "dr. ana");
- só preenche a FK quando o nome normalizado casa EXATAMENTE UM profissional
  (nomes ambíguos — 2+ profissionais com o mesmo nome — ficam com a FK nula
  para decisão humana, evitando atribuição errada);
- contagem impressa no stdout para conferência da implantação.

Esta migração NÃO apaga nome_profissional nem torna a FK obrigatória:
essas decisões dependem de validação posterior (fora deste changeset).
"""

from django.db import migrations


def normalizar(nome: str) -> str:
    """Espaços colapsados + minúsculas."""
    return " ".join((nome or "").split()).casefold()


def casar_profissionais(apps, schema_editor):
    Atendimento = apps.get_model("atendimentos", "Atendimento")
    Profissional = apps.get_model("veterinarios", "Profissional")

    # nome normalizado -> lista de ids de profissionais
    por_nome = {}
    for profissional in Profissional.objects.all().only("id", "nome"):
        por_nome.setdefault(normalizar(profissional.nome), []).append(
            profissional.id
        )

    casados = 0
    nao_casados = 0
    ambiguos = 0

    pendentes = (
        Atendimento.objects.filter(profissional__isnull=True)
        .exclude(nome_profissional="")
        .only("id", "nome_profissional")
    )
    for atendimento in pendentes:
        candidatos = por_nome.get(normalizar(atendimento.nome_profissional), [])
        if len(candidatos) == 1:
            atendimento.profissional_id = candidatos[0]
            atendimento.save(update_fields=["profissional"])
            casados += 1
        elif len(candidatos) > 1:
            ambiguos += 1
        else:
            nao_casados += 1

    print(
        "[atendimentos.0005] casados=%d nao_casados=%d ambiguos=%d"
        % (casados, nao_casados, ambiguos)
    )


def reverter_profissionais(apps, schema_editor):
    """Reversão segura: apenas desfaz os vínculos criados por esta migração."""
    Atendimento = apps.get_model("atendimentos", "Atendimento")
    Atendimento.objects.update(profissional=None)


class Migration(migrations.Migration):
    dependencies = [
        ("atendimentos", "0004_atendimento_profissional"),
        ("veterinarios", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(casar_profissionais, reverter_profissionais),
    ]
