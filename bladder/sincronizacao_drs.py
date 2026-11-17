"""Fila durável das DR.114/115. Não cria colunas, abas, notas ou metadados remotos.

Sem chave na planilha, uma escrita sem resposta exige reconciliação; nunca se
repete APPEND às cegas. Todas as operações de rede ficam fora do request web.
"""
import logging
import re
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from unicodedata import normalize

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (ApontamentoTurnoBladder, BloqueioDRBladder,
                     HistoricoSincronizacaoDRBladder, SincronizacaoDRBladder)

logger = logging.getLogger(__name__)
DESTINOS = {
    'DR115': {
        'id': '14269PPh3_5htlV1QFh2qsX4JhPBvZZyYKTS_EzOD5A8',
        'gid': 161109830, 'aba': 'VUCANIZAÇÃO', 'fim': 'J',
        'cabecalhos': ['Carimbo de data/hora', 'OPERADOR', 'TEMPO DE VULCANIZAÇÃO',
                       'LOTE BLA', 'MODELO', 'PRENSA', 'OBSERVAÇÕES',
                       'PRESSÃO DE VULCANIZAÇÃO', 'TEMPERATURA DE VULCANIZAÇÃO', 'CONDIÇÃO'],
        'numericos': {7, 8},
    },
    'DR114': {
        'id': '14Y_BaIQA5nyEH3c_RLJHW2sVFaMZHlI1Ps2bEWu55f4',
        'gid': 832094045, 'aba': 'DR.114', 'fim': 'U',
        'cabecalhos': ['Carimbo de data/hora', 'Operador', 'Fornecedor Matéria-prima',
                       'Lote FBB', 'Lote BLA', 'Referência do produto', 'Tipo de processamento',
                       'Peso Médio', 'Comprimento Médio', 'Diametro Médio',
                       'Temperatura - Zona 01', 'Temperatura - Zona 02', 'Temperatura - Zona 03',
                       'Temperatura - Zona 04', 'Temperatura de trabalho', 'Velocidade do fuso',
                       'Velocidade da esteira', 'Coluna 18', 'Resfriamento', 'Volumes', 'Observações'],
        'numericos': set(range(7, 17)) | {19},
    },
}
CONDICOES = {'Bom': 'BOM', 'IA': 'IMPERFEIÇÕES DE VULCANIZAÇÃO', 'Lixo': 'LIXO'}


def _numero(valor):
    if valor is None:
        raise ValueError('Há medição obrigatória não informada.')
    return float(valor)


def _nome(ap):
    return (ap.identificacao_registrada.get('operador') or ap.operador.get_full_name()
            or ap.operador.username).strip().upper()


def projetar(ap):
    """Retorna destino, linha e eventual motivo de espera, sem acessar o Google."""
    data = timezone.localtime(ap.data_hora_inicio).strftime('%d/%m/%Y %H:%M:%S')
    produto = ap.identificacao_registrada.get('produto') or (
        ap.produto_registrado.codigo if ap.produto_registrado_id else '')
    if ap.codigo_processo in ('01', '02'):
        if not all((ap.temperatura is not None, ap.pressao is not None,
                    ap.tempo_vulcanizacao is not None, ap.lote_produto, produto,
                    ap.condicao in CONDICOES)):
            return 'DR115', [], 'Complete os parâmetros da vulcanização pela correção auditada.'
        return 'DR115', [data, _nome(ap), f'{ap.tempo_vulcanizacao.normalize():f}min',
                         ap.lote_produto, produto, f'PRENSA {ap.codigo_processo}',
                         ap.observacoes or '', _numero(ap.pressao), _numero(ap.temperatura),
                         CONDICOES[ap.condicao]], ''
    if ap.codigo_processo == '03':
        try:
            man = ap.manuseio
        except ApontamentoTurnoBladder.DoesNotExist:
            return 'DR114', [], 'Aguardando o manuseio vinculado à extrusão.'
        numeros = [man.media_peso, man.media_comprimento, man.media_diametro,
                   ap.temperatura_tcu_1, ap.temperatura_tcu_2, ap.temperatura_tcu_3,
                   ap.temperatura_tcu_4, ap.temperatura, ap.velocidade_fuso, ap.velocidade_esteira]
        if (any(v is None for v in numeros) or not all((man.materia_prima, man.lote_material,
                man.lote_produto, ap.tipo_processamento, ap.resfriamento, produto,
                ap.quantidade_realizada > 0, man.amostras.exists()))):
            return 'DR114', [], 'Complete os parâmetros da extrusão e do manuseio pela correção auditada.'
        observacoes = '\n'.join(f'{etapa}: {texto}' for etapa, texto in (
            ('Extrusão', ap.observacoes), ('Manuseio', man.observacoes)) if texto)
        return 'DR114', [data, _nome(ap), man.materia_prima, man.lote_material,
                         man.lote_produto, produto, ap.tipo_processamento,
                         *[_numero(v) for v in numeros], '', ap.resfriamento,
                         ap.quantidade_realizada, observacoes], ''
    raise ValueError('Processo sem DR de produção definida.')


def enfileirar(registro):
    """Chamado dentro da transação da produção, inclusive nas correções."""
    if registro.origem == 'LEGADO' or registro.codigo_processo not in ('01', '02', '03', '06'):
        return
    pk = registro.extrusao_origem_id if registro.codigo_processo == '06' else registro.pk
    ap = ApontamentoTurnoBladder.objects.select_related('operador', 'produto_registrado', 'manuseio').get(pk=pk)
    destino, payload, espera = projetar(ap)
    fila, criada = SincronizacaoDRBladder.objects.get_or_create(apontamento=ap, defaults={
        'destino': destino, 'payload': payload, 'status': 'PENDENTE' if payload else 'AGUARDANDO', 'erro': espera})
    if not criada and fila.payload != payload:
        fila.revisao += 1
        fila.payload = payload
        # A tentativa antiga ainda precisa ser resolvida mesmo que o operador corrija.
        if not fila.payload_tentativa and fila.status != 'CONFERIR':
            fila.status = 'PENDENTE' if payload else 'AGUARDANDO'
            fila.erro = espera
        fila.proxima_tentativa = None
        fila.save()


def _texto(valor):
    return ' '.join(normalize('NFKD', str(valor or '')).encode('ascii', 'ignore').decode().casefold().split())


def _canon(linha, destino):
    cfg = DESTINOS[destino]
    valores = (list(linha) + [''] * len(cfg['cabecalhos']))[:len(cfg['cabecalhos'])]
    resultado = []
    for i, v in enumerate(valores):
        if destino == 'DR114' and i == 17:
            resultado.append('')  # Coluna18 nunca é usada, inclusive na comparação.
        elif i in cfg['numericos'] and v not in ('', None):
            try:
                resultado.append(str(Decimal(str(v).replace(',', '.')).normalize()))
            except InvalidOperation:
                resultado.append(str(v))
        else:
            resultado.append(str(v if v is not None else ''))
    return resultado


def _linhas(ws, destino):
    cfg = DESTINOS[destino]
    linhas = ws.get(f"A1:{cfg['fim']}{ws.row_count}", value_render_option='UNFORMATTED_VALUE',
                    date_time_render_option='FORMATTED_STRING')
    if not linhas or [_texto(v) for v in linhas[0]] != [_texto(v) for v in cfg['cabecalhos']]:
        raise ValueError('Cabeçalhos da DR divergentes; nenhuma coluna foi criada ou alterada.')
    return linhas


def _encontrar(linhas, payload, destino):
    esperado = _canon(payload, destino)
    return [i for i, linha in enumerate(linhas[1:], 2) if _canon(linha, destino) == esperado]


def _historico(fila, evento, descricao='', usuario=None):
    HistoricoSincronizacaoDRBladder.objects.create(
        sincronizacao=fila, evento=evento, descricao=descricao, usuario=usuario)


def _conferir(fila, motivo):
    atual = SincronizacaoDRBladder.objects.get(pk=fila.pk)
    SincronizacaoDRBladder.objects.filter(pk=fila.pk).update(
        status='CONFERIR', erro=motivo, updated_at=timezone.now(),
        proxima_tentativa=timezone.now() + timedelta(minutes=5))
    if atual.status != 'CONFERIR' or atual.erro != motivo:
        _historico(fila, 'CONFERIR', motivo)


def _confirmar(fila, linha):
    with transaction.atomic():
        atual = SincronizacaoDRBladder.objects.select_for_update().get(pk=fila.pk)
        atual.payload_enviado = atual.payload_tentativa
        atual.revisao_enviada = atual.revisao_tentativa
        atual.payload_tentativa = []
        atual.operacao_tentativa = ''
        atual.linha_planilha = linha
        atual.sincronizado_em = timezone.now()
        atual.status = ('SINCRONIZADO' if atual.revisao == atual.revisao_enviada else
                        ('PENDENTE' if atual.payload else 'AGUARDANDO'))
        atual.erro = ''
        atual.proxima_tentativa = None
        atual.save()
        _historico(atual, 'CONFIRMADO', f'Revisão {atual.revisao_enviada}; linha {linha}.')


def _atribuida(fila):
    # O conteúdo confirmado identifica a atribuição mesmo depois de uma ordenação;
    # o número de linha guardado no banco pode ter se tornado desatualizado.
    outras = SincronizacaoDRBladder.objects.filter(destino=fila.destino).exclude(pk=fila.pk).exclude(payload_enviado=[])
    return any(_canon(outro.payload_enviado, fila.destino) == _canon(fila.payload_tentativa, fila.destino)
               for outro in outras)


def adquirir(destino):
    BloqueioDRBladder.objects.get_or_create(destino=destino)
    token = uuid.uuid4()
    agora = timezone.now()
    alteradas = BloqueioDRBladder.objects.filter(destino=destino).filter(
        Q(expira_em__isnull=True) | Q(expira_em__lte=agora)).update(
            token=token, expira_em=agora + timedelta(minutes=10))
    return token if alteradas else None


def _renovar(destino, token):
    agora = timezone.now()
    return BloqueioDRBladder.objects.filter(destino=destino, token=token, expira_em__gt=agora).update(
        expira_em=agora + timedelta(minutes=10)) == 1


def _processar(fila, ws, token):
    linhas = _linhas(ws, fila.destino)
    fila.refresh_from_db()
    if fila.payload_tentativa:
        encontradas = _encontrar(linhas, fila.payload_tentativa, fila.destino)
        if len(encontradas) == 1 and not _atribuida(fila):
            _confirmar(fila, encontradas[0])
        elif fila.operacao_tentativa == 'REVISAR' and len(_encontrar(linhas, fila.payload_enviado, fila.destino)) == 1:
            # Liderança pediu conferência de UPDATE incerto. Se a versão antiga
            # continua intacta, pode-se reenfileirar a atualização, sem APPEND.
            SincronizacaoDRBladder.objects.filter(pk=fila.pk).update(
                payload_tentativa=[], operacao_tentativa='', status='PENDENTE', proxima_tentativa=None)
            _historico(fila, 'UPDATE_REENFILEIRADO', 'Conteúdo anteriormente confirmado permanece único na DR.')
        else:
            _conferir(fila, 'O envio anterior não foi confirmado de forma única. Confira a DR antes de liberar novo envio.')
        return
    if fila.status == 'CONFERIR' or not fila.payload:
        return
    linha = None
    if fila.payload_enviado:
        encontradas = _encontrar(linhas, fila.payload_enviado, fila.destino)
        if len(encontradas) != 1:
            _conferir(fila, 'A linha já enviada foi alterada, removida ou possui cópias. Nenhuma linha foi sobrescrita.')
            return
        linha = encontradas[0]
    elif any(_encontrar(linhas, antigo, fila.destino) for antigo in [fila.payload, *fila.payloads_nao_confirmados]):
        _conferir(fila, 'Já existe conteúdo idêntico na DR. Confira a origem para evitar duplicação.')
        return
    if not _renovar(fila.destino, token):
        return
    with transaction.atomic():
        atual = SincronizacaoDRBladder.objects.select_for_update().get(pk=fila.pk)
        if atual.revisao != fila.revisao or atual.status == 'CONFERIR':
            return
        atual.status = 'ENVIANDO'
        atual.payload_tentativa = atual.payload
        atual.revisao_tentativa = atual.revisao
        atual.operacao_tentativa = 'UPDATE' if linha else 'APPEND'
        atual.tentativas += 1
        atual.save()
        fila = atual
        _historico(fila, 'ENVIANDO', f'Revisão {fila.revisao_tentativa}; {fila.operacao_tentativa}.')
    # A tentativa é durável ANTES de chamar o Google. Qualquer falha posterior
    # (inclusive interrupção do processo) será reconciliada, nunca reapendada.
    try:
        if linha:
            if fila.destino == 'DR114':
                ws.batch_update([{'range': f'A{linha}:Q{linha}', 'values': [fila.payload_tentativa[:17]]},
                                 {'range': f'S{linha}:U{linha}', 'values': [fila.payload_tentativa[18:]]}],
                                value_input_option='RAW')
            else:
                ws.update(range_name=f'A{linha}:J{linha}', values=[fila.payload_tentativa], value_input_option='RAW')
        else:
            resposta = ws.append_rows([fila.payload_tentativa], value_input_option='RAW',
                                     insert_data_option='INSERT_ROWS', table_range=f"A:{DESTINOS[fila.destino]['fim']}")
            intervalo = resposta.get('updates', {}).get('updatedRange', '')
            match = re.search(r'!A(\d+):' + DESTINOS[fila.destino]['fim'] + r'(\d+)$', intervalo)
            if not match or match[1] != match[2] or int(match[1]) < 2:
                raise ValueError('Google não confirmou a linha gravada.')
            linha = int(match[1])
        # Releitura confirma conteúdo e identifica edição concorrente na planilha.
        gravada = ws.get(f"A{linha}:{DESTINOS[fila.destino]['fim']}{linha}",
                         value_render_option='UNFORMATTED_VALUE', date_time_render_option='FORMATTED_STRING')
        if not gravada or _canon(gravada[0], fila.destino) != _canon(fila.payload_tentativa, fila.destino):
            raise ValueError('Conteúdo da linha não corresponde à tentativa.')
        _confirmar(fila, linha)
    except Exception as erro:
        _conferir(fila, 'O Google não confirmou a gravação. O sistema conferirá a DR antes de qualquer reenvio.')
        logger.warning('DR produção sem confirmação: fila=%s tipo=%s', fila.pk, type(erro).__name__)


def _abrir(destino):
    import gspread
    cliente = gspread.service_account(filename=str(settings.BASE_DIR / 'credentials.json'))
    cliente.set_timeout(30)
    cfg = DESTINOS[destino]
    ws = cliente.open_by_key(cfg['id']).get_worksheet_by_id(cfg['gid'])
    if ws.title != cfg['aba']:
        raise ValueError('Nome da aba da DR divergente; verifique a configuração.')
    return ws


def processar_pendentes(limite=10, destino=None):
    total = 0
    for nome in ([destino] if destino else DESTINOS):
        if nome not in DESTINOS:
            raise ValueError('Destino inválido.')
        token = adquirir(nome)
        if not token:
            continue
        try:
            filas = SincronizacaoDRBladder.objects.filter(
                destino=nome, status__in=['PENDENTE', 'ENVIANDO', 'CONFERIR', 'ERRO']
            ).filter(Q(proxima_tentativa__isnull=True) | Q(proxima_tentativa__lte=timezone.now())).exclude(
                status='CONFERIR', payload_tentativa=[]).order_by('updated_at', 'pk')
            ids = list(filas.values_list('pk', flat=True)[:limite])
            if not ids:
                continue
            ws = None
            for pk in ids:
                if not _renovar(nome, token):
                    break
                fila = SincronizacaoDRBladder.objects.get(pk=pk)
                if fila.status == 'CONFERIR' and not fila.payload_tentativa:
                    continue
                try:
                    ws = ws or _abrir(nome)
                    _processar(fila, ws, token)
                except Exception as erro:
                    fila.refresh_from_db()
                    if fila.payload_tentativa:
                        _conferir(fila, 'Não foi possível conferir o envio. Verifique a conexão e o acesso à DR.')
                    else:
                        intervalo = min(3600, 60 * 2 ** min(fila.tentativas, 6))
                        SincronizacaoDRBladder.objects.filter(pk=pk).update(
                            status='ERRO', erro=(str(erro) if isinstance(erro, ValueError) else
                                'Não foi possível acessar a DR. Confira a conexão e o acesso da integração. Nova tentativa agendada.'),
                            tentativas=fila.tentativas + 1,
                            proxima_tentativa=timezone.now() + timedelta(seconds=intervalo))
                    logger.warning('Falha na conferência/acesso à DR: fila=%s tipo=%s', pk, type(erro).__name__)
                total += 1
        finally:
            BloqueioDRBladder.objects.filter(destino=nome, token=token).update(token=None, expira_em=None)
    return total


def solicitar_reenvio(pk, usuario, confirmar_ausencia=False, justificativa='', reconferir=False):
    """Recuperação explícita pela liderança; não executa rede na requisição."""
    from .decorators import user_is_lider_bladder
    if not usuario.is_active or not user_is_lider_bladder(usuario):
        raise PermissionError('Somente a liderança pode solicitar reenvio.')
    with transaction.atomic():
        fila = SincronizacaoDRBladder.objects.select_for_update().get(pk=pk)
        if fila.status == 'ENVIANDO':
            raise ValueError('Aguarde a conferência do envio em andamento.')
        if fila.status == 'CONFERIR' and reconferir:
            # Com tentativa incerta, o trabalhador só lê e reconcilia. Sem ela,
            # uma nova tentativa continua exigindo localizar o conteúdo anterior.
            fila.status = 'CONFERIR' if fila.payload_tentativa else 'PENDENTE'
            if fila.payload_enviado and fila.operacao_tentativa == 'UPDATE':
                fila.operacao_tentativa = 'REVISAR'
            fila.proxima_tentativa = None
            fila.save()
            _historico(fila, 'CONFERENCIA_SOLICITADA', usuario=usuario)
            return
        if fila.status == 'CONFERIR':
            if not confirmar_ausencia or len(justificativa.strip()) < 10:
                raise ValueError('Confirme a ausência da linha na DR e informe uma justificativa de ao menos 10 caracteres.')
            # UPDATE ambíguo não pode ser convertido em APPEND nem sobrescrever
            # outra linha. Só a inserção inicial pode ser liberada por ausência.
            if fila.payload_enviado:
                raise ValueError('Uma linha já foi sincronizada. Restaure seu conteúdo na DR para permitir a conferência.')
            if fila.payload_tentativa and fila.payload_tentativa not in fila.payloads_nao_confirmados:
                fila.payloads_nao_confirmados.append(fila.payload_tentativa)
            fila.payload_tentativa = []
            fila.operacao_tentativa = ''
            _historico(fila, 'AUSENCIA_CONFIRMADA', justificativa.strip(), usuario)
        elif fila.status not in ('ERRO', 'PENDENTE'):
            raise ValueError('Este registro não possui falha de envio a reprocessar.')
        fila.status = 'PENDENTE' if fila.payload else 'AGUARDANDO'
        fila.proxima_tentativa = None
        fila.erro = ''
        fila.save()
        _historico(fila, 'REENVIO_SOLICITADO', justificativa.strip(), usuario)
