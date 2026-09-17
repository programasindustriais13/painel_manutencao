from django import forms
from django.contrib import admin
from .models import (
    ProductionShift,
    ProductionMachineConfig,
    ProductionCavityConfig,
    ProductionGlobalParameter,
    ProductionGlobalAlarm,
    WhatsAppAlertRecipient,
    ProductionCavityState,
    ProductionCavityDowntimeEvent,
    ProductionCavityMatrixHistory,
    ProductionMachineStateInterval,
    ProductionRateAggregate,
    ProductionParameterConfig,
    ProductionParameterAnomalyEvent,
    ProductionCycle,
    ProductionShiftAccumulated,
    ProductionMatrixCatalog,
    ProductionTarget,
    ProductionMatrixSize,
    ProductionBladder,
    ProductionPCPSetting,
    ProductionPCPPlan,
    ProductionPCPPlanShiftTarget,
    ProductionPCPPlanHistory,
    ProductionBladderUsage,
    ProductionBladderSetupMismatchEvent,
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



class ProductionCavityConfigAdminForm(forms.ModelForm):
    meta_producao_manual = forms.IntegerField(
        required=False,
        initial=0,
        label="Meta Manual de Produção (Legado / Opcional)",
        help_text="Campo legado. As novas metas devem ser definidas pela Programação PCP."
    )

    class Meta:
        model = ProductionCavityConfig
        fields = "__all__"

    def clean_meta_producao_manual(self):
        val = self.cleaned_data.get("meta_producao_manual")
        if val is None or val == "":
            return 0
        return val


class ProductionCavityConfigInline(admin.TabularInline):
    model = ProductionCavityConfig
    form = ProductionCavityConfigAdminForm
    extra = 2
    fields = (
        "ordem",
        "nome",
        "xid_matriz",
        "xid_produto",
        "xid_lote_bladder",
        "xid_bla_real",
        "xid_producao",
        "meta_producao_manual",
        "xid_meta",
        "xid_motivo_parada",
        "xid_motivo_troca_bladder",
    )


@admin.register(ProductionCavityConfig)
class ProductionCavityConfigAdmin(admin.ModelAdmin):
    form = ProductionCavityConfigAdminForm
    list_display = (
        "machine_config",
        "nome",
        "ordem",
        "xid_matriz",
        "xid_produto",
        "xid_lote_bladder",
        "xid_bla_real",
        "xid_producao",
        "meta_producao_manual",
        "xid_meta",
        "xid_motivo_parada",
        "xid_motivo_troca_bladder",
    )
    list_editable = ("ordem", "meta_producao_manual")
    search_fields = (
        "nome",
        "machine_config__machine__nome",
        "xid_matriz",
        "xid_produto",
        "xid_lote_bladder",
        "xid_bla_real",
        "xid_producao",
        "xid_meta",
    )
    list_filter = ("machine_config__machine",)
    fieldsets = (
        ("Identificação", {
            "fields": ("machine_config", "nome", "ordem")
        }),
        ("Telemetria e Mapeamento Scada", {
            "fields": (
                "xid_matriz",
                "xid_produto",
                "xid_lote_bladder",
                "xid_bla_real",
                "xid_producao",
                "xid_motivo_parada",
                "xid_motivo_troca_bladder",
            )
        }),
        ("Metas e Limites de Produção", {
            "fields": (
                "meta_producao_manual",
                "xid_meta",
            )
        }),
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


@admin.register(WhatsAppAlertRecipient)
class WhatsAppAlertRecipientAdmin(admin.ModelAdmin):
    list_display = ("nome", "telefone", "telefone_normalizado_display", "ativo", "criado_em")
    list_filter = ("ativo", "criado_em")
    search_fields = ("nome", "telefone")
    list_editable = ("ativo",)

    def telefone_normalizado_display(self, obj):
        return obj.telefone_normalizado
    telefone_normalizado_display.short_description = "WhatsApp Formatado"


class ProductionGlobalAlarmAdminForm(forms.ModelForm):
    class Meta:
        model = ProductionGlobalAlarm
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        vmin = cleaned_data.get("valor_minimo")
        vmax = cleaned_data.get("valor_maximo")
        if vmin is None and vmax is None:
            raise forms.ValidationError("Pelo menos um limite (mínimo ou máximo) deve ser configurado.")
        if vmin is not None and vmax is not None and vmin >= vmax:
            raise forms.ValidationError("O valor mínimo deve ser estritamente menor que o valor máximo.")
        return cleaned_data


@admin.register(ProductionGlobalAlarm)
class ProductionGlobalAlarmAdmin(admin.ModelAdmin):
    form = ProductionGlobalAlarmAdminForm
    list_display = (
        "nome",
        "xid",
        "faixa_permitida_display",
        "delay_segundos",
        "intervalo_repeticao_minutos",
        "habilitado",
        "total_destinos",
        "estado_atual",
        "ultima_leitura_display",
    )
    list_filter = ("habilitado", "estado_atual", "intervalo_repeticao_minutos")
    search_fields = ("nome", "chave", "xid")
    filter_horizontal = ("destinatarios", "grupos")
    actions = ["testar_xid_action"]

    fieldsets = (
        ("Identificação Básica", {
            "fields": ("nome", "chave", "descricao", "ordem", "habilitado")
        }),
        ("Telemetria SCADA (XID)", {
            "fields": ("xid", "unidade")
        }),
        ("Limites e Faixa Permitida", {
            "fields": ("valor_minimo", "valor_maximo"),
            "description": "Configure pelo menos um dos limites. Se ambos forem definidos, o mínimo deve ser menor que o máximo."
        }),
        ("Temporização e Anti-Oscilação", {
            "fields": ("delay_segundos", "intervalo_repeticao_minutos"),
            "description": "Delay antes do alerta: tempo que o valor precisa permanecer continuamente fora da faixa antes do primeiro envio. Repetição: intervalo mínimo entre notificações enquanto continuar fora."
        }),
        ("Destinatários WhatsApp", {
            "fields": ("destinatarios", "grupos", "notificar_normalizacao")
        }),
        ("Telemetria e Estado do Monitor", {
            "fields": (
                "estado_atual",
                "ultima_leitura_valor",
                "ultima_leitura_timestamp",
                "inicio_fora_faixa",
                "ultimo_alerta_enviado_em",
                "alerta_inicial_enviado",
                "ultima_normalizacao_em",
            ),
            "classes": ("collapse",)
        }),
    )

    readonly_fields = (
        "estado_atual",
        "ultima_leitura_valor",
        "ultima_leitura_timestamp",
        "inicio_fora_faixa",
        "ultimo_alerta_enviado_em",
        "alerta_inicial_enviado",
        "ultima_normalizacao_em",
    )

    def faixa_permitida_display(self, obj):
        return obj.faixa_formatada
    faixa_permitida_display.short_description = "Faixa Permitida"

    def total_destinos(self, obj):
        n_ind = obj.destinatarios.count()
        n_grp = obj.grupos.count()
        return f"{n_ind} indiv. / {n_grp} grupo(s)"
    total_destinos.short_description = "Destinatários"

    def ultima_leitura_display(self, obj):
        if obj.ultima_leitura_valor is not None:
            u = f" {obj.unidade}" if obj.unidade else ""
            return f"{obj.ultima_leitura_valor:.1f}{u}"
        return "Sem leitura"
    ultima_leitura_display.short_description = "Última Leitura"

    @admin.action(description="Testar leitura de XID no Scada-LTS")
    def testar_xid_action(self, request, queryset):
        from .xid_configuration import XIDTestService
        from django.contrib import messages
        for alarm in queryset:
            if not alarm.xid:
                self.message_user(request, f"Alarme '{alarm.nome}' não possui XID configurado.", level=messages.WARNING)
                continue
            res = XIDTestService.test_xid(alarm.xid)
            if res.get("status") == "success":
                self.message_user(
                    request,
                    f"XID '{alarm.xid}' do alarme '{alarm.nome}': Leitura OK! Valor: {res.get('value')} (tipo {res.get('data_type')})",
                    level=messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"XID '{alarm.xid}' do alarme '{alarm.nome}': Falha ou sem comunicação. {res.get('message')}",
                    level=messages.WARNING,
                )


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


@admin.register(ProductionCycle)
class ProductionCycleAdmin(admin.ModelAdmin):
    list_display = ("cavity_config", "matriz", "produto", "lote_bladder", "started_at", "ended_at", "initial_counter", "final_counter", "quantity_produced", "close_reason")
    list_filter = ("close_reason", "started_at", "ended_at")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "matriz", "produto", "lote_bladder")
    date_hierarchy = "started_at"


@admin.register(ProductionShiftAccumulated)
class ProductionShiftAccumulatedAdmin(admin.ModelAdmin):
    list_display = ("date", "shift", "cavity_config", "matriz", "produto", "quantity_accumulated", "last_scada_counter", "updated_at")
    list_filter = ("date", "shift")
    search_fields = ("cavity_config__nome", "cavity_config__machine_config__machine__nome", "matriz", "produto")
    date_hierarchy = "date"


@admin.register(ProductionMatrixSize)
class ProductionMatrixSizeAdmin(admin.ModelAdmin):
    list_display = ("medida", "medida_normalizada", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("medida", "medida_normalizada")


@admin.register(ProductionBladder)
class ProductionBladderAdmin(admin.ModelAdmin):
    list_display = ("codigo_bladder", "descricao", "ativo", "created_at")
    list_filter = ("ativo",)
    search_fields = ("codigo_bladder", "descricao")
    filter_horizontal = ("medidas",)


@admin.register(ProductionPCPSetting)
class ProductionPCPSettingAdmin(admin.ModelAdmin):
    list_display = ("chave", "valor", "descricao", "updated_at")
    search_fields = ("chave", "descricao")


@admin.register(ProductionMatrixCatalog)
class ProductionMatrixCatalogAdmin(admin.ModelAdmin):
    list_display = ("codigo_scada", "codigo", "nome_exibicao", "medida_str", "tempo_producao_segundos", "tempo_vulcanizacao_segundos", "variante_sc", "ativo")
    list_filter = ("ativo", "variante_sc")
    search_fields = ("codigo_scada", "codigo", "nome_scada", "nome_exibicao", "produto", "medida_str")


@admin.register(ProductionTarget)
class ProductionTargetAdmin(admin.ModelAdmin):
    list_display = ("date", "shift", "matriz_codigo", "produto", "planned_quantity", "predicted_machine", "status", "created_by")
    list_filter = ("status", "date", "shift")
    search_fields = ("matriz_codigo", "produto", "observation")
    date_hierarchy = "date"


class ProductionPCPPlanShiftTargetInline(admin.TabularInline):
    model = ProductionPCPPlanShiftTarget
    extra = 0
    readonly_fields = ("date", "shift", "data_hora_inicio_janela", "data_hora_fim_janela", "meta_prevista", "target_legado")


@admin.register(ProductionPCPPlan)
class ProductionPCPPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "matriz", "data_hora_inicio", "quantidade_programada", "turno_opcao", "cavidades_disponiveis", "data_hora_fim_prevista", "lixo_estimado", "ia_estimada", "producao_boa_estimada", "status", "created_at")
    list_filter = ("status", "turno_opcao", "created_at")
    search_fields = ("matriz__nome_exibicao", "matriz__codigo", "observacao")
    date_hierarchy = "data_hora_inicio"
    inlines = [ProductionPCPPlanShiftTargetInline]


@admin.register(ProductionPCPPlanHistory)
class ProductionPCPPlanHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "pcp_plan", "action_type", "user", "created_at")
    list_filter = ("action_type", "created_at")
    search_fields = ("pcp_plan__id", "reason")


@admin.register(ProductionBladderUsage)
class ProductionBladderUsageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "codigo_bla_real",
        "lote_completo_snapshot",
        "cavity_config",
        "started_at",
        "ended_at",
        "passadas_acumuladas",
        "limite_vida_snapshot",
        "motivo_troca",
        "status",
    )
    list_filter = ("status", "motivo_troca", "started_at", "ended_at", "codigo_bla_real")
    search_fields = (
        "codigo_bla_real",
        "lote_completo_snapshot",
        "cavity_config__nome",
        "cavity_config__machine_config__machine__nome",
    )
    date_hierarchy = "started_at"


@admin.register(ProductionBladderSetupMismatchEvent)
class ProductionBladderSetupMismatchEventAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cavity_config",
        "codigo_bla_instalado",
        "bladders_esperados_snapshot",
        "started_at",
        "ended_at",
        "duracao_segundos",
        "passadas_produzidas_em_divergencia",
        "status",
        "resolvido_por",
    )
    list_filter = ("status", "resolvido_por", "started_at", "codigo_bla_instalado")
    search_fields = (
        "codigo_bla_instalado",
        "bladders_esperados_snapshot",
        "cavity_config__nome",
        "cavity_config__machine_config__machine__nome",
    )
    date_hierarchy = "started_at"








