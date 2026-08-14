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



