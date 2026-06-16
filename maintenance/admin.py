from django.contrib import admin
from django.contrib.admin.models import LogEntry
from .models import Sector, Machine, Technician, Allocation

@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)

@admin.register(Machine)
class MaquinaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'setor', 'criticidade')
    list_filter = ('setor', 'criticidade')
    search_fields = ('nome', 'setor__nome')

@admin.register(Technician)
class TecnicoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'matricula', 'status')
    list_filter = ('status',)
    search_fields = ('nome', 'matricula')

@admin.register(Allocation)
class AlocacaoAdmin(admin.ModelAdmin):
    list_display = ('tecnico', 'maquina', 'status', 'data_inicio', 'data_pausa', 'data_fim')
    list_filter = ('status', 'data_inicio', 'data_pausa', 'data_fim')
    search_fields = ('tecnico__nome', 'maquina__nome')
    date_hierarchy = 'data_inicio'

@admin.register(LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ('action_time', 'user', 'content_type', 'object_repr', 'action_flag', 'change_message')
    list_filter = ('action_flag', 'content_type', 'user', 'action_time')
    search_fields = ('object_repr', 'change_message', 'user__username')
    date_hierarchy = 'action_time'

    # Make the LogEntry read-only in admin to keep the logs safe
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

