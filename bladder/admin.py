from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.core.exceptions import PermissionDenied
from django.db import transaction
from .models import (
    ProcessoBladder,
    ConfiguracaoEscalaBladder,
    AjusteEscalaExcepcionalBladder,
    FuncionarioApoioBladder,
    PerfilOperacionalBladder,
    ProdutoBladder,
    RecursoBladder,
    OrdemProducaoBladder,
    SaldoPendenteBladder,
    ApontamentoTurnoBladder,
    FechamentoTurnoBladder,
    ItemFechamentoTurnoBladder,
    CategoriaDesvioBladder,
    HistoricoApontamentoBladder,
    HistoricoProgramacaoBladder,
    MensagemPassagemTurnoBladder,
    AcaoMensagemTurnoBladder,
    TipoAtividadeBladder,
    AtividadeTurnoBladder,
    MovimentacaoEstoqueBladder,
    HistoricoEdicaoMensagemTurnoBladder,
    ConfiguracaoWhatsAppBladder,
    EnvioWhatsAppBladder,
)


@admin.register(ProcessoBladder)
class ProcessoBladderAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nome', 'tipo', 'maquina', 'ordem_exibicao', 'ativo')
    list_filter = ('tipo', 'ativo')
    search_fields = ('codigo', 'nome')
    ordering = ('ordem_exibicao', 'codigo')


@admin.register(ConfiguracaoEscalaBladder)
class ConfiguracaoEscalaBladderAdmin(admin.ModelAdmin):
    list_display = ('data_referencia', 'turma_referencia', 'hora_inicio', 'hora_fim', 'ativo', 'updated_at')
    list_filter = ('turma_referencia', 'ativo')


@admin.register(AjusteEscalaExcepcionalBladder)
class AjusteEscalaExcepcionalBladderAdmin(admin.ModelAdmin):
    list_display = ('data', 'turma_designada', 'motivo', 'criado_por', 'created_at')
    list_filter = ('turma_designada',)
    search_fields = ('motivo',)


@admin.register(FuncionarioApoioBladder)
class FuncionarioApoioBladderAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'papel', 'tipo_escala', 'dias_semana', 'hora_inicio', 'hora_fim', 'ativo')
    list_filter = ('tipo_escala', 'ativo')
    search_fields = ('usuario__first_name', 'usuario__last_name', 'usuario__username', 'papel')
    raw_id_fields = ('usuario',)


@admin.register(PerfilOperacionalBladder)
class PerfilOperacionalBladderAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'get_nome_completo', 'turma', 'ativo', 'status_grupo_operadores', 'updated_at')
    list_filter = ('turma', 'ativo')
    search_fields = ('usuario__username', 'usuario__first_name', 'usuario__last_name', 'usuario__email')
    ordering = ('turma', 'usuario__first_name', 'usuario__username')
    raw_id_fields = ('usuario',)

    def get_nome_completo(self, obj):
        return obj.usuario.get_full_name() or obj.usuario.username
    get_nome_completo.short_description = "Nome Completo"

    def status_grupo_operadores(self, obj):
        if obj.usuario.groups.filter(name='Operadores Bladder').exists():
            return "✅ No grupo 'Operadores Bladder'"
        return "⚠️ Adicionar ao grupo 'Operadores Bladder'"
    status_grupo_operadores.short_description = "Status do Grupo"


@admin.register(TipoAtividadeBladder)
class TipoAtividadeBladderAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nome', 'categoria', 'exige_quantidade', 'exige_modelo', 'exige_conclusao', 'ordem_exibicao', 'ativo')
    list_filter = ('categoria', 'ativo', 'exige_quantidade', 'exige_modelo')
    search_fields = ('codigo', 'nome', 'descricao')
    ordering = ('ordem_exibicao', 'nome')


@admin.register(ProdutoBladder)
class ProdutoBladderAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descricao', 'estoque_atual', 'estoque_minimo', 'get_situacao', 'peso_tarugo_kg', 'peso_vulcanizado_kg', 'status', 'ativo')
    list_editable = ('estoque_minimo',)
    list_filter = ('status', 'ativo', 'matriz_extrusao')
    search_fields = ('codigo', 'descricao', 'nomenclatura_antiga')

    def get_situacao(self, obj):
        return obj.situacao_estoque_display
    get_situacao.short_description = "Situação Estoque"


@admin.register(AtividadeTurnoBladder)
class AtividadeTurnoBladderAdmin(admin.ModelAdmin):
    list_display = ('tipo_atividade', 'data_turno', 'turma', 'processo', 'quantidade', 'status', 'concluido_por', 'concluido_em')
    list_filter = ('turma', 'status', 'data_turno', 'tipo_atividade')
    search_fields = ('tipo_atividade__nome', 'observacao', 'criado_por__username')
    date_hierarchy = 'data_turno'


@admin.register(MovimentacaoEstoqueBladder)
class MovimentacaoEstoqueBladderAdmin(admin.ModelAdmin):
    list_display = ('data_hora', 'tipo', 'produto', 'quantidade', 'saldo_anterior', 'saldo_posterior', 'turma', 'usuario', 'destino')
    list_filter = ('tipo', 'turma', 'data_turno')
    search_fields = ('produto__codigo', 'destino', 'justificativa', 'usuario__username', 'lote_etiqueta')
    date_hierarchy = 'data_hora'
    readonly_fields = ('data_hora', 'saldo_anterior', 'saldo_posterior', 'created_at')


@admin.register(ConfiguracaoWhatsAppBladder)
class ConfiguracaoWhatsAppBladderAdmin(admin.ModelAdmin):
    change_form_template = 'admin/bladder/configuracaowhatsappbladder/change_form.html'
    list_display = ('horario_envio', 'habilitado', 'grupo_destino', 'numero_destino', 'dias_semana', 'ultimo_envio', 'ultimo_status')
    list_filter = ('habilitado',)
    readonly_fields = ('ultimo_envio', 'ultimo_status', 'ultimo_log', 'ultimo_disparo')

    def has_add_permission(self, request):
        return super().has_add_permission(request) and not ConfiguracaoWhatsAppBladder.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            # O formulário não deve sobrescrever controles atualizados por outro processo.
            obj.save(update_fields=['habilitado', 'grupo_destino', 'numero_destino', 'horario_envio', 'dias_semana', 'updated_at'])
        else:
            super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        context = dict(extra_context or {})
        context['ultimos_envios'] = EnvioWhatsAppBladder.objects.filter(configuracao_id=object_id)[:10]
        return super().change_view(request, object_id, form_url, context)

    def response_change(self, request, obj):
        if '_enviar_teste' in request.POST or '_consultar_envios' in request.POST:
            if not self.has_change_permission(request, obj):
                raise PermissionDenied
            from .whatsapp import enviar_resumo, consultar_envios
            if '_enviar_teste' in request.POST:
                def enviar_apos_salvar():
                    resultado = enviar_resumo(config_id=obj.pk, teste=True, usuario=request.user)
                    nivel = messages.INFO if resultado['status'] == 'em_fila' else messages.WARNING
                    self.message_user(request, resultado['mensagem'], level=nivel)
                # O admin envolve o salvamento em uma transação. Só iniciar o serviço
                # depois dela: a reserva do envio precisa estar durável antes do HTTP.
                transaction.on_commit(enviar_apos_salvar)
            else:
                def consultar_apos_salvar():
                    consultar_envios(config_id=obj.pk)
                    self.message_user(request, 'Consulta concluída. Confira o histórico de envios abaixo.', level=messages.INFO)
                transaction.on_commit(consultar_apos_salvar)
            return HttpResponseRedirect(request.path)
        return super().response_change(request, obj)


@admin.register(EnvioWhatsAppBladder)
class EnvioWhatsAppBladderAdmin(admin.ModelAdmin):
    list_display = ('criado_em', 'tipo', 'destino', 'status', 'tentativas', 'solicitado_por')
    list_filter = ('tipo', 'status', 'data_referencia')
    search_fields = ('destino', 'chave')
    readonly_fields = tuple(field.name for field in EnvioWhatsAppBladder._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RecursoBladder)
class RecursoBladderAdmin(admin.ModelAdmin):
    list_display = ('categoria', 'codigo', 'nome', 'ativo')
    list_filter = ('categoria', 'ativo')
    search_fields = ('codigo', 'nome', 'descricao')


@admin.register(OrdemProducaoBladder)
class OrdemProducaoBladderAdmin(admin.ModelAdmin):
    list_display = ('numero_ordem', 'produto', 'processo', 'data_programada', 'turma_prevista', 'quantidade_planejada', 'quantidade_realizada', 'status')
    list_filter = ('status', 'turma_prevista', 'prioridade', 'processo', 'data_programada')
    search_fields = ('numero_ordem', 'produto__codigo', 'produto__descricao')
    date_hierarchy = 'data_programada'


@admin.register(SaldoPendenteBladder)
class SaldoPendenteBladderAdmin(admin.ModelAdmin):
    list_display = ('id', 'op_origem', 'produto', 'quantidade', 'status', 'op_destino', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('op_origem__numero_ordem', 'produto__codigo')


@admin.register(ApontamentoTurnoBladder)
class ApontamentoTurnoBladderAdmin(admin.ModelAdmin):
    list_display = ('ordem', 'operador', 'turma', 'data_turno', 'quantidade_realizada', 'situacao', 'data_hora_inicio')
    list_filter = ('turma', 'situacao', 'data_turno')
    search_fields = ('ordem__numero_ordem', 'operador__username', 'operador__first_name')


@admin.register(HistoricoApontamentoBladder)
class HistoricoApontamentoBladderAdmin(admin.ModelAdmin):
    list_display = ('apontamento', 'quantidade_anterior', 'quantidade_nova', 'usuario', 'created_at')
    readonly_fields = ('apontamento', 'quantidade_anterior', 'quantidade_nova', 'situacao_anterior', 'situacao_nova', 'motivo_correcao', 'usuario', 'created_at')


@admin.register(HistoricoProgramacaoBladder)
class HistoricoProgramacaoBladderAdmin(admin.ModelAdmin):
    list_display = ('ordem', 'tipo_evento', 'data_anterior', 'data_nova', 'usuario', 'created_at')
    list_filter = ('tipo_evento', 'created_at')
    search_fields = ('ordem__numero_ordem', 'motivo')
    readonly_fields = ('ordem', 'tipo_evento', 'data_anterior', 'data_nova', 'quantidade_anterior', 'quantidade_nova', 'motivo', 'usuario', 'created_at')


@admin.register(CategoriaDesvioBladder)
class CategoriaDesvioBladderAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nome', 'ordem', 'ativo')
    list_filter = ('ativo',)
    search_fields = ('codigo', 'nome')
    ordering = ('ordem', 'nome')


class ItemFechamentoTurnoInline(admin.TabularInline):
    model = ItemFechamentoTurnoBladder
    extra = 0
    readonly_fields = ('ordem', 'quantidade_programada', 'quantidade_realizada', 'saldo_gerado', 'situacao', 'motivo_completo', 'descricao_desvio', 'observacao')


@admin.register(FechamentoTurnoBladder)
class FechamentoTurnoBladderAdmin(admin.ModelAdmin):
    list_display = ('data_turno', 'turma', 'operador', 'data_hora_fechamento', 'status', 'created_at')
    list_filter = ('turma', 'status', 'data_turno')
    search_fields = ('operador__username', 'operador__first_name', 'observacoes')
    date_hierarchy = 'data_turno'
    inlines = [ItemFechamentoTurnoInline]


class HistoricoEdicaoMensagemTurnoInline(admin.TabularInline):
    model = HistoricoEdicaoMensagemTurnoBladder
    extra = 0
    readonly_fields = ('texto_anterior', 'texto_novo', 'usuario', 'created_at')


class AcaoMensagemTurnoInline(admin.TabularInline):
    model = AcaoMensagemTurnoBladder
    extra = 0
    readonly_fields = ('usuario', 'acao', 'observacao', 'created_at')


@admin.register(MensagemPassagemTurnoBladder)
class MensagemPassagemTurnoBladderAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'prioridade', 'tipo', 'categoria',
        'data_turno_origem', 'turma_origem',
        'data_turno_destino', 'turma_destino',
        'autor', 'status', 'created_at', 'editado_em'
    )
    list_filter = ('tipo', 'categoria', 'prioridade', 'status', 'turma_origem', 'turma_destino')
    search_fields = ('mensagem', 'autor__username', 'autor__first_name', 'ordem_producao__numero_ordem')
    date_hierarchy = 'data_turno_origem'
    raw_id_fields = ('autor', 'ordem_producao', 'processo', 'maquina', 'produto', 'mensagem_origem', 'resolvido_por', 'repassado_por', 'editado_por')
    inlines = [AcaoMensagemTurnoInline, HistoricoEdicaoMensagemTurnoInline]


@admin.register(AcaoMensagemTurnoBladder)
class AcaoMensagemTurnoBladderAdmin(admin.ModelAdmin):
    list_display = ('mensagem', 'usuario', 'acao', 'observacao', 'created_at')
    list_filter = ('acao', 'created_at')
    search_fields = ('mensagem__mensagem', 'usuario__username', 'usuario__first_name', 'observacao')
    raw_id_fields = ('mensagem', 'usuario')


