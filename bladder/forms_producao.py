"""Formulários de execução: seleção exclusivamente pelo código cadastrado da OP."""
from decimal import Decimal
from django import forms


class DecimalOperacional(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.strip().replace(',', '.')
        return super().to_python(value)


class NumeroOperacionalInput(forms.NumberInput):
    def format_value(self, value):
        # HTML number exige ponto inclusive quando um POST inválido volta à tela.
        if isinstance(value, str):
            value = value.strip().replace(',', '.')
        return super().format_value(value)


def numero(label, positivo=False):
    return DecimalOperacional(
        label=label, max_digits=12, decimal_places=3,
        min_value=Decimal('0.001') if positivo else Decimal('0'),
        widget=NumeroOperacionalInput(attrs={'class': 'form-control form-control-lg',
                                       'inputmode': 'decimal', 'step': '0.001',
                                       'autocomplete': 'off'}))


def texto(label, limite=60, obrigatorio=True):
    return forms.CharField(label=label, max_length=limite, required=obrigatorio,
                           widget=forms.TextInput(attrs={'class': 'form-control form-control-lg'}))


class ExecucaoForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, required=False)
    observacoes = forms.CharField(label='Observações', required=False,
                                 widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}))

    def clean(self):
        dados = super().clean()
        # Não aceitar campos operacionais de outro processo, mesmo ocultados no browser.
        indevidos = CAMPOS_PROCESSOS.intersection(self.data.keys()) - set(self.fields)
        if indevidos:
            raise forms.ValidationError('Os parâmetros enviados não pertencem ao processo desta OP.')
        return dados


class VulcanizacaoForm(ExecucaoForm):
    tempo_vulcanizacao = numero('Tempo de vulcanização (min)', positivo=True)
    pressao = numero('Pressão aplicada', positivo=True)
    temperatura = numero('Temperatura de vulcanização', positivo=True)
    condicao = forms.ChoiceField(label='Condição do Bladder', choices=[('', 'Selecione'), ('Bom', 'Bom'), ('IA', 'IA — Imperfeição Aparente'), ('Lixo', 'Lixo')], widget=forms.Select(attrs={'class': 'form-select form-select-lg'}))
    lote_produto = texto('Lote do produto')
    volume = texto('Volume')


class ExtrusaoForm(ExecucaoForm):
    quantidade_realizada = forms.IntegerField(label='Quantidade produzida (un)', min_value=1, max_value=2147483647,
                                             widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg', 'inputmode': 'numeric', 'step': '1'}))
    temperatura = numero('Temperatura geral')
    velocidade_esteira = numero('Velocidade da esteira')
    velocidade_fuso = numero('Velocidade do fuso')
    temperatura_tcu_1 = numero('Temperatura TCU 1')
    temperatura_tcu_2 = numero('Temperatura TCU 2')
    temperatura_tcu_3 = numero('Temperatura TCU 3')
    temperatura_tcu_4 = numero('Temperatura TCU 4')


class ExtrusaoBladderForm(ExtrusaoForm):
    tipo_processamento = texto('Tipo de processamento', limite=150)
    resfriamento = texto('Resfriamento', limite=150)


class AneisForm(ExecucaoForm):
    tempo_vulcanizacao = numero('Tempo de vulcanização (min)', positivo=True)
    temperatura = numero('Temperatura')
    pressao = numero('Pressão', positivo=True)
    condicao = forms.ChoiceField(label='Condição dos anéis', choices=[('', 'Selecione'), ('Bons', 'Bons'), ('Parcialmente Bons', 'Parcialmente Bons'), ('Ruins', 'Ruins')], widget=forms.Select(attrs={'class': 'form-select form-select-lg'}))


class ManuseioForm(ExecucaoForm):
    quantidade_manuseada = forms.IntegerField(
        label='Quantidade manuseada (un)',
        min_value=1,
        max_value=2147483647,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control form-control-lg', 'inputmode': 'numeric', 'step': '1'})
    )
    lote_produto = texto('Lote do produto')
    materia_prima = texto('Fornecedor e matéria-prima (ex.: TORTUGA - FBB0001)', limite=150)
    lote_material = texto('Lote do material')


class AmostraForm(forms.Form):
    diametro = numero('Diâmetro (mm)', positivo=True)
    comprimento = numero('Comprimento (cm)', positivo=True)
    peso = numero('Peso (kg)', positivo=True)


FORMULARIOS = {'01': VulcanizacaoForm, '02': VulcanizacaoForm, '03': ExtrusaoBladderForm,
              '04': ExtrusaoForm, '05': AneisForm, '06': ManuseioForm}
CAMPOS_PROCESSOS = set().union(*(set(form.base_fields) for form in FORMULARIOS.values())) - {'token', 'observacoes'}


def formulario_processo(codigo, *args, **kwargs):
    if codigo not in FORMULARIOS:
        raise ValueError('Este processo ainda não possui formulário de produção definido.')
    return FORMULARIOS[codigo](*args, **kwargs)


def numero_amostras(quantidade):
    return (int(quantidade) + 9) // 10 if quantidade > 0 else 0


def formulario_amostras(quantidade, data=None, initial=None, obrigatorias=None):
    n = numero_amostras(quantidade)
    min_n = obrigatorias if obrigatorias is not None else n
    initial_count = len(initial) if initial else 0
    extra = max(0, n - initial_count)
    classe = forms.formset_factory(
        AmostraForm,
        extra=extra,
        min_num=min_n,
        max_num=n,
        validate_min=min_n > 0,
        validate_max=True,
        absolute_max=n
    )
    # min_num já cria as N linhas obrigatórias, não adicionar outras N extras.
    classe.extra = extra
    return classe(data=data, initial=initial, prefix='amostras')
