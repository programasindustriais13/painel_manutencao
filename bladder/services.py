import datetime
from django.db import transaction
from django.db.models import Case, When, Value, IntegerField, Q
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
    MensagemPassagemTurnoBladder,
    AcaoMensagemTurnoBladder,
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


def calcular_proximo_turno_operacional(data_referencia=None):
    """
    Calcula dinamicamente a data e a turma do próximo turno operacional a partir de uma data de referência.
    Varre os dias subsequentes respeitando a alternância 12x36 de ConfiguracaoEscalaBladder
    e eventuais ajustes excepcionais em AjusteEscalaExcepcionalBladder.
    Dias marcados como 'FOLGA' (sem produção) são pulados até encontrar o próximo turno ativo.
    Retorna tupla: (data_proximo_turno, turma_proximo_turno, is_ajuste, motivo)
    """
    if data_referencia is None:
        data_referencia = timezone.localdate()

    dia_candidato = data_referencia + datetime.timedelta(days=1)
    limite_dias = 60  # Proteção contra loop infinito

    for _ in range(limite_dias):
        turma, is_ajuste, motivo = calcular_turma_do_dia(dia_candidato)
        if turma in ['TURMA_A', 'TURMA_B']:
            return dia_candidato, turma, is_ajuste, motivo
        dia_candidato += datetime.timedelta(days=1)

    # Fallback seguro caso não encontre
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
    A data e turma de destino são calculadas automaticamente para o próximo turno operacional.
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

    if data_turno_origem is None:
        data_turno_origem = timezone.localdate()

    turma_origem, _, _ = calcular_turma_do_dia(data_turno_origem)
    data_turno_destino, turma_destino, _, _ = calcular_proximo_turno_operacional(data_turno_origem)

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
    prox_data_destino, prox_turma_destino, _, _ = calcular_proximo_turno_operacional(data_origem_repasse)

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


def obter_mensagens_recebidas_turno(data_turno=None, turma=None, usuario=None):
    """
    Retorna a lista de mensagens recebidas para a data/turma informada.
    Ordenação canônica:
    1. Urgentes primeiro
    2. Importantes em seguida
    3. Normais por último
    4. Mais recentes (-created_at)
    Cada mensagem recebe o atributo `usuario_ciente` se usuario for informado.
    """
    if data_turno is None:
        data_turno = timezone.localdate()

    if turma is None:
        turma, _, _ = calcular_turma_do_dia(data_turno)

    # Inclui recados destinados para esta data/turma que estejam abertos ou que foram recebidos neste turno
    # Permite também ver recados em aberto de datas anteriores destinados a esta turma se não foram tratados
    qs = MensagemPassagemTurnoBladder.objects.filter(
        Q(data_turno_destino=data_turno, turma_destino=turma) |
        Q(data_turno_destino__lt=data_turno, turma_destino=turma, status='ABERTA')
    ).select_related(
        'autor', 'ordem_producao', 'processo', 'maquina', 'produto',
        'resolvido_por', 'repassado_por', 'mensagem_origem'
    ).prefetch_related(
        'acoes__usuario'
    ).annotate(
        peso_prioridade=Case(
            When(prioridade='URGENTE', then=Value(1)),
            When(prioridade='IMPORTANTE', then=Value(2)),
            default=Value(3),
            output_field=IntegerField()
        )
    ).order_by('peso_prioridade', '-created_at')

    mensagens_lista = list(qs)
    if usuario and usuario.is_authenticated:
        for m in mensagens_lista:
            m.usuario_ciente = any(a.usuario_id == usuario.id and a.acao == 'CIENTE' for a in m.acoes.all())
    else:
        for m in mensagens_lista:
            m.usuario_ciente = False

    return mensagens_lista


