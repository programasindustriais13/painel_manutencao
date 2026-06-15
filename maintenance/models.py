from django.db import models
from django.utils import timezone

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
        ('OCIOSO', 'Ocioso'),
        ('EM_ATENDIMENTO', 'Em Atendimento'),
        ('EM_PAUSA', 'Em Pausa'),
    ]

    nome = models.CharField(max_length=100, verbose_name="Nome do Técnico")
    matricula = models.CharField(max_length=50, unique=True, verbose_name="Matrícula")
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='OCIOSO', 
        verbose_name="Status"
    )

    def __str__(self):
        return f"{self.nome} ({self.matricula})"

    @property
    def active_allocation(self):
        return self.allocations.filter(data_fim__isnull=True).order_by('-data_inicio').first()

    class Meta:
        verbose_name = "Técnico"
        verbose_name_plural = "Técnicos"


class Allocation(models.Model):
    tecnico = models.ForeignKey(Technician, on_delete=models.CASCADE, related_name="allocations", verbose_name="Técnico")
    maquina = models.ForeignKey(Machine, on_delete=models.SET_NULL, null=True, blank=True, related_name="allocations", verbose_name="Máquina")
    atividade_observacao = models.TextField(verbose_name="Atividade/Observação")
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
    def tempo_decorrido_str(self):
        if not self.data_inicio:
            return "N/A"
        
        # Calculate time spent up to completion or current time or pause start
        fim = self.data_fim or timezone.now()
        
        # If currently paused, time elapsed is calculated up to the point of pause
        if self.data_pausa and not self.data_fim:
            fim = self.data_pausa

        delta = fim - self.data_inicio
        total_seconds = int(delta.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    class Meta:
        verbose_name = "Alocação"
        verbose_name_plural = "Alocações"
