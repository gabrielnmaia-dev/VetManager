from django.contrib import admin

from apps.veterinarios.models import Profissional,Veterinario

# Register your models here.
admin.site.register(Profissional) 
admin.site.register(Veterinario)