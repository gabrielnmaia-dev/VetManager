# Popula modelos padrão de documentos veterinários.
#
# São apenas textos de modelo (configuração), sem dados clínicos. Podem ser
# editados ou desativados pela clínica.

from django.db import migrations

MODELOS = [
    (
        "receituario",
        "Receituário padrão",
        """USO VETERINÁRIO

Paciente: {{pet_nome}} — {{pet_especie}} / {{pet_raca}}
Tutor: {{tutor_nome}}

Prescrição:

1.

Orientações ao tutor:

""",
    ),
    (
        "atestado",
        "Atestado padrão",
        """ATESTADO VETERINÁRIO

Atesto, para os devidos fins, que o animal {{pet_nome}}, da espécie {{pet_especie}}, raça {{pet_raca}}, pertencente ao tutor {{tutor_nome}}, foi atendido nesta clínica em {{atendimento_data}}.

Diagnóstico / observações:
{{prontuario_diagnostico}}

Data de emissão: {{data_emissao}}
""",
    ),
    (
        "laudo",
        "Laudo padrão",
        """LAUDO VETERINÁRIO

Animal: {{pet_nome}} — {{pet_especie}} / {{pet_raca}}
Tutor: {{tutor_nome}}
Atendimento: {{atendimento_data}}

Histórico e achados:
{{prontuario_observacoes}}

Diagnóstico:
{{prontuario_diagnostico}}

Conclusão:

""",
    ),
    (
        "encaminhamento",
        "Encaminhamento padrão",
        """ENCAMINHAMENTO

Encaminho o animal {{pet_nome}}, da espécie {{pet_especie}}, raça {{pet_raca}}, pertencente ao tutor {{tutor_nome}}, para avaliação especializada.

Motivo do encaminhamento:
{{prontuario_diagnostico}}

Observações:
{{prontuario_observacoes}}

Data de emissão: {{data_emissao}}
""",
    ),
    (
        "relatorio_clinico",
        "Relatório clínico padrão",
        """RELATÓRIO CLÍNICO

Animal: {{pet_nome}} — {{pet_especie}} / {{pet_raca}}
Tutor: {{tutor_nome}}
Atendimento: {{atendimento_data}}

Resumo do atendimento:
{{prontuario_observacoes}}

Diagnóstico:
{{prontuario_diagnostico}}

Conduta:
{{prontuario_prescricao}}

Data de emissão: {{data_emissao}}
""",
    ),
    (
        "declaracao_comparecimento",
        "Declaração de comparecimento padrão",
        """DECLARAÇÃO DE COMPARECIMENTO

Declaro que o animal {{pet_nome}}, pertencente ao tutor {{tutor_nome}}, compareceu a esta clínica em {{atendimento_data}} para atendimento veterinário.

Data de emissão: {{data_emissao}}
""",
    ),
    (
        "documento_alta",
        "Documento de alta padrão",
        """DOCUMENTO DE ALTA

O animal {{pet_nome}}, pertencente ao tutor {{tutor_nome}}, recebe alta após atendimento realizado em {{atendimento_data}}.

Orientações:
{{prontuario_observacoes}}

Prescrição:
{{prontuario_prescricao}}

Data de emissão: {{data_emissao}}
""",
    ),
]


def criar_modelos(apps, schema_editor):
    ModeloDocumento = apps.get_model("documentos", "ModeloDocumento")
    db_alias = schema_editor.connection.alias
    for tipo, nome, corpo in MODELOS:
        ModeloDocumento.objects.using(db_alias).get_or_create(
            tipo=tipo,
            nome=nome,
            versao=1,
            defaults={"corpo": corpo, "ativo": True},
        )


def remover_modelos(apps, schema_editor):
    ModeloDocumento = apps.get_model("documentos", "ModeloDocumento")
    db_alias = schema_editor.connection.alias
    for tipo, nome, corpo in MODELOS:
        # Remove apenas o texto exato semeado; modelos editados pela clínica
        # são preservados na reversão.
        ModeloDocumento.objects.using(db_alias).filter(
            tipo=tipo, nome=nome, versao=1, corpo=corpo
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("documentos", "0002_modelodocumento_documentoveterinario_and_more"),
    ]

    operations = [
        migrations.RunPython(criar_modelos, reverse_code=remover_modelos),
    ]
