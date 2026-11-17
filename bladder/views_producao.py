import uuid
from django import forms
from django.contrib import messages
from django.core import signing
from django.db import OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from .decorators import operador_ou_lider_bladder_required
from .models import ApontamentoTurnoBladder, OrdemProducaoBladder, CategoriaDesvioBladder, ProcessoBladder
from .forms_producao import formulario_processo, formulario_amostras, numero_amostras
from .producao import (validar_op, validar_extrusao, registrar_producao, corrigir_producao,
                       pode_corrigir, PARAMETROS)


def _contexto(request, op, codigo, form, formset=None, extrusao=None, registro=None):
    processo = ProcessoBladder.objects.filter(codigo=codigo).select_related('maquina').first()
    return {'op': op, 'codigo': codigo, 'form': form, 'amostras_formset': formset,
            'equipamento_executado': registro.equipamento if registro else processo.maquina if processo else None,
            'extrusao': extrusao, 'registro': registro, 'is_correcao': registro is not None,
            'numero_amostras': numero_amostras(extrusao.quantidade_realizada) if extrusao else 0,
            'agora': timezone.now(), 'theme_class': 'theme-light', 'is_operador_view': True}


def _token(request, op, codigo, fonte):
    if not request.session.session_key:
        request.session.save()
    return signing.dumps({'chave': str(uuid.uuid4()), 'op': op.pk, 'codigo': codigo,
                          'fonte': fonte, 'usuario': request.user.pk,
                          'sessao': request.session.session_key}, salt='bladder.producao')


def _chave(request, op, codigo, fonte):
    try:
        dados = signing.loads(request.POST.get('token', ''), salt='bladder.producao', max_age=86400)
    except signing.BadSignature:
        raise ValueError('O formulário expirou ou é inválido. Abra novamente o registro de produção.')
    if any(dados.get(k) != v for k, v in {'op': op.pk, 'codigo': codigo, 'fonte': fonte,
                                         'usuario': request.user.pk, 'sessao': request.session.session_key}.items()):
        raise PermissionError('Este formulário pertence a outra OP, execução ou sessão.')
    return dados['chave']


@operador_ou_lider_bladder_required
def registrar(request, pk):
    op = get_object_or_404(OrdemProducaoBladder.objects.select_related('processo__maquina', 'produto'), pk=pk)
    return _registrar(request, op, op.processo.codigo)


@operador_ou_lider_bladder_required
def registrar_manuseio(request, pk):
    fonte = get_object_or_404(ApontamentoTurnoBladder.objects.select_related('ordem__processo__maquina', 'ordem__produto', 'produto_registrado'), pk=pk)
    try:
        validar_extrusao(fonte)
    except ValueError as erro:
        return render(request, 'bladder/producao_erro.html', {'erro': str(erro)}, status=403)
    return _registrar(request, fonte.ordem, '06', fonte)


def _registrar(request, op, codigo, extrusao=None):
    try:
        if codigo == '06' and extrusao is None:
            raise ValueError('O manuseio deve ser aberto pela execução de Extrusão de Bladder na lista de etapas pendentes.')
        if request.method != 'POST':
            validar_op(op, request.user, manuseio=extrusao is not None)
            if extrusao and ApontamentoTurnoBladder.objects.filter(extrusao_origem=extrusao).exists():
                return redirect('bladder:producao_detalhe', pk=extrusao.manuseio.pk)
        form = formulario_processo(codigo, request.POST if request.method == 'POST' else None,
                                   initial={'token': _token(request, op, codigo, extrusao.pk if extrusao else None)} if request.method != 'POST' else None)
    except (ValueError, PermissionError) as erro:
        return render(request, 'bladder/producao_erro.html', {'erro': str(erro)}, status=403)
    amostras = formulario_amostras(extrusao.quantidade_realizada, request.POST if request.method == 'POST' else None) if extrusao else None
    if request.method == 'POST' and form.is_valid() and (amostras is None or amostras.is_valid()):
        try:
            chave = _chave(request, op, codigo, extrusao.pk if extrusao else None)
            registro, criado = registrar_producao(op.pk, request.user, form.cleaned_data, chave,
                                                  extrusao_id=extrusao.pk if extrusao else None,
                                                  amostras=amostras.cleaned_data if amostras else None)
            op.refresh_from_db()
            if codigo in ('01', '02'):
                texto = f'Bladder registrado com sucesso — {op.quantidade_realizada} de {op.quantidade_planejada} unidades.'
            elif codigo == '06':
                texto = 'Manuseio registrado com sucesso. Amostras e médias salvas.'
            elif codigo == '05':
                texto = 'Parâmetros e qualidade dos anéis registrados. Quantidade não apurada.'
            else:
                texto = f'Produção registrada com sucesso — {op.quantidade_realizada} de {op.quantidade_planejada} unidades.'
            messages.success(request, texto if criado else 'Este envio já foi registrado; nenhuma produção foi duplicada.')
            return redirect(reverse('bladder:operador') + f'?producao={op.pk}#op-{op.pk}')
        except (ValueError, PermissionError) as erro:
            form.add_error(None, str(erro))
    return render(request, 'bladder/producao_form.html', _contexto(request, op, codigo, form, amostras, extrusao))


@operador_ou_lider_bladder_required
def corrigir(request, pk):
    registro = get_object_or_404(ApontamentoTurnoBladder.objects.select_related('ordem__processo__maquina', 'ordem__produto', 'extrusao_origem'), pk=pk)
    if registro.origem == 'LEGADO':
        return redirect('bladder:corrigir_apontamento', pk=pk)
    if not pode_corrigir(registro, request.user):
        return render(request, 'bladder/producao_erro.html', {'erro': 'Correção permitida ao próprio operador no turno aberto ou à liderança.'}, status=403)
    initial = {campo: getattr(registro, campo) for campo in PARAMETROS}
    initial['quantidade_realizada'] = registro.quantidade_realizada
    form = formulario_processo(registro.codigo_processo, request.POST if request.method == 'POST' else None, initial=initial)
    form.fields['motivo_correcao'] = forms.CharField(label='Justificativa da correção', min_length=4, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    if registro.fechamento_id and registro.codigo_processo in ('03', '04'):
        form.fields['categorias'] = forms.ModelMultipleChoiceField(label='Categorias do déficit (quando aplicável)', queryset=CategoriaDesvioBladder.objects.filter(ativo=True), required=False, widget=forms.CheckboxSelectMultiple)
        form.fields['descricao_desvio'] = forms.CharField(label='O que aconteceu? (quando houver déficit)', required=False, widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}))
    fonte = registro.extrusao_origem
    amostras = formulario_amostras(fonte.quantidade_realizada, request.POST if request.method == 'POST' else None,
                                  initial=list(registro.amostras.values('diametro', 'comprimento', 'peso'))) if fonte else None
    if request.method == 'POST' and form.is_valid() and (amostras is None or amostras.is_valid()):
        try:
            corrigir_producao(registro.pk, request.user, form.cleaned_data, form.cleaned_data['motivo_correcao'],
                             amostras=amostras.cleaned_data if amostras else None,
                             categorias=[c.pk for c in form.cleaned_data['categorias']] if 'categorias' in form.cleaned_data else None,
                             descricao_desvio=form.cleaned_data.get('descricao_desvio', ''))
            messages.success(request, 'Correção salva com histórico dos valores anteriores e novos.')
            return redirect('bladder:producao_detalhe', pk=pk)
        except (ValueError, PermissionError) as erro:
            form.add_error(None, str(erro))
    return render(request, 'bladder/producao_form.html', _contexto(request, registro.ordem, registro.codigo_processo, form, amostras, fonte, registro))


@operador_ou_lider_bladder_required
def detalhe(request, pk):
    registro = get_object_or_404(ApontamentoTurnoBladder.objects.select_related('ordem', 'operador', 'produto_registrado', 'processo_registrado', 'equipamento', 'extrusao_origem'), pk=pk)
    form = formulario_processo(registro.codigo_processo) if registro.origem != 'LEGADO' else None
    valores = [(field.label, getattr(registro, nome)) for nome, field in form.fields.items() if nome in PARAMETROS] if form else []
    return render(request, 'bladder/producao_detalhe.html', {'registro': registro, 'valores': valores,
                  'pode_corrigir': pode_corrigir(registro, request.user), 'theme_class': 'theme-light',
                  'is_operador_view': True})
