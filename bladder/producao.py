"""Execução operacional e qualidade; integrações são enfileiradas sem acesso à rede."""
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from django.db import OperationalError, transaction
from django.db.models import F, Sum
from django.utils import timezone
from .models import (ApontamentoTurnoBladder, AmostraManuseioBladder,
                     ConfiguracaoEscalaBladder, FechamentoTurnoBladder,
                     OrdemProducaoBladder, ProcessoBladder, HistoricoApontamentoBladder,
                     SaldoPendenteBladder, CategoriaDesvioBladder)
from .forms_producao import formulario_processo, formulario_amostras, numero_amostras
from .decorators import user_is_operador_bladder, user_is_lider_bladder


PARAMETROS = ('tempo_vulcanizacao', 'pressao', 'temperatura', 'velocidade_esteira',
              'velocidade_fuso', 'temperatura_tcu_1', 'temperatura_tcu_2',
              'temperatura_tcu_3', 'temperatura_tcu_4', 'condicao', 'lote_produto',
              'volume', 'materia_prima', 'lote_material', 'tipo_processamento',
              'resfriamento', 'observacoes')


def repetir_concorrencia(func):
    @wraps(func)
    def executa(*args, **kwargs):
        for tentativa in range(5):
            try:
                return func(*args, **kwargs)
            except OperationalError as erro:
                if not any(s in str(erro).lower() for s in ('locked', 'deadlock', 'lock wait')):
                    raise
                if tentativa == 4:
                    raise ValueError('Outro registro está sendo salvo. Tente novamente; o envio não será duplicado.') from erro
                time.sleep(0.05 * (tentativa + 1))
    return executa


def serializar_turno():
    """Primeira operação da transação: lock de escrita inclusive no SQLite.

    Uma linha de escala já existente serializa criação/correção/fechamento.
    Não altera horários, turma nem o timestamp. MySQL também bloqueia a linha.
    """
    if not ConfiguracaoEscalaBladder.objects.using('default').filter(ativo=True).update(updated_at=F('updated_at')):
        raise ValueError('Cadastre uma configuração de escala ativa antes de registrar produção.')


def autorizar_turno(usuario, data=None, permitir_fechado=False):
    from .services import calcular_turma_do_dia, verificar_usuario_apoio_no_dia
    data = data or timezone.localdate()
    if not user_is_operador_bladder(usuario) or not usuario.is_active:
        raise PermissionError('Usuário sem autorização para registrar produção no Bladder.')
    turma, _, _ = calcular_turma_do_dia(data)
    if turma not in ('TURMA_A', 'TURMA_B'):
        raise PermissionError('Não há turno operacional programado nesta data.')
    apoio, _ = verificar_usuario_apoio_no_dia(usuario, data)
    if not user_is_lider_bladder(usuario):
        perfil = getattr(usuario, 'perfil_operacional_bladder', None)
        if not apoio and (not perfil or not perfil.ativo or perfil.turma != turma):
            raise PermissionError('Você não está autorizado na escala deste turno.')
    if not permitir_fechado and FechamentoTurnoBladder.objects.using('default').filter(data_turno=data, turma=turma, status='CONCLUIDO').exists():
        raise ValueError('Este turno já foi fechado. Novos apontamentos estão bloqueados.')
    return 'APOIO' if apoio else turma


def execucoes_op(op):
    return ApontamentoTurnoBladder.objects.using('default').filter(ordem=op, origem='PROCESSO')


def total_executado(op):
    return execucoes_op(op).filter(quantidade_apurada=True).aggregate(s=Sum('quantidade_realizada'))['s'] or 0


def validar_op(op, usuario, manuseio=False):
    turma = autorizar_turno(usuario)
    if op.status == 'CANCELADA':
        raise ValueError('Esta OP foi cancelada.')
    if not manuseio:
        if op.data_programada != timezone.localdate():
            raise ValueError('A produção só pode ser registrada na data programada da OP.')
        if op.itens_fechamento.filter(fechamento__status='CONCLUIDO').exists() or op.status == 'PARCIAL':
            raise ValueError('A OP já foi encerrada no fechamento do turno.')
        if not op.processo.ativo:
            raise ValueError('O processo desta OP está inativo.')
        if op.apontamentos.filter(origem='LEGADO', quantidade_realizada__gt=0).exists():
            raise ValueError('Esta OP possui produção histórica. A liderança deve reconciliar os registros antes de usar o novo formulário.')
    return turma


def validar_extrusao(extrusao):
    if extrusao.origem != 'PROCESSO' or extrusao.codigo_processo != '03' or not extrusao.quantidade_apurada or extrusao.quantidade_realizada <= 0:
        raise ValueError('Manuseio exige uma execução salva de Extrusão de Bladder com quantidade positiva.')
    if extrusao.ordem.processo.codigo != '03' or extrusao.ordem.status == 'CANCELADA':
        raise ValueError('A execução de extrusão não possui vínculo operacional válido.')


def manuseios_pendentes():
    return ApontamentoTurnoBladder.objects.using('default').filter(
        origem='PROCESSO', codigo_processo='03', quantidade_apurada=True,
        quantidade_realizada__gt=0, manuseio__isnull=True,
    ).exclude(ordem__status='CANCELADA').select_related('ordem', 'produto_registrado', 'operador').order_by('created_at')


def _dados_validados(codigo, dados):
    formulario = formulario_processo(codigo, data=dados)
    if not formulario.is_valid():
        raise ValueError('Confira os dados: ' + '; '.join(str(erro) for erros in formulario.errors.values() for erro in erros))
    return formulario.cleaned_data


def _amostras_validadas(quantidade, dados):
    # Dados recebidos pelo serviço são revalidados, independentemente da view/JS.
    n = numero_amostras(quantidade)
    if not isinstance(dados, list) or len(dados) != n:
        raise ValueError(f'Informe exatamente {n} amostras completas da execução de extrusão.')
    from .forms_producao import AmostraForm
    amostras = []
    for valores in dados:
        form = AmostraForm(valores)
        if not form.is_valid():
            raise ValueError('Todas as amostras devem conter diâmetro, comprimento e peso positivos válidos.')
        amostras.append(form.cleaned_data)
    return amostras


def _salvar_amostras(apontamento, dados):
    for campo, precisao in [('diametro', '0.01'), ('comprimento', '0.01'), ('peso', '0.001')]:
        media = sum(a[campo] for a in dados) / Decimal(len(dados))
        setattr(apontamento, 'media_' + campo, media.quantize(Decimal(precisao), rounding=ROUND_HALF_UP))
    apontamento.save(using='default')
    for numero, valores in enumerate(dados, 1):
        # Correções preservam o ID da medição; snapshot integral fica na auditoria.
        AmostraManuseioBladder.objects.using('default').update_or_create(apontamento=apontamento, sequencia=numero, defaults=valores)


def snapshot(apontamento):
    valores = {campo: str(getattr(apontamento, campo)) if getattr(apontamento, campo) is not None else None for campo in PARAMETROS + ('quantidade_realizada', 'quantidade_apurada', 'media_diametro', 'media_comprimento', 'media_peso')}
    valores['amostras'] = [{k: str(v) for k, v in a.items()} for a in apontamento.amostras.values('sequencia', 'diametro', 'comprimento', 'peso')]
    return valores


@repetir_concorrencia
def registrar_producao(ordem_id, usuario, dados, chave, extrusao_id=None, amostras=None):
    with transaction.atomic(using='default'):
        serializar_turno()
        op = OrdemProducaoBladder.objects.using('default').select_for_update().select_related('processo__maquina', 'produto').get(pk=ordem_id)
        codigo = '06' if extrusao_id is not None else op.processo.codigo
        try:
            chave = uuid.UUID(str(chave))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Identificador de envio inválido. Abra novamente o formulário.')
        anterior = ApontamentoTurnoBladder.objects.using('default').filter(chave_idempotencia=chave).first()
        if anterior:
            if anterior.ordem_id != op.pk or anterior.codigo_processo != codigo or anterior.operador_id != usuario.pk or anterior.extrusao_origem_id != extrusao_id:
                raise PermissionError('Este identificador de envio pertence a outro registro.')
            # Reenvio também exige que o usuário continue autorizado no módulo.
            if not user_is_operador_bladder(usuario) or not usuario.is_active:
                raise PermissionError('Usuário sem autorização.')
            return anterior, False
        turma = validar_op(op, usuario, manuseio=extrusao_id is not None)
        extrusao = None
        if codigo == '06':
            if extrusao_id is None:
                raise ValueError('Manuseio deve ser aberto a partir da execução de Extrusão de Bladder, sem criar outra OP.')
            extrusao = ApontamentoTurnoBladder.objects.using('default').select_for_update().select_related('ordem', 'produto_registrado').get(pk=extrusao_id)
            validar_extrusao(extrusao)
            if extrusao.ordem_id != op.pk:
                raise ValueError('A extrusão informada não pertence à OP.')
            if ApontamentoTurnoBladder.objects.using('default').filter(extrusao_origem=extrusao).exists():
                raise ValueError('O manuseio desta execução já foi registrado.')
            processo = ProcessoBladder.objects.using('default').get(codigo='06', ativo=True)
        else:
            processo = op.processo
        valores = _dados_validados(codigo, dados)
        if codigo in ('01', '02', '03', '04') and not op.produto_id:
            raise ValueError('A liderança deve vincular o produto à OP antes do apontamento.')
        quantidade = 1 if codigo in ('01', '02') else valores.get('quantidade_realizada', 0)
        quantidade_apurada = codigo not in ('05', '06')
        produto = extrusao.produto_registrado if extrusao else op.produto
        apontamento = ApontamentoTurnoBladder(
            origem='MANUSEIO' if extrusao else 'PROCESSO', chave_idempotencia=chave,
            ordem=op, operador=usuario, turma=turma, data_turno=timezone.localdate(),
            data_hora_inicio=timezone.now(), data_hora_fim=timezone.now(), situacao='CONCLUIDA',
            quantidade_realizada=quantidade, quantidade_apurada=quantidade_apurada,
            processo_registrado=processo, codigo_processo=codigo, equipamento=processo.maquina,
            produto_registrado=produto, extrusao_origem=extrusao,
            identificacao_registrada={'op': op.numero_ordem, 'produto': produto.codigo if produto else '',
                                     'medida': produto.medida if produto else '', 'processo': processo.nome,
                                     'equipamento': str(processo.maquina) if processo.maquina_id else '',
                                     'operador': usuario.get_full_name() or usuario.username})
        for campo in PARAMETROS:
            if campo in valores:
                setattr(apontamento, campo, valores[campo])
        medições = _amostras_validadas(extrusao.quantidade_realizada, amostras) if extrusao else None
        apontamento.save(using='default')
        if medições:
            _salvar_amostras(apontamento, medições)
        if not extrusao:
            op.exige_execucoes = True
            op.quantidade_apurada = quantidade_apurada
            op.quantidade_realizada = total_executado(op)
            op.status = 'EM_EXECUCAO'
            op.save(using='default', update_fields=['exige_execucoes', 'quantidade_apurada', 'quantidade_realizada', 'status', 'updated_at'])
        from .sincronizacao_drs import enfileirar
        enfileirar(apontamento)
        return apontamento, True


def pode_corrigir(apontamento, usuario):
    if not user_is_operador_bladder(usuario) or not usuario.is_active:
        return False
    if user_is_lider_bladder(usuario):
        return True
    if apontamento.operador_id != usuario.pk or apontamento.data_turno != timezone.localdate() or apontamento.fechamento_id:
        return False
    try:
        autorizar_turno(usuario)
    except (ValueError, PermissionError):
        return False
    return True


@repetir_concorrencia
def corrigir_producao(apontamento_id, usuario, dados, motivo, amostras=None, categorias=None, descricao_desvio=''):
    if not motivo or len(str(motivo).strip()) < 4:
        raise ValueError('Informe a justificativa da correção com pelo menos 4 caracteres.')
    with transaction.atomic(using='default'):
        serializar_turno()
        registro = ApontamentoTurnoBladder.objects.using('default').get(pk=apontamento_id)
        op = OrdemProducaoBladder.objects.using('default').select_for_update().get(pk=registro.ordem_id)
        registro = ApontamentoTurnoBladder.objects.using('default').select_for_update().get(pk=apontamento_id)
        if registro.origem == 'LEGADO' or not pode_corrigir(registro, usuario):
            raise PermissionError('Correção não permitida: somente o próprio operador no turno aberto ou a liderança.')
        valores = _dados_validados(registro.codigo_processo, dados)
        nova_qtd = valores.get('quantidade_realizada', registro.quantidade_realizada)
        mudou_qtd = nova_qtd != registro.quantidade_realizada
        if mudou_qtd and ApontamentoTurnoBladder.objects.using('default').filter(extrusao_origem=registro).exists():
            raise ValueError('A quantidade desta extrusão não pode ser alterada: seu manuseio e amostras já foram registrados.')
        saldos = SaldoPendenteBladder.objects.using('default').select_for_update().filter(op_origem=op)
        if mudou_qtd and saldos.exclude(status='PENDENTE').exists():
            raise ValueError('A pendência desta OP já foi incorporada ou encerrada. A quantidade não pode ser alterada automaticamente.')
        antes = snapshot(registro)
        qtd_anterior = registro.quantidade_realizada
        for campo in PARAMETROS:
            if campo in valores:
                setattr(registro, campo, valores[campo])
        registro.quantidade_realizada = nova_qtd
        if registro.origem == 'MANUSEIO':
            validar_extrusao(registro.extrusao_origem)
            medidas = _amostras_validadas(registro.extrusao_origem.quantidade_realizada, amostras)
            _salvar_amostras(registro, medidas)
        else:
            registro.save(using='default')
        if mudou_qtd:
            op.quantidade_realizada = total_executado(op)
            item = op.itens_fechamento.select_for_update().filter(fechamento__status='CONCLUIDO').first()
            if item:
                saldo = max(0, op.quantidade_planejada - op.quantidade_realizada)
                cats = list(CategoriaDesvioBladder.objects.using('default').filter(pk__in=categorias or [], ativo=True)) if categorias is not None else list(item.categorias.all())
                descricao = str(descricao_desvio or item.descricao_desvio or '').strip()
                if saldo and (not cats or not descricao):
                    raise ValueError('A correção com déficit exige categorias e descrição do ocorrido.')
                item.quantidade_realizada = op.quantidade_realizada
                item.saldo_gerado = saldo
                item.situacao = 'CONCLUIDA' if not saldo else ('PARCIAL' if op.quantidade_realizada else 'NAO_REALIZADA')
                item.descricao_desvio = descricao if saldo else ''
                item.motivo = cats[0].codigo if saldo else None
                item.motivo_outro = descricao if saldo and any(c.codigo == 'OUTRO' for c in cats) else None
                item.save(using='default')
                item.categorias.set(cats if saldo else [])
                atual = saldos.first()
                if atual:
                    atual.quantidade = saldo
                    if not saldo:
                        atual.status = 'CANCELADO'
                        atual.motivo_cancelamento = 'Saldo zerado por correção auditada: ' + str(motivo).strip()
                    atual.save(using='default', update_fields=['quantidade', 'status', 'motivo_cancelamento'])
                elif saldo:
                    SaldoPendenteBladder.objects.using('default').create(op_origem=op, produto=op.produto, quantidade=saldo, status='PENDENTE', fechamento=item.fechamento)
                op.status = 'PARCIAL' if saldo else 'CONCLUIDA'
            op.save(using='default', update_fields=['quantidade_realizada', 'status', 'updated_at'])
        HistoricoApontamentoBladder.objects.using('default').create(
            apontamento=registro, usuario=usuario, motivo_correcao=str(motivo).strip(),
            quantidade_anterior=qtd_anterior, quantidade_nova=registro.quantidade_realizada,
            situacao_anterior=registro.situacao, situacao_nova=registro.situacao,
            valores_anteriores=antes, valores_novos=snapshot(registro))
        from .sincronizacao_drs import enfileirar
        enfileirar(registro)
        return registro
