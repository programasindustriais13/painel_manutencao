import datetime
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ProcessoBladder(models.Model):
    """
    Processos e equipamentos de transformação do setor de Bladder.
    Permite ordenação dinâmica, ativação/desativação e vínculo opcional
    com os equipamentos físicos cadastrados no setor BLADDER em maintenance.Machine.
    """
    TIPO_CHOICES = [
        ('PRENSA', 'Prensa de Vulcanização'),
        ('EXTRUSAO', 'Extrusão'),
        ('ACABAMENTO', 'Acabamento / Anéis'),
        ('MANUAL', 'Processo Manual / Bancada'),
        ('OUTRO', 'Outro'),
    ]

    codigo = models.CharField(max_length=10, unique=True, verbose_name="Código do Processo")
    nome = models.CharField(max_length=100, verbose_name="Nome do Processo")
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default='PRENSA', verbose_name="Tipo de Processo")
    maquina = models.ForeignKey(
        'maintenance.Machine',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processos_bladder',
        verbose_name="Máquina Vinculada (Opcional)"
    )
    ordem_exibicao = models.PositiveIntegerField(default=1, verbose_name="Ordem de Exibição")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    class Meta:
        verbose_name = "Processo do Setor de Bladder"
        verbose_name_plural = "Processos do Setor de Bladder"
        ordering = ['ordem_exibicao', 'codigo']

    def __str__(self):
        return f"{self.codigo} - {self.nome}"


class ConfiguracaoEscalaBladder(models.Model):
    """
    Configuração dinâmica da alternância da escala 12x36 (06:00 às 18:00).
    A Turma A e a Turma B trabalham em dias alternados no mesmo horário.
    A referência de início e a turma que atua na data base são configuradas aqui pelo Admin.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
    ]

    data_referencia = models.DateField(
        default=timezone.localdate,
        verbose_name="Data de Referência"
    )
    turma_referencia = models.CharField(
        max_length=10,
        choices=TURMA_CHOICES,
        default='TURMA_A',
        verbose_name="Turma que Trabalhou na Data de Referência"
    )
    hora_inicio = models.TimeField(
        default=datetime.time(6, 0),
        verbose_name="Horário Normal de Início (06:00)"
    )
    hora_fim = models.TimeField(
        default=datetime.time(18, 0),
        verbose_name="Horário Normal de Término (18:00)"
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Configuração Ativa"
    )
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuração de Escala 12x36"
        verbose_name_plural = "Configurações de Escala 12x36"

    def __str__(self):
        status = "ATIVA" if self.ativo else "INATIVA"
        return f"Escala Ref: {self.data_referencia.strftime('%d/%m/%Y')} -> {self.get_turma_referencia_display()} ({status})"


class AjusteEscalaExcepcionalBladder(models.Model):
    """
    Ajustes excepcionais pontuais de escala para uma data específica.
    Sobrepõe o cálculo automático da alternância de dias.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
        ('FOLGA', 'Parada Geral / Sem Produção'),
    ]

    data = models.DateField(unique=True, verbose_name="Data do Ajuste")
    turma_designada = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma Designada")
    motivo = models.CharField(max_length=200, verbose_name="Motivo do Ajuste")
    criado_por = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="Registrado por")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ajuste Excepcional de Escala"
        verbose_name_plural = "Ajustes Excepcionais de Escala"
        ordering = ['-data']

    def __str__(self):
        return f"{self.data.strftime('%d/%m/%Y')}: {self.get_turma_designada_display()} ({self.motivo})"


class FuncionarioApoioBladder(models.Model):
    """
    Funcionários que atuam com papel de Apoio Operacional fora da escala normal 12x36.
    Não altera a turma titular do dia e tem dias/horários flexíveis configuráveis no Admin.
    """
    TIPO_ESCALA_CHOICES = [
        ('DIAS_SEMANA', 'Dias da Semana Recorrentes'),
        ('DATAS_ESPECIFICAS', 'Datas Específicas / Pontuais'),
    ]

    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='apoios_bladder',
        verbose_name="Usuário"
    )
    papel = models.CharField(max_length=100, default="Apoio Operacional", verbose_name="Papel / Função de Apoio")
    tipo_escala = models.CharField(
        max_length=20,
        choices=TIPO_ESCALA_CHOICES,
        default='DIAS_SEMANA',
        verbose_name="Tipo de Escala"
    )
    dias_semana = models.CharField(
        max_length=30,
        blank=True,
        null=True,
        verbose_name="Dias da Semana",
        help_text="Números separados por vírgula (0=Segunda, 1=Terça, 2=Quarta, 3=Quinta, 4=Sexta, 5=Sábado, 6=Domingo)"
    )
    datas_especificas = models.TextField(
        blank=True,
        null=True,
        verbose_name="Datas Específicas (YYYY-MM-DD)",
        help_text="Uma data por linha ou separadas por vírgula"
    )
    hora_inicio = models.TimeField(default=datetime.time(6, 0), verbose_name="Horário de Início")
    hora_fim = models.TimeField(default=datetime.time(18, 0), verbose_name="Horário de Término")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações")

    class Meta:
        verbose_name = "Funcionário de Apoio Bladder"
        verbose_name_plural = "Funcionários de Apoio Bladder"
        ordering = ['usuario__first_name', 'usuario__username']

    def __str__(self):
        nome = self.usuario.get_full_name() or self.usuario.username
        return f"{nome} - {self.papel} ({'Ativo' if self.ativo else 'Inativo'})"


class PerfilOperacionalBladder(models.Model):
    """
    Perfil operacional complementar para operadores regulares do setor de Bladder.
    Vincula o usuário à sua respectiva equipe de revezamento 12x36 (Turma A ou Turma B).
    Líderes e funcionários de apoio não necessitam de vínculo a Turma A/B fixa.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
    ]

    usuario = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='perfil_operacional_bladder',
        verbose_name="Usuário"
    )
    turma = models.CharField(
        max_length=10,
        choices=TURMA_CHOICES,
        verbose_name="Turma Operacional Regular"
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Perfil Operacional Bladder"
        verbose_name_plural = "Perfis Operacionais Bladder"
        ordering = ['turma', 'usuario__first_name', 'usuario__username']

    def __str__(self):
        status = "Ativo" if self.ativo else "Inativo"
        nome = self.usuario.get_full_name() or self.usuario.username
        return f"{nome} - {self.get_turma_display()} ({status})"


class ProdutoBladder(models.Model):
    """
    Catálogo de produtos fabricados no Setor de Bladder.
    Estruturado a partir da especificação técnica ET.029 (Extrusão e Vulcanização).
    """
    STATUS_CHOICES = [
        ('ATIVO', 'Ativo'),
        ('EM DESENVOLVIMENTO', 'Em Desenvolvimento'),
        ('INATIVO', 'Inativo'),
    ]

    codigo = models.CharField(max_length=50, unique=True, verbose_name="Código do Bladder")
    descricao = models.CharField(max_length=150, verbose_name="Descrição / Medida")
    nomenclatura_antiga = models.CharField(max_length=50, blank=True, null=True, verbose_name="Nomenclatura Antiga")
    matriz_extrusao = models.CharField(max_length=50, blank=True, null=True, verbose_name="Matriz de Extrusão")
    comprimento_extrusao_cm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Comprimento Extrusão (cm)"
    )
    comprimento_chanfrado_cm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Comprimento Chanfrado (cm)"
    )
    peso_tarugo_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Peso do Tarugo (kg)"
    )
    diametro_tarugo_mm = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Diâmetro do Tarugo (mm)"
    )
    tempo_vulcanizacao_min = models.PositiveIntegerField(
        default=120,
        null=True,
        blank=True,
        verbose_name="Tempo de Vulcanização (min)"
    )
    peso_vulcanizado_kg = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        verbose_name="Peso Vulcanizado (kg)"
    )
    circunferencia_centro_mm = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Circunferência no Centro (mm)"
    )
    altura_cm = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Altura (cm)"
    )
    production_bladder = models.ForeignKey(
        'production.ProductionBladder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='produtos_setor_bladder',
        verbose_name="Vínculo com Catálogo de Vulcanização (Opcional)"
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='ATIVO', verbose_name="Status")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Produto / Modelo de Bladder"
        verbose_name_plural = "Produtos / Modelos de Bladder"
        ordering = ['codigo']

    @property
    def medida(self):
        """
        Retorna a medida canônica do bladder conforme especificação ET.029
        (ex: 'B200/16', 'B140/15', 'B240/15', etc.).
        Extraída da descrição do produto.
        """
        if not self.descricao:
            return ""
        for sep in ['—', ' - ', '-']:
            if sep in self.descricao:
                return self.descricao.split(sep)[0].strip()
        return self.descricao.strip()

    @property
    def codigo_com_medida(self):
        """Retorna a representação simplificada canônica para o Líder: CÓDIGO — MEDIDA."""
        m = self.medida
        return f"{self.codigo} — {m}" if m else self.codigo

    def __str__(self):
        return self.codigo_com_medida


class RecursoBladder(models.Model):
    """
    Recursos necessários para execução de OPs no setor de Bladder:
    matrizes, compostos, ferramentas, tarugos, etc.
    """
    CATEGORIA_CHOICES = [
        ('MATRIZ', 'Matriz de Extrusão / Prensa'),
        ('COMPOSTO', 'Composto de Borracha'),
        ('FERRAMENTA', 'Ferramenta / Acessório'),
        ('MATERIA_PRIMA', 'Matéria-Prima / Tarugo'),
        ('OUTROS', 'Outro Recurso'),
    ]

    categoria = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default='MATRIZ', verbose_name="Categoria")
    codigo = models.CharField(max_length=50, blank=True, null=True, verbose_name="Código de Identificação")
    nome = models.CharField(max_length=150, verbose_name="Nome do Recurso")
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição / Especificação")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    class Meta:
        verbose_name = "Recurso do Setor de Bladder"
        verbose_name_plural = "Recursos do Setor de Bladder"
        ordering = ['categoria', 'nome']

    def __str__(self):
        cod = f"[{self.codigo}] " if self.codigo else ""
        return f"{self.get_categoria_display()} - {cod}{self.nome}"


class OrdemProducaoBladder(models.Model):
    """
    Ordem de Produção (OP) do Setor de Bladder.
    Pertence estritamente ao turno/data para o qual foi programada.
    Se não atingir a totalidade no turno, encerra como PARCIAL e gera saldo no Ledger.
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente'),
        ('EM_EXECUCAO', 'Em Execução'),
        ('CONCLUIDA', 'Concluída'),
        ('PARCIAL', 'Encerrada Parcial'),
        ('CANCELADA', 'Cancelada'),
    ]

    PRIORIDADE_CHOICES = [
        ('BAIXA', 'Baixa'),
        ('NORMAL', 'Normal'),
        ('ALTA', 'Alta'),
        ('URGENTE', 'Urgente'),
    ]

    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
    ]

    numero_ordem = models.CharField(max_length=40, unique=True, verbose_name="Número da OP")
    processo = models.ForeignKey(ProcessoBladder, on_delete=models.PROTECT, related_name='ordens', verbose_name="Processo")
    produto = models.ForeignKey(ProdutoBladder, on_delete=models.PROTECT, related_name='ordens', verbose_name="Produto / Modelo")
    data_programada = models.DateField(db_index=True, verbose_name="Data Programada")
    turma_prevista = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma Prevista")
    prioridade = models.CharField(max_length=10, choices=PRIORIDADE_CHOICES, default='NORMAL', verbose_name="Prioridade")

    quantidade_nova = models.PositiveIntegerField(
        verbose_name="Qtd Nova Solicitada",
        help_text="Necessidade nova planejada pelo líder"
    )
    saldo_anterior_incorporado = models.PositiveIntegerField(
        default=0,
        verbose_name="Saldo Anterior Incorporado",
        help_text="Saldo pendente incorporado de programações anteriores"
    )
    quantidade_planejada = models.PositiveIntegerField(
        verbose_name="Total Programado a Produzir",
        help_text="Soma da Quantidade Nova com o Saldo Anterior Incorporado"
    )
    quantidade_realizada = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade Realizada"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status"
    )

    recursos_alocados = models.ManyToManyField(
        RecursoBladder,
        blank=True,
        related_name='ordens',
        verbose_name="Recursos Necessários"
    )
    recursos_observacoes = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observações de Recursos / Instruções"
    )
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações Gerais")

    motivo_cancelamento = models.TextField(blank=True, null=True, verbose_name="Motivo do Cancelamento")
    cancelado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ordens_bladder_canceladas',
        verbose_name="Cancelado por"
    )
    data_cancelamento = models.DateTimeField(null=True, blank=True, verbose_name="Data/Hora do Cancelamento")

    criado_por = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='ordens_bladder_criadas',
        verbose_name="Criado por"
    )
    atualizado_por = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ordens_bladder_atualizadas',
        verbose_name="Atualizado por"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ordem de Produção de Bladder"
        verbose_name_plural = "Ordens de Produção de Bladder"
        ordering = ['data_programada', '-prioridade', 'numero_ordem']

    def __str__(self):
        return f"{self.numero_ordem} - {self.produto.codigo} ({self.get_status_display()})"

    @property
    def saldo_remanescente(self):
        """Diferença entre o total programado e o que foi realizado (pendência): max(0, planejada - realizada)."""
        return max(0, self.quantidade_planejada - self.quantidade_realizada)

    @property
    def excedente(self):
        """Produção excedente acima da meta programada: max(0, realizada - planejada)."""
        return max(0, self.quantidade_realizada - self.quantidade_planejada)

    @property
    def diferenca(self):
        """Diferença entre a quantidade realizada e a planejada (realizada - planejada)."""
        return self.quantidade_realizada - self.quantidade_planejada

    @property
    def consumo_teorico_planejado_kg(self):
        """Consumo teórico planejado: quantidade_planejada * peso do tarugo."""
        if self.produto and self.produto.peso_tarugo_kg:
            return round(self.quantidade_planejada * float(self.produto.peso_tarugo_kg), 3)
        return None

    @property
    def consumo_teorico_realizado_kg(self):
        """Consumo teórico associado ao realizado: quantidade_realizada * peso do tarugo."""
        if self.produto and self.produto.peso_tarugo_kg:
            return round(self.quantidade_realizada * float(self.produto.peso_tarugo_kg), 3)
        return None

    @property
    def percentual_conclusao(self):
        """Percentual atingido da programação (realizado / programado * 100), sem corte silencioso em 100%."""
        if self.quantidade_planejada == 0:
            return 100.0
        return round((self.quantidade_realizada / self.quantidade_planejada) * 100, 1)

    def esta_atrasada(self, hora_fim=None):
        """
        Cálculo dinâmico de atraso:
        OP nos estados PENDENTE ou EM_EXECUCAO cuja data_programada já encerrou o turno
        conforme o horário configurado em ConfiguracaoEscalaBladder (ou hora_fim informada).
        Após o fechamento do turno (OP em CONCLUIDA ou PARCIAL), a OP reflete o fechamento e não é mais considerada atrasada.
        """
        if self.status not in ('PENDENTE', 'EM_EXECUCAO'):
            return False

        if hora_fim is None:
            config = ConfiguracaoEscalaBladder.objects.filter(ativo=True).order_by('-updated_at').first()
            hora_fim = config.hora_fim if (config and config.hora_fim) else datetime.time(18, 0)

        agora = timezone.localtime(timezone.now())
        dt_limite = timezone.make_aware(
            datetime.datetime.combine(self.data_programada, hora_fim),
            timezone.get_current_timezone()
        )
        return agora > dt_limite

    @property
    def status_visual(self):
        """
        Apresentação visual padronizada do status da OP:
        - 'CANCELADA': OP cancelada pelo planejamento
        - 'CONCLUÍDA': Turno fechado e produção atingiu a meta total
        - 'PARCIAL / PENDÊNCIA': Turno fechado com produção parcial e saldo remanescente
        - 'NÃO REALIZADA / PENDÊNCIA': Turno fechado com produção zero
        - 'PROGRAMADA': OP criada e ainda não fechada pelo operador (turno em aberto)
        """
        if self.status == 'CANCELADA':
            return 'CANCELADA'
        if self.status == 'CONCLUIDA':
            return 'CONCLUÍDA'
        if self.status == 'PARCIAL':
            if self.quantidade_realizada == 0:
                return 'NÃO REALIZADA / PENDÊNCIA'
            return 'PARCIAL / PENDÊNCIA'
        return 'PROGRAMADA'

    @property
    def numero_ordem_curto(self):
        """
        Identificação visual curta da OP para apresentação resumida no Card do Operador (ex: 'OP #002').
        Não altera o número oficial integral gravado no banco em numero_ordem (ex: 'OP-BLA-20260930-0002').
        """
        if not self.numero_ordem:
            return ""
        partes = self.numero_ordem.split("-")
        sufixo = partes[-1]
        if sufixo.isdigit():
            num = int(sufixo)
            if num < 1000:
                return f"OP #{num:03d}"
            return f"OP #{num}"
        return f"OP #{sufixo}"

    @property
    def saldo_gerado(self):
        """Retorna o saldo remanescente gerado quando a OP é encerrada como PARCIAL ou possui saldo pendente."""
        if self.status == 'PARCIAL':
            return max(0, self.quantidade_planejada - self.quantidade_realizada)
        return 0

    @property
    def motivo_pendencia(self):
        """Retorna o motivo registrado para a pendência desta OP."""
        item = self.itens_fechamento.order_by('-id').first()
        if item and (item.motivo or item.categorias.exists()):
            return item.get_motivo_display() or (item.categorias.first().nome if item.categorias.exists() else item.motivo)
        ap = self.apontamentos.filter(motivo_desvio__isnull=False).exclude(motivo_desvio='').order_by('-id').first()
        if ap and ap.motivo_desvio:
            return ap.motivo_desvio
        hist = self.historicos_programacao.filter(tipo_evento='ENCERRAMENTO_PARCIAL').order_by('-id').first()
        if hist and hist.motivo:
            return hist.motivo
        saldo = self.saldos_gerados.first()
        if saldo and saldo.motivo_cancelamento:
            return saldo.motivo_cancelamento
        return "Sem justificativa informada"

    @property
    def data_fechamento(self):
        """Data/hora de fechamento ou encerramento da OP."""
        if self.status in ('PARCIAL', 'CONCLUIDA'):
            item = self.itens_fechamento.select_related('fechamento').order_by('-id').first()
            if item and item.fechamento:
                return item.fechamento.data_hora_fechamento
            hist = self.historicos_programacao.filter(tipo_evento__in=['ENCERRAMENTO_PARCIAL', 'CONCLUSAO']).order_by('-id').first()
            if hist:
                return hist.created_at
            ap = self.apontamentos.order_by('-updated_at').first()
            if ap:
                return ap.data_hora_fim or ap.updated_at
            return self.updated_at
        return None

    @property
    def turma_responsavel_fechamento(self):
        """Turma responsável pelo fechamento operacional."""
        item = self.itens_fechamento.select_related('fechamento').order_by('-id').first()
        if item and item.fechamento:
            return item.fechamento.get_turma_display()
        ap = self.apontamentos.order_by('-id').first()
        if ap:
            return ap.get_turma_display()
        return self.get_turma_prevista_display()


class FechamentoTurnoBladder(models.Model):
    """
    Cabeçalho de auditoria do Fechamento do Turno realizado pelo Operador.
    Representa o evento único, formal e auditável de encerramento do turno de produção de Bladder.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
        ('APOIO', 'Apoio Operacional'),
    ]
    STATUS_CHOICES = [
        ('CONCLUIDO', 'Fechamento Concluído'),
        ('RETIFICADO', 'Retificado pela Liderança'),
    ]

    data_turno = models.DateField(db_index=True, verbose_name="Data do Turno")
    turma = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma")
    operador = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='fechamentos_bladder',
        verbose_name="Operador Responsável pelo Fechamento"
    )
    data_hora_fechamento = models.DateTimeField(default=timezone.now, verbose_name="Data/Hora do Fechamento")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='CONCLUIDO',
        verbose_name="Status do Fechamento"
    )
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações Gerais do Turno")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fechamento de Turno Bladder"
        verbose_name_plural = "Fechamentos de Turno Bladder"
        unique_together = ('data_turno', 'turma')
        ordering = ['-data_turno', '-data_hora_fechamento']

    def __str__(self):
        return f"Fechamento {self.data_turno.strftime('%d/%m/%Y')} - {self.get_turma_display()} ({self.operador.username})"


class CategoriaDesvioBladder(models.Model):
    """
    Catálogo estruturado de categorias de desvio / pendência no fechamento de turno.
    Suporta seleção de uma ou mais categorias por item de fechamento com déficit.
    """
    codigo = models.CharField(max_length=40, unique=True, verbose_name="Código da Categoria")
    nome = models.CharField(max_length=100, verbose_name="Nome da Categoria")
    ordem = models.PositiveIntegerField(default=1, verbose_name="Ordem de Exibição")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")

    class Meta:
        verbose_name = "Categoria de Desvio Bladder"
        verbose_name_plural = "Categorias de Desvios Bladder"
        ordering = ['ordem', 'nome']

    def __str__(self):
        return self.nome


class ItemFechamentoTurnoBladder(models.Model):
    """
    Item individual auditado de cada OP incluída no Fechamento do Turno.
    Armazena snapshot de programado, realizado, saldo, situação e motivo obrigatório se incompleta.
    Suporta múltiplas categorias estruturadas e descrição obrigatória ('O que aconteceu?').
    """
    SITUACAO_CHOICES = [
        ('CONCLUIDA', 'Concluída'),
        ('PARCIAL', 'Parcial'),
        ('NAO_REALIZADA', 'Não Realizada'),
    ]

    MOTIVO_CHOICES = [
        ('PROBLEMA_EQUIPAMENTO', 'Problema de equipamento'),
        ('FALTA_MATERIA_PRIMA', 'Falta de matéria-prima'),
        ('FALTA_COMPONENTE', 'Falta de componente'),
        ('PROBLEMA_OPERACIONAL', 'Problema operacional'),
        ('ALTERACAO_PROGRAMACAO', 'Alteração de programação'),
        ('PROBLEMA_QUALIDADE', 'Problema de qualidade'),
        ('MANUTENCAO', 'Manutenção'),
        ('FALTA_OPERADOR', 'Falta de operador'),
        ('OUTRO', 'Outro'),
    ]

    fechamento = models.ForeignKey(
        FechamentoTurnoBladder,
        on_delete=models.CASCADE,
        related_name='itens',
        verbose_name="Fechamento de Turno"
    )
    ordem = models.ForeignKey(
        OrdemProducaoBladder,
        on_delete=models.PROTECT,
        related_name='itens_fechamento',
        verbose_name="Ordem de Produção"
    )
    quantidade_programada = models.PositiveIntegerField(verbose_name="Meta Programada")
    quantidade_realizada = models.PositiveIntegerField(verbose_name="Quantidade Realizada")
    saldo_gerado = models.PositiveIntegerField(default=0, verbose_name="Saldo Gerado")
    situacao = models.CharField(max_length=20, choices=SITUACAO_CHOICES, verbose_name="Situação")
    categorias = models.ManyToManyField(
        CategoriaDesvioBladder,
        blank=True,
        related_name='itens_fechamento',
        verbose_name="Categorias do Desvio"
    )
    descricao_desvio = models.TextField(
        blank=True,
        null=True,
        verbose_name="Descrição do Ocorrido (O que aconteceu?)"
    )
    motivo = models.CharField(
        max_length=40,
        choices=MOTIVO_CHOICES,
        blank=True,
        null=True,
        verbose_name="Motivo do Saldo"
    )
    motivo_outro = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Descrição do Motivo (Outro)"
    )
    observacao = models.TextField(blank=True, null=True, verbose_name="Observações")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Item de Fechamento de Turno"
        verbose_name_plural = "Itens de Fechamento de Turno"
        unique_together = ('fechamento', 'ordem')
        ordering = ['ordem__numero_ordem']

    def __str__(self):
        return f"{self.ordem.numero_ordem}: {self.quantidade_realizada}/{self.quantidade_programada} ({self.get_situacao_display()})"

    @property
    def excedente(self):
        """Produção excedente acima da meta programada: max(0, realizada - programada)."""
        return max(0, self.quantidade_realizada - self.quantidade_programada)

    @property
    def diferenca(self):
        """Diferença entre a quantidade realizada e a programada (realizada - programada)."""
        return self.quantidade_realizada - self.quantidade_programada

    @property
    def categorias_display(self):
        """Retorna os nomes das categorias associadas separados por vírgula."""
        cats = list(self.categorias.all())
        if cats:
            return ", ".join(c.nome for c in cats)
        if self.motivo:
            return self.get_motivo_display() or self.motivo
        return ""

    @property
    def motivo_completo(self):
        """Retorna categorias formatadas e a descrição do ocorrido."""
        cats_str = self.categorias_display or self.get_motivo_display() or ""
        desc = (self.descricao_desvio or (self.motivo_outro if self.motivo == 'OUTRO' else '') or self.observacao or "").strip()
        if cats_str and desc and cats_str != desc:
            return f"{cats_str} — {desc}"
        elif cats_str:
            return cats_str
        elif desc:
            return desc
        if self.motivo == 'OUTRO' and self.motivo_outro:
            return f"Outro: {self.motivo_outro}"
        return self.get_motivo_display() or ""


class SaldoPendenteBladder(models.Model):
    """
    Ledger de rastreabilidade de saldos remanescentes de OPs encerradas como PARCIAL.
    Permite auditar:
    - de qual OP nasceu o saldo;
    - de qual produto;
    - qual quantidade;
    - quando foi gerado;
    - se ainda está pendente ou se foi incorporado em qual OP futura.
    """
    STATUS_CHOICES = [
        ('PENDENTE', 'Pendente de Produção'),
        ('INCORPORADO', 'Incorporado em Nova OP'),
        ('CANCELADO', 'Cancelado pela Liderança'),
    ]

    op_origem = models.ForeignKey(
        OrdemProducaoBladder,
        on_delete=models.CASCADE,
        related_name='saldos_gerados',
        verbose_name="OP de Origem"
    )
    produto = models.ForeignKey(
        ProdutoBladder,
        on_delete=models.PROTECT,
        related_name='saldos_pendentes',
        verbose_name="Produto / Modelo"
    )
    quantidade = models.PositiveIntegerField(verbose_name="Quantidade do Saldo")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDENTE',
        db_index=True,
        verbose_name="Status do Saldo"
    )
    op_destino = models.ForeignKey(
        OrdemProducaoBladder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='saldos_incorporados',
        verbose_name="OP de Destino (Onde foi Incorporado)"
    )
    fechamento = models.ForeignKey(
        FechamentoTurnoBladder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='saldos_gerados_fechamento',
        verbose_name="Fechamento de Origem"
    )
    data_incorporacao = models.DateTimeField(null=True, blank=True, verbose_name="Data da Incorporação")
    motivo_cancelamento = models.TextField(blank=True, null=True, verbose_name="Motivo de Cancelamento")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data de Geração do Saldo")

    class Meta:
        verbose_name = "Saldo Pendente (Ledger de Bladder)"
        verbose_name_plural = "Saldos Pendentes (Ledger de Bladder)"
        ordering = ['created_at']

    def __str__(self):
        return f"Saldo {self.quantidade} un de {self.produto.codigo} (Origem: {self.op_origem.numero_ordem}) [{self.get_status_display()}]"


class ApontamentoTurnoBladder(models.Model):
    """
    Registro operacional de chão de fábrica realizado pelos operadores.
    Grava início, término, quantidade realizada, ocorrências e operador responsável.
    """
    TURMA_CHOICES = [
        ('TURMA_A', 'Turma A'),
        ('TURMA_B', 'Turma B'),
        ('APOIO', 'Apoio Operacional'),
    ]

    SITUACAO_CHOICES = [
        ('EM_ANDAMENTO', 'Em Andamento'),
        ('CONCLUIDA', 'Concluída'),
        ('PARCIAL', 'Execução Parcial'),
        ('INTERROMPIDA', 'Interrompida com Problema'),
    ]

    fechamento = models.ForeignKey(
        FechamentoTurnoBladder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='apontamentos_fechamento',
        verbose_name="Fechamento de Origem"
    )
    ordem = models.ForeignKey(
        OrdemProducaoBladder,
        on_delete=models.CASCADE,
        related_name='apontamentos',
        verbose_name="Ordem de Produção"
    )
    operador = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name='apontamentos_bladder',
        verbose_name="Operador"
    )
    turma = models.CharField(max_length=10, choices=TURMA_CHOICES, verbose_name="Turma")
    data_turno = models.DateField(default=timezone.localdate, verbose_name="Data do Turno")
    data_hora_inicio = models.DateTimeField(verbose_name="Início da Atividade")
    data_hora_fim = models.DateTimeField(null=True, blank=True, verbose_name="Término da Atividade")
    quantidade_realizada = models.PositiveIntegerField(default=0, verbose_name="Quantidade Produzida")
    situacao = models.CharField(
        max_length=20,
        choices=SITUACAO_CHOICES,
        default='EM_ANDAMENTO',
        verbose_name="Situação"
    )
    motivo_desvio = models.TextField(blank=True, null=True, verbose_name="Motivo do Desvio / Ocorrência")
    observacoes = models.TextField(blank=True, null=True, verbose_name="Observações do Operador")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Apontamento Operacional de Bladder"
        verbose_name_plural = "Apontamentos Operacionais de Bladder"
        ordering = ['-data_hora_inicio']

    def __str__(self):
        nome = self.operador.get_full_name() or self.operador.username
        return f"{self.ordem.numero_ordem} - {nome} ({self.quantidade_realizada} un) [{self.get_situacao_display()}]"


class HistoricoApontamentoBladder(models.Model):
    """
    Trilha de auditoria para correções de apontamentos no chão de fábrica.
    Preserva valor anterior, novo valor, usuário, data/hora e justificativa.
    """
    apontamento = models.ForeignKey(
        ApontamentoTurnoBladder,
        on_delete=models.CASCADE,
        related_name='historico_correcoes',
        verbose_name="Apontamento"
    )
    quantidade_anterior = models.PositiveIntegerField(verbose_name="Quantidade Anterior")
    quantidade_nova = models.PositiveIntegerField(verbose_name="Quantidade Corrigida")
    situacao_anterior = models.CharField(max_length=20, blank=True, null=True, verbose_name="Situação Anterior")
    situacao_nova = models.CharField(max_length=20, blank=True, null=True, verbose_name="Situação Corrigida")
    motivo_correcao = models.TextField(verbose_name="Justificativa da Correção")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="Usuário Responsável")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora da Correção")

    class Meta:
        verbose_name = "Histórico de Correção de Apontamento"
        verbose_name_plural = "Históricos de Correções de Apontamentos"
        ordering = ['-created_at']

    def __str__(self):
        return f"Correção Apontamento #{self.apontamento_id}: {self.quantidade_anterior} -> {self.quantidade_nova}"


class HistoricoProgramacaoBladder(models.Model):
    """
    Trilha de auditoria da Ordem de Produção (reprogramações, alterações, encerramentos, cancelamentos).
    Registra de forma imutável a data anterior, data nova, motivo e usuário.
    """
    EVENTO_CHOICES = [
        ('CRIACAO', 'Criação da OP'),
        ('ALTERACAO', 'Alteração de Dados'),
        ('REPROGRAMACAO', 'Reprogramação de Data'),
        ('CANCELAMENTO', 'Cancelamento da OP'),
        ('ENCERRAMENTO_PARCIAL', 'Encerramento Parcial de Turno'),
        ('CONCLUSAO', 'Conclusão da Ordem'),
    ]

    ordem = models.ForeignKey(
        OrdemProducaoBladder,
        on_delete=models.CASCADE,
        related_name='historicos_programacao',
        verbose_name="Ordem de Produção"
    )
    tipo_evento = models.CharField(max_length=25, choices=EVENTO_CHOICES, verbose_name="Tipo de Evento")
    data_anterior = models.DateField(null=True, blank=True, verbose_name="Data Anterior")
    data_nova = models.DateField(null=True, blank=True, verbose_name="Nova Data")
    quantidade_anterior = models.PositiveIntegerField(null=True, blank=True, verbose_name="Quantidade Anterior")
    quantidade_nova = models.PositiveIntegerField(null=True, blank=True, verbose_name="Nova Quantidade")
    motivo = models.TextField(verbose_name="Motivo / Justificativa")
    usuario = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name="Usuário Responsável")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Data/Hora do Evento")

    class Meta:
        verbose_name = "Histórico de Programação de Bladder"
        verbose_name_plural = "Históricos de Programação de Bladder"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.ordem.numero_ordem} - {self.get_tipo_evento_display()} em {self.created_at.strftime('%d/%m/%Y %H:%M')}"
