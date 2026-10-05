from django.contrib import admin
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


@admin.register(ProdutoBladder)
class ProdutoBladderAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'descricao', 'matriz_extrusao', 'peso_tarugo_kg', 'peso_vulcanizado_kg', 'status', 'ativo')
    list_filter = ('status', 'ativo', 'matriz_extrusao')
    search_fields = ('codigo', 'descricao', 'nomenclatura_antiga')


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
        'autor', 'status', 'created_at'
    )
    list_filter = ('tipo', 'categoria', 'prioridade', 'status', 'turma_origem', 'turma_destino')
    search_fields = ('mensagem', 'autor__username', 'autor__first_name', 'ordem_producao__numero_ordem')
    date_hierarchy = 'data_turno_origem'
    raw_id_fields = ('autor', 'ordem_producao', 'processo', 'maquina', 'produto', 'mensagem_origem', 'resolvido_por', 'repassado_por')
    inlines = [AcaoMensagemTurnoInline]


@admin.register(AcaoMensagemTurnoBladder)
class AcaoMensagemTurnoBladderAdmin(admin.ModelAdmin):
    list_display = ('mensagem', 'usuario', 'acao', 'observacao', 'created_at')
    list_filter = ('acao', 'created_at')
    search_fields = ('mensagem__mensagem', 'usuario__username', 'usuario__first_name', 'observacao')
    raw_id_fields = ('mensagem', 'usuario')


