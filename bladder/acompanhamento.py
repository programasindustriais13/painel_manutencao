"""Consulta de apontamentos do líder, compartilhada pela tela inicial e pelo Excel."""

import json
from io import BytesIO

from django import forms
from django.db.models import Exists, Max, Min, OuterRef, Q
from django.http import HttpResponse
from django.utils import timezone

from .models import (
    AmostraManuseioBladder,
    ApontamentoTurnoBladder,
    HistoricoApontamentoBladder,
    OrdemProducaoBladder,
    ProcessoBladder,
    ProdutoBladder,
)


class FiltroAcompanhamentoForm(forms.Form):
    data_inicial = forms.DateField(label='De', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    data_final = forms.DateField(label='Até', widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    op = forms.CharField(label='OP', required=False, max_length=60, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número da OP'}))
    processo = forms.ChoiceField(label='Processo', required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    turma = forms.ChoiceField(label='Turma', required=False, choices=[('', 'Todas'), ('TURMA_A', 'Turma A'), ('TURMA_B', 'Turma B'), ('APOIO', 'Apoio')], widget=forms.Select(attrs={'class': 'form-select'}))
    condicao = forms.ChoiceField(label='Condição', required=False, choices=[('', 'Todas'), ('Bom', 'Bom'), ('IA', 'IA'), ('Lixo', 'Lixo'), ('Bons', 'Bons'), ('Parcialmente Bons', 'Parcialmente Bons'), ('Ruins', 'Ruins')], widget=forms.Select(attrs={'class': 'form-select'}))
    fechamento = forms.ChoiceField(label='Fechamento', required=False, choices=[('', 'Todos'), ('ABERTO', 'Turno aberto'), ('FECHADO', 'Turno fechado')], widget=forms.Select(attrs={'class': 'form-select'}))
    produto = forms.ModelChoiceField(label='Produto', required=False, queryset=ProdutoBladder.objects.all().order_by('codigo'), empty_label='Todos', widget=forms.Select(attrs={'class': 'form-select'}))
    operador = forms.CharField(label='Operador', required=False, max_length=80, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome ou usuário'}))
    corrigidos = forms.BooleanField(label='Somente corrigidos', required=False)
    incluir_legados = forms.BooleanField(label='Incluir históricos legados', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['processo'].choices = [('', 'Todos')] + list(ProcessoBladder.objects.order_by('codigo').values_list('codigo', 'nome'))

    def clean(self):
        dados = super().clean()
        inicio, fim = dados.get('data_inicial'), dados.get('data_final')
        if inicio and fim:
            if inicio > fim:
                self.add_error('data_final', 'A data final deve ser igual ou posterior à inicial.')
            elif (fim - inicio).days > 366 and not OrdemProducaoBladder.objects.filter(numero_ordem=dados.get('op', '').strip()).exists():
                self.add_error('data_final', 'Consulte no máximo 366 dias por vez, ou informe o número exato da OP.')
        return dados


def preparar_consulta(parametros, hoje=None):
    """Filtra pela data do apontamento, independente da programação da OP."""
    hoje = hoje or timezone.localdate()
    dados = parametros.copy()
    if dados.get('periodo') == 'op' and dados.get('op') and 'data_inicial' not in dados and 'data_final' not in dados:
        datas_op = ApontamentoTurnoBladder.objects.filter(ordem__numero_ordem=dados['op']).aggregate(primeiro=Min('data_turno'), ultimo=Max('data_turno'))
        if datas_op['primeiro']:
            dados['data_inicial'] = datas_op['primeiro'].isoformat()
            dados['data_final'] = datas_op['ultimo'].isoformat()
    if 'data_inicial' not in dados:
        dados['data_inicial'] = hoje.isoformat()
    if 'data_final' not in dados:
        dados['data_final'] = hoje.isoformat()
    form = FiltroAcompanhamentoForm(dados)
    if not form.is_valid():
        return form, ApontamentoTurnoBladder.objects.none()

    filtro = form.cleaned_data
    correcoes = HistoricoApontamentoBladder.objects.filter(apontamento_id=OuterRef('pk'))
    registros = ApontamentoTurnoBladder.objects.using('default').annotate(
        foi_corrigido=Exists(correcoes),
    ).filter(data_turno__range=(filtro['data_inicial'], filtro['data_final']))
    if not filtro['incluir_legados']:
        registros = registros.exclude(origem='LEGADO')
    if filtro['op']:
        registros = registros.filter(ordem__numero_ordem__icontains=filtro['op'].strip())
    if filtro['processo']:
        # A OP histórica não comprova qual processo gerou cada apontamento legado.
        registros = registros.filter(codigo_processo=filtro['processo'])
    if filtro['turma']:
        registros = registros.filter(turma=filtro['turma'])
    if filtro['condicao']:
        registros = registros.filter(condicao=filtro['condicao'])
    if filtro['fechamento']:
        registros = registros.filter(fechamento__isnull=filtro['fechamento'] == 'ABERTO')
    if filtro['produto']:
        registros = registros.filter(Q(produto_registrado=filtro['produto']) | Q(origem='LEGADO', ordem__produto=filtro['produto']))
    if filtro['operador']:
        for parte in filtro['operador'].split():
            registros = registros.filter(
                Q(operador__username__icontains=parte) |
                Q(operador__first_name__icontains=parte) |
                Q(operador__last_name__icontains=parte)
            )
    if filtro['corrigidos']:
        registros = registros.filter(foi_corrigido=True)
    return form, registros.select_related(
        'ordem', 'operador', 'processo_registrado', 'produto_registrado', 'extrusao_origem',
        'sincronizacao_dr', 'extrusao_origem__sincronizacao_dr',
    ).order_by('-data_hora_inicio', '-pk')


def _texto_excel(valor):
    """Preserva identificadores textuais e impede execução de fórmulas na planilha."""
    texto = '' if valor is None else str(valor)
    if texto and texto[0] in ('=', '+', '-', '@', '\t', '\r', '\n', '＝', '＋', '－', '＠'):
        return "'" + texto
    return texto


def _usuario(usuario):
    return usuario.get_full_name() or usuario.username


def _horario(valor):
    return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M:%S') if valor else ''


def exportar_excel(registros, filtros):
    """Exporta a consulta inteira, com amostras e revisões em abas vinculadas por ID."""
    from openpyxl import Workbook

    wb = Workbook(write_only=True)
    consulta = wb.create_sheet('Consulta')
    consulta.append(['Acompanhamento da produção Bladder', ''])
    consulta.append(['Gerado em', _horario(timezone.now())])
    consulta.append(['Período do registro', f"{filtros['data_inicial']:%d/%m/%Y} a {filtros['data_final']:%d/%m/%Y}"])
    consulta.append(['OP', _texto_excel(filtros['op'] or 'Todas')])
    consulta.append(['Processo', _texto_excel(filtros['processo'] or 'Todos')])
    consulta.append(['Turma', _texto_excel(filtros['turma'] or 'Todas')])
    consulta.append(['Condição', _texto_excel(filtros['condicao'] or 'Todas')])
    consulta.append(['Fechamento', _texto_excel(filtros['fechamento'] or 'Todos')])
    consulta.append(['Produto', _texto_excel(filtros['produto'] or 'Todos')])
    consulta.append(['Operador', _texto_excel(filtros['operador'] or 'Todos')])
    consulta.append(['Somente corrigidos', 'Sim' if filtros['corrigidos'] else 'Não'])
    consulta.append(['Históricos legados', 'Incluídos' if filtros['incluir_legados'] else 'Excluídos'])
    consulta.append(['Nota', 'Manuseio não acrescenta produção. Anéis podem ter quantidade não apurada. Registros legados podem ser início ou consolidação.'])

    linhas = wb.create_sheet('Registros')
    linhas.append(['ID registro', 'Data do turno', 'Registrado em', 'OP', 'Tipo', 'Código processo', 'Processo', 'Produto', 'Turma', 'Operador', 'Quantidade', 'Apuração', 'Condição', 'Lote produto', 'Volume', 'Equipamento', 'Extrusão origem ID', 'Fechamento ID', 'Corrigido', 'Observações', 'Tipo de processamento', 'Resfriamento', 'Temperatura', 'Situação da DR'])
    ids = registros.order_by().values('pk')
    for ap in registros.iterator(chunk_size=500):
        identidade = ap.identificacao_registrada or {}
        quantidade = None if ap.origem == 'MANUSEIO' or not ap.quantidade_apurada else ap.quantidade_realizada
        apuracao = 'Sem produção adicional' if ap.origem == 'MANUSEIO' else ('Apurada' if ap.quantidade_apurada else 'Não apurada')
        linhas.append([
            ap.pk, ap.data_turno.strftime('%d/%m/%Y'), _horario(ap.data_hora_inicio),
            _texto_excel(ap.ordem.numero_ordem), ap.get_origem_display(),
            ap.codigo_processo if ap.origem != 'LEGADO' else '',
            _texto_excel(ap.processo_registrado.nome if ap.processo_registrado_id else ('Não identificado' if ap.origem == 'LEGADO' else identidade.get('processo', ''))),
            _texto_excel(identidade.get('produto') or (ap.produto_registrado.codigo if ap.produto_registrado_id else '')),
            ap.get_turma_display(), _texto_excel(_usuario(ap.operador)), quantidade, apuracao,
            _texto_excel(ap.condicao), _texto_excel(ap.lote_produto), _texto_excel(ap.volume),
            _texto_excel(identidade.get('equipamento', '')), ap.extrusao_origem_id, ap.fechamento_id,
            'Sim' if ap.foi_corrigido else 'Não', _texto_excel(ap.observacoes),
            _texto_excel(ap.tipo_processamento), _texto_excel(ap.resfriamento), ap.temperatura,
            ap.controle_dr.get_status_display() if ap.controle_dr else 'Sem integração',
        ])

    amostras = wb.create_sheet('Amostras')
    amostras.append(['ID registro', 'OP', 'Extrusão origem ID', 'Sequência', 'Diâmetro (mm)', 'Comprimento (cm)', 'Peso (kg)'])
    for amostra in AmostraManuseioBladder.objects.filter(apontamento_id__in=ids).select_related('apontamento__ordem').order_by('apontamento_id', 'sequencia').iterator(chunk_size=500):
        amostras.append([amostra.apontamento_id, _texto_excel(amostra.apontamento.ordem.numero_ordem), amostra.apontamento.extrusao_origem_id, amostra.sequencia, amostra.diametro, amostra.comprimento, amostra.peso])

    correcoes = wb.create_sheet('Correções')
    correcoes.append(['ID registro', 'OP', 'Corrigido em', 'Responsável', 'Justificativa', 'Quantidade anterior', 'Quantidade nova', 'Valores anteriores (JSON)', 'Valores novos (JSON)'])
    for historico in HistoricoApontamentoBladder.objects.filter(apontamento_id__in=ids).select_related('apontamento__ordem', 'usuario').order_by('apontamento_id', 'created_at', 'pk').iterator(chunk_size=500):
        correcoes.append([
            historico.apontamento_id, _texto_excel(historico.apontamento.ordem.numero_ordem),
            _horario(historico.created_at), _texto_excel(_usuario(historico.usuario)),
            _texto_excel(historico.motivo_correcao), historico.quantidade_anterior,
            historico.quantidade_nova, _texto_excel(json.dumps(historico.valores_anteriores, ensure_ascii=False, default=str)),
            _texto_excel(json.dumps(historico.valores_novos, ensure_ascii=False, default=str)),
        ])

    arquivo = BytesIO()
    wb.save(arquivo)
    resposta = HttpResponse(arquivo.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    nome = f"bladder_registros_{filtros['data_inicial']:%Y%m%d}_{filtros['data_final']:%Y%m%d}.xlsx"
    resposta['Content-Disposition'] = f'attachment; filename="{nome}"'
    resposta['Cache-Control'] = 'private, no-store'
    return resposta
