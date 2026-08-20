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
        ('AUSENTE_FALTA_JUSTIFICADA', 'Ausente – Falta Justificada'),
        ('AUSENTE_FALTA_NAO_JUSTIFICADA', 'Ausente – Falta Não Justificada'),
    ]

    PERFIL_CHOICES = [
        ('TECNICO', 'Técnico (Acesso apenas ao próprio card)'),
        ('TECNICO_LIDER', 'Técnico Líder (Acesso ao painel e dashboard — sem cadastros)'),
        ('OPERADOR', 'Operador/Administrador (Acesso total incluindo cadastros)'),
    ]

    # Conjunto de status que indicam que o técnico está ausente/fora da fábrica
    # e não pode receber novas ordens de serviço.
    STATUS_AUSENCIA = {
        'AUSENTE_FOLGA', 
        'AUSENTE_FERIAS', 
        'AUSENTE_MEDICO', 
        'EXTERNO_PLANTAO',
        'AUSENTE_FALTA_JUSTIFICADA',
        'AUSENTE_FALTA_NAO_JUSTIFICADA',
    }

    nome = models.CharField(max_length=100, verbose_name="Nome do Técnico")
    matricula = models.CharField(max_length=50, unique=True, verbose_name="Matrícula")
    status = models.CharField(
        max_length=30, 
        choices=STATUS_CHOICES, 
        default='OCIOSO', 
        verbose_name="Status"
    )
    is_active = models.BooleanField(
        default=True, 
        verbose_name="Ativo no quadro da empresa"
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

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        if self.pk and not self.is_active:
            if self.allocations.filter(data_fim__isnull=True).exists():
                raise ValidationError(
                    "O técnico possui atendimentos em aberto. Conclua ou transfira os atendimentos antes de inativá-lo."
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


class OrdemServico(models.Model):
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente (Aguardando Atendimento)'),
        ('EM_ANDAMENTO', 'Em Andamento'),
        ('CONCLUIDA', 'Concluída'),
        ('CANCELADA', 'Cancelada'),
    ]

    TIPO_MANUTENCAO_CHOICES = [
        ('CORRETIVA', 'Corretiva'),
        ('PREVENTIVA', 'Preventiva'),
        ('MELHORIA', 'Melhoria'),
        ('PREDIAL', 'Predial'),
        ('OUTRO', 'Outro'),
    ]

    CRITICIDADE_CHOICES = [
        ('BAIXA', 'Baixa (Normal)'),
        ('MEDIA', 'Média'),
        ('ALTA', 'Alta (Urgente / Parada de Máquina)'),
    ]

    # --- 1. CABEÇALHO ---
    numero_os = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Número da OS Física",
        help_text="Número impresso na folha física (ex: 10216). Deve ser único para evitar duplicidades."
    )

    # --- 2. ETAPA 1: ABERTURA PELO LÍDER ---
    tag = models.CharField(
        max_length=50, 
        null=True, 
        blank=True, 
        verbose_name="TAG do Equipamento"
    )
    descricao_equipamento = models.CharField(
        max_length=150, 
        null=True, 
        blank=True, 
        verbose_name="Descrição do Equipamento"
    )
    maquina = models.ForeignKey(
        'Machine', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="ordens_servico", 
        verbose_name="Máquina Relacionada"
    )
    setor = models.ForeignKey(
        'Sector', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="ordens_servico", 
        verbose_name="Setor"
    )
    solicitante = models.CharField(
        max_length=120, 
        null=True, 
        blank=True, 
        verbose_name="Solicitante / Líder de Produção"
    )
    motivo = models.CharField(
        max_length=200, 
        null=True, 
        blank=True, 
        verbose_name="Motivo do Chamado"
    )
    tipo_manutencao = models.CharField(
        max_length=20, 
        choices=TIPO_MANUTENCAO_CHOICES, 
        default='CORRETIVA', 
        verbose_name="Tipo de Serviço"
    )
    parou_maquina = models.BooleanField(
        default=True, 
        verbose_name="Parou a Máquina?"
    )
    criticidade = models.CharField(
        max_length=15, 
        choices=CRITICIDADE_CHOICES, 
        default='MEDIA', 
        verbose_name="Criticidade"
    )
    descricao_falha = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Descrição do Serviço a ser Realizado"
    )
    data_hora_inicio_ocorrencia = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Início da Ocorrência"
    )
    data_abertura = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Data/Hora de Cadastro no Sistema"
    )

    # --- 3. ETAPA 2: EXECUÇÃO & FECHAMENTO PELO TÉCNICO ---
    causa = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Causa da Falha (Conferir no Verso)"
    )
    descricao_servico_realizado = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Descrição do Serviço Realizado"
    )
    data_hora_inicio_conserto = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Início do Conserto"
    )
    data_hora_fim_conserto = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fim do Conserto"
    )
    visto_executante_nome = models.CharField(
        max_length=120, 
        null=True, 
        blank=True, 
        verbose_name="Visto Executante (Nome do Técnico)"
    )
    visto_executante_data = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Data do Visto Executante"
    )
    tecnico_designado = models.ForeignKey(
        'Technician', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='os_designadas', 
        verbose_name="Técnico Designado Principal (Opcional)"
    )

    # --- 4. ETAPA 3: FINALIZAÇÃO & ACEITE PELO LÍDER ---
    data_hora_fim_ocorrencia = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Fim da Ocorrência (Máquina Liberada)"
    )
    visto_responsavel_nome = models.CharField(
        max_length=120, 
        null=True, 
        blank=True, 
        verbose_name="Visto Responsável (Nome do Líder)"
    )
    visto_responsavel_data = models.DateField(
        null=True, 
        blank=True, 
        verbose_name="Data do Visto Responsável"
    )

    # --- 5. CONTROLE DO SISTEMA & AUDITORIA ---
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='PENDENTE', 
        verbose_name="Status da OS"
    )
    foto_abertura = models.ImageField(
        upload_to='ordens_servico/abertura/%Y/%m/', 
        null=True, 
        blank=True, 
        verbose_name="Foto da OS na Abertura"
    )
    foto_conclusao = models.ImageField(
        upload_to='ordens_servico/conclusao/%Y/%m/', 
        null=True, 
        blank=True, 
        verbose_name="Foto da OS Finalizada e Assinada"
    )
    foto_verso = models.ImageField(
        upload_to='ordens_servico/verso/%Y/%m/', 
        null=True, 
        blank=True, 
        verbose_name="Foto do Verso da OS (Opcional)"
    )
    criado_por = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='os_abertas',
        verbose_name="Usuário que Cadastrou"
    )
    data_conclusao = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Data/Hora de Conclusão no Sistema"
    )
    observacao_fechamento = models.TextField(
        null=True, 
        blank=True, 
        verbose_name="Observações de Fechamento / Ação Executada"
    )
    lider_assinatura_nome = models.CharField(
        max_length=120, 
        null=True, 
        blank=True, 
        verbose_name="Nome do Líder que Assinou a Conclusão"
    )

    class Meta:
        verbose_name = "Ordem de Serviço"
        verbose_name_plural = "Ordens de Serviço"
        ordering = ['-data_abertura']

    def __str__(self):
        identificador = self.descricao_equipamento or (self.maquina.nome if self.maquina else "Sem Máquina")
        return f"OS #{self.numero_os} - {identificador} ({self.get_status_display()})"

    @property
    def tecnicos_envolvidos(self):
        """Retorna lista única de técnicos que trabalharam nas alocações ligadas a esta OS."""
        if hasattr(self, '_prefetched_objects_cache') and 'allocations' in self._prefetched_objects_cache:
            seen = set()
            techs = []
            for alloc in self.allocations.all():
                if alloc.tecnico and alloc.tecnico_id not in seen:
                    seen.add(alloc.tecnico_id)
                    techs.append(alloc.tecnico)
            return techs
        tech_ids = self.allocations.values_list('tecnico_id', flat=True).distinct()
        return list(Technician.objects.filter(id__in=tech_ids))

    @property
    def pode_ser_iniciada(self):
        """Retorna True se o status for PENDENTE ou EM_ANDAMENTO."""
        return self.status in ['PENDENTE', 'EM_ANDAMENTO']

    @property
    def tempo_total_homem_hora_segundos(self):
        """Soma total de homem-hora em segundos de todas as alocações vinculadas."""
        total_seconds = 0
        allocations = self.allocations.all()
        for alloc in allocations:
            total_seconds += alloc.tempo_decorrido_segundos
        return total_seconds

    @property
    def tempo_total_homem_hora_str(self):
        """Retorna o tempo homem-hora total acumulado formatado (ex: '2h 30m' ou '45m')."""
        seconds = self.tempo_total_homem_hora_segundos
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def tempo_conserto_segundos(self):
        """Calcula a duração do conserto a partir dos horários físicos (início ao fim do conserto)."""
        if self.data_hora_inicio_conserto and self.data_hora_fim_conserto:
            return max(0, int((self.data_hora_fim_conserto - self.data_hora_inicio_conserto).total_seconds()))
        return 0

    @property
    def tempo_conserto_str(self):
        seconds = self.tempo_conserto_segundos
        if not seconds:
            return "N/A"
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def tempo_liquido_parada_segundos(self):
        """Calcula o tempo total de parada da ocorrência física ou da data_abertura até conclusão."""
        if self.data_hora_inicio_ocorrencia and self.data_hora_fim_ocorrencia:
            return max(0, int((self.data_hora_fim_ocorrencia - self.data_hora_inicio_ocorrencia).total_seconds()))
        if self.data_hora_inicio_ocorrencia:
            fim = self.data_hora_fim_ocorrencia or timezone.now()
            return max(0, int((fim - self.data_hora_inicio_ocorrencia).total_seconds()))
        if not self.data_abertura:
            return 0
        fim = self.data_conclusao or timezone.now()
        return max(0, int((fim - self.data_abertura).total_seconds()))

    @property
    def tempo_liquido_parada_str(self):
        seconds = self.tempo_liquido_parada_segundos
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def alocacoes_ativas(self):
        """Retorna as alocações atualmente em andamento ou pausadas nesta OS."""
        return self.allocations.filter(data_fim__isnull=True).select_related('tecnico')

    @property
    def tecnicos_ativos(self):
        """Retorna lista dos técnicos com alocações ativas nesta OS."""
        return [alloc.tecnico for alloc in self.alocacoes_ativas if alloc.tecnico]

    @property
    def tempo_espera_str(self):
        """Retorna o tempo de espera desde o início da ocorrência ou abertura da OS."""
        ref = self.data_hora_inicio_ocorrencia or self.data_abertura
        if not ref:
            return "0m"
        now = timezone.now()
        seconds = max(0, int((now - ref).total_seconds()))
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    @property
    def criticidade_badge_class(self):
        """Retorna a classe CSS do Bootstrap conforme a criticidade."""
        if self.criticidade == 'ALTA':
            return 'danger'
        elif self.criticidade == 'MEDIA':
            return 'warning text-dark'
        return 'info text-dark'

    @property
    def tempo_total_intervencao(self):
        """Retorna dicionário com o tempo total acumulado de homem-hora e tempo de máquina parada."""
        return {
            'homem_hora_segundos': self.tempo_total_homem_hora_segundos,
            'homem_hora_str': self.tempo_total_homem_hora_str,
            'tempo_conserto_segundos': self.tempo_conserto_segundos,
            'tempo_conserto_str': self.tempo_conserto_str,
            'tempo_parada_segundos': self.tempo_liquido_parada_segundos,
            'tempo_parada_str': self.tempo_liquido_parada_str,
        }



class OrdemServicoPeca(models.Model):
    ordem_servico = models.ForeignKey(
        OrdemServico, 
        on_delete=models.CASCADE, 
        related_name='pecas_utilizadas', 
        verbose_name="Ordem de Serviço"
    )
    codigo = models.CharField(
        max_length=50, 
        blank=True, 
        null=True, 
        verbose_name="Código da Peça"
    )
    descricao = models.CharField(
        max_length=200, 
        verbose_name="Descrição da Peça / Material"
    )
    quantidade = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=1.0, 
        verbose_name="Quantidade"
    )

    def __str__(self):
        cod_str = f"[{self.codigo}] " if self.codigo else ""
        return f"{cod_str}{self.descricao} (Qtd: {self.quantidade})"

    class Meta:
        verbose_name = "Peça Utilizada"
        verbose_name_plural = "Peças Utilizadas"


class Allocation(models.Model):
    STATUS_CHOICES = [
        ('EM_ATENDIMENTO', 'Em Atendimento'),
        ('EM_PAUSA', 'Em Pausa'),
        ('CONCLUIDO', 'Concluído'),
    ]

    ordem_servico = models.ForeignKey(
        'OrdemServico',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='allocations',
        verbose_name="Ordem de Serviço Vinculada"
    )
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
    def tempo_decorrido_segundos(self):
        if not self.data_inicio:
            return 0
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
            
        return max(0, round(duration_bruto - total_pause_seconds))

    @property
    def tempo_decorrido_liquido(self):
        if not self.data_inicio:
            return "N/A"
        seconds = self.tempo_decorrido_segundos
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
        max_length=30,
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


class AllocationProgressUpdate(models.Model):
    allocation = models.ForeignKey(
        Allocation,
        on_delete=models.CASCADE,
        related_name="progress_updates",
        verbose_name="Alocação"
    )
    autor = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Autor da Atualização"
    )
    descricao = models.TextField(verbose_name="Descrição da Atualização")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    def __str__(self):
        autor_str = self.autor.get_full_name() or self.autor.username if self.autor else "Sistema"
        return f"Nota em Alocação #{self.allocation_id} por {autor_str} em {self.criado_em.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        verbose_name = "Atualização de Progresso"
        verbose_name_plural = "Atualizações de Progresso"
        ordering = ["criado_em"]

