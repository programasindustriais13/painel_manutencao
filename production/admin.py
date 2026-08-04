from django.contrib import admin
from .models import (
    ProductionShift,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    ProductionCavityState,
    ProductionCavityDowntimeEvent,
    ProductionCavityMatrixHistory,
    ProductionMachineStateInterval,
    ProductionRateAggregate,
    ProductionParameterConfig,
    ProductionParameterAnomalyEvent,
)


@admin.register(ProductionShift)
class ProductionShiftAdmin(admin.ModelAdmin):
    list_display = (
        "nome",
        "horario_inicial",
        "horario_final",
        "atravessa_meia_noite",
        "percentual_meta",
        "ordem_exibicao",
        "ativo",
    )
    list_editable = ("ordem_exibicao", "percentual_meta", "ativo")
    list_filter = ("ativo", "atravessa_meia_noite")
    search_fields = ("nome",)



class ProductionCavityConfigInline(admin.TabularInline):
    model = ProductionCavityConfig
    extra = 2
    fields = (
        "ordem",
        "nome",
        "xid_matriz",
        "xid_produto",
        "xid_lote_bladder",
        "xid_producao",
        "meta_producao_manual",
        "xid_meta",
        "xid_motivo_parada",
    )


@admin.register(ProductionMachineConfig)
class ProductionMachineConfigAdmin(admin.ModelAdmin):
    list_display = (
        "machine",
        "ordem_exibicao",
        "produzindo_value",
        "stale_limit_seconds",
        "xid_status_prensa",
        "xid_abertura",
        "xid_motivo_parada_geral",
    )
    list_editable = ("ordem_exibicao", "stale_limit_seconds", "produzindo_value")
    search_fields = ("machine__nome", "xid_status_prensa", "xid_motivo_parada_geral")
    inlines = [ProductionCavityConfigInline]


@admin.register(ProductionGlobalParameter)
class ProductionGlobalParameterAdmin(admin.ModelAdmin):
    list_display = ("nome", "chave", "xid", "unidade", "ordem")
    list_editable = ("ordem", "xid", "unidade")
    search_fields = ("nome", "chave", "xid")


@admin.register(ProductionGlobalAlarm)
class ProductionGlobalAlarmAdmin(admin.ModelAdmin):
    list_display = ("nome", "chave", "xid", "ordem")
    list_editable = ("ordem", "xid")
    search_fields = ("nome", "chave", "xid")


@admin.register(ProductionCavityMatrixHistory)
class ProductionCavityMatrixHistoryAdmin(admin.ModelAdmin):
    list_display = ("cavity_config", "matrix_value", "started_at", "ended_at")
    list_filter = ("started_at", "ended_at")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "matrix_value")


@admin.register(ProductionMachineStateInterval)
class ProductionMachineStateIntervalAdmin(admin.ModelAdmin):
    list_display = ("machine_config", "state", "started_at", "ended_at", "status_raw_value")
    list_filter = ("state", "started_at", "ended_at")
    search_fields = ("machine_config__machine__nome", "state", "status_raw_value")


@admin.register(ProductionCavityState)
class ProductionCavityStateAdmin(admin.ModelAdmin):
    list_display = ("cavity_config", "estado_atual", "inicio_estado_atual", "ultimo_motivo", "updated_at")
    list_filter = ("estado_atual", "inicio_estado_atual")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "ultimo_motivo")


@admin.register(ProductionCavityDowntimeEvent)
class ProductionCavityDowntimeEventAdmin(admin.ModelAdmin):
    list_display = ("cavity_config", "inicio", "fim", "duracao_segundos", "motivo_parada", "origem")
    list_filter = ("inicio", "fim", "origem")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "motivo_parada")


@admin.register(ProductionRateAggregate)
class ProductionRateAggregateAdmin(admin.ModelAdmin):
    list_display = ("cavity_config", "produto", "matriz", "inicio_intervalo", "fim_intervalo", "minutos_produzindo", "quantidade_produzida", "taxa_pneus_hora", "quantidade_amostras")
    list_filter = ("inicio_intervalo", "produto")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "produto", "matriz")
    date_hierarchy = "inicio_intervalo"


@admin.register(ProductionParameterConfig)
class ProductionParameterConfigAdmin(admin.ModelAdmin):
    list_display = ("nome", "chave", "xid", "unidade", "limite_minimo", "limite_maximo", "tolerancia_segundos", "histerese", "ativo")
    list_filter = ("ativo", "unidade")
    search_fields = ("nome", "chave", "xid")


@admin.register(ProductionParameterAnomalyEvent)
class ProductionParameterAnomalyEventAdmin(admin.ModelAdmin):
    list_display = ("parameter_config", "machine_config", "cavity_config", "inicio", "fim", "duracao_segundos", "menor_valor", "maior_valor", "ultimo_valor", "tipo_limite")
    list_filter = ("tipo_limite", "inicio", "fim")
    search_fields = ("parameter_config__nome", "machine_config__machine__nome", "produto_snapshot", "matriz_snapshot")
    date_hierarchy = "inicio"




