"""Testes das garantias transversais de ``apps.base``.

Usa ``Pet`` como modelo concreto porque os modelos de ``apps.base`` são
abstratos: o que se testa aqui é o comportamento herdado por todos os apps.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.pets.models import Especie, Pet
from apps.tutores.models import Tutor

User = get_user_model()


class SoftDeleteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="admin_base", password="senha123"
        )
        self.tutor = Tutor.objects.create(
            nome="Tutor Base", telefone="11 99999-5555"
        )
        self.especie = Especie.objects.create(nome="Cão")
        self.pet = Pet.objects.create(
            tutor=self.tutor, especie=self.especie, nome="Rex Base"
        )

    def test_delete_e_logico_e_preenche_auditoria(self):
        self.pet.delete(user=self.user)

        self.assertFalse(Pet.objects.filter(pk=self.pet.pk).exists())
        registro = Pet.all_objects.get(pk=self.pet.pk)
        self.assertTrue(registro.is_deleted)
        self.assertIsNotNone(registro.deleted_at)
        self.assertEqual(registro.deleted_by, self.user)
        self.assertFalse(registro.is_active)

    def test_restore_devolve_visao_normal(self):
        self.pet.delete(user=self.user)
        registro = Pet.all_objects.get(pk=self.pet.pk)

        registro.restore(user=self.user)

        self.assertTrue(Pet.objects.filter(pk=self.pet.pk).exists())
        self.assertFalse(registro.is_deleted)
        self.assertIsNone(registro.deleted_at)
        self.assertIsNone(registro.deleted_by)
        self.assertEqual(registro.updated_by, self.user)

    def test_hard_delete_remove_fisicamente(self):
        self.pet.hard_delete()
        self.assertFalse(Pet.all_objects.filter(pk=self.pet.pk).exists())

    def test_save_com_usuario_registra_autoria(self):
        novo = Pet(
            tutor=self.tutor, especie=self.especie, nome="Bolt Base"
        )
        novo.save(user=self.user)
        self.assertEqual(novo.created_by, self.user)
        self.assertEqual(novo.updated_by, self.user)

    def test_save_sem_usuario_nao_inventa_autoria(self):
        novo = Pet(
            tutor=self.tutor, especie=self.especie, nome="Sem Autoria"
        )
        novo.save()
        self.assertIsNone(novo.created_by)
        self.assertIsNone(novo.updated_by)
