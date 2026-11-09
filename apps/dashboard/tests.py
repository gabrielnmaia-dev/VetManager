"""Testes do painel (Prompt 11).

Cobrem autenticação, agregações server-side, janela de 7 dias, variação,
ranking de serviços, alertas clínicos e agenda do dia.
"""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.atendimentos.models import Atendimento
from apps.pets.models import Especie, Pet
from apps.prontuario.models import Vacina, Vermifugacao
from apps.tutores.models import Tutor
from apps.veterinarios.models import Profissional, Veterinario

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

    def quando(self, dia, hora=9):
        naive = datetime.combine(dia, time(hora, 0))
        return timezone.make_aware(naive)

    def criar_atendimento(
        self, dia=None, hora=9, status=None, tipo_servico=None, **extra
    ):
        dados = {
            "pet": self.pet,
            "tipo_servico": tipo_servico or Atendimento.TipoServico.CONSULTA,
            "data_hora_inicio": self.quando(dia or self.hoje, hora),
        }
        if status:
            dados["status"] = status
        dados.update(extra)
        return Atendimento.objects.create(**dados)

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
