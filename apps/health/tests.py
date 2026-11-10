"""Testes dos healthchecks do VetManager."""

from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.health.checks import (
    verificar_banco,
    verificar_backend,
    verificar_cache,
    verificar_worker,
    verificar_armazenamento,
    executar_readiness,
)


class HealthChecksTestCase(TestCase):
    def test_verificar_backend_ok(self):
        self.assertEqual(verificar_backend()["status"], "ok")

    def test_verificar_banco_ok(self):
        resultado = verificar_banco()
        self.assertEqual(resultado["status"], "ok")
        self.assertIn("latencia_ms", resultado)

    def test_verificar_worker_nao_configurado(self):
        self.assertEqual(verificar_worker()["status"], "nao_configurado")

    def test_verificar_cache_locmem_nao_configurado(self):
        resultado = verificar_cache()
        # Em testes o cache é LocMem; não há serviço Redis externo.
        self.assertIn(resultado["status"], ("ok", "nao_configurado"))

    def test_executar_readiness_retorna_checks_esperados(self):
        checks = executar_readiness()
        for nome in ("backend", "database", "cache", "worker", "storage"):
            self.assertIn(nome, checks)
            self.assertIn("status", checks[nome])

    @patch("apps.health.checks.connection.cursor")
    def test_verificar_banco_erro(self, mock_cursor):
        mock_cursor.side_effect = Exception("conexao recusada")
        resultado = verificar_banco()
        self.assertEqual(resultado["status"], "erro")
        self.assertEqual(resultado["erro_tipo"], "Exception")


class HealthEndpointsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_liveness_responde_ok(self):
        resposta = self.client.get("/health/")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertEqual(dados["status"], "ok")
        self.assertEqual(dados["checks"]["backend"]["status"], "ok")

    def test_readiness_responde_ok(self):
        resposta = self.client.get("/health/ready/")
        self.assertIn(resposta.status_code, (200, 503))
        dados = resposta.json()
        self.assertIn("checks", dados)
        self.assertIn("database", dados["checks"])

    def test_metrics_retorna_contadores(self):
        resposta = self.client.get("/health/metrics/")
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.json()
        self.assertIn("metricas", dados)
        self.assertIn("total_failures", dados["metricas"])
        self.assertIn("erros_500", dados["metricas"])

    def test_resposta_tem_request_id(self):
        resposta = self.client.get("/health/", HTTP_X_REQUEST_ID="abc123")
        self.assertEqual(resposta["X-Request-ID"], "abc123")
        dados = resposta.json()
        self.assertEqual(dados["request_id"], "abc123")

    @override_settings(DEBUG=False)
    def test_health_sem_cache_control(self):
        resposta = self.client.get("/health/")
        self.assertIn("no-store", resposta["Cache-Control"])
