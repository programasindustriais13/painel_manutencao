import uuid
from django import forms
from django.contrib import messages
from django.core import signing
from django.db import OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST
from .decorators import operador_ou_lider_bladder_required, lider_bladder_required, user_is_lider_bladder
from .models import ApontamentoTurnoBladder, OrdemProducaoBladder, CategoriaDesvioBladder, ProcessoBladder
from .forms_producao import formulario_processo, formulario_amostras, numero_amostras
from .producao import (validar_op, validar_extrusao, registrar_producao, corrigir_producao,
                       pode_corrigir, PARAMETROS)


def _contexto(request, op, codigo, form, formset=None, extrusao=None, registro=None, manuseio_existente=None):
    processo = ProcessoBladder.objects.filter(codigo=codigo).select_related('maquina').first()
    return {'op': op, 'codigo': codigo, 'form': form, 'amostras_formset': formset,
            'equipamento_executado': registro.equipamento if registro else processo.maquina if processo else None,
            'extrusao': extrusao, 'registro': registro, 'manuseio_existente': manuseio_existente,
            'is_correcao': registro is not None, 'is_manuseio': codigo == '06',
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
    manuseio_existente = None
    initial_form = {}
    initial_amostras = None
    try:
        if codigo == '06':
            if extrusao is None:
                raise ValueError('O manuseio deve ser aberto pela execução de Extrusão de Bladder na lista de etapas pendentes.')
            manuseio_existente = getattr(extrusao, 'manuseio', None)
            if manuseio_existente and manuseio_existente.status_manuseio == 'CONCLUIDO':
                return redirect('bladder:producao_detalhe', pk=manuseio_existente.pk)
            if manuseio_existente:
                initial_form = {
                    'lote_produto': manuseio_existente.lote_produto,
                    'materia_prima': manuseio_existente.materia_prima,
                    'lote_material': manuseio_existente.lote_material,
                    'quantidade_manuseada': manuseio_existente.quantidade_manuseada,
                    'observacoes': manuseio_existente.observacoes,
                }
                initial_amostras = list(manuseio_existente.amostras.order_by('sequencia').values('diametro', 'comprimento', 'peso'))
            else:
                initial_form = {
                    'quantidade_manuseada': extrusao.quantidade_realizada,
                }

        if request.method != 'POST':
            validar_op(op, request.user, manuseio=extrusao is not None)

        initial_form['token'] = _token(request, op, codigo, extrusao.pk if extrusao else None)
        form = formulario_processo(codigo, request.POST if request.method == 'POST' else None,
                                   initial=initial_form if request.method != 'POST' else None)
    except (ValueError, PermissionError) as erro:
        return render(request, 'bladder/producao_erro.html', {'erro': str(erro)}, status=403)

    acao = request.POST.get('acao', 'concluir') if request.method == 'POST' else 'concluir'
    obrigatorias = 0 if (codigo == '06') else None
    amostras = formulario_amostras(
        extrusao.quantidade_realizada,
        request.POST if request.method == 'POST' else None,
        initial=initial_amostras,
        obrigatorias=obrigatorias
    ) if extrusao else None

    if request.method == 'POST' and form.is_valid() and (amostras is None or amostras.is_valid()):
        try:
            chave = _chave(request, op, codigo, extrusao.pk if extrusao else None)
            registro, criado = registrar_producao(
                op.pk, request.user, form.cleaned_data, chave,
                extrusao_id=extrusao.pk if extrusao else None,
                amostras=amostras.cleaned_data if amostras else None,
                acao=acao
            )
            op.refresh_from_db()
            if codigo in ('01', '02'):
                texto = f'Bladder registrado com sucesso — {op.quantidade_realizada} de {op.quantidade_planejada} unidades.'
            elif codigo == '06':
                if acao == 'salvar_parcial':
                    texto = f'Manuseio parcial salvo com sucesso ({registro.quantidade_manuseada} de {extrusao.quantidade_realizada} tarugos). Amostras salvas.'
                else:
                    texto = 'Manuseio concluído com sucesso. Todas as amostras e médias salvas.'
            elif codigo == '05':
                texto = 'Parâmetros e qualidade dos anéis registrados. Quantidade não apurada.'
            else:
                texto = f'Produção registrada com sucesso — {op.quantidade_realizada} de {op.quantidade_planejada} unidades.'
            messages.success(request, texto if criado else 'Este envio já foi registrado; nenhuma produção foi duplicada.')
            return redirect(reverse('bladder:operador') + f'?producao={op.pk}#op-{op.pk}')
        except (ValueError, PermissionError) as erro:
            form.add_error(None, str(erro))
    return render(request, 'bladder/producao_form.html', _contexto(request, op, codigo, form, amostras, extrusao, manuseio_existente=manuseio_existente))


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
    controle = registro.controle_dr
    from .sincronizacao_drs import DESTINOS
    cfg = DESTINOS.get(controle.destino) if controle else None
    linha_conferencia = (controle.payload_tentativa or controle.payload_enviado or controle.payload) if controle else []
    return render(request, 'bladder/producao_detalhe.html', {'registro': registro, 'valores': valores,
                  'pode_corrigir': pode_corrigir(registro, request.user), 'theme_class': 'theme-light',
                  'is_operador_view': True, 'controle_dr': controle,
                  'url_dr': f"https://docs.google.com/spreadsheets/d/{cfg['id']}/edit#gid={cfg['gid']}" if cfg else '',
                  'valores_conferencia_dr': [(label, valor) for label, valor in zip(cfg['cabecalhos'], linha_conferencia)
                                             if label != 'Coluna 18'] if cfg else [],
                  'lider_dr': request.user.is_active and user_is_lider_bladder(request.user)})


@lider_bladder_required
@require_POST
def reprocessar_dr(request, pk):
    from .models import SincronizacaoDRBladder
    from .sincronizacao_drs import solicitar_reenvio
    fila = get_object_or_404(SincronizacaoDRBladder, apontamento_id=pk)
    try:
        solicitar_reenvio(fila.pk, request.user, confirmar_ausencia=request.POST.get('confirmar_ausencia') == 'sim',
                         justificativa=request.POST.get('justificativa', ''),
                         reconferir=request.POST.get('acao') == 'conferir')
        messages.success(request, 'Solicitação registrada. A integração fará a conferência na próxima execução.')
    except (ValueError, PermissionError) as erro:
        messages.error(request, str(erro))
    return redirect('bladder:producao_detalhe', pk=pk)
