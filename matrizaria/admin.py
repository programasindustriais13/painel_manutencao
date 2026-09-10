from django.contrib import admin
from .models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    SolicitacaoServicoMatrizaria,
    CicloExecucaoMatrizaria,
    HistoricoTransicaoServicoMatrizaria,
)


@admin.register(TipoServicoMatrizaria)
class TipoServicoMatrizariaAdmin(admin.ModelAdmin):
    list_display = ("nome", "exige_matriz_fisica", "ativo", "ordem_exibicao")
    list_filter = ("ativo", "exige_matriz_fisica")
    search_fields = ("nome", "descricao")
    ordering = ("ordem_exibicao", "nome")


@admin.register(MatrizFisica)
class MatrizFisicaAdmin(admin.ModelAdmin):
    list_display = (
        "nome_exibicao",
        "modelo",
        "numero_sequencial",
        "identificador_estavel",
        "ativo",
        "created_at",
    )
    list_filter = ("ativo", "modelo")
    search_fields = ("identificador_estavel", "modelo__nome_exibicao")
    ordering = ("modelo__nome_exibicao", "numero_sequencial")


class CicloExecucaoInline(admin.TabularInline):
    model = CicloExecucaoMatrizaria
    extra = 0
    can_delete = False
    readonly_fields = (
        "numero_ciclo",
        "usuario_inicio",
        "data_inicio",
        "usuario_fim",
        "data_fim",
        "forma_encerramento",
        "matriz_fisica_snapshot",
        "descricao_servico_executado",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class HistoricoTransicaoInline(admin.TabularInline):
    model = HistoricoTransicaoServicoMatrizaria
    extra = 0
    can_delete = False
    readonly_fields = (
        "data_evento",
        "usuario_nome_snapshot",
        "tipo_evento",
        "status_anterior",
        "status_novo",
        "observacao",
        "dados_modificados",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SolicitacaoServicoMatrizaria)
class SolicitacaoServicoMatrizariaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "prensa_nome_snapshot",
        "tipo_servico_nome_snapshot",
        "status",
        "solicitado_por_nome",
        "responsavel_atribuido_nome",
        "data_solicitacao",
        "versao",
    )
    list_filter = ("status", "tipo_servico", "prensa")
    search_fields = (
        "id",
        "prensa_nome_snapshot",
        "tipo_servico_nome_snapshot",
        "descricao_solicitacao",
        "descricao_servico_executado",
    )
    inlines = [CicloExecucaoInline, HistoricoTransicaoInline]
    actions = None

    readonly_fields = (
        "prensa",
        "tipo_servico",
        "matriz_fisica",
        "status",
        "solicitado_por",
        "data_solicitacao",
        "responsavel_atribuido",
        "responsavel_atribuido_nome",
        "data_inicio_execucao",
        "finalizado_por",
        "data_fim_execucao",
        "conferido_por",
        "conferido_por_nome",
        "data_conferencia",
        "cancelado_por",
        "cancelado_por_nome",
        "data_cancelamento",
        "motivo_cancelamento",
        "observacao_conferencia",
        "quantidade_retrabalhos",
        "versao",
        "prensa_nome_snapshot",
        "tipo_servico_nome_snapshot",
        "matriz_identificador_snapshot",
        "solicitado_por_nome",
        "descricao_solicitacao",
        "descricao_servico_executado",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CicloExecucaoMatrizaria)
class CicloExecucaoMatrizariaAdmin(admin.ModelAdmin):
    list_display = (
        "solicitacao",
        "numero_ciclo",
        "usuario_inicio",
        "data_inicio",
        "usuario_fim",
        "data_fim",
        "forma_encerramento",
    )
    list_filter = ("forma_encerramento", "data_inicio")
    search_fields = ("solicitacao__id", "descricao_servico_executado", "matriz_fisica_snapshot")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HistoricoTransicaoServicoMatrizaria)
class HistoricoTransicaoServicoMatrizariaAdmin(admin.ModelAdmin):
    list_display = (
        "solicitacao",
        "tipo_evento",
        "status_anterior",
        "status_novo",
        "usuario",
        "data_evento",
    )
    list_filter = ("tipo_evento", "status_novo", "data_evento")
    search_fields = ("solicitacao__id", "detalhes")
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
