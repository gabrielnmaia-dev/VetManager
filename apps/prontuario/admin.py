from django.contrib import admin

from apps.prontuario.models import Prontuario, Vacina

# Register your models here.
admin.site.register(Prontuario)
admin.site.register(Vacina)