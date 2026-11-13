import re
import uuid
from datetime import date, timedelta
from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from maintenance.models import Machine
from .models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    SolicitacaoServicoMatrizaria,
    is_checklist_machine,
    EXCLUDED_PRENSA_NAMES,
)

User = get_user_model()


def format_prensa_label(machine) -> str:
    """
    Retorna apenas o nome limpo da prensa, sem trechos entre parênteses de criticidade.
    Exemplo: 'PRENSA BOM 08 (Média (Amarela))' -> 'PRENSA BOM 08'.
    Preserva o ID original e os hífens/números do nome da prensa.
    """
    if not machine:
        return ""
    raw_name = getattr(machine, "nome", str(machine))
    # Remove blocos com criticidade aninhados como (Média (Amarela)), (Alta (Vermelha)), (Baixa (Verde))
    cleaned = re.sub(r'\s*\([^()]*\((?:Verde|Amarela|Vermelha)\)\)', '', raw_name)
    cleaned = re.sub(r'\s*\((?:Baixa|Média|Media|Alta)[^)]*\)', '', cleaned, flags=re.IGNORECASE)
    return cleaned.strip() or raw_name.strip()


def get_prensas_queryset():
    """
    Retorna o QuerySet canônico de prensas de vulcanização:
    1. Máquinas com configuração de produção (production_config); OU
    2. Máquinas de setores de Vulcanização/Prensas ou com 'prensa' no nome.
    Exclui estritamente registros de apoio/checklist da Manutenção ('CHECK-LIST', 'CHECK LIST', 'CHECKLIST').
    Fallback seguro para todas as máquinas caso nenhuma atenda ao filtro.
    """
    base_qs = Machine.objects.all().select_related("setor")
    vulcanizacao_filter = (
        Q(production_config__isnull=False)
        | Q(setor__nome__icontains="vulc")
        | Q(setor__nome__icontains="prens")
        | Q(nome__icontains="prensa")
    )
    checklist_filter = (
        Q(nome__iexact="CHECK-LIST")
        | Q(nome__iexact="CHECK LIST")
        | Q(nome__iexact="CHECKLIST")
    )
    prensas = base_qs.filter(vulcanizacao_filter).exclude(checklist_filter).distinct().order_by("nome")
    if not prensas.exists():
        return base_qs.exclude(checklist_filter).order_by("nome")
    return prensas


OPCAO_MATRIZARIA_VALOR = "__MATRIZARIA__"
OPCAO_MATRIZARIA_LABEL = "Matrizaria — Serviço interno / Sem máquina"


class PrensaOuMatrizariaChoiceIterator(forms.models.ModelChoiceIterator):
    def __iter__(self):
        if self.field.empty_label is not None:
            yield ("", self.field.empty_label)
        yield (OPCAO_MATRIZARIA_VALOR, OPCAO_MATRIZARIA_LABEL)
        for obj in self.queryset:
            yield self.choice(obj)


class PrensaOuMatrizariaChoiceField(forms.ModelChoiceField):
    iterator = PrensaOuMatrizariaChoiceIterator

    def to_python(self, value):
        if value == OPCAO_MATRIZARIA_VALOR:
            return OPCAO_MATRIZARIA_VALOR
        return super().to_python(value)

    def validate(self, value):
        if value == OPCAO_MATRIZARIA_VALOR:
            return
        return super().validate(value)


def format_matriz_fisica_label(obj: MatrizFisica) -> str:
    if not obj:
        return ""
    return getattr(obj, "rotulo_completo", str(obj))


class SolicitacaoServicoForm(forms.ModelForm):
    idempotency_key = forms.CharField(widget=forms.HiddenInput(), required=False)
    destino = forms.CharField(widget=forms.HiddenInput(), required=False)
    prensa = PrensaOuMatrizariaChoiceField(
        queryset=Machine.objects.none(),
        required=True,
        empty_label="--- Selecione o Destino do Serviço ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Destino do Serviço",
        error_messages={"required": "Selecione o Destino do Serviço (Matrizaria ou uma Prensa / Máquina)."},
    )

    class Meta:
        model = SolicitacaoServicoMatrizaria
        fields = [
            "destino",
            "prensa",
            "tipo_servico",
            "matriz_fisica",
            "prioridade",
            "descricao_solicitacao",
        ]
        widgets = {
            "tipo_servico": forms.Select(attrs={"class": "form-select"}),
            "matriz_fisica": forms.Select(attrs={"class": "form-select"}),
            "prioridade": forms.Select(attrs={"class": "form-select"}),
            "descricao_solicitacao": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Descreva detalhadamente o serviço solicitado para a Matrizaria...",
                    "required": "required",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prensa"].queryset = get_prensas_queryset()
        self.fields["prensa"].label_from_instance = lambda obj: format_prensa_label(obj)
        if self.instance and self.instance.pk and self.instance.destino == "MATRIZARIA":
            self.initial["prensa"] = OPCAO_MATRIZARIA_VALOR
        self.fields["tipo_servico"].queryset = TipoServicoMatrizaria.objects.filter(ativo=True).order_by("ordem_exibicao", "nome")
        self.fields["matriz_fisica"].queryset = MatrizFisica.objects.filter(ativo=True).select_related("modelo").order_by("modelo__nome_exibicao", "numero_sequencial")
        self.fields["matriz_fisica"].label_from_instance = lambda obj: format_matriz_fisica_label(obj)
        self.fields["matriz_fisica"].required = False
        self.fields["matriz_fisica"].empty_label = "--- Matriz física não definida no momento ---"
        self.fields["tipo_servico"].empty_label = "--- Selecione o Tipo de Serviço ---"

        if not self.initial.get("idempotency_key"):
            self.initial["idempotency_key"] = str(uuid.uuid4())

    def clean_prensa(self):
        prensa_val = self.cleaned_data.get("prensa")
        if prensa_val == OPCAO_MATRIZARIA_VALOR:
            self.cleaned_data["destino"] = "MATRIZARIA"
            return None
        elif prensa_val:
            if is_checklist_machine(prensa_val):
                raise forms.ValidationError("Máquinas de apoio ou CHECK-LIST não são válidas para chamados de Matrizaria.")
            self.cleaned_data["destino"] = "MAQUINA"
            return prensa_val
        raise forms.ValidationError("Selecione o Destino do Serviço (Matrizaria ou uma Prensa / Máquina).")

    def clean(self):
        cleaned_data = super().clean()
        destino = cleaned_data.get("destino")
        prensa = cleaned_data.get("prensa")

        # Garante a atualização da instância antes do _post_clean() executar instance.full_clean()
        if destino:
            self.instance.destino = destino
        self.instance.prensa = prensa

        if destino == "MAQUINA" and not prensa:
            self.add_error("prensa", "Prensa / Máquina é obrigatória quando o destino for máquina.")
        elif destino == "MATRIZARIA" and prensa is not None:
            self.add_error("prensa", "Serviço interno da Matrizaria não deve possuir máquina vinculada.")
        return cleaned_data


class FinalizarExecucaoForm(forms.Form):
    descricao_servico_realizado = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Descreva objetivamente o serviço técnico executado (peças ajustadas, vedações, limpezas, trocas)...",
                "required": "required",
            }
        ),
        label="Descrição do Serviço Realizado",
        min_length=5,
    )
    matriz_fisica = forms.ModelChoiceField(
        queryset=MatrizFisica.objects.filter(ativo=True).select_related("modelo").order_by("modelo__nome_exibicao", "numero_sequencial"),
        required=False,
        empty_label="--- Selecione a Matriz Física (se aplicável) ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Matriz Física Instalada / Atendida",
    )
    versao = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["matriz_fisica"].label_from_instance = lambda obj: format_matriz_fisica_label(obj)


class ConferirServicoForm(forms.Form):
    ACAO_CHOICES = [
        ("APROVAR", "Aprovar Serviço e Concluir"),
        ("DEVOLVER_RETRABALHO", "Recusar e Devolver para Retrabalho"),
    ]

    acao = forms.ChoiceField(
        choices=ACAO_CHOICES,
        widget=forms.RadioSelect(attrs={"class": "btn-check"}),
        label="Decisão da Conferência",
        initial="APROVAR",
    )
    motivo_devolucao = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Descreva obrigatoriamente o motivo da recusa e orientações para o retrabalho...",
            }
        ),
        label="Motivo da Devolução (Obrigatório em caso de retrabalho)",
    )
    observacoes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Observações adicionais da conferência (opcional)...",
            }
        ),
        label="Observações da Conferência",
    )
    versao = forms.IntegerField(widget=forms.HiddenInput())

    def clean(self):
        cleaned_data = super().clean()
        acao = cleaned_data.get("acao")
        motivo = cleaned_data.get("motivo_devolucao", "").strip()
        if acao == "DEVOLVER_RETRABALHO" and not motivo:
            self.add_error("motivo_devolucao", "O motivo da recusa é obrigatório para devolver o chamado para retrabalho.")
        return cleaned_data


class TransferirResponsabilidadeForm(forms.Form):
    novo_responsavel = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=True,
        empty_label="--- Selecione o Colaborador da Matrizaria ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Novo Responsável na Matrizaria",
    )
    motivo_transferencia = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Justificativa da transferência de atendimento...",
                "required": "required",
            }
        ),
        label="Motivo da Transferência",
    )
    versao = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, solicitacao=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.solicitacao = solicitacao
        from .services import MatrizariaService

        qs = MatrizariaService.get_matrizeiros_habilitados(solicitacao=solicitacao)
        self.fields["novo_responsavel"].queryset = qs
        if not qs.exists():
            self.fields["novo_responsavel"].empty_label = "Nenhum outro colaborador da Matrizaria está habilitado para receber este chamado."
        else:
            self.fields["novo_responsavel"].empty_label = "--- Selecione o Colaborador da Matrizaria ---"

        self.fields["novo_responsavel"].label_from_instance = lambda u: (
            f"{u.get_full_name()} ({u.username})" if u.get_full_name() else u.username
        )

    def clean_novo_responsavel(self):
        resp = self.cleaned_data.get("novo_responsavel")
        if not resp:
            raise ValidationError("Selecione um técnico responsável válido.")
        from .services import MatrizariaService

        if not MatrizariaService.is_matrizeiro_habilitado(resp, solicitacao=self.solicitacao):
            raise ValidationError("O colaborador selecionado não está habilitado para receber serviços da Matrizaria.")
        return resp


class EditarSolicitacaoForm(forms.Form):
    destino = forms.CharField(widget=forms.HiddenInput(), required=False)
    prensa = PrensaOuMatrizariaChoiceField(
        queryset=Machine.objects.none(),
        required=True,
        empty_label="--- Selecione o Destino do Serviço ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Destino do Serviço",
        error_messages={"required": "Selecione o Destino do Serviço (Matrizaria ou uma Prensa / Máquina)."},
    )
    tipo_servico = forms.ModelChoiceField(
        queryset=TipoServicoMatrizaria.objects.filter(ativo=True).order_by("nome"),
        required=True,
        empty_label="--- Selecione o Tipo de Serviço ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Tipo de Serviço",
    )
    matriz_fisica = forms.ModelChoiceField(
        queryset=MatrizFisica.objects.filter(ativo=True).select_related("modelo").order_by("modelo__nome_exibicao", "numero_sequencial"),
        required=False,
        empty_label="--- Selecione a Matriz Física (se aplicável) ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Matriz Física (Obrigatória para Troca de Matriz)",
    )
    prioridade = forms.ChoiceField(
        choices=SolicitacaoServicoMatrizaria.PRIORIDADE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Prioridade do Atendimento",
    )
    descricao_solicitacao = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Descreva detalhadamente a necessidade da matriz...",
                "required": "required",
            }
        ),
        label="Descrição da Necessidade / Problema",
    )
    motivo_edicao = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Descreva obrigatoriamente o motivo da correção (auditoria)...",
                "required": "required",
            }
        ),
        label="Motivo da Correção (Auditoria)",
    )
    versao = forms.IntegerField(widget=forms.HiddenInput())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prensa"].queryset = get_prensas_queryset()
        self.fields["prensa"].label_from_instance = lambda obj: format_prensa_label(obj)
        self.fields["matriz_fisica"].label_from_instance = lambda obj: format_matriz_fisica_label(obj)

    def clean_prensa(self):
        prensa_val = self.cleaned_data.get("prensa")
        if prensa_val == OPCAO_MATRIZARIA_VALOR:
            self.cleaned_data["destino"] = "MATRIZARIA"
            return None
        elif prensa_val:
            if is_checklist_machine(prensa_val):
                raise ValidationError("A máquina 'CHECK-LIST' não é permitida para chamados de Matrizaria.")
            self.cleaned_data["destino"] = "MAQUINA"
            return prensa_val
        raise ValidationError("Selecione o Destino do Serviço (Matrizaria ou uma Prensa / Máquina).")

    def clean(self):
        cleaned_data = super().clean()
        destino = cleaned_data.get("destino")
        prensa = cleaned_data.get("prensa")
        if destino == "MAQUINA" and not prensa:
            self.add_error("prensa", "Prensa / Máquina é obrigatória quando o destino for máquina.")
        elif destino == "MATRIZARIA" and prensa is not None:
            self.add_error("prensa", "Serviço interno da Matrizaria não deve possuir máquina vinculada.")

        tipo = cleaned_data.get("tipo_servico")
        matriz = cleaned_data.get("matriz_fisica")
        if tipo and tipo.exige_matriz_fisica and not matriz:
            self.add_error(
                "matriz_fisica",
                f"O serviço '{tipo.nome}' exige obrigatoriamente a vinculação de uma matriz física.",
            )
        return cleaned_data


class CancelarServicoForm(forms.Form):
    motivo_cancelamento = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Justifique obrigatoriamente o cancelamento desta solicitação...",
                "required": "required",
            }
        ),
        label="Motivo do Cancelamento",
    )
    versao = forms.IntegerField(widget=forms.HiddenInput())


class RelatorioFiltroForm(forms.Form):
    CRITERIO_TEMPORAL_CHOICES = [
        ("COM_EXECUCAO", "1. Serviços com execução no período (Padrão)"),
        ("ABERTAS", "2. Solicitações abertas no período"),
        ("FINALIZADAS", "3. Execuções técnicas finalizadas no período"),
        ("CONCLUIDAS", "4. Serviços conferidos e concluídos no período"),
        ("CANCELADAS", "5. Chamados cancelados no período"),
    ]

    criterio_temporal = forms.ChoiceField(
        choices=CRITERIO_TEMPORAL_CHOICES,
        initial="COM_EXECUCAO",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Consultar por",
    )
    data_inicio = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        label="Data Inicial",
    )
    data_fim = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        label="Data Final",
    )
    prensa = PrensaOuMatrizariaChoiceField(
        queryset=Machine.objects.none(),
        required=False,
        empty_label="Todas as Prensas / Máquinas",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Prensa",
    )
    tipo_servico = forms.ModelChoiceField(
        queryset=TipoServicoMatrizaria.objects.all().order_by("ordem_exibicao", "nome"),
        required=False,
        empty_label="Todos os Tipos",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Tipo de Serviço",
    )
    status = forms.ChoiceField(
        choices=[("", "Todos os Status")] + list(SolicitacaoServicoMatrizaria.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Status Atual",
    )
    solicitante = forms.ModelChoiceField(
        queryset=User.objects.filter(solicitacoes_matrizaria_criadas__isnull=False).distinct().order_by("first_name", "username"),
        required=False,
        empty_label="Todos os Solicitantes",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Solicitante",
    )
    executante = forms.ModelChoiceField(
        queryset=User.objects.filter(ciclos_matrizaria_iniciados__isnull=False).distinct().order_by("first_name", "username"),
        required=False,
        empty_label="Todos os Executantes",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Executante",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prensa"].queryset = get_prensas_queryset()
        self.fields["prensa"].label_from_instance = lambda obj: format_prensa_label(obj)


class PrensaDashboardChoiceIterator(PrensaOuMatrizariaChoiceIterator):
    def __iter__(self):
        yield from super().__iter__()
        yield ("__SEM_PRENSA__", "Máquina não informada")


class PrensaDashboardChoiceField(PrensaOuMatrizariaChoiceField):
    iterator = PrensaDashboardChoiceIterator

    def to_python(self, value):
        return value if value == "__SEM_PRENSA__" else super().to_python(value)

    def validate(self, value):
        if value != "__SEM_PRENSA__":
            super().validate(value)


class DashboardFiltroForm(forms.Form):
    periodo = forms.ChoiceField(
        choices=[("7", "Últimos 7 dias"), ("30", "Últimos 30 dias"),
                 ("mes", "Mês atual"), ("personalizado", "Personalizado")],
        label="Período", widget=forms.Select(attrs={"class": "form-select"}),
    )
    data_inicio = forms.DateField(required=False, label="Data inicial",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    data_fim = forms.DateField(required=False, label="Data final",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    prensa = PrensaDashboardChoiceField(
        queryset=Machine.objects.none(), required=False, empty_label="Todas / serviço interno",
        label="Prensa / destino", widget=forms.Select(attrs={"class": "form-select"}),
    )
    tipo_servico = forms.ModelChoiceField(
        queryset=TipoServicoMatrizaria.objects.all(), required=False,
        empty_label="Todos os tipos", label="Tipo de serviço",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    matriz = forms.ChoiceField(required=False, label="Matriz física",
        widget=forms.Select(attrs={"class": "form-select"}))
    prioridade = forms.ChoiceField(
        required=False, choices=[("", "Todas")] + SolicitacaoServicoMatrizaria.PRIORIDADE_CHOICES,
        label="Prioridade", widget=forms.Select(attrs={"class": "form-select"}),
    )
    visao = forms.ChoiceField(required=False, choices=[
        ("fila", "Fila atual"), ("urgentes", "Urgentes pendentes"), ("abertas", "Solicitações abertas"),
        ("concluidas", "Serviços concluídos"), ("execucao", "Solicitações com execução"),
        ("retrabalho", "Solicitações devolvidas para retrabalho"),
        ("conferencias", "Solicitações avaliadas na conferência"),
        ("canceladas", "Solicitações canceladas"),
    ], widget=forms.HiddenInput())
    estado = forms.ChoiceField(required=False, choices=[("", "Todos os estados")] +
        [(key, label) for key, label in SolicitacaoServicoMatrizaria.STATUS_CHOICES
         if key not in ("CONCLUIDO", "CANCELADO")], widget=forms.HiddenInput())
    dia = forms.DateField(required=False, widget=forms.HiddenInput())
    ordem = forms.ChoiceField(required=False, choices=[
        ("prioridade", "Urgentes e mais antigas"), ("idade", "Maior idade da solicitação"),
        ("etapa", "Maior tempo na etapa"),
    ], label="Ordenar por", widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, data=None, *args, **kwargs):
        data = data.copy() if data is not None else {}
        data.setdefault("periodo", "7")
        today = timezone.localdate()
        if data.get("periodo") in ("7", "30", "mes"):
            start = today.replace(day=1) if data["periodo"] == "mes" else today - timedelta(days=int(data["periodo"]) - 1)
            data.setdefault("data_inicio", start.isoformat())
            data.setdefault("data_fim", today.isoformat())
        super().__init__(data, *args, **kwargs)
        self.fields["prensa"].queryset = Machine.objects.filter(
            Q(pk__in=get_prensas_queryset().values("pk")) | Q(solicitacoes_matrizaria__isnull=False)
        ).select_related("setor").distinct().order_by("nome")
        self.fields["prensa"].label_from_instance = format_prensa_label
        self.fields["matriz"].choices = [("", "Todas as matrizes"),
            ("__SEM_MATRIZ__", "Matriz não informada")] + [
                (str(m.pk), f"{m.identificador_estavel} · {m.nome_exibicao}")
                for m in MatrizFisica.objects.select_related("modelo").all()
            ]

    def clean(self):
        cleaned = super().clean()
        today = timezone.localdate()
        period = cleaned.get("periodo")
        if period in ("7", "30", "mes"):
            cleaned["data_inicio"] = (today.replace(day=1) if period == "mes"
                                      else today - timedelta(days=int(period) - 1))
            cleaned["data_fim"] = today
        elif period == "personalizado":
            for field in ("data_inicio", "data_fim"):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, "Informe a data para o período personalizado.")
        start, end = cleaned.get("data_inicio"), cleaned.get("data_fim")
        if start and end:
            if end < start:
                self.add_error("data_fim", "A data final deve ser igual ou posterior à inicial.")
            elif (end - start).days >= 366 or end == date.max:
                self.add_error("data_fim", "Selecione um intervalo de até 366 dias.")
            day = cleaned.get("dia")
            if day and not start <= day <= end:
                self.add_error("dia", "O dia selecionado deve pertencer ao período consultado.")
        return cleaned
