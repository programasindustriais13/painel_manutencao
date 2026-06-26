from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.utils.html import format_html
from .models import Sector, Machine, Technician, Allocation, HistoricoPausa, HistoricoEscala, WhatsAppGroup


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)


@admin.register(Machine)
class MaquinaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'setor', 'criticidade')
    list_filter = ('setor', 'criticidade')
    search_fields = ('nome', 'setor__nome')


# ---------------------------------------------------------------------------
# Inline: exibe o histórico de escalas diretamente na ficha do Técnico
# ---------------------------------------------------------------------------
class HistoricoEscalaInline(admin.TabularInline):
    model = HistoricoEscala
    extra = 0
    readonly_fields = ('status_definido_label', 'data_alteracao', 'usuario_responsavel')
    fields = ('status_definido_label', 'data_alteracao', 'usuario_responsavel')
    ordering = ('-data_alteracao',)
    can_delete = False

    def status_definido_label(self, obj):
        return obj.get_status_definido_display_label()
    status_definido_label.short_description = "Status Definido"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Technician)
class TecnicoAdmin(admin.ModelAdmin):
    list_display = ('nome', 'matricula', 'status', 'perfil', 'user')
    list_filter = ('status', 'perfil')
    search_fields = ('nome', 'matricula', 'user__username')
    inlines = [HistoricoEscalaInline]


class HistoricoPausaInline(admin.TabularInline):
    model = HistoricoPausa
    extra = 0
    readonly_fields = ['data_pausa', 'data_retorno', 'motivo_pausa']


@admin.register(Allocation)
class AlocacaoAdmin(admin.ModelAdmin):
    list_display = ('tecnico', 'maquina', 'exibir_status_real', 'usuario_operador', 'data_inicio', 'data_pausa', 'data_fim')
    list_filter = ('status', 'usuario_operador', 'data_inicio', 'data_pausa', 'data_fim')
    search_fields = ('tecnico__nome', 'maquina__nome', 'usuario_operador__username')
    date_hierarchy = 'data_inicio'
    inlines = [HistoricoPausaInline]

    def exibir_status_real(self, obj):
        if obj.data_fim is not None:
            return format_html('<span style="color: #2e7d32; font-weight: bold;">Concluído</span>')
        if obj.pausas.filter(data_retorno__isnull=True).exists():
            return format_html('<span style="color: #d84315; font-weight: bold;">Em Pausa</span>')
        return format_html('<span style="color: #1565c0; font-weight: bold;">Em Atendimento</span>')

    exibir_status_real.short_description = "Status Real"


# ---------------------------------------------------------------------------
# Admin dedicado ao Histórico de Escalas (listagem global de auditoria)
# ---------------------------------------------------------------------------
@admin.register(HistoricoEscala)
class HistoricoEscalaAdmin(admin.ModelAdmin):
    list_display = ('tecnico', 'status_definido_label', 'data_alteracao', 'usuario_responsavel')
    list_filter = ('data_alteracao', 'status_definido')
    search_fields = ('tecnico__nome', 'tecnico__matricula')
    date_hierarchy = 'data_alteracao'
    readonly_fields = ('tecnico', 'status_definido', 'data_alteracao', 'usuario_responsavel')
    ordering = ('-data_alteracao',)

    def status_definido_label(self, obj):
        return obj.get_status_definido_display_label()
    status_definido_label.short_description = "Status Definido"
    status_definido_label.admin_order_field = 'status_definido'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


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


@admin.register(WhatsAppGroup)
class WhatsAppGroupAdmin(admin.ModelAdmin):
    list_display = ('nome', 'jid', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('nome', 'jid')
