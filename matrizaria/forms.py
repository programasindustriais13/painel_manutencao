import re
import uuid
from django import forms
from django.db.models import Q
from django.contrib.auth import get_user_model
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


class SolicitacaoServicoForm(forms.ModelForm):
    idempotency_key = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
    )

    class Meta:
        model = SolicitacaoServicoMatrizaria
        fields = [
            "prensa",
            "tipo_servico",
            "matriz_fisica",
            "prioridade",
            "descricao_solicitacao",
        ]
        widgets = {
            "prensa": forms.Select(attrs={"class": "form-select form-select-lg", "required": "required"}),
            "tipo_servico": forms.Select(attrs={"class": "form-select form-select-lg", "required": "required"}),
            "matriz_fisica": forms.Select(attrs={"class": "form-select"}),
            "prioridade": forms.Select(attrs={"class": "form-select"}),
            "descricao_solicitacao": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Descreva claramente a necessidade ou anomalia observada na prensa...",
                    "required": "required",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["prensa"].queryset = get_prensas_queryset()
        self.fields["prensa"].label_from_instance = lambda obj: format_prensa_label(obj)
        self.fields["tipo_servico"].queryset = TipoServicoMatrizaria.objects.filter(ativo=True).order_by("ordem_exibicao", "nome")
        self.fields["matriz_fisica"].queryset = MatrizFisica.objects.filter(ativo=True).select_related("modelo").order_by("modelo__nome_exibicao", "numero_sequencial")
        self.fields["matriz_fisica"].required = False
        self.fields["matriz_fisica"].empty_label = "--- Matriz física não definida no momento ---"
        self.fields["prensa"].empty_label = "--- Selecione a Prensa ---"
        self.fields["tipo_servico"].empty_label = "--- Selecione o Tipo de Serviço ---"

        if not self.initial.get("idempotency_key"):
            self.initial["idempotency_key"] = str(uuid.uuid4())

    def clean_prensa(self):
        prensa = self.cleaned_data.get("prensa")
        if prensa and is_checklist_machine(prensa):
            raise forms.ValidationError("Máquinas de apoio ou CHECK-LIST não são válidas para chamados de Matrizaria.")
        return prensa


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
    prensa = forms.ModelChoiceField(
        queryset=Machine.objects.none(),
        required=True,
        empty_label="--- Selecione a Prensa ---",
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Prensa / Máquina",
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

    def clean_prensa(self):
        prensa = self.cleaned_data.get("prensa")
        if prensa and is_checklist_machine(prensa):
            raise ValidationError("A máquina 'CHECK-LIST' não é permitida para chamados de Matrizaria.")
        return prensa

    def clean(self):
        cleaned_data = super().clean()
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
    prensa = forms.ModelChoiceField(
        queryset=Machine.objects.none(),
        required=False,
        empty_label="Todas as Prensas",
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
