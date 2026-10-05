import datetime
from django import forms
from django.utils import timezone
from .models import (
    OrdemProducaoBladder,
    ProcessoBladder,
    ProdutoBladder,
    RecursoBladder,
    ApontamentoTurnoBladder,
)


class OrdemProducaoBladderForm(forms.ModelForm):
    """Formulário para o Líder programar uma nova Ordem de Produção."""
    class Meta:
        model = OrdemProducaoBladder
        fields = [
            'processo',
            'produto',
            'data_programada',
            'quantidade_nova',
            'prioridade',
            'recursos_alocados',
            'recursos_observacoes',
            'observacoes',
        ]
        widgets = {
            'processo': forms.Select(attrs={'class': 'form-select'}),
            'produto': forms.Select(attrs={'class': 'form-select', 'id': 'select-produto-bladder'}),
            'data_programada': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'quantidade_nova': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Ex: 100'}),
            'prioridade': forms.Select(attrs={'class': 'form-select'}),
            'recursos_alocados': forms.SelectMultiple(attrs={'class': 'form-select', 'size': '5'}),
            'recursos_observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Observações técnicas sobre ferramental, compostos ou tarugos...'}),
            'observacoes': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Instruções gerais para a equipe de turno...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['processo'].queryset = ProcessoBladder.objects.filter(ativo=True)
        self.fields['produto'].queryset = ProdutoBladder.objects.filter(ativo=True)
        self.fields['produto'].label_from_instance = lambda obj: obj.codigo_com_medida
        self.fields['recursos_alocados'].queryset = RecursoBladder.objects.filter(ativo=True)
        self.fields['prioridade'].required = False
        self.fields['prioridade'].initial = 'NORMAL'
        if not self.initial.get('data_programada'):
            self.initial['data_programada'] = timezone.localdate()

    def clean_quantidade_nova(self):
        qtd = self.cleaned_data.get('quantidade_nova')
        if not qtd or qtd <= 0:
            raise forms.ValidationError("A quantidade nova solicitada deve ser maior que zero.")
        return qtd

    def clean_prioridade(self):
        return self.cleaned_data.get('prioridade') or 'NORMAL'


class ReprogramarOrdemForm(forms.Form):
    """Formulário de Reprogramação de OP pelo Líder."""
    nova_data = forms.DateField(
        label="Nova Data Programada",
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    motivo = forms.CharField(
        label="Motivo da Reprogramação (Obrigatório)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Informe detalhadamente o motivo da reprogramação...'}),
        required=True
    )

    def clean_motivo(self):
        m = self.cleaned_data.get('motivo', '').strip()
        if len(m) < 5:
            raise forms.ValidationError("Informe uma justificativa com no mínimo 5 caracteres.")
        return m


class CancelarOrdemForm(forms.Form):
    """Formulário de Cancelamento Lógico de OP pelo Líder."""
    motivo = forms.CharField(
        label="Motivo do Cancelamento (Obrigatório)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Informe a justificativa do cancelamento (ex: alteração de demanda, projeto urgente)...'}),
        required=True
    )

    def clean_motivo(self):
        m = self.cleaned_data.get('motivo', '').strip()
        if len(m) < 5:
            raise forms.ValidationError("Informe uma justificativa com no mínimo 5 caracteres.")
        return m


class ApontamentoTurnoForm(forms.Form):
    """Formulário para apontamento operacional pelo operador."""
    quantidade_realizada = forms.IntegerField(
        label="Quantidade Produzida (un)",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center font-monospace', 'style': 'font-size: 1.5rem;'})
    )
    situacao = forms.ChoiceField(
        label="Situação da Operação",
        choices=[
            ('CONCLUIDA', 'Concluída Totalmente'),
            ('PARCIAL', 'Encerrada Parcialmente (com saldo pendente)'),
            ('INTERROMPIDA', 'Interrompida com Problema / Ocorrência'),
        ],
        widget=forms.Select(attrs={'class': 'form-select form-select-lg'})
    )
    motivo_desvio = forms.CharField(
        label="Motivo / Ocorrência (Obrigatório se não atingir meta ou interrompida)",
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Descreva eventuais paradas, falta de tarugo ou problemas no equipamento...'})
    )
    observacoes = forms.CharField(
        label="Observações Adicionais",
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Observações gerais do operador...'})
    )

    def clean(self):
        cleaned_data = super().clean()
        situacao = cleaned_data.get('situacao')
        motivo = cleaned_data.get('motivo_desvio', '').strip()

        if situacao in ('PARCIAL', 'INTERROMPIDA') and not motivo:
            self.add_error('motivo_desvio', "O motivo do desvio/ocorrência é obrigatório para apontamentos parciais ou interrompidos.")

        return cleaned_data


class CorrecaoApontamentoForm(forms.Form):
    """Formulário de correção de apontamento pelo operador ou líder."""
    quantidade_realizada = forms.IntegerField(
        label="Quantidade Corrigida",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'})
    )
    motivo_correcao = forms.CharField(
        label="Justificativa da Correção (Obrigatória)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descreva o motivo da correção (ex: erro de digitação)...'}),
        required=True
    )

    def clean_motivo_correcao(self):
        m = self.cleaned_data.get('motivo_correcao', '').strip()
        if len(m) < 4:
            raise forms.ValidationError("Informe uma justificativa com no mínimo 4 caracteres.")
        return m
