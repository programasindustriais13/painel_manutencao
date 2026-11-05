import datetime
from django import forms
from django.utils import timezone
from .models import (
    OrdemProducaoBladder,
    ProcessoBladder,
    ProdutoBladder,
    RecursoBladder,
    ApontamentoTurnoBladder,
    TipoAtividadeBladder,
    AtividadeTurnoBladder,
    MovimentacaoEstoqueBladder,
    MensagemPassagemTurnoBladder,
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
        self.fields['produto'].required = False
        self.fields['quantidade_nova'].required = False
        self.fields['recursos_alocados'].queryset = RecursoBladder.objects.filter(ativo=True)
        self.fields['prioridade'].required = False
        self.fields['prioridade'].initial = 'NORMAL'
        if not self.initial.get('data_programada'):
            self.initial['data_programada'] = timezone.localdate()

    def clean_quantidade_nova(self):
        qtd = self.cleaned_data.get('quantidade_nova')
        if qtd is None:
            return 0
        if qtd < 0:
            raise forms.ValidationError("A quantidade nova solicitada não pode ser negativa.")
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


class MensagemPassagemTurnoForm(forms.Form):
    """Formulário para registrar uma mensagem de Passagem de Turno."""
    tipo = forms.ChoiceField(
        label="Tipo de Recado",
        choices=[
            ('INFORMATIVO', 'Informativo (Apenas dar ciência)'),
            ('ACOMPANHAMENTO', 'Acompanhamento (Pede ação / verificação)'),
        ],
        initial='INFORMATIVO',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    categoria = forms.ChoiceField(
        label="Categoria",
        choices=[
            ('PRODUCAO', 'Produção'),
            ('EQUIPAMENTO', 'Equipamento'),
            ('QUALIDADE', 'Qualidade'),
            ('MATERIAL', 'Material'),
            ('SEGURANCA', 'Segurança'),
            ('OUTRO', 'Outro'),
        ],
        initial='PRODUCAO',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    prioridade = forms.ChoiceField(
        label="Prioridade",
        choices=[
            ('NORMAL', 'Normal'),
            ('IMPORTANTE', 'Importante'),
            ('URGENTE', 'Urgente'),
        ],
        initial='NORMAL',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    mensagem = forms.CharField(
        label="Mensagem para o Próximo Turno",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'O que o próximo turno precisa saber ou verificar com atenção?...'
        }),
        required=True
    )
    # Campos contextuais opcionais
    ordem_producao_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    processo_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    maquina_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    produto_id = forms.IntegerField(required=False, widget=forms.HiddenInput())

    def clean_mensagem(self):
        m = self.cleaned_data.get('mensagem', '').strip()
        if not m:
            raise forms.ValidationError("A mensagem não pode ser vazia.")
        return m


class EditarMensagemPassagemTurnoForm(forms.Form):
    """Formulário para edição in-place de mensagem de Passagem de Turno."""
    tipo = forms.ChoiceField(
        label="Tipo de Recado",
        choices=[
            ('INFORMATIVO', 'Informativo (Apenas dar ciência)'),
            ('ACOMPANHAMENTO', 'Acompanhamento (Pede ação / verificação)'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    categoria = forms.ChoiceField(
        label="Categoria",
        choices=[
            ('PRODUCAO', 'Produção'),
            ('EQUIPAMENTO', 'Equipamento'),
            ('QUALIDADE', 'Qualidade'),
            ('MATERIAL', 'Material'),
            ('SEGURANCA', 'Segurança'),
            ('OUTRO', 'Outro'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    prioridade = forms.ChoiceField(
        label="Prioridade",
        choices=[
            ('NORMAL', 'Normal'),
            ('IMPORTANTE', 'Importante'),
            ('URGENTE', 'Urgente'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    mensagem = forms.CharField(
        label="Mensagem Atualizada",
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Atualize o conteúdo do recado operacional...'
        }),
        required=True
    )

    def clean_mensagem(self):
        m = self.cleaned_data.get('mensagem', '').strip()
        if not m:
            raise forms.ValidationError("A mensagem não pode ser vazia.")
        return m


class MovimentacaoEstoqueForm(forms.Form):
    """Formulário para Entrada ou Saída de Bladders Acabados no estoque integrado à DR-201."""
    TIPO_CHOICES = [
        ('SAIDA', 'Saída de bladder para produção'),
        ('ENTRADA', 'Entrada de bladder para estoque'),
    ]

    produto = forms.ModelChoiceField(
        queryset=ProdutoBladder.objects.filter(ativo=True, codigo__startswith='BLA').order_by('codigo'),
        label="Modelo de Bladder",
        widget=forms.Select(attrs={'class': 'form-select select-mov-produto'})
    )
    tipo = forms.ChoiceField(
        choices=TIPO_CHOICES,
        label="Tipo de Operação",
        initial='SAIDA',
        widget=forms.Select(attrs={'class': 'form-select select-mov-tipo'})
    )
    quantidade = forms.IntegerField(
        label="Quantidade (un)",
        min_value=1,
        initial=1,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center font-monospace input-qtd-modal', 'placeholder': '1', 'min': '1', 'value': '1'})
    )
    destino = forms.CharField(
        label="Responsável pela Retirada",
        initial="",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control input-responsavel-retirada', 'placeholder': 'Nome de quem retirou (ex: Edilson, Rodrigo, Ivanildo...)'})
    )
    lote_etiqueta = forms.CharField(
        label="Lote / Etiqueta da Peça",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control font-monospace input-lote-item', 'placeholder': 'Ex: 7586193161'})
    )
    observacao = forms.CharField(
        label="Observações (Opcional)",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Observações complementares da movimentação...'})
    )
    data_turno = forms.DateField(
        label="Data",
        required=False,
        widget=forms.DateInput(attrs={'class': 'form-control', 'type': 'date'})
    )
    turno = forms.ChoiceField(
        choices=[('MANHÃ', 'MANHÃ'), ('NOITE', 'NOITE')],
        label="Turno",
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].label_from_instance = lambda obj: f"{obj.codigo_com_medida} (Saldo: {obj.estoque_atual} un)"

    @property
    def tipo_movimentacao(self):
        return self['tipo']

    @property
    def motivo(self):
        return self['destino']

    @property
    def responsavel_retirada(self):
        return self['destino']

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get('destino') and self.data.get('responsavel_retirada'):
            cleaned_data['destino'] = self.data.get('responsavel_retirada')
        elif not cleaned_data.get('destino') and self.data.get('motivo'):
            cleaned_data['destino'] = self.data.get('motivo')

        if not cleaned_data.get('lote_etiqueta') and self.data.get('lotes'):
            lotes_list = self.data.getlist('lotes')
            if lotes_list:
                cleaned_data['lote_etiqueta'] = lotes_list[0]

        if not cleaned_data.get('tipo') and self.data.get('tipo_movimentacao'):
            cleaned_data['tipo'] = self.data.get('tipo_movimentacao')
        return cleaned_data


class AjusteEstoqueForm(forms.Form):
    """Formulário para Ajuste formal de Inventário (Líder)."""
    produto = forms.ModelChoiceField(
        queryset=ProdutoBladder.objects.filter(ativo=True, codigo__startswith='BLA').order_by('codigo'),
        label="Modelo do Bladder",
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    novo_saldo = forms.IntegerField(
        label="Novo Saldo Físico Contado (un)",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg text-center font-monospace'})
    )
    justificativa = forms.CharField(
        label="Justificativa do Ajuste (Obrigatória)",
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Descreva detalhadamente o motivo do ajuste (ex: contagem física de inventário, refugo descartado)...'}),
        required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].label_from_instance = lambda obj: f"{obj.codigo_com_medida} (Saldo: {obj.estoque_atual} un)"

    def clean_justificativa(self):
        j = self.cleaned_data.get('justificativa', '').strip()
        if len(j) < 5:
            raise forms.ValidationError("Informe uma justificativa com no mínimo 5 caracteres.")
        return j


class ConfigurarMinimoEstoqueForm(forms.Form):
    """Formulário para configurar estoque mínimo de segurança."""
    produto = forms.ModelChoiceField(
        queryset=ProdutoBladder.objects.filter(ativo=True, codigo__startswith='BLA').order_by('codigo'),
        label="Modelo do Bladder",
        widget=forms.Select(attrs={'class': 'form-select'}),
        required=True
    )
    estoque_minimo = forms.IntegerField(
        label="Estoque Mínimo de Segurança (un)",
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control text-center font-monospace'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].label_from_instance = lambda obj: f"{obj.codigo_com_medida} (Mínimo atual: {obj.estoque_minimo} un)"


class AtividadeOperacionalForm(forms.ModelForm):
    """Formulário para registro de atividade operacional flexível no turno."""
    class Meta:
        model = AtividadeTurnoBladder
        fields = [
            'tipo_atividade',
            'processo',
            'maquina',
            'produto',
            'quantidade',
            'observacao',
        ]
        widgets = {
            'tipo_atividade': forms.Select(attrs={'class': 'form-select', 'id': 'select-tipo-atividade'}),
            'processo': forms.Select(attrs={'class': 'form-select'}),
            'maquina': forms.Select(attrs={'class': 'form-select'}),
            'produto': forms.Select(attrs={'class': 'form-select'}),
            'quantidade': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'placeholder': 'Se aplicável'}),
            'observacao': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Observações operacionais...'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo_atividade'].queryset = TipoAtividadeBladder.objects.filter(ativo=True)
        self.fields['processo'].queryset = ProcessoBladder.objects.filter(ativo=True)
        self.fields['processo'].required = False
        from maintenance.models import Machine
        self.fields['maquina'].queryset = Machine.objects.all().order_by('nome')
        self.fields['maquina'].required = False
        self.fields['produto'].queryset = ProdutoBladder.objects.filter(ativo=True)
        self.fields['produto'].label_from_instance = lambda obj: obj.codigo_com_medida
        self.fields['produto'].required = False
        self.fields['quantidade'].required = False
        self.fields['observacao'].required = False

