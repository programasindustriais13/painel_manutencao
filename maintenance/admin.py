from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.utils.html import format_html
from .models import (
    Sector, 
    Machine, 
    Technician, 
    OrdemServico, 
    OrdemServicoPeca,
    Allocation, 
    HistoricoPausa, 
    HistoricoEscala, 
    WhatsAppGroup, 
    AllocationProgressUpdate
)


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
# Inlines para serem exibidos dentro da Ordem de Serviço
# ---------------------------------------------------------------------------
class OrdemServicoPecaInline(admin.TabularInline):
    model = OrdemServicoPeca
    extra = 1
    fields = ('codigo', 'descricao', 'quantidade')


class AllocationInline(admin.TabularInline):
    model = Allocation
    extra = 0
    fields = ('tecnico', 'maquina', 'status', 'data_inicio', 'data_fim', 'tempo_decorrido_str')
    readonly_fields = ('tempo_decorrido_str',)
    show_change_link = True


@admin.register(OrdemServico)
class OrdemServicoAdmin(admin.ModelAdmin):
    list_display = (
        'numero_os',
        'tag',
        'descricao_equipamento',
        'maquina',
        'tipo_manutencao',
        'parou_maquina',
        'status',
        'solicitante',
        'data_hora_inicio_ocorrencia',
        'exibir_foto_abertura_thumb',
        'exibir_foto_conclusao_thumb',
    )
    list_filter = ('status', 'tipo_manutencao', 'parou_maquina', 'criticidade', 'setor', 'data_abertura')
    search_fields = ('numero_os', 'tag', 'descricao_equipamento', 'solicitante', 'motivo', 'causa', 'descricao_falha', 'maquina__nome')
    date_hierarchy = 'data_abertura'
    inlines = [OrdemServicoPecaInline, AllocationInline]
    readonly_fields = (
        'tempo_total_homem_hora_display',
        'tempo_conserto_display',
        'tempo_liquido_parada_display',
        'exibir_foto_abertura_large',
        'exibir_foto_conclusao_large',
        'exibir_foto_verso_large',
    )
    fieldsets = (
        ('1. Cabeçalho & Status Geral', {
            'fields': ('numero_os', 'status', 'criticidade', 'criado_por')
        }),
        ('2. Abertura pelo Líder (Folha Física)', {
            'fields': (
                'tag', 
                'descricao_equipamento', 
                'maquina', 
                'setor', 
                'motivo', 
                'tipo_manutencao', 
                'parou_maquina', 
                'descricao_falha', 
                'data_hora_inicio_ocorrencia', 
                'solicitante'
            )
        }),
        ('3. Execução & Fechamento pelo Técnico (Folha Física)', {
            'fields': (
                'tecnico_designado',
                'causa', 
                'descricao_servico_realizado', 
                'data_hora_inicio_conserto', 
                'data_hora_fim_conserto', 
                'visto_executante_nome', 
                'visto_executante_data'
            )
        }),
        ('4. Finalização & Aceite pelo Líder (Folha Física)', {
            'fields': (
                'data_hora_fim_ocorrencia', 
                'visto_responsavel_nome', 
                'visto_responsavel_data'
            )
        }),
        ('5. Registro Fotográfico da Folha Física', {
            'fields': (
                'foto_abertura', 'exibir_foto_abertura_large', 
                'foto_conclusao', 'exibir_foto_conclusao_large',
                'foto_verso', 'exibir_foto_verso_large'
            )
        }),
        ('6. Auditoria e Métricas de Tempo', {
            'fields': (
                'data_abertura', 
                'data_conclusao', 
                'tempo_conserto_display',
                'tempo_total_homem_hora_display', 
                'tempo_liquido_parada_display',
                'observacao_fechamento',
                'lider_assinatura_nome'
            )
        }),
    )

    def exibir_foto_abertura_thumb(self, obj):
        if obj.foto_abertura:
            return format_html('<img src="{}" style="height: 35px; max-width: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc;" />', obj.foto_abertura.url)
        return format_html('<span style="color: #999; font-size: 0.85em;">Sem foto</span>')
    exibir_foto_abertura_thumb.short_description = "Foto Abertura"

    def exibir_foto_conclusao_thumb(self, obj):
        if obj.foto_conclusao:
            return format_html('<img src="{}" style="height: 35px; max-width: 60px; object-fit: cover; border-radius: 4px; border: 1px solid #ccc;" />', obj.foto_conclusao.url)
        return format_html('<span style="color: #999; font-size: 0.85em;">Sem foto</span>')
    exibir_foto_conclusao_thumb.short_description = "Foto Conclusão"

    def exibir_foto_abertura_large(self, obj):
        if obj.foto_abertura:
            return format_html('<a href="{}" target="_blank"><img src="{}" style="max-height: 250px; max-width: 100%; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" /></a>', obj.foto_abertura.url, obj.foto_abertura.url)
        return "Nenhuma foto de abertura anexada."
    exibir_foto_abertura_large.short_description = "Visualização da Foto de Abertura"

    def exibir_foto_conclusao_large(self, obj):
        if obj.foto_conclusao:
            return format_html('<a href="{}" target="_blank"><img src="{}" style="max-height: 250px; max-width: 100%; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" /></a>', obj.foto_conclusao.url, obj.foto_conclusao.url)
        return "Nenhuma foto de conclusão anexada."
    exibir_foto_conclusao_large.short_description = "Visualização da Foto de Conclusão"

    def exibir_foto_verso_large(self, obj):
        if obj.foto_verso:
            return format_html('<a href="{}" target="_blank"><img src="{}" style="max-height: 250px; max-width: 100%; border-radius: 6px; box-shadow: 0 2px 6px rgba(0,0,0,0.15);" /></a>', obj.foto_verso.url, obj.foto_verso.url)
        return "Nenhuma foto do verso anexada."
    exibir_foto_verso_large.short_description = "Visualização da Foto do Verso"

    def tempo_total_homem_hora_display(self, obj):
        return obj.tempo_total_homem_hora_str
    tempo_total_homem_hora_display.short_description = "Tempo Total Homem-Hora"

    def tempo_conserto_display(self, obj):
        return obj.tempo_conserto_str
    tempo_conserto_display.short_description = "Duração do Conserto Físico"

    def tempo_liquido_parada_display(self, obj):
        return obj.tempo_liquido_parada_str
    tempo_liquido_parada_display.short_description = "Tempo Total de Parada"


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
    list_display = ('nome', 'matricula', 'status', 'is_active', 'perfil', 'user')
    list_filter = ('is_active', 'status', 'perfil')
    search_fields = ('nome', 'matricula', 'user__username')
    inlines = [HistoricoEscalaInline]


class HistoricoPausaInline(admin.TabularInline):
    model = HistoricoPausa
    extra = 0
    readonly_fields = ['data_pausa', 'data_retorno', 'motivo_pausa']


class AllocationProgressUpdateInline(admin.TabularInline):
    model = AllocationProgressUpdate
    extra = 0
    readonly_fields = ['autor', 'criado_em', 'descricao']
    can_delete = False


@admin.register(Allocation)
class AlocacaoAdmin(admin.ModelAdmin):
    list_display = ('ordem_servico', 'tecnico', 'maquina', 'exibir_status_real', 'usuario_operador', 'data_inicio', 'data_pausa', 'data_fim')
    list_filter = ('status', 'ordem_servico', 'usuario_operador', 'data_inicio', 'data_pausa', 'data_fim')
    search_fields = ('tecnico__nome', 'maquina__nome', 'usuario_operador__username', 'ordem_servico__numero_os')
    date_hierarchy = 'data_inicio'
    inlines = [HistoricoPausaInline, AllocationProgressUpdateInline]

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


@admin.register(AllocationProgressUpdate)
class AllocationProgressUpdateAdmin(admin.ModelAdmin):
    list_display = ("allocation", "autor", "criado_em", "descricao")
    list_filter = ("criado_em", "autor")
    search_fields = ("allocation__maquina__nome", "allocation__tecnico__nome", "descricao", "autor__username")
    date_hierarchy = "criado_em"

