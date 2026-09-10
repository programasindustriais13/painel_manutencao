from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from maintenance.models import Machine
from production.models import ProductionMatrixCatalog


EXCLUDED_PRENSA_NAMES = ["CHECK-LIST", "CHECK LIST", "CHECKLIST"]


def is_checklist_machine(machine_or_name) -> bool:
    """
    Retorna True se o objeto de máquina ou denominação textual corresponder
    a registros de apoio/checklist da manutenção ('CHECK-LIST', 'CHECK LIST', 'CHECKLIST').
    Não utiliza exclusão genérica por 'CHECK' para não afetar outras máquinas válidas.
    """
    if not machine_or_name:
        return False
    name = getattr(machine_or_name, "nome", str(machine_or_name)).strip().upper()
    return name in EXCLUDED_PRENSA_NAMES


class TipoServicoMatrizaria(models.Model):
    """
    Catálogo de serviços executados pela oficina de Matrizaria.
    Gerenciável via Django Admin pela gestão industrial.
    """
    nome = models.CharField(max_length=100, unique=True, verbose_name="Nome do Tipo de Serviço")
    descricao = models.TextField(null=True, blank=True, verbose_name="Descrição Detalhada")
    exige_matriz_fisica = models.BooleanField(
        default=False,
        verbose_name="Exige Matriz Física?",
        help_text="Se marcado, a solicitação não poderá ser finalizada sem a identificação do exemplar físico da matriz."
    )
    ativo = models.BooleanField(default=True, db_index=True, verbose_name="Ativo")
    ordem_exibicao = models.PositiveIntegerField(default=1, verbose_name="Ordem de Exibição")

    class Meta:
        verbose_name = "Tipo de Serviço de Matrizaria"
        verbose_name_plural = "Tipos de Serviço de Matrizaria"
        ordering = ["ordem_exibicao", "nome"]

    def __str__(self):
        return self.nome


class MatrizFisica(models.Model):
    """
    Representação dos exemplares físicos individuais de matrizes existentes no chão de fábrica.
    Cada unidade física pertence a um modelo canônico cadastrado no SCADA (ProductionMatrixCatalog).
    """
    modelo = models.ForeignKey(
        ProductionMatrixCatalog,
        on_delete=models.PROTECT,
        related_name="unidades_fisicas",
        verbose_name="Modelo Canônico (Catálogo SCADA)"
    )
    identificador_estavel = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Identificador Estável / Código Interno",
        help_text="Código único de rastreabilidade (ex: MF-HOPPER-001)"
    )
    numero_sequencial = models.PositiveIntegerField(
        verbose_name="Número Sequencial da Unidade",
        help_text="Ex: 1 para 001, 2 para 002"
    )
    ativo = models.BooleanField(default=True, db_index=True, verbose_name="Ativo no Chão de Fábrica")
    observacoes = models.TextField(null=True, blank=True, verbose_name="Observações do Exemplar")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Cadastrado em")

    class Meta:
        verbose_name = "Matriz Física (Exemplar)"
        verbose_name_plural = "Matrizes Físicas (Exemplares)"
        ordering = ["modelo__nome_exibicao", "numero_sequencial"]
        constraints = [
            models.UniqueConstraint(
                fields=["modelo", "numero_sequencial"],
                name="uniq_matriz_fisica_modelo_seq"
            )
        ]

    @property
    def numero_sequencial_str(self):
        """Retorna o número sequencial formatado em 3 dígitos (ex: '001', '002')."""
        return f"{self.numero_sequencial:03d}"

    @property
    def nome_exibicao(self):
        """Nome amigável combinando o modelo canônico e o número do exemplar físico."""
        modelo_str = self.modelo.nome_exibicao or self.modelo.produto or self.modelo.nome_scada or f"Código {self.modelo.codigo_scada}"
        return f"{modelo_str} #{self.numero_sequencial_str}"

    def __str__(self):
        return self.nome_exibicao


class SolicitacaoServicoMatrizaria(models.Model):
    """
    Ordem de Serviço / Chamado de atendimento da oficina de Matrizaria.
    """
    STATUS_CHOICES = [
        ("SOLICITADO", "Solicitado"),
        ("EM_EXECUCAO", "Em Execução"),
        ("AGUARDANDO_CONFERENCIA", "Aguardando Conferência"),
        ("AGUARDANDO_RETRABALHO", "Aguardando Retrabalho"),
        ("CONCLUIDO", "Concluído"),
        ("CANCELADO", "Cancelado"),
    ]

    PRIORIDADE_CHOICES = [
        ("NORMAL", "Normal"),
        ("URGENTE", "Urgente"),
    ]

    versao = models.PositiveIntegerField(
        default=1,
        db_index=True,
        verbose_name="Versão de Concorrência"
    )

    # Vínculo com Prensa (obrigatório, reutiliza maintenance.Machine)
    prensa = models.ForeignKey(
        Machine,
        on_delete=models.PROTECT,
        related_name="solicitacoes_matrizaria",
        verbose_name="Prensa / Máquina"
    )
    prensa_nome_snapshot = models.CharField(
        max_length=120,
        editable=False,
        verbose_name="Snapshot do Nome da Prensa na Abertura"
    )

    # Vínculo com Matriz Física (opcional na abertura, validado conforme o tipo)
    matriz_fisica = models.ForeignKey(
        MatrizFisica,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_servico",
        verbose_name="Matriz Física (Exemplar)"
    )
    matriz_identificador_snapshot = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Snapshot da Matriz Física Vinculada"
    )

    # Tipo de Serviço
    tipo_servico = models.ForeignKey(
        TipoServicoMatrizaria,
        on_delete=models.PROTECT,
        related_name="solicitacoes",
        verbose_name="Tipo de Serviço"
    )
    tipo_servico_nome_snapshot = models.CharField(
        max_length=120,
        editable=False,
        verbose_name="Snapshot do Tipo de Serviço"
    )
    exige_matriz_fisica_snapshot = models.BooleanField(
        default=False,
        editable=False,
        verbose_name="Snapshot da Regra de Exigência de Matriz"
    )

    descricao_solicitacao = models.TextField(
        verbose_name="Descrição da Necessidade / Problema"
    )
    prioridade = models.CharField(
        max_length=15,
        choices=PRIORIDADE_CHOICES,
        default="NORMAL",
        db_index=True,
        verbose_name="Prioridade"
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="SOLICITADO",
        db_index=True,
        verbose_name="Status Atual"
    )

    # Autoria da Abertura
    solicitado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="solicitacoes_matrizaria_criadas",
        verbose_name="Solicitante"
    )
    solicitado_por_nome = models.CharField(
        max_length=150,
        editable=False,
        verbose_name="Nome do Solicitante"
    )
    data_solicitacao = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Data/Hora da Solicitação"
    )

    # Responsável Atribuído Atual
    responsavel_atribuido = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_matrizaria_atribuidas",
        verbose_name="Responsável Atual na Matrizaria"
    )
    responsavel_atribuido_nome = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Nome do Responsável Atual"
    )

    # Primeiro Início e Último Término (Campos Resumo)
    iniciado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_matrizaria_iniciadas",
        verbose_name="Primeiro Executor que Iniciou"
    )
    data_inicio_execucao = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Primeiro Início da Execução"
    )
    finalizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_matrizaria_finalizadas",
        verbose_name="Último Executor que Finalizou"
    )
    data_fim_execucao = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Último Término da Execução Técnica"
    )
    descricao_servico_executado = models.TextField(
        null=True,
        blank=True,
        verbose_name="Última Descrição do Serviço Executado"
    )

    # Conferência e Aceite Final
    conferido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_matrizaria_conferidas",
        verbose_name="Conferente / Responsável pelo Aceite"
    )
    conferido_por_nome = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Nome do Conferente"
    )
    data_conferencia = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Data/Hora da Conferência"
    )
    observacao_conferencia = models.TextField(
        null=True,
        blank=True,
        verbose_name="Observação da Conferência"
    )

    # Cancelamento
    cancelado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="solicitacoes_matrizaria_canceladas",
        verbose_name="Cancelado Por"
    )
    cancelado_por_nome = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        editable=False,
        verbose_name="Nome de Quem Cancelou"
    )
    data_cancelamento = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora do Cancelamento"
    )
    motivo_cancelamento = models.TextField(
        null=True,
        blank=True,
        verbose_name="Motivo do Cancelamento"
    )

    quantidade_retrabalhos = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade de Ciclos de Retrabalho"
    )

    class Meta:
        verbose_name = "Solicitação de Serviço da Matrizaria"
        verbose_name_plural = "Solicitações de Serviço da Matrizaria"
        ordering = ["-data_solicitacao"]
        indexes = [
            models.Index(fields=["status", "-data_solicitacao"]),
            models.Index(fields=["prensa", "-data_solicitacao"]),
            models.Index(fields=["data_inicio_execucao", "data_fim_execucao"]),
        ]

    def __str__(self):
        matriz_str = self.matriz_identificador_snapshot or (self.matriz_fisica.nome_exibicao if self.matriz_fisica else "Matriz N/I")
        return f"SM #{self.pk} - {self.prensa_nome_snapshot or self.prensa.nome} - {matriz_str} ({self.get_status_display()})"

    @property
    def ciclo_atual(self):
        """Retorna o ciclo de execução ativo (ou o mais recente cadastrado)."""
        return self.ciclos_execucao.order_by("-numero_ciclo").first()

    @property
    def duracao_total_intervencao_segundos(self):
        """Soma total da duração de todos os ciclos de execução técnica da solicitação."""
        total = 0
        for ciclo in self.ciclos_execucao.all():
            total += ciclo.duracao_segundos
        return total

    @property
    def duracao_total_intervencao_str(self):
        """Retorna a duração total acumulada formatada (ex: '2h 15m' ou '45m')."""
        seconds = self.duracao_total_intervencao_segundos
        if seconds <= 0:
            return "0m"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    @property
    def tempo_espera_str(self):
        """Tempo decorrido desde a abertura da solicitação até a finalização ou momento atual."""
        ref_inicio = self.data_solicitacao
        ref_fim = self.data_conferencia or self.data_cancelamento or timezone.now()
        seconds = max(0, int((ref_fim - ref_inicio).total_seconds()))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 24:
            days = hours // 24
            rem_hours = hours % 24
            return f"{days}d {rem_hours}h"
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    @property
    def badge_prioridade_classe(self):
        return "danger" if self.prioridade == "URGENTE" else "secondary"

    @property
    def motivo_devolucao_retrabalho(self):
        """Retorna o motivo da devolução para retrabalho registrado na conferência."""
        return self.observacao_conferencia or ""

    @property
    def badge_status_classe(self):
        classes = {
            "SOLICITADO": "warning text-dark",
            "EM_EXECUCAO": "primary",
            "AGUARDANDO_CONFERENCIA": "info text-dark",
            "AGUARDANDO_RETRABALHO": "danger",
            "CONCLUIDO": "success",
            "CANCELADO": "dark",
        }
        return classes.get(self.status, "secondary")

    def clean(self):
        super().clean()
        try:
            if hasattr(self, "prensa") and self.prensa and is_checklist_machine(self.prensa):
                raise ValidationError({"prensa": "Máquinas de apoio ou CHECK-LIST não são permitidas para chamados de Matrizaria."})
        except Machine.DoesNotExist:
            pass


class CicloExecucaoMatrizaria(models.Model):
    """
    Registra individualmente cada ciclo de atendimento técnico de uma solicitação.
    Se um chamado for devolvido para retrabalho, um novo ciclo é aberto sem sobrescrever o anterior.
    """
    FORMA_ENCERRAMENTO_CHOICES = [
        ("EM_ANDAMENTO", "Em Andamento"),
        ("FINALIZADO_TECNICO", "Finalizado Técnico"),
        ("INTERROMPIDO_CANCELAMENTO", "Interrompido por Cancelamento"),
    ]

    solicitacao = models.ForeignKey(
        SolicitacaoServicoMatrizaria,
        on_delete=models.PROTECT,
        related_name="ciclos_execucao",
        verbose_name="Solicitação Vinculada"
    )
    numero_ciclo = models.PositiveIntegerField(
        default=1,
        verbose_name="Número do Ciclo"
    )
    usuario_inicio = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="ciclos_matrizaria_iniciados",
        verbose_name="Usuário de Início"
    )
    usuario_inicio_nome = models.CharField(
        max_length=150,
        verbose_name="Nome de Quem Iniciou o Ciclo"
    )
    data_inicio = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Data/Hora de Início do Ciclo"
    )

    usuario_fim = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ciclos_matrizaria_finalizados",
        verbose_name="Usuário de Encerramento"
    )
    usuario_fim_nome = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="Nome de Quem Encerrou o Ciclo"
    )
    data_fim = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Data/Hora de Fim do Ciclo"
    )

    descricao_servico_executado = models.TextField(
        null=True,
        blank=True,
        verbose_name="Descrição do Serviço Executado Neste Ciclo"
    )
    forma_encerramento = models.CharField(
        max_length=30,
        choices=FORMA_ENCERRAMENTO_CHOICES,
        default="EM_ANDAMENTO",
        verbose_name="Forma de Encerramento"
    )
    matriz_fisica_snapshot = models.CharField(
        max_length=150,
        null=True,
        blank=True,
        verbose_name="Snapshot da Matriz no Ciclo"
    )

    class Meta:
        verbose_name = "Ciclo de Execução da Matrizaria"
        verbose_name_plural = "Ciclos de Execução da Matrizaria"
        ordering = ["solicitacao", "numero_ciclo"]
        constraints = [
            models.UniqueConstraint(
                fields=["solicitacao", "numero_ciclo"],
                name="uniq_ciclo_solicitacao_numero"
            )
        ]

    def __str__(self):
        return f"Solicitação #{self.solicitacao_id} - Ciclo {self.numero_ciclo} ({self.get_forma_encerramento_display()})"

    @property
    def duracao_segundos(self):
        """Retorna a duração em segundos do ciclo de execução."""
        if not self.data_inicio:
            return 0
        fim = self.data_fim or (timezone.now() if self.forma_encerramento == "EM_ANDAMENTO" else self.data_inicio)
        return max(0, int((fim - self.data_inicio).total_seconds()))

    @property
    def duracao_str(self):
        seconds = self.duracao_segundos
        if seconds <= 0:
            return "0m"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"


class HistoricoTransicaoServicoMatrizaria(models.Model):
    """
    Trilha de auditoria 1:N imutável de todas as transições de status e eventos relevantes.
    Blindada contra exclusões em cascata e modificações posteriores.
    """
    solicitacao = models.ForeignKey(
        SolicitacaoServicoMatrizaria,
        on_delete=models.PROTECT,
        related_name="historico_transicoes",
        verbose_name="Solicitação Vinculada"
    )
    status_anterior = models.CharField(max_length=30, verbose_name="Status Anterior")
    status_novo = models.CharField(max_length=30, verbose_name="Status Novo")
    tipo_evento = models.CharField(
        max_length=40,
        choices=[
            ("CRIACAO", "Abertura da Solicitação"),
            ("INICIO", "Início de Execução"),
            ("FINALIZACAO_EXECUCAO", "Finalização Técnica"),
            ("CONFERENCIA_APROVADA", "Aprovação na Conferência"),
            ("REJEICAO_RETRABALHO", "Devolução para Retrabalho"),
            ("TRANSFERENCIA", "Transferência de Responsável"),
            ("ALTERACAO_DADO", "Ajuste Justificado de Informação"),
            ("CANCELAMENTO", "Cancelamento"),
        ],
        verbose_name="Tipo de Evento"
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        verbose_name="Usuário Autor da Ação"
    )
    usuario_nome_snapshot = models.CharField(max_length=150, verbose_name="Nome do Usuário Autor")
    data_evento = models.DateTimeField(default=timezone.now, db_index=True, verbose_name="Data/Hora do Evento")
    observacao = models.TextField(null=True, blank=True, verbose_name="Observação / Justificativa")
    dados_modificados = models.TextField(null=True, blank=True, verbose_name="Resumo Estruturado de Dados Alterados")

    class Meta:
        verbose_name = "Histórico de Transição da Matrizaria"
        verbose_name_plural = "Histórico de Transições da Matrizaria"
        ordering = ["data_evento", "id"]

    def __str__(self):
        return f"SM #{self.solicitacao_id}: {self.status_anterior} -> {self.status_novo} por {self.usuario_nome_snapshot} em {self.data_evento.strftime('%d/%m/%Y %H:%M')}"
