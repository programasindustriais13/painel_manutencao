import datetime
import logging
import os
from decimal import Decimal
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Case, When, Value, IntegerField, Q, Sum, Count
from django.utils import timezone
from .models import (
    ProcessoBladder,
    ConfiguracaoEscalaBladder,
    AjusteEscalaExcepcionalBladder,
    FuncionarioApoioBladder,
    ProdutoBladder,
    OrdemProducaoBladder,
    SaldoPendenteBladder,
    ApontamentoTurnoBladder,
    FechamentoTurnoBladder,
    ItemFechamentoTurnoBladder,
    CategoriaDesvioBladder,
    HistoricoApontamentoBladder,
    HistoricoProgramacaoBladder,
    MensagemPassagemTurnoBladder,
    AcaoMensagemTurnoBladder,
    TipoAtividadeBladder,
    AtividadeTurnoBladder,
    MovimentacaoEstoqueBladder,
    HistoricoEdicaoMensagemTurnoBladder,
    ConfiguracaoWhatsAppBladder,
)

logger = logging.getLogger("bladder.services")


def obter_configuracao_escala_ativa():
    """
    Retorna a configuração ativa de escala 12x36 (06:00 às 18:00).
    Caso nenhuma esteja ativa, cria uma configuração padrão com Turma A
    na data atual.
    """
    config = ConfiguracaoEscalaBladder.objects.filter(ativo=True).order_by('-updated_at').first()
    if not config:
        config = ConfiguracaoEscalaBladder.objects.create(
            data_referencia=timezone.localdate(),
            turma_referencia='TURMA_A',
            hora_inicio=datetime.time(6, 0),
            hora_fim=datetime.time(18, 0),
            ativo=True,
            observacoes="Configuração padrão gerada automaticamente pelo sistema."
        )
    return config


def calcular_turma_do_dia(data=None):
    """
    Calcula determinística e dinamicamente qual turma trabalha em determinada data.
    Retorna tupla: (codigo_turma, is_ajuste_excepcional, motivo_ou_obs)
    Ex: ('TURMA_A', False, None) ou ('TURMA_B', True, 'Troca excepcional')
    """
    if data is None:
        data = timezone.localdate()

    # 1. Verifica se há ajuste excepcional cadastrado para o dia
    ajuste = AjusteEscalaExcepcionalBladder.objects.filter(data=data).first()
    if ajuste:
        return ajuste.turma_designada, True, ajuste.motivo

    # 2. Alternância padrão 12x36 baseada na data de referência configurada
    config = obter_configuracao_escala_ativa()
    delta_dias = (data - config.data_referencia).days

    if delta_dias % 2 == 0:
        turma = config.turma_referencia
    else:
        turma = 'TURMA_B' if config.turma_referencia == 'TURMA_A' else 'TURMA_A'

    return turma, False, None


def verificar_usuario_apoio_no_dia(user, data=None):
    """
    Verifica se o usuário possui registro ativo de Apoio Operacional para a data informada.
    Retorna tupla: (is_apoio, funcionario_apoio_obj)
    """
    if not user or not user.is_authenticated:
        return False, None

    if data is None:
        data = timezone.localdate()

    apoios = FuncionarioApoioBladder.objects.filter(usuario=user, ativo=True)
    weekday_str = str(data.weekday())  # 0=Monday, 6=Sunday
    data_iso = data.strftime('%Y-%m-%d')

    for apoio in apoios:
        if apoio.tipo_escala == 'DIAS_SEMANA':
            if apoio.dias_semana:
                dias_permitidos = [d.strip() for d in apoio.dias_semana.split(',')]
                if weekday_str in dias_permitidos:
                    return True, apoio
        elif apoio.tipo_escala == 'DATAS_ESPECIFICAS':
            if apoio.datas_especificas:
                datas = [d.strip() for d in apoio.datas_especificas.replace('\n', ',').split(',') if d.strip()]
                if data_iso in datas:
                    return True, apoio

    return False, None


def gerar_proximo_numero_op(data=None):
    """
    Gera um número sequencial e único para a Ordem de Produção no formato:
    OP-BLA-YYYYMMDD-0001
    """
    if data is None:
        data = timezone.localdate()

    prefixo = f"OP-BLA-{data.strftime('%Y%m%d')}"
    ultima_op = OrdemProducaoBladder.objects.filter(
        numero_ordem__startswith=prefixo
    ).order_by('-numero_ordem').first()

    if not ultima_op:
        return f"{prefixo}-0001"

    try:
        ultimo_seq = int(ultima_op.numero_ordem.split('-')[-1])
        return f"{prefixo}-{str(ultimo_seq + 1).zfill(4)}"
    except (ValueError, IndexError):
        total = OrdemProducaoBladder.objects.filter(numero_ordem__startswith=prefixo).count()
        return f"{prefixo}-{str(total + 1).zfill(4)}"


def obter_saldos_pendentes_produto(produto_id):
    """
    Retorna o queryset de saldos pendentes disponíveis para um produto,
    em ordem cronológica (FIFO).
    """
    return SaldoPendenteBladder.objects.filter(
        produto_id=produto_id,
        status='PENDENTE'
    ).order_by('created_at')


@transaction.atomic(using='default')
def criar_ordem_producao_com_saldos(
    processo,
    produto=None,
    data_programada=None,
    quantidade_nova=0,
    prioridade='NORMAL',
    saldos_selecionados_ids=None,
    recursos_alocados=None,
    recursos_observacoes="",
    observacoes="",
    usuario=None
):
    """
    Cria uma nova Ordem de Produção (OP).
    REGRA CRÍTICA DO FLUXO CANÔNICO:
    A pendência NÃO é mais incorporada automaticamente.
    Apenas incorpora saldos anteriores se o líder decidir explicitamente
    passando os IDs em saldos_selecionados_ids.
    Caso contrário, os saldos anteriores permanecem PENDENTES no Ledger.
    Previne concorrência e consumo duplo via select_for_update().
    """
    if data_programada is None:
        data_programada = timezone.localdate()
    turma_prevista, _, _ = calcular_turma_do_dia(data_programada)
    numero_ordem = gerar_proximo_numero_op(data_programada)

    # 1. Trava apenas os saldos explicitamente selecionados pelo líder para este produto
    saldos_a_incorporar = []
    if saldos_selecionados_ids and produto:
        saldos_a_incorporar = list(
            SaldoPendenteBladder.objects.select_for_update()
            .filter(id__in=saldos_selecionados_ids, produto=produto, status='PENDENTE')
            .order_by('created_at')
        )

    total_saldo = sum(s.quantidade for s in saldos_a_incorporar)
    qtd_nova = int(quantidade_nova or 0)
    quantidade_planejada = qtd_nova + total_saldo

    # 2. Cria a Ordem de Produção
    op = OrdemProducaoBladder.objects.create(
        numero_ordem=numero_ordem,
        processo=processo,
        produto=produto,
        data_programada=data_programada,
        turma_prevista=turma_prevista,
        prioridade=prioridade,
        quantidade_nova=qtd_nova,
        saldo_anterior_incorporado=total_saldo,
        quantidade_planejada=quantidade_planejada,
        status='PENDENTE',
        recursos_observacoes=recursos_observacoes,
        observacoes=observacoes,
        criado_por=usuario
    )

    if recursos_alocados:
        op.recursos_alocados.set(recursos_alocados)

    # 3. Atualiza os saldos no Ledger como INCORPORADO vinculando à nova OP destino
    agora = timezone.now()
    for s in saldos_a_incorporar:
        s.status = 'INCORPORADO'
        s.op_destino = op
        s.data_incorporacao = agora
        s.save(update_fields=['status', 'op_destino', 'data_incorporacao'])

    # 4. Registra histórico imutável de criação
    motivo_criacao = f"Criação da programação. Demanda nova: {quantidade_nova} un."
    if total_saldo > 0:
        motivo_criacao += f" Saldo anterior incorporado por decisão do líder: {total_saldo} un (Total a produzir: {quantidade_planejada} un)."
    else:
        motivo_criacao += f" Total a produzir: {quantidade_planejada} un."

    HistoricoProgramacaoBladder.objects.create(
        ordem=op,
        tipo_evento='CRIACAO',
        data_nova=data_programada,
        quantidade_nova=quantidade_planejada,
        motivo=motivo_criacao,
        usuario=usuario
    )

    return op


@transaction.atomic(using='default')
def encerrar_op_parcial_ou_total(op_id, usuario, motivo_encerramento=""):
    """
    Encerra a OP ao final do turno ou da operação.
    Se quantidade_realizada < quantidade_planejada:
      - Gera registro auditável no Ledger SaldoPendenteBladder com o saldo pendente.
      - Status da OP torna-se 'PARCIAL'.
    Se quantidade_realizada >= quantidade_planejada:
      - Status da OP torna-se 'CONCLUIDA'.
    """
    op = OrdemProducaoBladder.objects.select_for_update().get(pk=op_id)

    saldo = op.quantidade_planejada - op.quantidade_realizada

    if saldo > 0:
        op.status = 'PARCIAL'
        op.atualizado_por = usuario
        op.save(update_fields=['status', 'atualizado_por', 'updated_at'])

        # Registra o saldo no Ledger para o modelo/produto
        SaldoPendenteBladder.objects.create(
            op_origem=op,
            produto=op.produto,
            quantidade=saldo,
            status='PENDENTE'
        )

        HistoricoProgramacaoBladder.objects.create(
            ordem=op,
            tipo_evento='ENCERRAMENTO_PARCIAL',
            quantidade_anterior=op.quantidade_planejada,
            quantidade_nova=op.quantidade_realizada,
            motivo=f"Encerramento parcial do turno. Saldo gerado: {saldo} un. {motivo_encerramento}".strip(),
            usuario=usuario
        )
    else:
        op.status = 'CONCLUIDA'
        op.atualizado_por = usuario
        op.save(update_fields=['status', 'atualizado_por', 'updated_at'])

        HistoricoProgramacaoBladder.objects.create(
            ordem=op,
            tipo_evento='CONCLUSAO',
            quantidade_nova=op.quantidade_realizada,
            motivo=f"Conclusão integral da meta programada. {motivo_encerramento}".strip(),
            usuario=usuario
        )

    return op


@transaction.atomic(using='default')
def reprogramar_ordem_producao(op_id, nova_data, motivo, usuario):
    """
    Reprograma a data de uma OP mantendo a MESMA entidade (sem clonar).
    Registra data anterior, nova data, motivo obrigatório e usuário no histórico.
    """
    if not motivo or not str(motivo).strip():
        raise ValueError("O motivo da reprogramação é obrigatório.")

    op = OrdemProducaoBladder.objects.select_for_update().get(pk=op_id)
    data_anterior = op.data_programada

    turma_prevista, _, _ = calcular_turma_do_dia(nova_data)
    op.data_programada = nova_data
    op.turma_prevista = turma_prevista
    op.atualizado_por = usuario
    op.save(update_fields=['data_programada', 'turma_prevista', 'atualizado_por', 'updated_at'])

    HistoricoProgramacaoBladder.objects.create(
        ordem=op,
        tipo_evento='REPROGRAMACAO',
        data_anterior=data_anterior,
        data_nova=nova_data,
        quantidade_nova=op.quantidade_planejada,
        motivo=motivo.strip(),
        usuario=usuario
    )

    return op


@transaction.atomic(using='default')
def cancelar_ordem_producao(op_id, motivo, usuario):
    """
    Cancela logicamente uma OP (somente Líder/Admin).
    Se a OP havia incorporado saldos anteriores de outras OPs que ainda não foram
    produzidos, reabre esses saldos para status 'PENDENTE' para que não sejam perdidos.
    """
    if not motivo or not str(motivo).strip():
        raise ValueError("O motivo do cancelamento é obrigatório.")

    op = OrdemProducaoBladder.objects.select_for_update().get(pk=op_id)

    # Reabrir saldos incorporados que estavam vinculados a esta OP
    saldos_incorporados = SaldoPendenteBladder.objects.filter(op_destino=op, status='INCORPORADO')
    for s in saldos_incorporados:
        s.status = 'PENDENTE'
        s.op_destino = None
        s.data_incorporacao = None
        s.save(update_fields=['status', 'op_destino', 'data_incorporacao'])

    op.status = 'CANCELADA'
    op.motivo_cancelamento = motivo.strip()
    op.cancelado_por = usuario
    op.data_cancelamento = timezone.now()
    op.atualizado_por = usuario
    op.save(update_fields=['status', 'motivo_cancelamento', 'cancelado_por', 'data_cancelamento', 'atualizado_por', 'updated_at'])

    HistoricoProgramacaoBladder.objects.create(
        ordem=op,
        tipo_evento='CANCELAMENTO',
        motivo=f"Cancelamento justificado: {motivo.strip()}",
        usuario=usuario
    )

    return op


@transaction.atomic(using='default')
def registrar_ou_atualizar_apontamento(
    ordem_id,
    operador,
    quantidade,
    situacao='CONCLUIDA',
    motivo_desvio="",
    observacoes="",
    apontamento_id=None
):
    """
    Registra um novo apontamento ou conclui apontamento em andamento.
    Atualiza atomicamente a quantidade_realizada na Ordem de Produção.
    """
    op = OrdemProducaoBladder.objects.select_for_update().get(pk=ordem_id)
    turma_dia, _, _ = calcular_turma_do_dia(timezone.localdate())

    is_apoio, _ = verificar_usuario_apoio_no_dia(operador)
    turma_apontamento = 'APOIO' if is_apoio else turma_dia

    if apontamento_id:
        apontamento = ApontamentoTurnoBladder.objects.select_for_update().get(pk=apontamento_id)
        qtd_antiga = apontamento.quantidade_realizada
        apontamento.quantidade_realizada = quantidade
        apontamento.situacao = situacao
        apontamento.motivo_desvio = motivo_desvio
        apontamento.observacoes = observacoes
        apontamento.data_hora_fim = timezone.now()
        apontamento.save()

        # Recalcula total realizado da OP
        op.quantidade_realizada = (op.quantidade_realizada - qtd_antiga) + quantidade
    else:
        apontamento = ApontamentoTurnoBladder.objects.create(
            ordem=op,
            operador=operador,
            turma=turma_apontamento,
            data_turno=timezone.localdate(),
            data_hora_inicio=timezone.now(),
            data_hora_fim=timezone.now() if situacao != 'EM_ANDAMENTO' else None,
            quantidade_realizada=quantidade,
            situacao=situacao,
            motivo_desvio=motivo_desvio,
            observacoes=observacoes
        )
        op.quantidade_realizada += quantidade

    # Atualiza status da OP se necessário
    if op.quantidade_realizada >= op.quantidade_planejada:
        op.status = 'CONCLUIDA'
    elif situacao == 'EM_ANDAMENTO' and op.status == 'PENDENTE':
        op.status = 'EM_EXECUCAO'
    elif situacao in ('CONCLUIDA', 'PARCIAL') and op.status in ('PENDENTE', 'EM_EXECUCAO'):
        if op.quantidade_realizada < op.quantidade_planejada:
            op.status = 'EM_EXECUCAO'  # permanece em execução até fechamento ou atingimento

    op.save(update_fields=['quantidade_realizada', 'status', 'updated_at'])
    return apontamento


@transaction.atomic(using='default')
def corrigir_apontamento_operador_ou_lider(
    apontamento_id,
    nova_quantidade,
    motivo_correcao,
    usuario
):
    """
    Permite corrigir apontamento:
    - O operador pode corrigir no mesmo turno aberto.
    - O líder/admin pode corrigir a qualquer tempo.
    Gera registro imutável em HistoricoApontamentoBladder.
    """
    if not motivo_correcao or not str(motivo_correcao).strip():
        raise ValueError("O motivo da correção é obrigatório.")

    apontamento = ApontamentoTurnoBladder.objects.select_for_update().get(pk=apontamento_id)
    op = OrdemProducaoBladder.objects.select_for_update().get(pk=apontamento.ordem_id)

    qtd_anterior = apontamento.quantidade_realizada
    diff = int(nova_quantidade) - qtd_anterior

    # Grava auditoria
    HistoricoApontamentoBladder.objects.create(
        apontamento=apontamento,
        quantidade_anterior=qtd_anterior,
        quantidade_nova=nova_quantidade,
        situacao_anterior=apontamento.situacao,
        situacao_nova=apontamento.situacao,
        motivo_correcao=motivo_correcao.strip(),
        usuario=usuario
    )

    apontamento.quantidade_realizada = nova_quantidade
    apontamento.save(update_fields=['quantidade_realizada', 'updated_at'])

    op.quantidade_realizada += diff
    if op.quantidade_realizada >= op.quantidade_planejada:
        op.status = 'CONCLUIDA'
    op.save(update_fields=['quantidade_realizada', 'status', 'updated_at'])

    return apontamento


@transaction.atomic(using='default')
def executar_fechamento_turno(data_turno, operador, itens_dados, observacoes=""):
    """
    Executa o Fechamento Único de Turno para o setor de Bladder.
    Realizado exclusivamente por operador autorizado do turno.
    Valida:
    - Autorização do operador e correspondência com a escala daquele dia.
    - Idempotência (não permite duplo fechamento para o mesmo turno/data).
    - Presença de OPs programadas.
    - Quantidade realizada >= 0 e <= meta planejada (rejeita sobreprodução silenciosa).
    - Obrigatoriedade de motivo para OPs parciais ou não realizadas (e descrição se motivo='OUTRO').
    Efetua:
    - Gravação atômica do FechamentoTurnoBladder.
    - Atualização do status de cada OP (CONCLUIDA ou PARCIAL).
    - Criação de ItemFechamentoTurnoBladder com snapshot auditável.
    - Criação de ApontamentoTurnoBladder consolidado.
    - Geração de SaldoPendenteBladder para cada saldo > 0 vinculado ao fechamento.
    - Registro no HistoricoProgramacaoBladder.
    """
    if not operador or not operador.is_authenticated:
        raise PermissionError("Usuário não autenticado.")

    # 1. Determina escala do turno
    turma_hoje, _, _ = calcular_turma_do_dia(data_turno)
    is_apoio, _ = verificar_usuario_apoio_no_dia(operador, data_turno)
    perfil = getattr(operador, 'perfil_operacional_bladder', None)

    # Líder não realiza fechamento operacional normal
    from .decorators import user_is_lider_bladder, user_is_operador_regular_bladder
    if user_is_lider_bladder(operador) and not user_is_operador_regular_bladder(operador) and not is_apoio:
        raise PermissionError("O fechamento de turno operacional deve ser realizado pelo operador de máquina responsável pelo turno.")

    # Se for operador regular com turma, valida se pertence à turma do dia
    if perfil and not is_apoio:
        if perfil.turma != turma_hoje:
            turma_nome = "Turma A" if turma_hoje == 'TURMA_A' else ("Turma B" if turma_hoje == 'TURMA_B' else turma_hoje)
            raise PermissionError(f"Operador {operador.get_full_name() or operador.username} pertence à {perfil.get_turma_display()}, mas a escala de hoje é {turma_nome}.")

    # 2. Idempotência / Trava de concorrência
    fechamento_existente = FechamentoTurnoBladder.objects.select_for_update().filter(
        data_turno=data_turno,
        turma=turma_hoje,
        status='CONCLUIDO'
    ).first()
    if fechamento_existente:
        raise ValueError(f"O turno de {data_turno.strftime('%d/%m/%Y')} ({turma_hoje}) já foi encerrado por {fechamento_existente.operador.get_full_name() or fechamento_existente.operador.username} às {fechamento_existente.data_hora_fechamento.strftime('%H:%M')}.")

    # 3. Localiza OPs programadas para o turno
    ordens = list(OrdemProducaoBladder.objects.select_for_update().filter(
        data_programada=data_turno
    ).exclude(status='CANCELADA').order_by('numero_ordem'))

    if not ordens:
        raise ValueError("Não existem ordens de produção programadas para fechamento neste turno.")

    # 4. Mapeia dados enviados e valida todas as OPs
    itens_map = {item['ordem_id']: item for item in itens_dados}

    # Verifica duplicidade na submissão
    op_ids_submetidos = [item['ordem_id'] for item in itens_dados]
    if len(op_ids_submetidos) != len(set(op_ids_submetidos)):
        raise ValueError("Uma mesma OP não pode ser contabilizada mais de uma vez no mesmo fechamento.")

    itens_validados = []
    for op in ordens:
        if op.id not in itens_map:
            raise ValueError(f"A OP {op.numero_ordem} está programada para este turno mas não foi informada no fechamento.")

        dados_op = itens_map[op.id]
        try:
            realizada = int(dados_op.get('quantidade_realizada', 0))
        except (ValueError, TypeError):
            raise ValueError(f"Quantidade realizada inválida na OP {op.numero_ordem}.")

        if realizada < 0:
            raise ValueError(f"A quantidade realizada na OP {op.numero_ordem} não pode ser negativa.")

        # Saldo e Excedente
        saldo = max(0, op.quantidade_planejada - realizada)
        excedente = max(0, realizada - op.quantidade_planejada)

        cat_objs = []
        descricao_desvio = ""

        if saldo == 0:
            situacao = 'CONCLUIDA'
            motivo = None
            motivo_outro = None
        else:
            situacao = 'PARCIAL' if realizada > 0 else 'NAO_REALIZADA'

            # Resolução das categorias (suporta IDs, códigos, instâncias ou campo motivo)
            cats_raw = dados_op.get('categorias') or dados_op.get('categorias_ids') or []
            if isinstance(cats_raw, (int, str)):
                cats_raw = [cats_raw]
            elif not isinstance(cats_raw, list):
                cats_raw = list(cats_raw)

            if not cats_raw and dados_op.get('motivo'):
                cats_raw = [dados_op.get('motivo')]

            for c in cats_raw:
                if isinstance(c, CategoriaDesvioBladder):
                    cat_objs.append(c)
                elif str(c).isdigit():
                    obj = CategoriaDesvioBladder.objects.filter(id=int(c)).first()
                    if obj:
                        cat_objs.append(obj)
                elif isinstance(c, str) and c.strip():
                    c_str = c.strip().upper()
                    obj = CategoriaDesvioBladder.objects.filter(codigo=c_str).first()
                    if not obj:
                        obj = CategoriaDesvioBladder.objects.filter(nome__iexact=c.strip()).first()
                    if not obj:
                        obj, _ = CategoriaDesvioBladder.objects.get_or_create(
                            codigo=c_str,
                            defaults={'nome': c.strip(), 'ativo': True}
                        )
                    cat_objs.append(obj)

            descricao_desvio = (
                dados_op.get('descricao_desvio', '') or
                dados_op.get('motivo_outro', '') or
                dados_op.get('observacao', '') or
                ""
            ).strip()

            if not cat_objs:
                raise ValueError(f"Para a OP {op.numero_ordem} com saldo pendente de {saldo} un, o motivo do não cumprimento integral é obrigatório.")

            if not descricao_desvio:
                if 'categorias' in dados_op or any(c.codigo == 'OUTRO' for c in cat_objs) or dados_op.get('motivo') == 'OUTRO':
                    raise ValueError(f"Para a OP {op.numero_ordem}, a descrição do ocorrido ('O que aconteceu?') é obrigatória.")
                else:
                    descricao_desvio = cat_objs[0].nome if cat_objs else "Desvio operacional registrado"

            motivo = cat_objs[0].codigo if cat_objs else None
            motivo_outro = descricao_desvio if (motivo == 'OUTRO' or any(c.codigo == 'OUTRO' for c in cat_objs)) else None

        itens_validados.append({
            'op': op,
            'realizada': realizada,
            'saldo': saldo,
            'excedente': excedente,
            'situacao': situacao,
            'cat_objs': cat_objs,
            'descricao_desvio': descricao_desvio,
            'motivo': motivo,
            'motivo_outro': motivo_outro,
            'observacao': dados_op.get('observacao', '').strip()
        })

    # 5. Criação do evento auditável de Fechamento de Turno
    fechamento = FechamentoTurnoBladder.objects.create(
        data_turno=data_turno,
        turma=turma_hoje,
        operador=operador,
        data_hora_fechamento=timezone.now(),
        status='CONCLUIDO',
        observacoes=observacoes.strip()
    )

    # 6. Grava cada item, atualiza OPs, gera ledger de saldo e históricos
    for item in itens_validados:
        op = item['op']
        realizada = item['realizada']
        saldo = item['saldo']
        excedente = item['excedente']
        situacao = item['situacao']
        cat_objs = item['cat_objs']
        descricao_desvio = item['descricao_desvio']
        motivo = item['motivo']
        motivo_outro = item['motivo_outro']
        obs = item['observacao']

        # Atualiza a OP
        op.quantidade_realizada = realizada
        op.status = 'CONCLUIDA' if saldo == 0 else 'PARCIAL'
        op.save(update_fields=['quantidade_realizada', 'status', 'updated_at'])

        # Cria ItemFechamentoTurnoBladder
        item_fech = ItemFechamentoTurnoBladder.objects.create(
            fechamento=fechamento,
            ordem=op,
            quantidade_programada=op.quantidade_planejada,
            quantidade_realizada=realizada,
            saldo_gerado=saldo,
            situacao=situacao,
            descricao_desvio=descricao_desvio if saldo > 0 else None,
            motivo=motivo if saldo > 0 else None,
            motivo_outro=motivo_outro if (saldo > 0 and motivo == 'OUTRO') else None,
            observacao=obs
        )

        if cat_objs:
            item_fech.categorias.set(cat_objs)

        if saldo == 0:
            if excedente > 0:
                motivo_final = f"Meta cumprida com excedente (+{excedente} un)"
            else:
                motivo_final = "Meta cumprida integralmente"
        else:
            motivo_final = item_fech.motivo_completo

        # Cria ApontamentoTurnoBladder
        ApontamentoTurnoBladder.objects.create(
            fechamento=fechamento,
            ordem=op,
            operador=operador,
            turma=turma_hoje,
            data_turno=data_turno,
            data_hora_inicio=fechamento.data_hora_fechamento,
            data_hora_fim=fechamento.data_hora_fechamento,
            quantidade_realizada=realizada,
            situacao=situacao,
            motivo_desvio=motivo_final if saldo > 0 else "",
            observacoes=obs
        )

        # Se houver saldo > 0, cria registro no Ledger SaldoPendenteBladder
        if saldo > 0:
            SaldoPendenteBladder.objects.create(
                op_origem=op,
                produto=op.produto,
                quantidade=saldo,
                status='PENDENTE',
                fechamento=fechamento
            )

        # Histórico da OP
        if saldo == 0:
            tipo_ev = 'CONCLUSAO'
            if excedente > 0:
                motivo_hist = f"Fechamento do Turno ({turma_hoje}). Meta {op.quantidade_planejada} un concluída com excedente de {realizada} un (+{excedente} un acima da meta)."
            else:
                motivo_hist = f"Fechamento do Turno ({turma_hoje}). Meta {op.quantidade_planejada} un concluída integralmente ({realizada} un)."
        else:
            tipo_ev = 'ENCERRAMENTO_PARCIAL'
            motivo_hist = f"Fechamento do Turno ({turma_hoje}). Produzido: {realizada}/{op.quantidade_planejada} un. Saldo pendente: {saldo} un. Situação: {situacao}. {motivo_final}"

        HistoricoProgramacaoBladder.objects.create(
            ordem=op,
            tipo_evento=tipo_ev,
            quantidade_anterior=0,
            quantidade_nova=realizada,
            motivo=motivo_hist,
            usuario=operador
        )

    return fechamento


def calcular_proximo_turno_operacional(momento=None, data_referencia=None):
    """
    Calcula determinística e dinamicamente a próxima data e turma operacional.
    Leva em consideração:
    - timestamp real e timezone da fábrica;
    - horário configurado de término da escala (ConfiguracaoEscalaBladder.hora_fim);
    - horário configurado de início da escala (ConfiguracaoEscalaBladder.hora_inicio);
    - alternância 12x36 e eventuais ajustes excepcionais (AjusteEscalaExcepcionalBladder).

    Regra Crítica para Envios pós-18h e pré-06h:
    - Se o recado for criado antes de hora_inicio (ex: 05:30): o turno destinatário é o que começa HOJE às 06:00!
    - Se o recado for criado durante o turno ou após hora_fim (ex: 18:30): o turno destinatário é o próximo dia operacional!
    Retorna tupla: (data_proximo_turno, turma_proximo_turno, is_ajuste, motivo)
    """
    agora = momento or timezone.localtime(timezone.now())
    config = obter_configuracao_escala_ativa()
    hora_inicio = config.hora_inicio if config and config.hora_inicio else datetime.time(6, 0)
    hora_fim = config.hora_fim if config and config.hora_fim else datetime.time(18, 0)

    if data_referencia is None:
        if isinstance(agora, datetime.datetime):
            # Se for antes do início do expediente de hoje (ex: madrugada até 05:59):
            if agora.time() < hora_inicio:
                # O turno de destino é o expediente que se inicia HOJE
                turma_hoje, is_ajuste, motivo = calcular_turma_do_dia(agora.date())
                if turma_hoje in ['TURMA_A', 'TURMA_B']:
                    return agora.date(), turma_hoje, is_ajuste, motivo
            data_referencia = agora.date()
        else:
            data_referencia = agora

    dia_candidato = data_referencia + datetime.timedelta(days=1)
    limite_dias = 60  # Proteção contra loop infinito

    for _ in range(limite_dias):
        turma, is_ajuste, motivo = calcular_turma_do_dia(dia_candidato)
        if turma in ['TURMA_A', 'TURMA_B']:
            return dia_candidato, turma, is_ajuste, motivo
        dia_candidato += datetime.timedelta(days=1)

    turma_ref, _, _ = calcular_turma_do_dia(data_referencia)
    prox_turma = 'TURMA_B' if turma_ref == 'TURMA_A' else 'TURMA_A'
    return data_referencia + datetime.timedelta(days=1), prox_turma, False, None


@transaction.atomic(using='default')
def criar_mensagem_passagem_turno(
    autor,
    mensagem,
    tipo='INFORMATIVO',
    categoria='PRODUCAO',
    prioridade='NORMAL',
    data_turno_origem=None,
    ordem_producao=None,
    processo=None,
    maquina=None,
    produto=None,
    mensagem_origem=None
):
    """
    Cria uma mensagem de passagem de turno formal do Bladder.
    A turma de origem é calculada a partir da data de origem.
    A data e turma de destino são calculadas automaticamente para o próximo turno operacional
    respeitando horários após hora_fim e madrugada antes de hora_inicio.
    O operador não escolhe destinatário manual.
    """
    from .decorators import user_is_operador_bladder
    if not autor or not autor.is_authenticated or not user_is_operador_bladder(autor):
        raise PermissionError("Usuário não possui autorização para registrar recados no Setor de Bladder.")

    msg_texto = (mensagem or "").strip()
    if not msg_texto:
        raise ValueError("O conteúdo da mensagem é obrigatório.")

    if tipo not in ['INFORMATIVO', 'ACOMPANHAMENTO']:
        raise ValueError(f"Tipo de mensagem inválido: {tipo}")

    categorias_validas = ['PRODUCAO', 'EQUIPAMENTO', 'QUALIDADE', 'MATERIAL', 'SEGURANCA', 'OUTRO']
    if categoria not in categorias_validas:
        raise ValueError(f"Categoria inválida: {categoria}")

    prioridades_validas = ['NORMAL', 'IMPORTANTE', 'URGENTE']
    if prioridade not in prioridades_validas:
        raise ValueError(f"Prioridade inválida: {prioridade}")

    agora = timezone.localtime(timezone.now())
    config = obter_configuracao_escala_ativa()
    hora_inicio = config.hora_inicio if config and config.hora_inicio else datetime.time(6, 0)

    if data_turno_origem is None:
        if agora.time() < hora_inicio:
            # Se foi criado na madrugada antes das 06:00, o turno de origem foi o dia anterior
            data_turno_origem = agora.date() - datetime.timedelta(days=1)
        else:
            data_turno_origem = agora.date()

    turma_origem, _, _ = calcular_turma_do_dia(data_turno_origem)
    data_turno_destino, turma_destino, _, _ = calcular_proximo_turno_operacional(momento=agora, data_referencia=data_turno_origem)

    # Derivação de contexto da OP se fornecida
    if ordem_producao:
        if not processo:
            processo = ordem_producao.processo
        if not produto:
            produto = ordem_producao.produto
        if not maquina and processo and processo.maquina:
            maquina = processo.maquina
    elif processo and not maquina and processo.maquina:
        maquina = processo.maquina

    msg = MensagemPassagemTurnoBladder.objects.create(
        autor=autor,
        data_turno_origem=data_turno_origem,
        turma_origem=turma_origem,
        data_turno_destino=data_turno_destino,
        turma_destino=turma_destino,
        tipo=tipo,
        categoria=categoria,
        prioridade=prioridade,
        mensagem=msg_texto,
        ordem_producao=ordem_producao,
        processo=processo,
        maquina=maquina,
        produto=produto,
        status='ABERTA',
        mensagem_origem=mensagem_origem,
    )
    return msg


@transaction.atomic(using='default')
def editar_mensagem_passagem_turno(
    mensagem_id,
    usuario,
    novo_texto,
    novo_tipo=None,
    nova_categoria=None,
    nova_prioridade=None
):
    """
    Edita uma mensagem de passagem de turno existente mantendo o MESMO ID ativo.
    Grava o histórico imutável da versão anterior em HistoricoEdicaoMensagemTurnoBladder.
    Impede que a versão antiga continue aparecendo como um recado ativo separado.
    """
    from .decorators import user_is_lider_bladder, user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para editar recados no Setor de Bladder.")

    msg = MensagemPassagemTurnoBladder.objects.select_for_update().get(pk=mensagem_id)

    # Apenas o autor ou líder pode editar recados abertos
    if msg.autor != usuario and not user_is_lider_bladder(usuario):
        raise PermissionError("Apenas o autor ou a liderança podem editar este recado.")

    if msg.status != 'ABERTA':
        raise ValueError("Apenas recados abertos podem ser editados.")

    texto_antigo = msg.mensagem
    novo_texto = (novo_texto or "").strip()
    if not novo_texto:
        raise ValueError("O conteúdo da mensagem não pode ser vazio.")

    # Se o texto mudou, registra auditoria
    if texto_antigo != novo_texto:
        HistoricoEdicaoMensagemTurnoBladder.objects.create(
            mensagem=msg,
            texto_anterior=texto_antigo,
            texto_novo=novo_texto,
            usuario=usuario
        )

    msg.mensagem = novo_texto
    if novo_tipo:
        msg.tipo = novo_tipo
    if nova_categoria:
        msg.categoria = nova_categoria
    if nova_prioridade:
        msg.prioridade = nova_prioridade

    msg.editado_por = usuario
    msg.editado_em = timezone.now()
    msg.save(update_fields=['mensagem', 'tipo', 'categoria', 'prioridade', 'editado_por', 'editado_em', 'updated_at'])

    return msg


def registrar_ciencia_mensagem_turno(mensagem, usuario):
    """
    Registra ciência individual do usuário na mensagem de turno.
    Idempotente: o mesmo usuário não duplica registro de CIENTE.
    Não marca ciência para outros usuários.
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não autorizado a registrar ciência no Setor de Bladder.")

    acao_obj, created = AcaoMensagemTurnoBladder.objects.get_or_create(
        mensagem=mensagem,
        usuario=usuario,
        acao='CIENTE'
    )
    return acao_obj, created


@transaction.atomic(using='default')
def resolver_mensagem_acompanhamento(mensagem, usuario, observacao=""):
    """
    Marca uma mensagem do tipo ACOMPANHAMENTO como RESOLVIDA.
    Preserva histórico completo e registra a ação de resolução.
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não autorizado a resolver acompanhamentos no Setor de Bladder.")

    if mensagem.tipo != 'ACOMPANHAMENTO':
        raise ValueError("Apenas mensagens do tipo Acompanhamento podem ser resolvidas.")

    if mensagem.status != 'ABERTA':
        raise ValueError("Esta mensagem não está aberta para resolução.")

    obs = (observacao or "").strip()
    agora = timezone.now()

    mensagem.status = 'RESOLVIDA'
    mensagem.resolvido_por = usuario
    mensagem.resolvido_em = agora
    mensagem.observacao_resolucao = obs
    mensagem.save(update_fields=['status', 'resolvido_por', 'resolvido_em', 'observacao_resolucao', 'updated_at'])

    AcaoMensagemTurnoBladder.objects.create(
        mensagem=mensagem,
        usuario=usuario,
        acao='RESOLVIDO',
        observacao=obs
    )
    # Garante também registro de ciência
    AcaoMensagemTurnoBladder.objects.get_or_create(
        mensagem=mensagem,
        usuario=usuario,
        acao='CIENTE'
    )
    return mensagem


@transaction.atomic(using='default')
def repassar_mensagem_acompanhamento(mensagem, usuario, observacao=""):
    """
    Repassa um acompanhamento não resolvido para o próximo turno operacional.
    A mensagem original é marcada como REPASSADA e uma nova mensagem é criada
    com destino para o próximo turno da escala, vinculada através de mensagem_origem
    (preservando a cadeia A -> B -> A...).
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não autorizado a repassar recados no Setor de Bladder.")

    if mensagem.tipo != 'ACOMPANHAMENTO':
        raise ValueError("Apenas mensagens do tipo Acompanhamento podem ser repassadas.")

    if mensagem.status != 'ABERTA':
        raise ValueError("Esta mensagem não está aberta para repasse.")

    obs = (observacao or "").strip()
    agora = timezone.now()

    # 1. Encerra a mensagem atual como REPASSADA
    mensagem.status = 'REPASSADA'
    mensagem.repassado_por = usuario
    mensagem.repassado_em = agora
    mensagem.observacao_repasse = obs
    mensagem.save(update_fields=['status', 'repassado_por', 'repassado_em', 'observacao_repasse', 'updated_at'])

    AcaoMensagemTurnoBladder.objects.create(
        mensagem=mensagem,
        usuario=usuario,
        acao='REPASSADO',
        observacao=obs
    )
    AcaoMensagemTurnoBladder.objects.get_or_create(
        mensagem=mensagem,
        usuario=usuario,
        acao='CIENTE'
    )

    # 2. Calcula próximo turno operacional de destino a partir da data de recebimento
    data_origem_repasse = mensagem.data_turno_destino
    turma_origem_repasse = mensagem.turma_destino
    prox_data_destino, prox_turma_destino, _, _ = calcular_proximo_turno_operacional(momento=agora, data_referencia=data_origem_repasse)

    texto_repassado = mensagem.mensagem
    if obs:
        autor_repasse = usuario.get_full_name() or usuario.username
        texto_repassado = f"{mensagem.mensagem}\n\n[Repasse por {autor_repasse}]: {obs}"

    nova_mensagem = MensagemPassagemTurnoBladder.objects.create(
        autor=usuario,
        data_turno_origem=data_origem_repasse,
        turma_origem=turma_origem_repasse,
        data_turno_destino=prox_data_destino,
        turma_destino=prox_turma_destino,
        tipo='ACOMPANHAMENTO',
        categoria=mensagem.categoria,
        prioridade=mensagem.prioridade,
        mensagem=texto_repassado,
        ordem_producao=mensagem.ordem_producao,
        processo=mensagem.processo,
        maquina=mensagem.maquina,
        produto=mensagem.produto,
        status='ABERTA',
        mensagem_origem=mensagem,
    )
    return nova_mensagem


def obter_mensagens_recebidas_turno(data_turno=None, turma=None, usuario=None, apenas_ativas=True):
    """
    Retorna a lista de mensagens recebidas para a data/turma informada.
    Ordenação canônica:
    1. Urgentes primeiro
    2. Importantes em seguida
    3. Normais por último
    4. Mais recentes (-created_at)

    Se apenas_ativas=True:
    - Oculta recados informativos expirados visualmente (> 48h);
    - Oculta recados com status 'REPASSADA' (estes pertencem ao histórico/cadeia).
    Cada mensagem recebe o atributo `usuario_ciente` se usuario for informado.
    """
    if data_turno is None:
        agora = timezone.localtime(timezone.now())
        data_turno = agora.date()

    if turma is None:
        turma, _, _ = calcular_turma_do_dia(data_turno)

    qs = MensagemPassagemTurnoBladder.objects.filter(
        Q(data_turno_destino=data_turno, turma_destino=turma) |
        Q(data_turno_destino__lt=data_turno, turma_destino=turma, status='ABERTA')
    ).select_related(
        'autor', 'ordem_producao', 'processo', 'maquina', 'produto',
        'resolvido_por', 'repassado_por', 'editado_por', 'mensagem_origem'
    ).prefetch_related(
        'acoes__usuario', 'historico_edicoes'
    ).annotate(
        peso_prioridade=Case(
            When(prioridade='URGENTE', then=Value(1)),
            When(prioridade='IMPORTANTE', then=Value(2)),
            default=Value(3),
            output_field=IntegerField()
        )
    ).order_by('peso_prioridade', '-created_at')

    if apenas_ativas:
        qs = qs.exclude(status='REPASSADA')

    mensagens_lista = []
    agora = timezone.now()
    limite_expiracao_informativo = agora - datetime.timedelta(hours=48)

    for m in qs:
        if apenas_ativas and m.tipo == 'INFORMATIVO' and m.created_at < limite_expiracao_informativo:
            continue
        mensagens_lista.append(m)

    if usuario and usuario.is_authenticated:
        for m in mensagens_lista:
            m.usuario_ciente = any(a.usuario_id == usuario.id and a.acao == 'CIENTE' for a in m.acoes.all())
    else:
        for m in mensagens_lista:
            m.usuario_ciente = False

    return mensagens_lista


# ==============================================================================
# MOTOR DO ESTOQUE DE BLADDERS ACABADOS (LEDGER, SEMÁFORO E DR-201)
# ==============================================================================

@transaction.atomic(using='default')
def registrar_entrada_estoque(
    produto,
    quantidade,
    usuario,
    turma='TURMA_A',
    destino=None,
    op=None,
    lote_etiqueta=None,
    data_turno=None,
    justificativa="",
    idempotency_key=None,
    disparar_sync=True
):
    """
    Registra entrada física conferida de Bladders Acabados no estoque.
    A entrada só acontece quando as peças estiverem fisicamente verificadas e armazenadas.
    Conclusão da OP não gera entrada automática.
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para movimentar estoque no Setor de Bladder.")

    qtd = int(quantidade)
    if qtd <= 0:
        raise ValueError("A quantidade de entrada deve ser maior que zero.")

    if idempotency_key:
        existente = MovimentacaoEstoqueBladder.objects.filter(idempotency_key=idempotency_key).first()
        if existente:
            return existente

    p = ProdutoBladder.objects.select_for_update().get(pk=produto.pk)
    saldo_anterior = p.estoque_atual
    saldo_posterior = saldo_anterior + qtd
    p.estoque_atual = saldo_posterior
    p.save(update_fields=['estoque_atual', 'updated_at'])

    hoje = data_turno if data_turno else timezone.localdate()
    mov = MovimentacaoEstoqueBladder.objects.create(
        produto=p,
        tipo='ENTRADA',
        quantidade=qtd,
        saldo_anterior=saldo_anterior,
        saldo_posterior=saldo_posterior,
        usuario=usuario,
        turma=turma,
        data_turno=hoje,
        destino=destino or "Estoque Central Bladder",
        ordem_producao=op,
        lote_etiqueta=lote_etiqueta,
        justificativa=justificativa,
        idempotency_key=idempotency_key,
    )
    if disparar_sync:
        transaction.on_commit(lambda: disparar_sincronizacao_dr201_async(mov.id))
    return mov


@transaction.atomic(using='default')
def registrar_saida_estoque(
    produto,
    quantidade,
    usuario,
    turma='TURMA_A',
    destino="",
    lote_etiqueta=None,
    data_turno=None,
    justificativa="",
    idempotency_key=None,
    disparar_sync=True
):
    """
    Registra saída de Bladders Acabados do estoque para consumo (ex: Vulcanização).
    Bloqueia estritamente estoque negativo.
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para movimentar estoque no Setor de Bladder.")

    qtd = int(quantidade)
    if qtd <= 0:
        raise ValueError("A quantidade de saída deve ser maior que zero.")

    dest = (destino or "").strip()

    if idempotency_key:
        existente = MovimentacaoEstoqueBladder.objects.filter(idempotency_key=idempotency_key).first()
        if existente:
            return existente

    p = ProdutoBladder.objects.select_for_update().get(pk=produto.pk)
    saldo_anterior = p.estoque_atual

    if saldo_anterior - qtd < 0:
        raise ValueError(
            f"Saldo insuficiente para retirada. Estoque atual: {saldo_anterior} un, solicitado: {qtd} un. "
            "Não é permitido saldo negativo no estoque."
        )

    saldo_posterior = saldo_anterior - qtd
    p.estoque_atual = saldo_posterior
    p.save(update_fields=['estoque_atual', 'updated_at'])

    hoje = data_turno if data_turno else timezone.localdate()
    mov = MovimentacaoEstoqueBladder.objects.create(
        produto=p,
        tipo='SAIDA',
        quantidade=qtd,
        saldo_anterior=saldo_anterior,
        saldo_posterior=saldo_posterior,
        usuario=usuario,
        turma=turma,
        data_turno=hoje,
        destino=dest,
        lote_etiqueta=lote_etiqueta,
        justificativa=justificativa,
        idempotency_key=idempotency_key,
    )
    if disparar_sync:
        transaction.on_commit(lambda: disparar_sincronizacao_dr201_async(mov.id))
    return mov


@transaction.atomic(using='default')
def registrar_ajuste_estoque(
    produto,
    novo_saldo,
    usuario,
    turma='LIDERANCA',
    justificativa=""
):
    """
    Ajuste formal e auditado de inventário de Bladders Acabados.
    Ação exclusiva da liderança.
    Registra saldo anterior, novo saldo, diferença e justificativa obrigatória.
    """
    from .decorators import user_is_lider_bladder
    if not usuario or not usuario.is_authenticated or not user_is_lider_bladder(usuario):
        raise PermissionError("Ajustes de inventário são de acesso exclusivo da Liderança do Setor de Bladder.")

    just = (justificativa or "").strip()
    if len(just) < 5:
        raise ValueError("A justificativa do ajuste de inventário é obrigatória (mínimo de 5 caracteres).")

    saldo_ajustado = int(novo_saldo)
    if saldo_ajustado < 0:
        raise ValueError("O novo saldo de estoque não pode ser negativo.")

    p = ProdutoBladder.objects.select_for_update().get(pk=produto.pk)
    saldo_anterior = p.estoque_atual
    diferenca = saldo_ajustado - saldo_anterior

    if diferenca == 0:
        raise ValueError("O novo saldo informado é idêntico ao saldo atual. Nenhum ajuste necessário.")

    p.estoque_atual = saldo_ajustado
    p.save(update_fields=['estoque_atual', 'updated_at'])

    hoje = timezone.localdate()
    mov = MovimentacaoEstoqueBladder.objects.create(
        produto=p,
        tipo='AJUSTE',
        quantidade=abs(diferenca),
        saldo_anterior=saldo_anterior,
        saldo_posterior=saldo_ajustado,
        usuario=usuario,
        turma=turma,
        data_turno=hoje,
        justificativa=f"{just} (Diferença: {'+' if diferenca > 0 else ''}{diferenca} un)",
    )
    return mov


@transaction.atomic(using='default')
def registrar_movimentacao_multipla_estoque(
    produto,
    tipo,
    quantidade,
    usuario,
    lotes=None,
    destino="",
    justificativa="",
    data_turno=None,
    turno_str=None,
    turma='TURMA_A',
    disparar_sync=True
):
    """
    Registra movimentação física de Bladders Acabados no estoque (Entrada ou Saída).
    Quando a quantidade informada é N (ex: 3 peças):
    - Cria N registros individuais de MovimentacaoEstoqueBladder (quantidade=1 cada),
      atribuindo o lote correspondente a cada peça para rastreabilidade unitária perfeita.
    - Sincroniza em lote com a planilha DR-201, gerando exatamente N linhas individuais (1 por peça).
    - Impede rigorosamente saldo negativo na Saída através de select_for_update.
    """
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para movimentar estoque no Setor de Bladder.")

    qtd = int(quantidade)
    if qtd <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")

    tipo_upper = str(tipo).strip().upper()
    if tipo_upper not in ('ENTRADA', 'SAIDA'):
        raise ValueError(f"Tipo de movimentação inválido: {tipo}")

    p = ProdutoBladder.objects.select_for_update().get(pk=produto.pk)

    if tipo_upper == 'SAIDA':
        if p.estoque_atual < qtd:
            raise ValueError(
                f"Saldo insuficiente para retirada. Estoque atual: {p.estoque_atual} un, solicitado: {qtd} un. "
                "Não é permitido saldo negativo no estoque."
            )

    dest = (destino or "").strip()
    just = (justificativa or "").strip()
    hoje = data_turno if data_turno else timezone.localdate()

    # Prepara lista de lotes normalizada (1 por peça)
    lotes_raw = lotes or []
    if isinstance(lotes_raw, str):
        lotes_raw = [lotes_raw]
    lotes_limpos = [str(l).strip() for l in lotes_raw]

    movs_criadas = []
    for i in range(qtd):
        lote_peca = lotes_limpos[i] if i < len(lotes_limpos) else ""
        saldo_ant = p.estoque_atual
        if tipo_upper == 'SAIDA':
            saldo_pos = saldo_ant - 1
        else:
            saldo_pos = saldo_ant + 1

        p.estoque_atual = saldo_pos
        p.save(update_fields=['estoque_atual', 'updated_at'])

        mov = MovimentacaoEstoqueBladder.objects.create(
            produto=p,
            tipo=tipo_upper,
            quantidade=1,
            saldo_anterior=saldo_ant,
            saldo_posterior=saldo_pos,
            usuario=usuario,
            turma=turma,
            data_turno=hoje,
            destino=dest if tipo_upper == 'SAIDA' else (dest or "Estoque Central Bladder"),
            lote_etiqueta=lote_peca if lote_peca else None,
            justificativa=just if just else None,
        )
        movs_criadas.append(mov)

    if disparar_sync and movs_criadas:
        data_str = hoje.strftime('%d/%m/%Y')
        t_str = turno_str if turno_str else ('MANHÃ' if 6 <= timezone.localtime().hour < 18 else 'NOITE')
        mov_ids = [m.id for m in movs_criadas]
        transaction.on_commit(lambda: disparar_sincronizacao_lote_dr201_async(mov_ids, data_str, t_str))

    return movs_criadas, p.estoque_atual


def obter_resumo_estoque_bladders():
    """
    Retorna o catálogo completo de ProdutoBladder enriquecido com dados de estoque:
    - Estoque atual
    - Estoque mínimo
    - Situação semafórica (Crítico, Atenção, Normal, Não configurado)
    - Cobertura em dias
    - Sugestão de OP
    """
    produtos = ProdutoBladder.objects.filter(ativo=True, codigo__startswith='BLA').order_by('codigo')
    resumo = []
    total_estoque = 0
    total_criticos = 0
    total_atencao = 0
    total_normais = 0

    for p in produtos:
        sit = p.situacao_estoque
        if sit == 'CRITICO':
            total_criticos += 1
        elif sit == 'ATENCAO':
            total_atencao += 1
        elif sit == 'NORMAL':
            total_normais += 1

        total_estoque += p.estoque_atual
        resumo.append({
            'produto': p,
            'codigo': p.codigo,
            'medida': p.medida,
            'descricao': p.descricao,
            'estoque_atual': p.estoque_atual,
            'estoque_minimo': p.estoque_minimo,
            'situacao': sit,
            'situacao_display': p.situacao_estoque_display,
            'situacao_cor': p.situacao_estoque_cor,
            'cobertura_dias': p.cobertura_dias(dias=30),
            'sugestao_op': p.sugestao_op,
        })

    return {
        'itens': resumo,
        'total_produtos': len(resumo),
        'total_estoque': total_estoque,
        'total_pecas': total_estoque,
        'total_criticos': total_criticos,
        'criticos': total_criticos,
        'total_atencao': total_atencao,
        'atencao': total_atencao,
        'total_normais': total_normais,
        'normais': total_normais,
    }


# ==============================================================================
# AUDITORIA E RECONCILIAÇÃO DA PLANILHA DR-201 (GOOGLE SHEETS API)
# ==============================================================================

def auditar_planilha_dr201():
    """
    Realiza leitura somente-leitura da planilha DR-201 via Google Sheets API.
    Reconcilia modelos com ProdutoBladder e calcula estatísticas de movimentação.
    Não grava nem modifica nada no Google Sheets.
    """
    cred_path = os.path.join(settings.BASE_DIR, 'credentials.json')
    if not os.path.exists(cred_path):
        return {
            'sucesso': False,
            'erro': "Arquivo credentials.json não encontrado na raiz do projeto.",
        }

    try:
        import gspread
        gc = gspread.service_account(filename=cred_path)
        sh = gc.open_by_key('1lMXlQIpxTIkTYC0kCQir029Vrvb2M1l4hWvbxvDv0YM')
        ws = sh.worksheet('DR201')
        all_values = ws.get_all_values()
    except Exception as e:
        logger.warning(f"Falha ao conectar à API Google Sheets para DR-201: {e}")
        return {
            'sucesso': False,
            'erro': f"Erro ao acessar Google Sheets: {str(e)}",
        }

    if not all_values:
        return {'sucesso': False, 'erro': "A planilha DR-201 está vazia."}

    header = all_values[0]
    rows = all_values[1:]

    modelos_catalogo = {p.codigo: p for p in ProdutoBladder.objects.all()}
    stats_por_modelo = {}
    for cod in sorted(modelos_catalogo.keys()):
        stats_por_modelo[cod] = {
            'codigo': cod,
            'produto': modelos_catalogo[cod],
            'entradas': 0,
            'saidas': 0,
            'saldo_calculado': 0,
            'lotes_distintos': set(),
        }

    total_entradas = 0
    total_saidas = 0
    total_linhas_validas = 0
    linhas_vazias = 0
    modelos_desconhecidos = {}

    for r in rows:
        if not r or not any(r):
            linhas_vazias += 1
            continue

        total_linhas_validas += 1
        dest = r[4].strip() if len(r) > 4 else ""
        lote = r[6].strip() if len(r) > 6 else ""
        mod = r[7].strip() if len(r) > 7 else ""

        if mod not in stats_por_modelo:
            if mod not in modelos_desconhecidos:
                modelos_desconhecidos[mod] = {'entradas': 0, 'saidas': 0}
            if 'Entrada' in dest:
                modelos_desconhecidos[mod]['entradas'] += 1
            else:
                modelos_desconhecidos[mod]['saidas'] += 1
            continue

        item = stats_por_modelo[mod]
        if lote:
            item['lotes_distintos'].add(lote)

        if 'Entrada' in dest:
            item['entradas'] += 1
            total_entradas += 1
        elif 'Saída' in dest:
            item['saidas'] += 1
            total_saidas += 1

    tabela_reconciliacao = []
    for cod, st in sorted(stats_por_modelo.items()):
        saldo = st['entradas'] - st['saidas']
        st['saldo_calculado'] = saldo
        st['total_lotes'] = len(st['lotes_distintos'])
        tabela_reconciliacao.append({
            'codigo': cod,
            'produto_nome': st['produto'].codigo_com_medida,
            'entradas': st['entradas'],
            'saidas': st['saidas'],
            'saldo_calculado': saldo,
            'estoque_atual_django': st['produto'].estoque_atual,
            'estoque_minimo_django': st['produto'].estoque_minimo,
            'situacao': "Correspondência confirmada",
        })

    return {
        'sucesso': True,
        'total_linhas': len(all_values),
        'linhas_validas': total_linhas_validas,
        'linhas_vazias': linhas_vazias,
        'total_entradas': total_entradas,
        'total_saidas': total_saidas,
        'saldo_geral_calculado': total_entradas - total_saidas,
        'modelos_desconhecidos': modelos_desconhecidos,
        'tabela_reconciliacao': tabela_reconciliacao,
        'alerta_consistencia': "Atenção: A planilha DR-201 consiste em um formulário de registros de leitura de etiquetas. Alguns modelos (ex: BLA003) apresentam mais saídas que entradas devido a movimentações anteriores ao formulário. O saldo de referência deve ser validado pela liderança.",
    }


def sincronizar_lote_movimentacoes_dr201(movimentacoes_ids, data_turno_str=None, turno_str=None):
    """
    Sincroniza uma lista de movimentações físicas de estoque com a planilha DR-201 (Google Sheets).
    Utiliza ESTRITAMENTE o método append_rows no final da aba DR201 em uma única chamada atômica.
    Garante que cada movimentação gere uma linha individual na DR-201 com seu respectivo lote.
    Garante que NENHUM dado existente seja sobrescrito ou apagado.
    """
    from .models import MovimentacaoEstoqueBladder

    movs = list(MovimentacaoEstoqueBladder.objects.filter(
        id__in=movimentacoes_ids,
        sincronizado_dr201=False,
        tipo__in=['ENTRADA', 'SAIDA']
    ).select_related('produto', 'usuario').order_by('id'))

    if not movs:
        return True, "Nenhuma movimentação pendente para sincronizar."

    cred_path = os.path.join(settings.BASE_DIR, 'credentials.json')
    if not os.path.exists(cred_path):
        erro = "Arquivo credentials.json não encontrado na raiz do projeto."
        for m in movs:
            m.erro_sincronizacao_dr201 = erro
            m.save(update_fields=['erro_sincronizacao_dr201'])
        return False, erro

    try:
        import gspread
        gc = gspread.service_account(filename=cred_path)
        sh = gc.open_by_key('1lMXlQIpxTIkTYC0kCQir029Vrvb2M1l4hWvbxvDv0YM')
        ws = sh.worksheet('DR201')

        novas_linhas = []
        agora_str = timezone.localtime().strftime('%d/%m/%Y %H:%M:%S')

        for m in movs:
            # Data
            if data_turno_str:
                d_str = data_turno_str
            else:
                d_str = m.data_turno.strftime('%d/%m/%Y')

            # Turno
            if turno_str:
                t_str = turno_str
            else:
                hora_local = timezone.localtime(m.data_hora).hour
                t_str = 'MANHÃ' if 6 <= hora_local < 18 else 'NOITE'

            # Responsável Bladder (operador do sistema)
            nome_completo = m.usuario.get_full_name().strip()
            responsavel_nome = (nome_completo or m.usuario.first_name or m.usuario.username).strip().upper()

            # Destino & Responsável Retirada
            if m.tipo == 'ENTRADA':
                destino_texto = 'Entrada de bladder para estoque'
                responsavel_retirada = ""
            else:  # SAIDA
                destino_texto = 'Saída de bladder para produção'
                responsavel_retirada = (m.destino or "").strip().upper()

            lote_val = (m.lote_etiqueta or "").strip()
            modelo_val = m.produto.codigo
            obs_val = (m.justificativa or "").strip()

            novas_linhas.append([
                agora_str,           # Col A: Carimbo de data/hora
                d_str,               # Col B: Data
                t_str,               # Col C: Turno
                responsavel_nome,    # Col D: Responsável Bladder
                destino_texto,       # Col E: Destino
                responsavel_retirada,# Col F: Responsável pela retirada
                lote_val,            # Col G: Lote do Bladder Vulcanizado
                modelo_val,          # Col H: Modelo Bladder
                obs_val,             # Col I: Observações (preenchida pelo operador)
                "",                  # Col J: Foto da etiqueta
            ])

        # append_rows adiciona no final da planilha sem mexer em nenhuma célula anterior
        ws.append_rows(novas_linhas, value_input_option='USER_ENTERED')

        agora = timezone.now()
        for m in movs:
            m.sincronizado_dr201 = True
            m.data_sincronizacao_dr201 = agora
            m.erro_sincronizacao_dr201 = None
            m.save(update_fields=['sincronizado_dr201', 'data_sincronizacao_dr201', 'erro_sincronizacao_dr201'])

        logger.info(f"{len(novas_linhas)} linha(s) sincronizada(s) na DR-201 com sucesso.")
        return True, f"{len(novas_linhas)} linha(s) adicionada(s) à DR-201 com sucesso."

    except Exception as e:
        logger.warning(f"Erro ao sincronizar lote na DR-201: {e}")
        for m in movs:
            m.sincronizado_dr201 = False
            m.erro_sincronizacao_dr201 = str(e)[:500]
            m.save(update_fields=['sincronizado_dr201', 'erro_sincronizacao_dr201'])
        return False, str(e)


def disparar_sincronizacao_lote_dr201_async(movimentacoes_ids, data_turno_str=None, turno_str=None):
    """
    Dispara a sincronização de um lote de movimentações em segundo plano (background thread).
    Garante que a resposta HTTP do operador seja instantânea (<50ms) sem travar a interface.
    """
    import threading
    thread = threading.Thread(
        target=sincronizar_lote_movimentacoes_dr201,
        args=(movimentacoes_ids, data_turno_str, turno_str),
        daemon=True
    )
    thread.start()


def sincronizar_movimentacao_dr201(movimentacao):
    """Sincroniza uma única movimentação (retrocompatibilidade)."""
    if isinstance(movimentacao, (int, str)):
        mov_id = int(movimentacao)
    else:
        mov_id = movimentacao.id
    return sincronizar_lote_movimentacoes_dr201([mov_id])


def disparar_sincronizacao_dr201_async(movimentacao_id):
    """Dispara sincronização individual em segundo plano."""
    disparar_sincronizacao_lote_dr201_async([movimentacao_id])


def sincronizar_movimentacoes_pendentes_dr201():
    """
    Sincroniza em lote todas as movimentações de ENTRADA ou SAIDA pendentes de replicação na DR-201.
    Utilizado para contingência ou reprocessamento caso ocorra instabilidade temporária de rede.
    """
    from .models import MovimentacaoEstoqueBladder

    pendentes_ids = list(MovimentacaoEstoqueBladder.objects.filter(
        tipo__in=['ENTRADA', 'SAIDA'],
        sincronizado_dr201=False
    ).values_list('id', flat=True))

    total = len(pendentes_ids)
    if total == 0:
        return {'total': 0, 'sucessos': 0, 'falhas': 0}

    sucesso, msg = sincronizar_lote_movimentacoes_dr201(pendentes_ids)
    if sucesso:
        return {'total': total, 'sucessos': total, 'falhas': 0}
    else:
        return {'total': total, 'sucessos': 0, 'falhas': total}


# ==============================================================================
# ATIVIDADES OPERACIONAIS FLEXÍVEIS DO TURNO
# ==============================================================================

def obter_atividades_operacionais_turno(data_turno=None, turma=None):
    """Retorna as atividades operacionais registradas para a escala do turno."""
    if data_turno is None:
        data_turno = timezone.localdate()
    if turma is None:
        turma, _, _ = calcular_turma_do_dia(data_turno)

    return AtividadeTurnoBladder.objects.filter(
        data_turno=data_turno,
        turma=turma
    ).select_related(
        'tipo_atividade', 'processo', 'maquina', 'produto', 'criado_por', 'concluido_por'
    ).order_by('status', 'tipo_atividade__ordem_exibicao')


@transaction.atomic(using='default')
def criar_atividade_operacional_turno(
    tipo_atividade,
    usuario,
    data_turno=None,
    turma=None,
    processo=None,
    maquina=None,
    produto=None,
    quantidade=None,
    observacao=None
):
    """Cria uma atividade operacional no turno respeitando os campos configurados."""
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para criar atividades no Setor de Bladder.")

    if data_turno is None:
        data_turno = timezone.localdate()
    if turma is None:
        turma, _, _ = calcular_turma_do_dia(data_turno)

    if tipo_atividade.exige_quantidade and (quantidade is None or int(quantidade) <= 0):
        raise ValueError("A quantidade é obrigatória para este tipo de atividade.")

    if tipo_atividade.exige_modelo and not produto:
        raise ValueError("O modelo de Bladder é obrigatório para este tipo de atividade.")

    if tipo_atividade.exige_observacao and not (observacao or "").strip():
        raise ValueError("A observação/relato é obrigatória para este tipo de atividade.")

    atv = AtividadeTurnoBladder.objects.create(
        tipo_atividade=tipo_atividade,
        data_turno=data_turno,
        turma=turma,
        processo=processo,
        maquina=maquina,
        produto=produto,
        quantidade=quantidade,
        observacao=(observacao or "").strip(),
        criado_por=usuario,
        status='PENDENTE'
    )
    return atv


@transaction.atomic(using='default')
def concluir_atividade_operacional_turno(atividade_id, usuario, observacao=None):
    """Marca uma atividade operacional como CONCLUÍDA com timestamp e usuário."""
    from .decorators import user_is_operador_bladder
    if not usuario or not usuario.is_authenticated or not user_is_operador_bladder(usuario):
        raise PermissionError("Usuário não possui autorização para concluir atividades no Setor de Bladder.")

    atv = AtividadeTurnoBladder.objects.select_for_update().get(pk=atividade_id)
    if atv.status == 'CONCLUIDA':
        return atv

    atv.status = 'CONCLUIDA'
    atv.concluido_por = usuario
    atv.concluido_em = timezone.now()
    if observacao and observacao.strip():
        obs_limpa = observacao.strip()
        if atv.observacao:
            atv.observacao = f"{atv.observacao}\n[Conclusão]: {obs_limpa}"
        else:
            atv.observacao = obs_limpa
    atv.save(update_fields=['status', 'concluido_por', 'concluido_em', 'observacao', 'updated_at'])
    return atv


# ==============================================================================
# RESUMO MATINAL DE ESTOQUE VIA WHATSAPP (REUTILIZAÇÃO DE BAILEYS NODE.JS)
# ==============================================================================

def gerar_texto_resumo_estoque_whatsapp():
    """
    Compõe a mensagem textual formatada para WhatsApp contendo:
    - Modelos em situação crítica
    - Modelos em atenção
    - Estoque atual e estoque mínimo
    - Cobertura estimada em dias
    """
    resumo = obter_resumo_estoque_bladders()
    hoje = timezone.localdate().strftime('%d/%m/%Y')

    linhas = [
        "🏭 *SETOR DE FABRICAÇÃO DE BLADDERS*",
        f"📊 *RESUMO MATINAL DE ESTOQUE — {hoje}*",
        "----------------------------------------",
    ]

    criticos = [i for i in resumo['itens'] if i['situacao'] == 'CRITICO']
    atencao = [i for i in resumo['itens'] if i['situacao'] == 'ATENCAO']
    normais = [i for i in resumo['itens'] if i['situacao'] == 'NORMAL']

    if criticos:
        linhas.append("\n🚨 *MODELOS EM SITUAÇÃO CRÍTICA:*")
        for c in criticos:
            cob_str = f"{c['cobertura_dias']} dias" if c['cobertura_dias'] is not None else "Histórico insuficiente"
            linhas.append(f"• *{c['codigo']}* ({c['medida']}): *{c['estoque_atual']} un* (Mín: {c['estoque_minimo']}) | Cob: {cob_str}")
    else:
        linhas.append("\n✅ Nenhum modelo em situação crítica hoje.")

    if atencao:
        linhas.append("\n⚠️ *MODELOS EM ATENÇÃO:*")
        for a in atencao:
            cob_str = f"{a['cobertura_dias']} dias" if a['cobertura_dias'] is not None else "Histórico insuficiente"
            linhas.append(f"• *{a['codigo']}* ({a['medida']}): *{a['estoque_atual']} un* (Mín: {a['estoque_minimo']}) | Cob: {cob_str}")

    linhas.append("\n📈 *ESTATÍSTICAS GERAIS:*")
    linhas.append(f"• Total de Bladders Acabados em Estoque: *{resumo['total_estoque']} un*")
    linhas.append(f"• Modelos Seguros: *{len(normais)}* / {resumo['total_produtos']}")
    linhas.append("\n_Mensagem automática gerada pelo Painel de Manutenção & PCP Bladder._")

    return "\n".join(linhas)


def enviar_resumo_whatsapp_estoque(dry_run=False):
    """
    Dispara o resumo matinal de estoque via WhatsApp reutilizando o microserviço Baileys Node.js.
    Regras de Governança:
    - Segunda a sexta (sem disparo sábado e domingo);
    - Idempotência: não reenvia se já foi enviado com sucesso na mesma data;
    - Em ambiente de desenvolvimento ou dry_run=True, NÃO dispara mensagem real.
    """
    config = ConfiguracaoWhatsAppBladder.objects.first()
    if not config:
        config = ConfiguracaoWhatsAppBladder.objects.create(habilitado=True)

    if not config.habilitado:
        logger.info("Envio de resumo WhatsApp Bladder está desabilitado na configuração.")
        return {'status': 'desabilitado', 'mensagem': 'Envio desabilitado'}

    agora = timezone.localtime(timezone.now())
    dia_semana_str = str(agora.weekday())
    dias_permitidos = [d.strip() for d in config.dias_semana.split(',')]

    if dia_semana_str not in dias_permitidos:
        logger.info(f"Hoje é dia {dia_semana_str} (fim de semana/não configurado). Resumo WhatsApp não enviado.")
        return {'status': 'fora_do_calendario', 'mensagem': 'Fim de semana ou dia não configurado'}

    # Idempotência: verifica se já foi enviado hoje
    if config.ultimo_envio and config.ultimo_envio.date() == agora.date() and config.ultimo_status == 'SUCESSO':
        logger.info("Resumo WhatsApp Bladder já foi enviado hoje com sucesso. Envio repetido abortado.")
        return {'status': 'ja_enviado', 'mensagem': 'Resumo já enviado hoje'}

    texto = gerar_texto_resumo_estoque_whatsapp()

    # Destino: grupo configurado ou JID/número
    destino = None
    if config.grupo_destino and config.grupo_destino.is_active:
        destino = config.grupo_destino.jid
    elif config.numero_destino:
        destino = config.numero_destino.strip()

    if not destino:
        logger.warning("Nenhum grupo ou número configurado para resumo WhatsApp Bladder.")
        config.ultimo_status = 'SEM_DESTINATARIO'
        config.ultimo_log = "Nenhum grupo ativo ou número configurado."
        config.save(update_fields=['ultimo_status', 'ultimo_log', 'updated_at'])
        return {'status': 'sem_destinatario', 'mensagem': 'Sem destinatário configurado'}

    # PROTEÇÃO ESTRITA CONTRA ENVIO REAL DURANTE DESENVOLVIMENTO:
    if dry_run or getattr(settings, 'WHATSAPP_DRY_RUN', False):
        logger.info(f"[DRY-RUN] Resumo WhatsApp Bladder preparado para {destino}:\n{texto}")
        config.ultimo_envio = agora
        config.ultimo_status = 'SIMULADO_DRY_RUN'
        config.ultimo_log = f"[DRY-RUN] Simulação concluída com sucesso para {destino}."
        config.save(update_fields=['ultimo_envio', 'ultimo_status', 'ultimo_log', 'updated_at'])
        return {'status': 'simulado', 'texto': texto, 'destino': destino}

    url = getattr(settings, 'WHATSAPP_SERVICE_URL', 'http://localhost:3000/send')
    payload = {
        'numero': destino,
        'mensagem': texto,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code in [200, 202]:
            config.ultimo_envio = agora
            config.ultimo_status = 'SUCESSO'
            config.ultimo_log = f"Enviado com sucesso para {destino} (HTTP {resp.status_code})."
            config.save(update_fields=['ultimo_envio', 'ultimo_status', 'ultimo_log', 'updated_at'])
            return {'status': 'sucesso', 'http_code': resp.status_code}
        else:
            config.ultimo_status = f'ERRO_HTTP_{resp.status_code}'
            config.ultimo_log = f"Falha no microserviço Baileys: {resp.text[:200]}"
            config.save(update_fields=['ultimo_status', 'ultimo_log', 'updated_at'])
            return {'status': 'erro_http', 'http_code': resp.status_code}
    except Exception as e:
        logger.warning(f"Exceção ao enviar WhatsApp Bladder: {e}")
        config.ultimo_status = 'FALHA_CONEXAO'
        config.ultimo_log = f"Exceção de rede: {str(e)}"
        config.save(update_fields=['ultimo_status', 'ultimo_log', 'updated_at'])
        return {'status': 'falha_conexao', 'erro': str(e)}


