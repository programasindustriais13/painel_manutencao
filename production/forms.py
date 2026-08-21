from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError
from .models import (
    ProductionShift,
    ProductionCavityConfig,
    ProductionMatrixCatalog,
    ProductionTarget,
    ProductionPCPPlan,
    ProductionBladder,
)


class ProductionMatrixCatalogForm(forms.ModelForm):
    class Meta:
        model = ProductionMatrixCatalog
        fields = ["codigo", "descricao", "produto", "aliases_scada", "ativo"]
        widgets = {
            "codigo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: M-1024"}),
            "descricao": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Matriz 175/70R14 Curing"}),
            "produto": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Pneu 175/70R14"}),
            "aliases_scada": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "MATRIZ 1024, Matriz 1024, 1024"}),
            "ativo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def clean_codigo(self):
        codigo = self.cleaned_data.get("codigo", "").strip()
        if not codigo:
            raise ValidationError("O código da matriz é obrigatório.")
        return codigo


class ProductionTargetForm(forms.ModelForm):
    class Meta:
        model = ProductionTarget
        fields = [
            "date",
            "shift",
            "matrix_catalog",
            "matriz_codigo",
            "produto",
            "planned_quantity",
            "priority",
            "predicted_machine",
            "predicted_cavity",
            "observation",
            "change_reason",
            "status",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "shift": forms.Select(attrs={"class": "form-select"}),
            "matrix_catalog": forms.Select(attrs={"class": "form-select"}),
            "matriz_codigo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Código canônico da matriz"}),
            "produto": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nome do produto"}),
            "planned_quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "priority": forms.NumberInput(attrs={"class": "form-control", "min": "1", "max": "99"}),
            "predicted_machine": forms.Select(attrs={"class": "form-select"}),
            "predicted_cavity": forms.Select(attrs={"class": "form-select"}),
            "observation": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Observações ou observações do PCP..."}),
            "change_reason": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Motivo da alteração pós-início do turno..."}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_planned_quantity(self):
        qty = self.cleaned_data.get("planned_quantity")
        if qty is None or qty <= 0:
            raise ValidationError("A quantidade planejada (meta) deve ser um número inteiro positivo maior que zero.")
        return qty

    def clean(self):
        cleaned_data = super().clean()
        date = cleaned_data.get("date")
        shift = cleaned_data.get("shift")
        matrix_catalog = cleaned_data.get("matrix_catalog")
        matriz_codigo = cleaned_data.get("matriz_codigo")
        produto = cleaned_data.get("produto")
        status = cleaned_data.get("status")

        if matrix_catalog:
            if not matriz_codigo:
                cleaned_data["matriz_codigo"] = str(matrix_catalog.codigo_scada or matrix_catalog.codigo)
            if not produto:
                cleaned_data["produto"] = matrix_catalog.nome_exibicao or matrix_catalog.nome_scada or matrix_catalog.produto

        mat_code = (cleaned_data.get("matriz_codigo") or "").strip()

        active_statuses = ["PLANEJADA", "AGUARDANDO_INSTALACAO", "EM_PRODUCAO", "ATIVO"]
        if status in active_statuses and date and (matrix_catalog or mat_code):
            filter_q = Q(matrix_catalog=matrix_catalog) if matrix_catalog else Q(matriz_codigo__iexact=mat_code)
            qs = ProductionTarget.objects.filter(
                Q(date=date) & Q(status__in=active_statuses) & filter_q
            )
            if shift:
                qs = qs.filter(shift=shift)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise ValidationError("Já existe uma meta ativa cadastrada com esta mesma combinação.")

        return cleaned_data


class ProductionPCPPlanForm(forms.ModelForm):
    class Meta:
        model = ProductionPCPPlan
        fields = [
            "matriz",
            "data_hora_inicio",
            "quantidade_programada",
            "turno_opcao",
            "cavidades_disponiveis",
        ]
        widgets = {
            "matriz": forms.Select(attrs={"class": "form-select select2-matrix"}),
            "data_hora_inicio": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M"
            ),
            "quantidade_programada": forms.NumberInput(attrs={"class": "form-control", "min": "1", "placeholder": "Ex: 3000"}),
            "turno_opcao": forms.Select(attrs={"class": "form-select"}),
            "cavidades_disponiveis": forms.NumberInput(attrs={"class": "form-control", "min": "1", "value": "4"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["matriz"].queryset = ProductionMatrixCatalog.objects.filter(ativo=True).order_by("nome_exibicao")
        self.fields["matriz"].label_from_instance = lambda obj: obj.nome_exibicao or obj.nome_scada or obj.produto or obj.codigo
        self.fields["matriz"].label = "Matriz"
        self.fields["data_hora_inicio"].input_formats = ["%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]
        self.fields["data_hora_inicio"].label = "Data de início"
        self.fields["quantidade_programada"].label = "Quantidade"
        self.fields["turno_opcao"].label = "Turno"
        self.fields["cavidades_disponiveis"].label = "Quantidade de Matrizes/Cavidades Disponíveis"

    def clean_quantidade_programada(self):
        qty = self.cleaned_data.get("quantidade_programada")
        if qty is None or qty <= 0:
            raise ValidationError("A quantidade programada deve ser maior que zero.")
        return qty

    def clean_cavidades_disponiveis(self):
        cav = self.cleaned_data.get("cavidades_disponiveis")
        if cav is None or cav <= 0:
            raise ValidationError("A quantidade de cavidades disponíveis deve ser pelo menos 1.")
        return cav


# ==============================================================================
# FORMULÁRIOS DA CENTRAL DE CONFIGURAÇÃO SCADA / XIDs
# ==============================================================================

class ProductionMachineConfigForm(forms.ModelForm):
    """
    Formulário para edição da configuração de máquina/prensa no Scada-LTS.
    """
    class Meta:
        from .models import ProductionMachineConfig
        model = ProductionMachineConfig
        fields = [
            "ordem_exibicao",
            "stale_limit_seconds",
            "produzindo_value",
            "xid_status_prensa",
            "xid_abertura",
            "xid_motivo_parada_geral",
        ]
        widgets = {
            "ordem_exibicao": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "stale_limit_seconds": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "produzindo_value": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: 1 ou true"}),
            "xid_status_prensa": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_STATUS"}),
            "xid_abertura": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_ABERTURA"}),
            "xid_motivo_parada_geral": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_MOTIVO"}),
        }

    def clean_stale_limit_seconds(self):
        val = self.cleaned_data.get("stale_limit_seconds")
        if val is None or val < 1:
            raise ValidationError("O limite para dado desatualizado deve ser de pelo menos 1 segundo.")
        return val

    def clean_produzindo_value(self):
        val = self.cleaned_data.get("produzindo_value", "1")
        if not val or not str(val).strip():
            return "1"
        return str(val).strip()

    def clean_xid_status_prensa(self):
        val = self.cleaned_data.get("xid_status_prensa")
        return str(val).strip() if val else None

    def clean_xid_abertura(self):
        val = self.cleaned_data.get("xid_abertura")
        return str(val).strip() if val else None

    def clean_xid_motivo_parada_geral(self):
        val = self.cleaned_data.get("xid_motivo_parada_geral")
        return str(val).strip() if val else None


class ProductionCavityConfigForm(forms.ModelForm):
    """
    Formulário para configuração individual de cada cavidade de uma prensa.
    """
    class Meta:
        from .models import ProductionCavityConfig
        model = ProductionCavityConfig
        fields = [
            "nome",
            "ordem",
            "xid_producao",
            "xid_motivo_parada",
            "xid_matriz",
            "xid_produto",
            "xid_lote_bladder",
            "xid_bla_real",
            "xid_meta",
            "xid_motivo_troca_bladder",
        ]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Cavidade 1"}),
            "ordem": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "xid_producao": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_PROD"}),
            "xid_motivo_parada": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_MOTIVO"}),
            "xid_matriz": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_MATRIZ"}),
            "xid_produto": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_PROD_PREFIX"}),
            "xid_lote_bladder": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_LOTE_NUM"}),
            "xid_bla_real": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_BLA"}),
            "xid_meta": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_META"}),
            "xid_motivo_troca_bladder": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_PR01_C1_MOTIVO_TROCA"}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get("nome", "").strip()
        if not nome:
            raise ValidationError("O nome da cavidade é obrigatório.")
        return nome

    def clean_ordem(self):
        ordem = self.cleaned_data.get("ordem")
        if ordem is None or ordem < 1:
            raise ValidationError("A ordem de exibição deve ser no mínimo 1.")
        return ordem

    def clean_xid_producao(self):
        val = self.cleaned_data.get("xid_producao")
        return str(val).strip() if val else None

    def clean_xid_motivo_parada(self):
        val = self.cleaned_data.get("xid_motivo_parada")
        return str(val).strip() if val else None

    def clean_xid_matriz(self):
        val = self.cleaned_data.get("xid_matriz")
        return str(val).strip() if val else None

    def clean_xid_produto(self):
        val = self.cleaned_data.get("xid_produto")
        return str(val).strip() if val else None

    def clean_xid_lote_bladder(self):
        val = self.cleaned_data.get("xid_lote_bladder")
        return str(val).strip() if val else None

    def clean_xid_bla_real(self):
        val = self.cleaned_data.get("xid_bla_real")
        return str(val).strip() if val else None

    def clean_xid_meta(self):
        val = self.cleaned_data.get("xid_meta")
        return str(val).strip() if val else None

    def clean_xid_motivo_troca_bladder(self):
        val = self.cleaned_data.get("xid_motivo_troca_bladder")
        return str(val).strip() if val else None


class BaseProductionCavityConfigFormSet(forms.BaseInlineFormSet):
    """
    Formset customizado para validação de unicidade de nomes e ordens entre cavidades da mesma máquina.
    """
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        names = set()
        orders = set()

        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE", False):
                continue

            nome = form.cleaned_data.get("nome")
            ordem = form.cleaned_data.get("ordem")

            if nome:
                norm_nome = nome.strip().lower()
                if norm_nome in names:
                    raise ValidationError(f"Existe mais de uma cavidade com o nome '{nome}' nesta máquina.")
                names.add(norm_nome)

            if ordem:
                if ordem in orders:
                    raise ValidationError(f"Existe mais de uma cavidade com a ordem {ordem} nesta máquina.")
                orders.add(ordem)


def get_cavity_formset(extra=0):
    from .models import ProductionMachineConfig, ProductionCavityConfig
    return forms.inlineformset_factory(
        ProductionMachineConfig,
        ProductionCavityConfig,
        form=ProductionCavityConfigForm,
        formset=BaseProductionCavityConfigFormSet,
        extra=extra,
        can_delete=False,
    )


class ProductionGlobalParameterForm(forms.ModelForm):
    """
    Formulário para cadastro e edição de parâmetros globais do Scada-LTS.
    """
    class Meta:
        from .models import ProductionGlobalParameter
        model = ProductionGlobalParameter
        fields = ["nome", "chave", "xid", "unidade", "ordem"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Pressão de Vácuo"}),
            "chave": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: pressao_vacuo"}),
            "xid": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_VACUO_GERAL"}),
            "unidade": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: bar, mmHg, °C"}),
            "ordem": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get("nome", "").strip()
        if not nome:
            raise ValidationError("O nome do parâmetro é obrigatório.")
        return nome

    def clean_chave(self):
        chave = self.cleaned_data.get("chave", "").strip()
        if not chave:
            raise ValidationError("A chave única é obrigatória.")
        return chave.lower().replace(" ", "_")

    def clean_xid(self):
        val = self.cleaned_data.get("xid")
        return str(val).strip() if val else None

    def clean_unidade(self):
        val = self.cleaned_data.get("unidade")
        return str(val).strip() if val else None


class ProductionGlobalAlarmForm(forms.ModelForm):
    """
    Formulário para cadastro e edição de alarmes globais do Scada-LTS.
    """
    class Meta:
        from .models import ProductionGlobalAlarm
        model = ProductionGlobalAlarm
        fields = ["nome", "chave", "xid", "ordem"]
        widgets = {
            "nome": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: Alarme Falha de Vácuo"}),
            "chave": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ex: alarme_falha_vacuo"}),
            "xid": forms.TextInput(attrs={"class": "form-control xid-input", "placeholder": "Ex: DP_ALARME_VACUO"}),
            "ordem": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }

    def clean_nome(self):
        nome = self.cleaned_data.get("nome", "").strip()
        if not nome:
            raise ValidationError("O nome do alarme é obrigatório.")
        return nome

    def clean_chave(self):
        chave = self.cleaned_data.get("chave", "").strip()
        if not chave:
            raise ValidationError("A chave única é obrigatória.")
        return chave.lower().replace(" ", "_")

    def clean_xid(self):
        val = self.cleaned_data.get("xid")
        return str(val).strip() if val else None




