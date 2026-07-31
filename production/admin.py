from django.contrib import admin
from .models import (
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
)


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
