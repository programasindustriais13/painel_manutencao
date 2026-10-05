import datetime
from django.db import transaction
from django.utils import timezone
from .models import (
    ConfiguracaoEscalaBladder,
    AjusteEscalaExcepcionalBladder,
    FuncionarioApoioBladder,
    OrdemProducaoBladder,
    SaldoPendenteBladder,
    ApontamentoTurnoBladder,
    FechamentoTurnoBladder,
    ItemFechamentoTurnoBladder,
    CategoriaDesvioBladder,
    HistoricoApontamentoBladder,
    HistoricoProgramacaoBladder,
)


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
    produto,
    data_programada,
    quantidade_nova,
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
    turma_prevista, _, _ = calcular_turma_do_dia(data_programada)
    numero_ordem = gerar_proximo_numero_op(data_programada)

    # 1. Trava apenas os saldos explicitamente selecionados pelo líder para este produto
    saldos_a_incorporar = []
    if saldos_selecionados_ids:
        saldos_a_incorporar = list(
            SaldoPendenteBladder.objects.select_for_update()
            .filter(id__in=saldos_selecionados_ids, produto=produto, status='PENDENTE')
            .order_by('created_at')
        )

    total_saldo = sum(s.quantidade for s in saldos_a_incorporar)
    quantidade_planejada = int(quantidade_nova) + total_saldo

    # 2. Cria a Ordem de Produção
    op = OrdemProducaoBladder.objects.create(
        numero_ordem=numero_ordem,
        processo=processo,
        produto=produto,
        data_programada=data_programada,
        turma_prevista=turma_prevista,
        prioridade=prioridade,
        quantidade_nova=quantidade_nova,
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

