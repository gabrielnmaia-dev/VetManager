"""Regras transacionais da internação veterinária.

* ``admitir_paciente`` bloqueia o animal e o leito antes de criar a ocupação.
* ``transferir_internacao`` encerra a ocupação atual e abre outra.
* ``dar_alta`` encerra a ocupação e grava os dados de alta.
* ``registrar_administracao`` baixa o lote como consumo clínico na mesma
  transação; o cancelamento gera devolução sem apagar o histórico.
"""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.estoque.models import Lote, MovimentacaoEstoque, Produto
from apps.estoque.services import _normalizar_quantidade, registrar_movimentacao
from apps.pets.models import Pet
from apps.prescricao.models import ItemPrescricao, Prescricao
from apps.veterinarios.models import Profissional

from .models import (
    AdministracaoMedicamentoInternacao,
    CuidadoInternacao,
    EvolucaoInternacao,
    Internacao,
    Leito,
    OcupacaoLeito,
)


def _validar_profissional(profissional, campo="profissional"):
    if profissional is None:
        raise ValidationError({campo: ["Informe o profissional responsável."]})
    if profissional.is_deleted:
        raise ValidationError({campo: ["Profissional excluído."]})


def _validar_pet(pet):
    if pet is None:
        raise ValidationError({"pet": ["Informe o animal."]})
    if pet.is_deleted:
        raise ValidationError({"pet": ["Animal excluído."]})


def _validar_atendimento(atendimento, pet):
    if atendimento is None:
        return
    if atendimento.is_deleted:
        raise ValidationError({"atendimento_origem": ["Atendimento excluído."]})
    if atendimento.pet_id != pet.pk:
        raise ValidationError(
            {"atendimento_origem": ["O atendimento pertence a outro animal."]}
        )


def _validar_prontuario(prontuario, pet):
    if prontuario is None:
        return
    if prontuario.is_deleted:
        raise ValidationError({"prontuario": ["Prontuário excluído."]})
    if prontuario.pet_id != pet.pk:
        raise ValidationError(
            {"prontuario": ["O prontuário pertence a outro animal."]}
        )


def _leito_bloqueado(leito):
    if leito is None:
        raise ValidationError({"leito": ["Informe o leito."]})
    if leito.is_deleted:
        raise ValidationError({"leito": ["Leito excluído."]})
    if leito.situacao != Leito.Situacao.ATIVO:
        raise ValidationError(
            {"leito": ["Somente leitos ativos podem receber internações."]}
        )


def _contar_ocupacoes_abertas(leito, *, ignorar_internacao=None):
    qs = OcupacaoLeito.objects.select_for_update().filter(
        leito=leito, data_saida__isnull=True, is_deleted=False
    )
    if ignorar_internacao is not None:
        qs = qs.exclude(internacao=ignorar_internacao)
    return qs.count()


def _validar_disponibilidade_leito(leito, *, ignorar_internacao=None):
    _leito_bloqueado(leito)
    capacidade = max(leito.capacidade or 1, 1)
    ocupados = _contar_ocupacoes_abertas(
        leito, ignorar_internacao=ignorar_internacao
    )
    if ocupados >= capacidade:
        raise ValidationError(
            {
                "leito": [
                    f"O leito {leito.nome} está lotado "
                    f"({ocupados}/{capacidade})."
                ]
            }
        )


def _internacao_existente(chave):
    if not chave:
        return None
    return (
        Internacao.objects.select_related(
            "pet", "prontuario", "atendimento_origem", "leito", "profissional_responsavel"
        )
        .prefetch_related("prescricoes", "documentos", "ocupacoes")
        .filter(chave_idempotencia=chave)
        .first()
    )


@transaction.atomic
def admitir_paciente(
    *,
    pet=None,
    atendimento_origem=None,
    prontuario=None,
    leito=None,
    profissional_responsavel=None,
    motivo_internacao="",
    data_hora_entrada=None,
    diagnostico_inicial="",
    estado_clinico=Internacao.EstadoClinico.ESTAVEL,
    observacoes="",
    chave_idempotencia="",
    usuario=None,
):
    """Admite o animal, cria a internação e ocupa o leito.

    Retorna ``(internacao, criada)``. Com chave de idempotência repetida,
    devolve a admissão já persistida sem ocupar outro leito.
    """
    chave = (chave_idempotencia or "").strip() or None
    existente = _internacao_existente(chave)
    if existente is not None:
        return existente, False

    if prontuario is not None:
        if prontuario.is_deleted:
            raise ValidationError({"prontuario": ["Prontuário excluído."]})
        if pet is None:
            pet = prontuario.pet
        if atendimento_origem is None:
            atendimento_origem = prontuario.atendimento
    if atendimento_origem is not None and pet is None:
        pet = atendimento_origem.pet

    _validar_pet(pet)
    _validar_atendimento(atendimento_origem, pet)
    _validar_prontuario(prontuario, pet)
    _validar_profissional(
        profissional_responsavel, campo="profissional_responsavel"
    )

    motivo_internacao = (motivo_internacao or "").strip()
    if not motivo_internacao:
        raise ValidationError(
            {"motivo_internacao": ["Informe o motivo da internação."]}
        )
    if leito is None:
        raise ValidationError({"leito": ["Informe o leito."]})

    # Serializa admissões concorrentes do mesmo animal.
    pet = (
        Pet.objects.select_for_update()
        .filter(pk=pet.pk, is_deleted=False)
        .first()
    )
    if pet is None:
        raise ValidationError({"pet": ["Animal não encontrado."]})
    if Internacao.objects.select_for_update().filter(
        pet=pet,
        status=Internacao.Status.INTERNADO,
        is_deleted=False,
    ).exists():
        raise ValidationError(
            {"pet": ["Este animal já possui uma internação ativa."]}
        )

    leito = (
        Leito.objects.select_for_update()
        .filter(pk=leito.pk, is_deleted=False)
        .first()
    )
    if leito is None:
        raise ValidationError({"leito": ["Leito não encontrado."]})
    _validar_disponibilidade_leito(leito)

    dados = {
        "pet": pet,
        "atendimento_origem": atendimento_origem,
        "prontuario": prontuario,
        "leito": leito,
        "profissional_responsavel": profissional_responsavel,
        "motivo_internacao": motivo_internacao,
        "data_hora_entrada": data_hora_entrada or timezone.now(),
        "diagnostico_inicial": diagnostico_inicial or "",
        "estado_clinico": estado_clinico or Internacao.EstadoClinico.ESTAVEL,
        "observacoes": observacoes or "",
        "chave_idempotencia": chave,
        "created_by": usuario,
        "updated_by": usuario,
    }

    try:
        with transaction.atomic():
            internacao = Internacao.objects.create(**dados)
    except IntegrityError:
        existente = _internacao_existente(chave)
        if existente is not None:
            return existente, False
        raise

    OcupacaoLeito.objects.create(
        internacao=internacao,
        leito=leito,
        data_entrada=internacao.data_hora_entrada,
        created_by=usuario,
        updated_by=usuario,
    )
    return internacao, True


@transaction.atomic
def transferir_internacao(
    *,
    internacao_id,
    novo_leito,
    motivo="",
    data_hora=None,
    usuario=None,
):
    """Transfere a internação para outro leito, preservando o histórico."""
    internacao = (
        Internacao.objects.select_for_update()
        .select_related("leito", "pet")
        .filter(pk=internacao_id, is_deleted=False)
        .first()
    )
    if internacao is None:
        raise ValidationError({"detail": "Internação não encontrada."})
    if internacao.status != Internacao.Status.INTERNADO:
        raise ValidationError(
            {"detail": "Somente internações ativas podem ser transferidas."}
        )
    if novo_leito is None:
        raise ValidationError({"leito": ["Informe o novo leito."]})
    if internacao.leito_id == novo_leito.pk:
        raise ValidationError(
            {"leito": ["A internação já está neste leito."]}
        )

    novo_leito = (
        Leito.objects.select_for_update()
        .filter(pk=novo_leito.pk, is_deleted=False)
        .first()
    )
    if novo_leito is None:
        raise ValidationError({"leito": ["Leito não encontrado."]})
    _validar_disponibilidade_leito(novo_leito)

    data_saida = data_hora or timezone.now()
    motivo = (motivo or "").strip() or "Transferência de leito"

    ocupacoes = OcupacaoLeito.objects.select_for_update().filter(
        internacao=internacao, data_saida__isnull=True, is_deleted=False
    )
    for ocupacao in ocupacoes:
        ocupacao.data_saida = data_saida
        ocupacao.motivo_saida = motivo
        ocupacao.save(
            user=usuario,
            update_fields=[
                "data_saida",
                "motivo_saida",
                "updated_at",
                "updated_by",
            ],
        )

    OcupacaoLeito.objects.create(
        internacao=internacao,
        leito=novo_leito,
        data_entrada=data_saida,
        created_by=usuario,
        updated_by=usuario,
    )
    internacao.leito = novo_leito
    internacao.save(
        user=usuario,
        update_fields=["leito", "updated_at", "updated_by"],
    )
    return internacao


@transaction.atomic
def registrar_evolucao(
    *,
    internacao=None,
    profissional=None,
    evolucao_clinica="",
    data_hora=None,
    observacoes="",
    intercorrencias="",
    peso=None,
    temperatura=None,
    frequencia_cardiaca=None,
    frequencia_respiratoria=None,
    pressao_arterial="",
    saturacao=None,
    glicemia=None,
    escore_corporal=None,
    usuario=None,
):
    """Registra uma evolução sem alterar evoluções anteriores."""
    if internacao is None:
        raise ValidationError({"internacao": ["Informe a internação."]})
    if internacao.is_deleted:
        raise ValidationError({"internacao": ["Internação excluída."]})
    if internacao.status != Internacao.Status.INTERNADO:
        raise ValidationError(
            {"internacao": ["Somente internações ativas recebem evolução."]}
        )
    _validar_profissional(profissional)
    evolucao_clinica = (evolucao_clinica or "").strip()
    if not evolucao_clinica:
        raise ValidationError(
            {"evolucao_clinica": ["Descreva a evolução clínica."]}
        )
    if saturacao is not None and not (0 <= saturacao <= 100):
        raise ValidationError(
            {"saturacao": ["A saturação deve estar entre 0 e 100."]}
        )

    return EvolucaoInternacao.objects.create(
        internacao=internacao,
        profissional=profissional,
        data_hora=data_hora or timezone.now(),
        evolucao_clinica=evolucao_clinica,
        observacoes=observacoes or "",
        intercorrencias=intercorrencias or "",
        peso=peso,
        temperatura=temperatura,
        frequencia_cardiaca=frequencia_cardiaca,
        frequencia_respiratoria=frequencia_respiratoria,
        pressao_arterial=(pressao_arterial or "").strip(),
        saturacao=saturacao,
        glicemia=glicemia,
        escore_corporal=escore_corporal,
        created_by=usuario,
        updated_by=usuario,
    )


@transaction.atomic
def registrar_cuidado(
    *,
    internacao=None,
    tipo,
    descricao="",
    profissional=None,
    data_hora=None,
    observacoes="",
    usuario=None,
):
    """Registra alimentação, hidratação, procedimento, monitoramento etc."""
    if internacao is None:
        raise ValidationError({"internacao": ["Informe a internação."]})
    if internacao.status != Internacao.Status.INTERNADO:
        raise ValidationError(
            {"internacao": ["Somente internações ativas recebem cuidados."]}
        )
    if tipo not in CuidadoInternacao.Tipo.values:
        raise ValidationError({"tipo": ["Tipo de cuidado inválido."]})
    descricao = (descricao or "").strip()
    if not descricao:
        raise ValidationError({"descricao": ["Descreva o cuidado realizado."]})
    _validar_profissional(profissional)

    return CuidadoInternacao.objects.create(
        internacao=internacao,
        tipo=tipo,
        descricao=descricao,
        profissional=profissional,
        data_hora=data_hora or timezone.now(),
        observacoes=observacoes or "",
        created_by=usuario,
        updated_by=usuario,
    )


def _validar_produto_medicamento(produto):
    if produto is None:
        raise ValidationError({"produto": ["Informe o medicamento."]})
    if produto.is_deleted:
        raise ValidationError({"produto": ["Medicamento excluído."]})
    if not produto.ativo:
        raise ValidationError({"produto": ["Medicamento inativo."]})
    if not produto.is_medicamento:
        raise ValidationError(
            {"produto": ["Selecione um produto da categoria Medicamento."]}
        )
    if produto.tipo_estoque != Produto.TipoEstoque.CLINICO:
        raise ValidationError(
            {
                "produto": [
                    "Somente medicamentos do estoque clínico podem ser "
                    "administrados na internação."
                ]
            }
        )
    if not produto.controla_estoque:
        raise ValidationError(
            {"produto": ["Este medicamento não controla estoque."]}
        )


def _administracao_existente(chave):
    if not chave:
        return None
    return (
        AdministracaoMedicamentoInternacao.objects.select_related(
            "internacao", "pet", "produto", "lote", "profissional", "prescricao"
        )
        .filter(chave_idempotencia=chave)
        .first()
    )


@transaction.atomic
def registrar_administracao(
    *,
    internacao=None,
    item_prescricao=None,
    produto=None,
    lote=None,
    profissional=None,
    quantidade=None,
    dose="",
    via="",
    data_hora=None,
    observacoes="",
    chave_idempotencia="",
    usuario=None,
):
    """Registra a medicação administrada e baixa o lote no estoque."""
    chave = (chave_idempotencia or "").strip() or None
    existente = _administracao_existente(chave)
    if existente is not None:
        return existente, False

    if internacao is None:
        raise ValidationError({"internacao": ["Informe a internação."]})
    internacao = (
        Internacao.objects.select_for_update()
        .select_related("pet", "leito")
        .filter(pk=internacao.pk, is_deleted=False)
        .first()
    )
    if internacao is None:
        raise ValidationError({"internacao": ["Internação não encontrada."]})
    if internacao.status != Internacao.Status.INTERNADO:
        raise ValidationError(
            {"internacao": ["Somente internações ativas recebem medicação."]}
        )

    prescricao = None
    if item_prescricao is not None:
        item = (
            ItemPrescricao.objects.select_for_update()
            .select_related("produto", "prescricao__pet", "prescricao__atendimento")
            .filter(pk=item_prescricao.pk, is_deleted=False)
            .first()
        )
        if item is None:
            raise ValidationError(
                {"item_prescricao": ["Item de prescrição não encontrado."]}
            )
        prescricao = (
            Prescricao.objects.select_for_update()
            .select_related("pet", "atendimento", "veterinario__profissional")
            .filter(pk=item.prescricao_id, is_deleted=False)
            .first()
        )
        if prescricao is None:
            raise ValidationError(
                {"item_prescricao": ["Prescrição não encontrada."]}
            )
        if prescricao.status != Prescricao.Status.ATIVA:
            raise ValidationError(
                {
                    "item_prescricao": [
                        "Não é possível administrar item de uma prescrição cancelada."
                    ]
                }
            )
        if prescricao.pet_id != internacao.pet_id:
            raise ValidationError(
                {"item_prescricao": ["O item pertence a outro animal."]}
            )
        if produto is not None and produto.pk != item.produto_id:
            raise ValidationError(
                {"produto": ["O medicamento não corresponde ao item prescrito."]}
            )
        produto = item.produto
        if not dose:
            dose = item.dose
        if not via:
            via = item.via
        if profissional is None and prescricao.veterinario_id:
            profissional = prescricao.veterinario.profissional

    if produto is None and lote is not None:
        produto = lote.produto
    if lote is None:
        raise ValidationError({"lote": ["Informe o lote utilizado."]})
    lote = (
        Lote.objects.select_related("produto")
        .filter(pk=lote.pk, is_deleted=False)
        .first()
    )
    if lote is None:
        raise ValidationError({"lote": ["Lote não encontrado."]})
    if produto is None:
        produto = lote.produto
    if lote.produto_id != produto.pk:
        raise ValidationError(
            {"lote": ["O lote informado não pertence ao medicamento selecionado."]}
        )
    _validar_produto_medicamento(produto)
    _validar_profissional(profissional)

    quantidade = _normalizar_quantidade(quantidade)

    dados = {
        "internacao": internacao,
        "pet": internacao.pet,
        "item_prescricao": item_prescricao,
        "prescricao": prescricao,
        "produto": produto,
        "lote": lote,
        "profissional": profissional,
        "quantidade": quantidade,
        "dose": (dose or "").strip(),
        "via": via or "oral",
        "data_hora": data_hora or timezone.now(),
        "observacoes": observacoes or "",
        "chave_idempotencia": chave,
        "created_by": usuario,
        "updated_by": usuario,
    }

    try:
        with transaction.atomic():
            administracao = AdministracaoMedicamentoInternacao.objects.create(
                **dados
            )
    except IntegrityError:
        existente = _administracao_existente(chave)
        if existente is not None:
            return existente, False
        raise

    movimentacao = registrar_movimentacao(
        produto=produto,
        lote=lote,
        tipo=MovimentacaoEstoque.Tipo.CONSUMO_CLINICO,
        quantidade=quantidade,
        motivo=f"Administração na internação {internacao.id}",
        atendimento=internacao.atendimento_origem,
        documento_referencia=str(administracao.id),
        usuario=usuario,
    )
    administracao.movimentacao = movimentacao
    administracao.save(
        user=usuario,
        update_fields=["movimentacao", "updated_at", "updated_by"],
    )
    return administracao, True


@transaction.atomic
def cancelar_administracao(*, administracao_id, motivo, usuario=None):
    """Cancela a administração e devolve a quantidade ao lote original."""
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValidationError(
            {"motivo": ["Informe o motivo do cancelamento/estorno."]}
        )
    administracao = (
        AdministracaoMedicamentoInternacao.objects.select_for_update()
        .select_related("internacao", "pet", "produto", "lote")
        .filter(pk=administracao_id, is_deleted=False)
        .first()
    )
    if administracao is None:
        raise ValidationError(
            {"detail": "Administração de medicamento não encontrada."}
        )
    if administracao.status == AdministracaoMedicamentoInternacao.Status.CANCELADA:
        raise ValidationError(
            {"detail": "Esta administração já foi cancelada."}
        )

    estorno = registrar_movimentacao(
        produto=administracao.produto,
        lote=administracao.lote,
        tipo=MovimentacaoEstoque.Tipo.DEVOLUCAO,
        quantidade=administracao.quantidade,
        motivo=f"Estorno da administração {administracao.id}: {motivo}",
        atendimento=administracao.internacao.atendimento_origem,
        documento_referencia=str(administracao.id),
        usuario=usuario,
    )
    administracao.status = AdministracaoMedicamentoInternacao.Status.CANCELADA
    administracao.motivo_cancelamento = motivo
    administracao.cancelada_em = timezone.now()
    administracao.cancelada_por = usuario
    administracao.estorno_movimentacao = estorno
    administracao.save(
        user=usuario,
        update_fields=[
            "status",
            "motivo_cancelamento",
            "cancelada_em",
            "cancelada_por",
            "estorno_movimentacao",
            "updated_at",
            "updated_by",
        ],
    )
    return administracao


def _validar_prescricoes_alta(internacao, prescricoes):
    if prescricoes is None:
        return None
    prescricoes = list(prescricoes)
    for prescricao in prescricoes:
        if prescricao.is_deleted:
            raise ValidationError(
                {"prescricoes": ["Prescrição excluída."]}
            )
        if prescricao.pet_id != internacao.pet_id:
            raise ValidationError(
                {"prescricoes": ["Todas as prescrições devem ser do mesmo animal."]}
            )
    return prescricoes


def _validar_documentos_alta(internacao, documentos):
    if documentos is None:
        return None
    documentos = list(documentos)
    for documento in documentos:
        if documento.is_deleted:
            raise ValidationError({"documentos": ["Documento excluído."]})
        if documento.pet_id != internacao.pet_id:
            raise ValidationError(
                {"documentos": ["Todos os documentos devem ser do mesmo animal."]}
            )
    return documentos


@transaction.atomic
def dar_alta(
    *,
    internacao_id,
    profissional_alta=None,
    data_hora_alta=None,
    condicao_alta="",
    orientacoes_tutor="",
    resumo_internacao="",
    prescricoes=None,
    documentos=None,
    usuario=None,
):
    """Encerra a internação, libera o leito e grava os dados de alta."""
    internacao = (
        Internacao.objects.select_for_update()
        .select_related("pet", "leito")
        .filter(pk=internacao_id, is_deleted=False)
        .first()
    )
    if internacao is None:
        raise ValidationError({"detail": "Internação não encontrada."})
    if internacao.status != Internacao.Status.INTERNADO:
        raise ValidationError(
            {"detail": "Somente internações ativas podem receber alta."}
        )
    _validar_profissional(profissional_alta, campo="profissional_alta")
    prescricoes = _validar_prescricoes_alta(internacao, prescricoes)
    documentos = _validar_documentos_alta(internacao, documentos)

    data_hora_alta = data_hora_alta or timezone.now()
    ocupacoes = OcupacaoLeito.objects.select_for_update().filter(
        internacao=internacao, data_saida__isnull=True, is_deleted=False
    )
    for ocupacao in ocupacoes:
        ocupacao.data_saida = data_hora_alta
        ocupacao.motivo_saida = "Alta"
        ocupacao.save(
            user=usuario,
            update_fields=[
                "data_saida",
                "motivo_saida",
                "updated_at",
                "updated_by",
            ],
        )

    internacao.status = Internacao.Status.ALTA
    internacao.data_hora_alta = data_hora_alta
    internacao.profissional_alta = profissional_alta
    internacao.condicao_alta = condicao_alta or ""
    internacao.orientacoes_tutor = orientacoes_tutor or ""
    internacao.resumo_internacao = resumo_internacao or ""
    internacao.save(
        user=usuario,
        update_fields=[
            "status",
            "data_hora_alta",
            "profissional_alta",
            "condicao_alta",
            "orientacoes_tutor",
            "resumo_internacao",
            "updated_at",
            "updated_by",
        ],
    )

    if prescricoes is not None:
        internacao.prescricoes.set(prescricoes)
    if documentos is not None:
        internacao.documentos.set(documentos)
    return internacao
