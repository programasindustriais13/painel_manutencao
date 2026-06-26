from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User

class Sector(models.Model):
    nome = models.CharField(max_length=100, verbose_name="Nome do Setor")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Setor"
        verbose_name_plural = "Setores"


class Machine(models.Model):
    CRITICIDADE_CHOICES = [
        ('BAIXA', 'Baixa (Verde)'),
        ('MEDIA', 'Média (Amarela)'),
        ('ALTA', 'Alta (Vermelha)'),
    ]

    nome = models.CharField(max_length=100, verbose_name="Nome da Máquina")
    setor = models.ForeignKey(Sector, on_delete=models.CASCADE, related_name="maquinas", verbose_name="Setor")
    criticidade = models.CharField(
        max_length=10, 
        choices=CRITICIDADE_CHOICES, 
        default='BAIXA', 
        verbose_name="Criticidade"
    )

    def __str__(self):
        return f"{self.nome} ({self.get_criticidade_display()})"

    @property
    def bootstrap_color(self):
        if self.criticidade == 'BAIXA':
            return 'success'
        elif self.criticidade == 'MEDIA':
            return 'warning'
        elif self.criticidade == 'ALTA':
            return 'danger'
        return 'secondary'

    class Meta:
        verbose_name = "Máquina"
        verbose_name_plural = "Máquinas"


class Technician(models.Model):
    STATUS_CHOICES = [
        ('OCIOSO', 'Disponível (Ocioso)'),
        ('EM_ATENDIMENTO', 'Em Atendimento'),
        ('EM_PAUSA', 'Em Pausa'),
        ('AUSENTE_FOLGA', 'Ausente – Folga/Escala'),
        ('AUSENTE_FERIAS', 'Ausente – Férias'),
        ('AUSENTE_MEDICO', 'Ausente – Licença Médica/Afastamento'),
        ('EXTERNO_PLANTAO', 'Plantão Fora da Fábrica'),
    ]

    PERFIL_CHOICES = [
        ('TECNICO', 'Técnico (Acesso apenas ao próprio card)'),
        ('TECNICO_LIDER', 'Técnico Líder (Acesso ao painel e dashboard — sem cadastros)'),
        ('OPERADOR', 'Operador/Administrador (Acesso total incluindo cadastros)'),
    ]

    # Conjunto de status que indicam que o técnico está ausente/fora da fábrica
    # e não pode receber novas ordens de serviço.
    STATUS_AUSENCIA = {'AUSENTE_FOLGA', 'AUSENTE_FERIAS', 'AUSENTE_MEDICO', 'EXTERNO_PLANTAO'}

    nome = models.CharField(max_length=100, verbose_name="Nome do Técnico")
    matricula = models.CharField(max_length=50, unique=True, verbose_name="Matrícula")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='OCIOSO', 
        verbose_name="Status"
    )
    # Vínculo opcional com usuário Django para autenticação do técnico.
    # null=True, blank=True: técnicos sem usuário continuam funcionando normalmente.
    user = models.OneToOneField(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='technician_profile',
        verbose_name="Usuário do Sistema"
    )
    # Perfil de acesso: TECNICO (apenas próprio card) ou OPERADOR (acesso total).
    perfil = models.CharField(
        max_length=15,
        choices=PERFIL_CHOICES,
        default='TECNICO',
        null=True,
        blank=True,
        verbose_name="Perfil de Acesso"
    )
    whatsapp = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name="WhatsApp"
    )


    def __str__(self):
        return f"{self.nome} ({self.matricula})"

    @property
    def is_ausente(self):
        """Retorna True se o técnico está em qualquer status de ausência/externo."""
        return self.status in self.STATUS_AUSENCIA

    @property
    def active_allocation(self):
        """Retorna apenas a alocação com status EM_ATENDIMENTO e sem data_fim."""
        if hasattr(self, '_prefetched_objects_cache') and 'allocations' in self._prefetched_objects_cache:
            active = [a for a in self.allocations.all() if a.data_fim is None and a.status == 'EM_ATENDIMENTO']
            if active:
                active.sort(key=lambda x: x.data_inicio, reverse=True)
                return active[0]
            return None
        return self.allocations.filter(data_fim__isnull=True, status='EM_ATENDIMENTO').order_by('-data_inicio').first()

    @property
    def paused_allocations(self):
        """Retorna todas as alocações pausadas (sem data_fim, status EM_PAUSA)."""
        return self.allocations.filter(data_fim__isnull=True, status='EM_PAUSA').order_by('data_pausa')

    class Meta:
        verbose_name = "Técnico"
        verbose_name_plural = "Técnicos"


class Allocation(models.Model):
    STATUS_CHOICES = [
        ('EM_ATENDIMENTO', 'Em Atendimento'),
        ('EM_PAUSA', 'Em Pausa'),
        ('CONCLUIDO', 'Concluído'),
    ]

    tecnico = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="allocations", verbose_name="Técnico")
    maquina = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name="allocations", verbose_name="Máquina")
    atividade_observacao = models.TextField(verbose_name="Atividade/Observação")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='EM_ATENDIMENTO',
        verbose_name="Status da Alocação"
    )
    usuario_operador = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Operador Responsável"
    )
    data_inicio = models.DateTimeField(verbose_name="Data/Hora de Início")
    data_pausa = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Pausa")
    motivo_pausa = models.TextField(null=True, blank=True, verbose_name="Motivo da Pausa")
    data_fim = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Fim")
    observacao_conclusao = models.TextField(null=True, blank=True, verbose_name="Observação de Conclusão")
    foto_anexo = models.ImageField(upload_to='alocacoes/', null=True, blank=True, verbose_name="Foto/Anexo")

    def __str__(self):
        maquina_str = self.maquina.nome if self.maquina else "Ocioso"
        return f"{self.tecnico.nome} em {maquina_str} - Início: {self.data_inicio.strftime('%d/%m/%Y %H:%M')}"

    @property
    def tempo_decorrido_liquido(self):
        if not self.data_inicio:
            return "N/A"
        
        now_time = timezone.now()
        fim = self.data_fim or now_time
        duration_bruto = (fim - self.data_inicio).total_seconds()
        
        # Calculate sum of all pauses
        total_pause_seconds = 0
        if hasattr(self, '_prefetched_objects_cache') and 'pausas' in self._prefetched_objects_cache:
            pausas_list = list(self.pausas.all())
        else:
            pausas_list = list(self.pausas.all())
            
        for p in pausas_list:
            if p.data_retorno:
                total_pause_seconds += (p.data_retorno - p.data_pausa).total_seconds()
            else:
                p_fim = self.data_fim or now_time
                total_pause_seconds += (p_fim - p.data_pausa).total_seconds()
                
        # Compatibility fallback if no relational pauses but data_pausa is set
        if not pausas_list and self.data_pausa:
            p_fim = self.data_fim or now_time
            total_pause_seconds += (p_fim - self.data_pausa).total_seconds()
            
        seconds = max(0, round(duration_bruto - total_pause_seconds))
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def tempo_decorrido_str(self):
        return self.tempo_decorrido_liquido

    class Meta:
        verbose_name = "Alocação"
        verbose_name_plural = "Alocações"


class HistoricoPausa(models.Model):
    alocacao = models.ForeignKey(
        Allocation, 
        on_delete=models.CASCADE, 
        related_name='pausas', 
        verbose_name="Alocação"
    )
    data_pausa = models.DateTimeField(verbose_name="Data/Hora de Pausa")
    data_retorno = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora de Retorno")
    motivo_pausa = models.TextField(verbose_name="Motivo da Pausa")

    def __str__(self):
        retorno_str = self.data_retorno.strftime('%d/%m/%Y %H:%M') if self.data_retorno else "Em aberto"
        return f"Pausa em {self.data_pausa.strftime('%d/%m/%Y %H:%M')} - Retorno: {retorno_str}"

    class Meta:
        verbose_name = "Histórico de Pausa"
        verbose_name_plural = "Histórico de Pausas"
        ordering = ['data_pausa']


class HistoricoEscala(models.Model):
    """Registra cada alteração de escala/disponibilidade de um técnico para fins de auditoria."""

    tecnico = models.ForeignKey(
        Technician,
        on_delete=models.CASCADE,
        related_name='historico_escalas',
        verbose_name="Técnico"
    )
    status_definido = models.CharField(
        max_length=20,
        verbose_name="Status Definido"
    )
    data_alteracao = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Data/Hora da Alteração"
    )
    usuario_responsavel = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Usuário Responsável"
    )

    def get_status_definido_display_label(self):
        """Retorna o rótulo legível do status, aproveitando as choices do Technician."""
        return dict(Technician.STATUS_CHOICES).get(self.status_definido, self.status_definido)

    def __str__(self):
        label = self.get_status_definido_display_label()
        return f"{self.tecnico.nome} → {label} em {self.data_alteracao.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        verbose_name = "Histórico de Escala"
        verbose_name_plural = "Histórico de Escalas"
        ordering = ['-data_alteracao']


class WhatsAppGroup(models.Model):
    nome = models.CharField(max_length=100, verbose_name="Nome do Grupo")
    jid = models.CharField(max_length=100, unique=True, verbose_name="JID do Grupo")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")

    def __str__(self):
        return self.nome

    class Meta:
        verbose_name = "Grupo de WhatsApp"
        verbose_name_plural = "Grupos de WhatsApp"
