from django.contrib import admin

from apps.prontuario.models import Prontuario, Vacina, Vermifugacao

# Register your models here.
admin.site.register(Prontuario)
admin.site.register(Vacina)
admin.site.register(Vermifugacao)