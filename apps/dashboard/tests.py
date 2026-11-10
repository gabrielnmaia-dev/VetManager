"""Testes do painel (Prompt 11).

Cobrem autenticação, agregações server-side, janela de 7 dias, variação,
ranking de serviços, alertas clínicos e agenda do dia.
"""

from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.atendimentos.models import Atendimento
from apps.pets.models import Especie, Pet
from apps.prontuario.models import Prontuario, Vacina, Vermifugacao
from apps.tutores.models import Tutor
from apps.veterinarios.models import (
    BloqueioAgenda,
    HorarioTrabalho,
    Profissional,
    Veterinario,
)

User = get_user_model()


def fazer_usuario(username, grupo):
    user = User.objects.create_user(username=username, password="senha123")
    g, _ = Group.objects.get_or_create(name=grupo)
    user.groups.add(g)
    return user


class DashboardTests(TestCase):
    def setUp(self):
        self.admin = fazer_usuario("admin_dash", "admin")
        self.recepcao = fazer_usuario("rec_dash", "recepcao")

        self.tutor = Tutor.objects.create(
            nome="Tutor Painel", telefone="11 97777-0000"
        )
        self.especie, _ = Especie.objects.get_or_create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, nome="Rex Painel", especie=self.especie
        )
        self.outro_pet = Pet.objects.create(
            tutor=self.tutor, nome="Mia Painel", especie=self.especie
        )
        self.profissional = Profissional.objects.create(
            nome="Dra. Painel", cargo="Veterinário"
        )
        self.veterinario = Veterinario.objects.create(
            profissional=self.profissional,
            crmv="CRMV-DASH-1",
            especialidade="Clínica",
        )
        self.client = APIClient()
        self.hoje = timezone.localdate()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def autenticar(self, user=None):
        self.client.force_authenticate(user or self.admin)
        return self.client

    def quando(self, dia, hora=9, minuto=0):
        naive = datetime.combine(dia, time(hora, minuto))
        return timezone.make_aware(naive)

    def criar_atendimento(
        self,
        dia=None,
        hora=9,
        minuto=0,
        status=None,
        tipo_servico=None,
        **extra,
    ):
        dados = {
            "pet": self.pet,
            "tipo_servico": tipo_servico or Atendimento.TipoServico.CONSULTA,
            "data_hora_inicio": self.quando(dia or self.hoje, hora, minuto),
        }
        if status:
            dados["status"] = status
        dados.update(extra)
        return Atendimento.objects.create(**dados)

    def criar_prontuario(self, **extra):
        dados = {
            "pet": self.pet,
            "veterinario": self.veterinario,
            "data_consulta": self.quando(self.hoje),
        }
        dados.update(extra)
        return Prontuario.objects.create(**dados)

    def criar_vacina(self, **extra):
        dados = {
            "pet": self.pet,
            "nome_vacina": "V10",
            "data_aplicacao": self.hoje - timedelta(days=30),
        }
        dados.update(extra)
        return Vacina.objects.create(**dados)

    def criar_vermifugacao(self, **extra):
        dados = {
            "pet": self.pet,
            "produto": "Vermifugo X",
            "data_aplicacao": self.hoje - timedelta(days=30),
        }
        dados.update(extra)
        return Vermifugacao.objects.create(**dados)

    # ------------------------------------------------------------------
    # Autenticação e RBAC
    # ------------------------------------------------------------------
    def test_exige_autenticacao(self):
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertEqual(resposta.status_code, 401)

    def test_recepcao_pode_consultar_painel(self):
        self.autenticar(self.recepcao)
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["perfil"], "recepcao")

    # ------------------------------------------------------------------
    # KPIs e soft delete
    # ------------------------------------------------------------------
    def test_kpis_basicos_e_exclusao_logica(self):
        self.criar_atendimento(status=Atendimento.Status.AGENDADO)
        self.criar_atendimento(hora=10, status=Atendimento.Status.REALIZADO)
        excluido = self.criar_atendimento(hora=11)
        excluido.delete()

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["usuario"], "admin_dash")
        self.assertEqual(resposta.data["atendimentos_hoje"], 2)
        self.assertEqual(resposta.data["atendimentos_pendentes"], 1)
        self.assertEqual(resposta.data["total_pets"], 2)
        self.assertEqual(resposta.data["total_tutores"], 1)

    # ------------------------------------------------------------------
    # Série semanal e variação
    # ------------------------------------------------------------------
    def test_serie_semanal_completa_com_dias_sem_atendimento(self):
        self.criar_atendimento(
            dia=self.hoje, status=Atendimento.Status.REALIZADO
        )
        self.criar_atendimento(
            dia=self.hoje,
            hora=10,
            status=Atendimento.Status.AGENDADO,
        )
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=2),
            status=Atendimento.Status.CONFIRMADO,
        )
        # Fora da janela de 7 dias.
        self.criar_atendimento(dia=self.hoje - timedelta(days=10))

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        serie = resposta.data["serie_semanal"]

        self.assertEqual(len(serie), 7)
        self.assertTrue(serie[-1]["hoje"])
        self.assertEqual(serie[-1]["iso"], self.hoje.isoformat())
        self.assertEqual(serie[-1]["total"], 2)
        self.assertEqual(serie[-1]["realizados"], 1)
        self.assertEqual(serie[-1]["pendentes"], 1)
        self.assertEqual(serie[-3]["total"], 1)
        self.assertEqual(serie[-3]["pendentes"], 1)
        # Dias sem atendimento aparecem zerados, não ausentes.
        self.assertEqual(serie[0]["total"], 0)
        self.assertIn("label", serie[0])
        self.assertIn("data", serie[0])

    def test_variacao_compara_com_os_7_dias_anteriores(self):
        self.criar_atendimento(dia=self.hoje)
        self.criar_atendimento(dia=self.hoje - timedelta(days=1))
        # Dois atendimentos na janela anterior: variação de 0%.
        self.criar_atendimento(dia=self.hoje - timedelta(days=8))
        self.criar_atendimento(dia=self.hoje - timedelta(days=9))

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertEqual(resposta.data["variacao_semanal"], 0)

    def test_variacao_nula_sem_base_anterior(self):
        self.criar_atendimento(dia=self.hoje)

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertIsNone(resposta.data["variacao_semanal"])

    def test_status_semana_conta_todos_os_status_da_janela(self):
        self.criar_atendimento(status=Atendimento.Status.AGENDADO)
        self.criar_atendimento(
            hora=10, status=Atendimento.Status.REALIZADO
        )
        self.criar_atendimento(
            hora=11, status=Atendimento.Status.CANCELADO
        )
        # Fora da janela: não deve entrar na contagem.
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=10),
            status=Atendimento.Status.FALTOU,
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        por_status = {
            item["status"]: item["total"]
            for item in resposta.data["status_semana"]
        }
        self.assertEqual(
            set(por_status),
            {
                "agendado",
                "confirmado",
                "realizado",
                "cancelado",
                "faltou",
            },
        )
        self.assertEqual(por_status["agendado"], 1)
        self.assertEqual(por_status["realizado"], 1)
        self.assertEqual(por_status["cancelado"], 1)
        self.assertEqual(por_status["faltou"], 0)
        self.assertEqual(por_status["confirmado"], 0)

    # ------------------------------------------------------------------
    # Serviços
    # ------------------------------------------------------------------
    def test_servicos_mais_procurados_ultimos_30_dias(self):
        self.criar_atendimento(tipo_servico=Atendimento.TipoServico.CONSULTA)
        self.criar_atendimento(
            hora=10, tipo_servico=Atendimento.TipoServico.CONSULTA
        )
        self.criar_atendimento(
            hora=11, tipo_servico=Atendimento.TipoServico.BANHO
        )
        # Fora dos 30 dias: não deve entrar no ranking.
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=40),
            tipo_servico=Atendimento.TipoServico.TOSA,
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        servicos = resposta.data["servicos"]
        self.assertEqual(resposta.data["servicos_periodo_dias"], 30)
        self.assertEqual(servicos[0]["nome"], "Consulta")
        self.assertEqual(servicos[0]["total"], 2)
        nomes = {item["nome"] for item in servicos}
        self.assertIn("Banho", nomes)
        self.assertNotIn("Tosa", nomes)

    # ------------------------------------------------------------------
    # Alertas clínicos
    # ------------------------------------------------------------------
    def test_alertas_de_vacinas_e_vermifugacoes(self):
        vacina_atrasada = self.criar_vacina(
            nome_vacina="V8",
            data_retorno=self.hoje - timedelta(days=1),
        )
        self.criar_vacina(
            nome_vacina="V10",
            data_retorno=self.hoje + timedelta(days=10),
        )
        # Fora da janela de alerta (mais de 30 dias).
        self.criar_vacina(
            nome_vacina="Antirrábica",
            data_retorno=self.hoje + timedelta(days=60),
        )
        self.criar_vacina(
            nome_vacina="Sem retorno",
            data_retorno=None,
        )
        # Excluída logicamente: não deve contar.
        excluida = self.criar_vacina(
            nome_vacina="Excluída",
            data_retorno=self.hoje - timedelta(days=5),
        )
        excluida.delete()

        self.criar_vermifugacao(
            produto="Vermifugo Atrasado",
            data_retorno=self.hoje - timedelta(days=3),
        )
        self.criar_vermifugacao(
            produto="Vermifugo Proximo",
            data_retorno=self.hoje + timedelta(days=20),
        )
        self.criar_vermifugacao(
            produto="Vermifugo Sem Retorno",
            data_retorno=None,
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        alertas = resposta.data["alertas"]

        self.assertEqual(alertas["vacinas"]["atrasadas"], 1)
        self.assertEqual(alertas["vacinas"]["proximas"], 1)
        self.assertEqual(alertas["vermifugacoes"]["atrasadas"], 1)
        self.assertEqual(alertas["vermifugacoes"]["proximas"], 1)

        itens = alertas["itens"]
        self.assertEqual(len(itens), 4)
        datas = [item["data_retorno"] for item in itens]
        self.assertEqual(datas, sorted(datas))
        self.assertIn(vacina_atrasada.id, {item["id"] for item in itens})
        self.assertEqual(
            {item["tipo"] for item in itens},
            {"vacina", "vermifugacao"},
        )
        atrasado = next(
            item
            for item in itens
            if item["tipo"] == "vacina"
            and item["descricao"] == "V8"
        )
        self.assertEqual(atrasado["situacao"], "atrasada")
        self.assertEqual(atrasado["dias_para_retorno"], -1)
        self.assertEqual(atrasado["pet"], "Rex Painel")
        self.assertEqual(atrasado["tutor"], "Tutor Painel")

    def test_alertas_vazios_sem_registros(self):
        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        alertas = resposta.data["alertas"]
        self.assertEqual(alertas["vacinas"]["atrasadas"], 0)
        self.assertEqual(alertas["vacinas"]["proximas"], 0)
        self.assertEqual(alertas["vermifugacoes"]["atrasadas"], 0)
        self.assertEqual(alertas["vermifugacoes"]["proximas"], 0)
        self.assertEqual(alertas["itens"], [])

    # ------------------------------------------------------------------
    # Agenda do dia
    # ------------------------------------------------------------------
    def test_agenda_do_dia_ordenada_e_sem_excluidos(self):
        self.criar_atendimento(
            hora=14,
            status=Atendimento.Status.CONFIRMADO,
            profissional=self.profissional,
            nome_profissional="Legado",
        )
        self.criar_atendimento(
            hora=9,
            status=Atendimento.Status.AGENDADO,
            profissional=self.profissional,
        )
        self.criar_atendimento(
            dia=self.hoje + timedelta(days=1), hora=8
        )
        excluido = self.criar_atendimento(hora=10)
        excluido.delete()

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        agenda = resposta.data["agenda_hoje"]

        self.assertEqual(len(agenda), 2)
        self.assertEqual([item["hora"] for item in agenda], ["09:00", "14:00"])
        self.assertEqual(agenda[0]["pet"], "Rex Painel")
        self.assertEqual(agenda[0]["tutor"], "Tutor Painel")
        self.assertEqual(agenda[0]["status_display"], "Agendado")
        self.assertEqual(agenda[0]["tipo_servico_display"], "Consulta")
        self.assertEqual(agenda[0]["profissional"], "Dra. Painel")
        self.assertEqual(agenda[1]["status"], "confirmado")
        self.assertEqual(agenda[1]["profissional"], "Dra. Painel")

    def test_agenda_do_dia_respeita_filtros_de_profissional_e_tipo(self):
        outro = Profissional.objects.create(
            nome="Dr. Banho", cargo="Banhista"
        )
        self.criar_atendimento(
            hora=9,
            profissional=self.profissional,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
        )
        self.criar_atendimento(
            hora=10,
            profissional=outro,
            tipo_servico=Atendimento.TipoServico.BANHO,
        )
        self.criar_atendimento(
            hora=11,
            profissional=self.profissional,
            tipo_servico=Atendimento.TipoServico.BANHO,
        )

        self.autenticar()
        resposta = self.client.get(
            "/api/v1/dashboard/",
            {"profissional": str(outro.pk)},
        )
        self.assertEqual(len(resposta.data["agenda_hoje"]), 1)
        self.assertEqual(
            resposta.data["agenda_hoje"][0]["profissional"], "Dr. Banho"
        )

        resposta = self.client.get(
            "/api/v1/dashboard/",
            {
                "profissional": str(self.profissional.pk),
                "tipo_servico": "banho",
            },
        )
        self.assertEqual(len(resposta.data["agenda_hoje"]), 1)
        self.assertEqual(resposta.data["agenda_hoje"][0]["hora"], "11:00")

    # ------------------------------------------------------------------
    # Indicadores corrigidos e fuso horário
    # ------------------------------------------------------------------
    def test_pendentes_inclui_agendado_e_confirmado_a_partir_de_hoje(self):
        self.criar_atendimento(status=Atendimento.Status.AGENDADO)
        self.criar_atendimento(
            hora=10, status=Atendimento.Status.CONFIRMADO
        )
        self.criar_atendimento(
            dia=self.hoje + timedelta(days=1),
            status=Atendimento.Status.AGENDADO,
        )
        # Pendente no passado não entra no backlog operacional.
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=1),
            status=Atendimento.Status.AGENDADO,
        )
        self.criar_atendimento(
            hora=11, status=Atendimento.Status.REALIZADO
        )
        self.criar_atendimento(
            hora=12, status=Atendimento.Status.CANCELADO
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/operacional/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["atendimentos_pendentes"], 3)
        self.assertEqual(resposta.data["atendimentos_pendentes_hoje"], 2)
        self.assertEqual(resposta.data["atendimentos_hoje"], 4)

    def test_cancelamentos_e_faltas_respeitam_periodo_e_status(self):
        self.criar_atendimento(status=Atendimento.Status.CANCELADO)
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=1),
            status=Atendimento.Status.CANCELADO,
        )
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=40),
            status=Atendimento.Status.CANCELADO,
        )
        self.criar_atendimento(
            hora=11, status=Atendimento.Status.FALTOU
        )
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=10),
            status=Atendimento.Status.FALTOU,
        )

        self.autenticar()
        # Janela padrão de 30 dias: a exclusão de 40 dias atrás fica de fora.
        resposta = self.client.get("/api/v1/dashboard/operacional/")
        self.assertEqual(resposta.data["cancelamentos"], 2)
        self.assertEqual(resposta.data["faltas"], 2)

        # Janela explícita de 60 dias inclui o cancelamento antigo.
        inicio = (self.hoje - timedelta(days=59)).isoformat()
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/",
            {"data_inicio": inicio, "data_fim": self.hoje.isoformat()},
        )
        self.assertEqual(resposta.data["cancelamentos"], 3)
        self.assertEqual(resposta.data["faltas"], 2)

        # Filtro de status restringe os totais ao status pedido.
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/",
            {"data_inicio": inicio, "data_fim": self.hoje.isoformat(), "status": "cancelado"},
        )
        self.assertEqual(resposta.data["atendimentos_periodo"], 3)
        self.assertEqual(resposta.data["cancelamentos"], 3)
        self.assertEqual(resposta.data["faltas"], 0)
        self.assertEqual(resposta.data["realizados"], 0)
        self.assertEqual(resposta.data["atendimentos_pendentes"], 0)

    def test_atendimentos_hoje_considera_limites_do_dia_local(self):
        # 00:15 e 23:30 de hoje entram; 23:30 de ontem não.
        self.criar_atendimento(hora=0, minuto=15)
        self.criar_atendimento(hora=23, minuto=30)
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=1), hora=23, minuto=30
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertEqual(resposta.data["atendimentos_hoje"], 2)
        serie = resposta.data["serie_semanal"]
        self.assertEqual(serie[-1]["iso"], self.hoje.isoformat())
        self.assertEqual(serie[-1]["total"], 2)
        self.assertEqual(serie[-2]["total"], 1)

    def test_novos_pacientes_no_periodo(self):
        # self.pet e self.outro_pet são criados agora; envelhecemos um deles.
        Pet.objects.filter(pk=self.outro_pet.pk).update(
            criado_em=timezone.now() - timedelta(days=40)
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/operacional/")
        self.assertEqual(resposta.data["total_animais"], 2)
        self.assertEqual(resposta.data["novos_pacientes"], 1)

        inicio = (self.hoje - timedelta(days=59)).isoformat()
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/",
            {"data_inicio": inicio, "data_fim": self.hoje.isoformat()},
        )
        self.assertEqual(resposta.data["novos_pacientes"], 2)

    # ------------------------------------------------------------------
    # Filtros
    # ------------------------------------------------------------------
    def test_filtros_por_profissional_tipo_e_status(self):
        outro_profissional = Profissional.objects.create(
            nome="Dr. Banho", cargo="Banhista"
        )
        cancelado = self.criar_atendimento(
            status=Atendimento.Status.CANCELADO,
            profissional=self.profissional,
        )
        self.criar_atendimento(
            status=Atendimento.Status.AGENDADO,
            profissional=self.profissional,
            tipo_servico=Atendimento.TipoServico.CONSULTA,
        )
        self.criar_atendimento(
            hora=10,
            status=Atendimento.Status.REALIZADO,
            profissional=outro_profissional,
            tipo_servico=Atendimento.TipoServico.BANHO,
        )

        self.autenticar()
        parametros = {
            "data_inicio": self.hoje.isoformat(),
            "data_fim": self.hoje.isoformat(),
            "profissional": str(self.profissional.pk),
            "tipo_servico": "consulta",
        }
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/", parametros
        )
        self.assertEqual(resposta.data["atendimentos_periodo"], 2)
        self.assertEqual(resposta.data["realizados"], 0)
        self.assertEqual(resposta.data["atendimentos_por_profissional"][0]["nome"], "Dra. Painel")

        parametros["status"] = "cancelado"
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/", parametros
        )
        self.assertEqual(resposta.data["atendimentos_periodo"], 1)
        self.assertEqual(resposta.data["cancelamentos"], 1)

        parametros["status"] = "realizado"
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/", parametros
        )
        self.assertEqual(resposta.data["atendimentos_periodo"], 0)
        self.assertEqual(cancelado.status, Atendimento.Status.CANCELADO)

    # ------------------------------------------------------------------
    # Indicadores clínicos e por profissional
    # ------------------------------------------------------------------
    def test_retornos_pendentes_e_vacinas_proximas(self):
        self.criar_prontuario(
            retorno_recomendado=self.quando(
                self.hoje - timedelta(days=1)
            )
        )
        self.criar_prontuario(
            retorno_recomendado=self.quando(
                self.hoje + timedelta(days=5)
            )
        )
        self.criar_prontuario(
            retorno_recomendado=self.quando(
                self.hoje + timedelta(days=60)
            )
        )
        self.criar_vacina(
            data_retorno=self.hoje - timedelta(days=2),
            veterinario=self.veterinario,
        )
        self.criar_vacina(
            data_retorno=self.hoje + timedelta(days=10),
            veterinario=self.veterinario,
        )
        self.criar_vacina(
            data_retorno=self.hoje + timedelta(days=45),
            veterinario=self.veterinario,
        )
        self.criar_vermifugacao(
            data_retorno=self.hoje - timedelta(days=3),
            veterinario=self.veterinario,
        )
        self.criar_vermifugacao(
            data_retorno=self.hoje + timedelta(days=15),
            veterinario=self.veterinario,
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/operacional/")
        detalhe = resposta.data["retornos_pendentes_detalhe"]
        self.assertEqual(detalhe["prontuarios"]["atrasados"], 1)
        self.assertEqual(detalhe["prontuarios"]["proximos"], 1)
        self.assertEqual(detalhe["vacinas"]["atrasadas"], 1)
        self.assertEqual(detalhe["vacinas"]["proximas"], 1)
        self.assertEqual(detalhe["vermifugacoes"]["atrasadas"], 1)
        self.assertEqual(detalhe["vermifugacoes"]["proximas"], 1)
        self.assertEqual(resposta.data["retornos_pendentes"], 6)
        self.assertEqual(resposta.data["vacinas_proximas_vencimento"], 1)

        # O filtro de profissional considera o veterinário responsável.
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/",
            {"profissional": str(self.profissional.pk)},
        )
        self.assertEqual(resposta.data["retornos_pendentes"], 6)

    def test_atendimentos_por_profissional_e_legado(self):
        outro = Profissional.objects.create(
            nome="Dr. Banho", cargo="Banhista"
        )
        self.criar_atendimento(
            status=Atendimento.Status.REALIZADO,
            profissional=self.profissional,
        )
        self.criar_atendimento(
            hora=10,
            status=Atendimento.Status.REALIZADO,
            profissional=self.profissional,
        )
        self.criar_atendimento(
            hora=11,
            status=Atendimento.Status.CANCELADO,
            profissional=self.profissional,
        )
        self.criar_atendimento(
            hora=12,
            status=Atendimento.Status.AGENDADO,
            profissional=outro,
        )
        self.criar_atendimento(
            hora=13,
            status=Atendimento.Status.AGENDADO,
            nome_profissional="Dr. Legado",
        )

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/operacional/")
        por_nome = {
            item["nome"]: item
            for item in resposta.data["atendimentos_por_profissional"]
        }
        self.assertEqual(por_nome["Dra. Painel"]["total"], 3)
        self.assertEqual(por_nome["Dra. Painel"]["realizados"], 2)
        self.assertEqual(por_nome["Dra. Painel"]["cancelados"], 1)
        self.assertEqual(por_nome["Dra. Painel"]["percentual"], 60.0)
        self.assertEqual(por_nome["Dr. Banho"]["total"], 1)
        self.assertIn("Dr. Legado", por_nome)
        self.assertIsNone(por_nome["Dr. Legado"]["id"])

    def test_ocupacao_da_agenda_com_jornada_e_bloqueio(self):
        HorarioTrabalho.objects.create(
            profissional=self.profissional,
            dia_semana=self.hoje.weekday(),
            hora_inicio=time(8, 0),
            hora_fim=time(12, 0),
        )
        self.criar_atendimento(
            hora=8,
            status=Atendimento.Status.AGENDADO,
            duracao_minutos=30,
        )
        self.criar_atendimento(
            hora=9,
            status=Atendimento.Status.CONFIRMADO,
            duracao_minutos=30,
        )
        # Cancelado não ocupa a agenda.
        self.criar_atendimento(
            hora=10,
            status=Atendimento.Status.CANCELADO,
            duracao_minutos=60,
        )

        self.autenticar()
        parametros = {
            "data_inicio": self.hoje.isoformat(),
            "data_fim": self.hoje.isoformat(),
        }
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/", parametros
        )
        ocupacao = resposta.data["ocupacao_agenda"]
        self.assertEqual(ocupacao["capacidade_minutos"], 240)
        self.assertEqual(ocupacao["ocupado_minutos"], 60)
        self.assertEqual(ocupacao["percentual"], 25.0)
        self.assertEqual(ocupacao["origem_capacidade"], "horarios")

        BloqueioAgenda.objects.create(
            tipo=BloqueioAgenda.TipoBloqueio.MANUTENCAO,
            data_inicio=self.quando(self.hoje, 8),
            data_fim=self.quando(self.hoje, 9),
        )
        resposta = self.client.get(
            "/api/v1/dashboard/operacional/", parametros
        )
        ocupacao = resposta.data["ocupacao_agenda"]
        self.assertEqual(ocupacao["capacidade_minutos"], 180)
        self.assertEqual(ocupacao["percentual"], 33.3)

    # ------------------------------------------------------------------
    # Histórico e comparação
    # ------------------------------------------------------------------
    def test_historico_semanal_mensal_e_comparacao(self):
        self.criar_atendimento(status=Atendimento.Status.REALIZADO)
        self.criar_atendimento(
            hora=10, status=Atendimento.Status.AGENDADO
        )
        self.criar_atendimento(dia=self.hoje - timedelta(days=8))
        self.criar_atendimento(dia=self.hoje - timedelta(days=40))
        # Fora do período atual: base da comparação com o período anterior.
        self.criar_atendimento(dia=self.hoje - timedelta(days=50))
        self.criar_atendimento(
            dia=self.hoje - timedelta(days=51), hora=10
        )

        self.autenticar()
        inicio = (self.hoje - timedelta(days=45)).isoformat()
        resposta = self.client.get(
            "/api/v1/dashboard/historico/",
            {"data_inicio": inicio, "data_fim": self.hoje.isoformat()},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.data["total_periodo"], 4)

        self.assertEqual(
            sum(item["total"] for item in resposta.data["por_semana"]), 4
        )
        self.assertEqual(
            sum(item["total"] for item in resposta.data["por_mes"]), 4
        )
        self.assertEqual(
            sum(item["total"] for item in resposta.data["por_dia"]), 4
        )
        self.assertEqual(resposta.data["por_dia"][-1]["iso"], self.hoje.isoformat())
        self.assertEqual(
            sum(
                item["total"]
                for item in resposta.data["distribuicao_status"]
            ),
            4,
        )
        self.assertEqual(
            sum(item["total"] for item in resposta.data["servicos"]), 4
        )

        primeira_semana = resposta.data["por_semana"][0]
        self.assertEqual(
            date.fromisoformat(primeira_semana["inicio"]).weekday(), 0
        )
        self.assertRegex(
            resposta.data["por_mes"][0]["mes"], r"^\d{4}-\d{2}$"
        )

        comparacao = resposta.data["comparacao"]
        self.assertEqual(comparacao["periodo_atual"]["total"], 4)
        self.assertEqual(comparacao["periodo_anterior"]["total"], 2)
        self.assertEqual(comparacao["variacao_absoluta"], 2)
        self.assertEqual(comparacao["variacao_percentual"], 100)

    def test_dashboard_principal_inclui_blocos_novos(self):
        self.criar_atendimento(status=Atendimento.Status.REALIZADO)

        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/")
        self.assertIn("operacional", resposta.data)
        self.assertIn("historico", resposta.data)
        self.assertIn("comparacao", resposta.data)
        self.assertEqual(
            resposta.data["operacional"]["realizados"],
            resposta.data["historico"]["comparacao"]["periodo_atual"]["realizados"],
        )
        self.assertEqual(
            resposta.data["total_pets"],
            resposta.data["operacional"]["total_animais"],
        )

    # ------------------------------------------------------------------
    # Independência da paginação
    # ------------------------------------------------------------------
    def test_indicadores_nao_dependem_da_paginacao_da_lista(self):
        statuses = (
            [Atendimento.Status.REALIZADO] * 10
            + [Atendimento.Status.AGENDADO] * 5
            + [Atendimento.Status.CONFIRMADO] * 5
            + [Atendimento.Status.CANCELADO] * 3
            + [Atendimento.Status.FALTOU] * 2
        )
        for indice, status in enumerate(statuses):
            self.criar_atendimento(
                hora=indice % 24,
                minuto=(indice // 24) * 30,
                status=status,
            )

        self.autenticar()
        principal = self.client.get("/api/v1/dashboard/")
        pagina_2 = self.client.get("/api/v1/dashboard/?page=2")
        operacional = self.client.get("/api/v1/dashboard/operacional/?page=9")

        self.assertEqual(principal.data["atendimentos_hoje"], 25)
        self.assertEqual(
            principal.data["operacional"]["atendimentos_periodo"], 25
        )
        self.assertEqual(principal.data["operacional"]["realizados"], 10)
        self.assertEqual(principal.data["operacional"]["cancelamentos"], 3)
        self.assertEqual(principal.data["operacional"]["faltas"], 2)
        self.assertEqual(
            principal.data["operacional"]["atendimentos_pendentes_periodo"],
            10,
        )
        self.assertEqual(
            pagina_2.data["operacional"], principal.data["operacional"]
        )
        self.assertEqual(
            operacional.data["atendimentos_periodo"],
            principal.data["operacional"]["atendimentos_periodo"],
        )

        # A lista de atendimentos continua paginada (20 por página); o painel
        # não herda esse limite.
        lista = self.client.get("/api/v1/atendimentos/")
        self.assertEqual(lista.data["count"], 25)
        self.assertEqual(len(lista.data["results"]), 20)

    # ------------------------------------------------------------------
    # Opções de filtro e validação
    # ------------------------------------------------------------------
    def test_endpoint_de_filtros(self):
        self.autenticar()
        resposta = self.client.get("/api/v1/dashboard/filtros/")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            resposta.data["periodo_padrao"]["data_fim"],
            self.hoje.isoformat(),
        )
        self.assertIn(
            str(self.profissional.pk),
            [item["id"] for item in resposta.data["profissionais"]],
        )
        self.assertEqual(len(resposta.data["status"]), 5)
        self.assertIn(
            "consulta",
            [item["value"] for item in resposta.data["tipos_servico"]],
        )

    def test_validacao_dos_filtros(self):
        self.autenticar()
        casos = [
            ({"data_inicio": "2026-13-01"}, "data_inicio"),
            (
                {"data_inicio": "2026-11-10", "data_fim": "2026-11-01"},
                "data_fim",
            ),
            ({"status": "inexistente"}, "status"),
            ({"tipo_servico": "inexistente"}, "tipo_servico"),
            ({"profissional": "nao-e-uuid"}, "profissional"),
            (
                {
                    "data_inicio": (self.hoje - timedelta(days=400)).isoformat(),
                    "data_fim": self.hoje.isoformat(),
                },
                "data_fim",
            ),
        ]
        for parametros, campo in casos:
            with self.subTest(parametros=parametros):
                resposta = self.client.get(
                    "/api/v1/dashboard/operacional/", parametros
                )
                self.assertEqual(resposta.status_code, 400)
                self.assertIn(campo, resposta.data)

    def test_novos_endpoints_exigem_autenticacao(self):
        for rota in (
            "/api/v1/dashboard/operacional/",
            "/api/v1/dashboard/historico/",
            "/api/v1/dashboard/filtros/",
        ):
            with self.subTest(rota=rota):
                resposta = self.client.get(rota)
                self.assertEqual(resposta.status_code, 401)
