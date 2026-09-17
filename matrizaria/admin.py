from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from .models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    LoteImportacaoMatrizFisica,
    SolicitacaoServicoMatrizaria,
    CicloExecucaoMatrizaria,
    HistoricoTransicaoServicoMatrizaria,
)
from .services import AdminCascadeDeletionService


class SuperuserCascadeDeleteMixin:
    """
    Mixin para fornecer exclusão em cascata atômica e segura exclusivamente para superusuários
    no Django Admin, contornando proteções (PROTECT) de registros operacionais/treinamento
    sem enfraquecer os models no banco de dados.
    """
    actions = ["excluir_com_dependentes_action"]

    def has_delete_permission(self, request, obj=None):
        return bool(request.user and request.user.is_superuser)

    @admin.action(description="Excluir selecionados (Forçado p/ Superuser - com dependentes)")
    def excluir_com_dependentes_action(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, "Apenas superusuários podem utilizar a exclusão forçada.", level=messages.ERROR)
            return None
        if "confirmar" in request.POST:
            resultado = AdminCascadeDeletionService.excluir_objetos(queryset, request.user)
            self.message_user(
                request,
                f"Exclusão concluída com sucesso! Total de registros removidos: {resultado['total_deletados']}.",
                level=messages.SUCCESS,
            )
            return None

        context = {
            **self.admin_site.each_context(request),
            "title": "Confirmação de Exclusão Administrativa com Dependentes",
            "preview": AdminCascadeDeletionService.coletar_dependentes(queryset),
            "queryset": queryset,
            "opts": self.model._meta,
            "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
        }
        return TemplateResponse(request, "admin/matrizaria/confirm_cascade_delete.html", context)

    def delete_view(self, request, object_id, extra_context=None):
        if not request.user.is_superuser:
            raise PermissionDenied("Apenas superusuários podem excluir este registro.")
        obj = self.get_object(request, object_id)
        if obj is None:
            return redirect(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")
        if request.method == "POST" and "confirmar" in request.POST:
            resultado = AdminCascadeDeletionService.excluir_objeto(obj, request.user)
            self.message_user(
                request,
                f"Registro '{obj}' e seus dependentes foram excluídos com sucesso ({resultado['total_deletados']} itens removidos).",
                level=messages.SUCCESS,
            )
            return redirect(f"admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist")

        context = {
            **self.admin_site.each_context(request),
            "title": f"Confirmação de Exclusão: {obj}",
            "preview": AdminCascadeDeletionService.coletar_dependentes([obj]),
            "object": obj,
            "opts": self.model._meta,
            **(extra_context or {}),
        }
        return TemplateResponse(request, "admin/matrizaria/confirm_cascade_delete.html", context)


@admin.register(TipoServicoMatrizaria)
class TipoServicoMatrizariaAdmin(SuperuserCascadeDeleteMixin, admin.ModelAdmin):
    list_display = ("nome", "exige_matriz_fisica", "ativo", "ordem_exibicao")
    list_filter = ("ativo", "exige_matriz_fisica")
    search_fields = ("nome", "descricao")
    ordering = ("ordem_exibicao", "nome")


@admin.register(MatrizFisica)
class MatrizFisicaAdmin(SuperuserCascadeDeleteMixin, admin.ModelAdmin):
    list_display = (
        "nome_exibicao",
        "modelo",
        "produtos_atendidos",
        "numero_sequencial",
        "possui_dote",
        "situacao_identificacao",
        "numero_fisico_confirmado",
        "origem_cadastro",
        "ativo",
        "created_at",
    )
    list_filter = ("ativo", "situacao_identificacao", "possui_dote", "origem_cadastro", "modelo")
    search_fields = (
        "identificador_estavel",
        "numero_fisico_confirmado",
        "modelo__nome_exibicao",
        "chave_unidade_origem",
        "lote_importacao",
    )
    ordering = ("modelo__nome_exibicao", "numero_sequencial")

    def produtos_atendidos(self, obj):
        prods = obj.produtos_compativeis
        if len(prods) > 1:
            return ", ".join([p.nome_exibicao for p in prods])
        return obj.modelo.nome_exibicao
    produtos_atendidos.short_description = "Produtos Atendidos (Câmara/SC)"


@admin.register(LoteImportacaoMatrizFisica)
class LoteImportacaoMatrizFisicaAdmin(admin.ModelAdmin):
    list_display = (
        "identificacao_lote",
        "arquivo_nome",
        "responsavel",
        "simulacao",
        "data_importacao",
        "quantidade_linhas_lidas",
        "quantidade_unidades_criadas",
        "quantidade_unidades_preservadas",
        "status",
    )
    list_filter = ("simulacao", "status", "responsavel")
    search_fields = ("identificacao_lote", "arquivo_nome", "responsavel", "arquivo_hash")
    readonly_fields = (
        "identificacao_lote",
        "arquivo_nome",
        "arquivo_hash",
        "responsavel",
        "data_importacao",
        "simulacao",
        "quantidade_linhas_lidas",
        "quantidade_unidades_criadas",
        "quantidade_unidades_preservadas",
        "status",
        "linhas_origem_json",
        "ids_criados_json",
        "relatorio_execucao",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False



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
        "descricao_servico_executado",
        "matriz_fisica_snapshot",
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
        "tipo_evento",
        "status_anterior",
        "status_novo",
        "usuario",
        "usuario_nome_snapshot",
        "data_evento",
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
class SolicitacaoServicoMatrizariaAdmin(SuperuserCascadeDeleteMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "destino",
        "prensa_nome_snapshot",
        "tipo_servico_nome_snapshot",
        "status",
        "solicitado_por_nome",
        "responsavel_atribuido_nome",
        "data_solicitacao",
        "versao",
    )
    list_filter = ("status", "destino", "tipo_servico", "prensa")
    search_fields = (
        "id",
        "prensa_nome_snapshot",
        "tipo_servico_nome_snapshot",
        "descricao_solicitacao",
        "descricao_servico_executado",
    )
    inlines = [CicloExecucaoInline, HistoricoTransicaoInline]

    readonly_fields = (
        "destino",
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


@admin.register(CicloExecucaoMatrizaria)
class CicloExecucaoMatrizariaAdmin(SuperuserCascadeDeleteMixin, admin.ModelAdmin):
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

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(HistoricoTransicaoServicoMatrizaria)
class HistoricoTransicaoServicoMatrizariaAdmin(SuperuserCascadeDeleteMixin, admin.ModelAdmin):
    list_display = (
        "solicitacao",
        "tipo_evento",
        "status_anterior",
        "status_novo",
        "usuario",
        "data_evento",
    )
    list_filter = ("tipo_evento", "status_novo", "data_evento")
    search_fields = ("solicitacao__id", "observacao", "dados_modificados")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
