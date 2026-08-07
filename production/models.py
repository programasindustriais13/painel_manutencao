from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.contrib.auth.models import User
from maintenance.models import Machine


class ProductionShift(models.Model):
    nome = models.CharField(
        max_length=50,
        verbose_name="Nome do Turno",
        help_text="Ex: 1º Turno, Turno Manhã, etc."
    )
    horario_inicial = models.TimeField(
        verbose_name="Horário Inicial"
    )
    horario_final = models.TimeField(
        verbose_name="Horário Final"
    )
    atravessa_meia_noite = models.BooleanField(
        default=False,
        verbose_name="Atravessa a Meia-Noite",
        help_text="Marcado automaticamente se o horário final for menor ou igual ao horário inicial."
    )
    percentual_meta = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        verbose_name="Percentual de Distribuição da Meta (%)",
        help_text="Percentual da meta diária alocado para este turno. A soma dos turnos ativos deve dar 100.00% (ou 0.00% para distribuição igual)."
    )
    ordem_exibicao = models.PositiveIntegerField(
        default=1,
        verbose_name="Ordem de Exibição"
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo"
    )

    class Meta:
        verbose_name = "Turno de Produção"
        verbose_name_plural = "Turnos de Produção"
        ordering = ["ordem_exibicao", "horario_inicial"]

    def __str__(self):
        h_ini = self.horario_inicial.strftime("%H:%M") if self.horario_inicial else ""
        h_fim = self.horario_final.strftime("%H:%M") if self.horario_final else ""
        return f"{self.nome} ({h_ini} - {h_fim})"

    def save(self, *args, **kwargs):
        if self.horario_inicial and self.horario_final:
            self.atravessa_meia_noite = (self.horario_final <= self.horario_inicial)
        super().save(*args, **kwargs)

    def clean(self):
        from django.core.exceptions import ValidationError
        super().clean()
        if self.horario_inicial and self.horario_final:
            self.atravessa_meia_noite = (self.horario_final <= self.horario_inicial)

        if self.ativo:
            qs = ProductionShift.objects.filter(ativo=True)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            active_shifts = list(qs) + [self]
            custom_percents = [float(s.percentual_meta or 0) for s in active_shifts]
            total_percent = sum(custom_percents)
            if any(p > 0 for p in custom_percents):
                if abs(total_percent - 100.0) > 0.01:
                    raise ValidationError(
                        f"A soma dos percentuais dos turnos ativos deve ser 100.00% (soma atual: {total_percent:.2f}%)."
                    )


class ProductionMachineConfig(models.Model):
    machine = models.OneToOneField(
        Machine,
        on_delete=models.CASCADE,
        related_name="production_config",
        verbose_name="Máquina"
    )
    ordem_exibicao = models.PositiveIntegerField(
        default=0,
        verbose_name="Ordem de Exibição"
    )
    stale_limit_seconds = models.PositiveIntegerField(
        default=120,
        validators=[MinValueValidator(1)],
        verbose_name="Limite para Dado Desatualizado (segundos)",
        help_text="Tempo máximo em segundos sem atualização do Scada antes de considerar dado desatualizado."
    )
    produzindo_value = models.CharField(
        max_length=50,
        default="1",
        verbose_name="Valor Bruto que Indica Produzindo",
        help_text="Valor do XID de status que indica que a máquina está produzindo (ex: '1' ou 'true')."
    )
    xid_status_prensa = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Status da Prensa (Produzindo/Parada)"
    )
    xid_abertura = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Sinal de Abertura"
    )
    xid_motivo_parada_geral = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Motivo de Parada Geral"
    )

    class Meta:
        verbose_name = "Configuração de Máquina (Produção)"
        verbose_name_plural = "Configurações de Máquinas (Produção)"
        ordering = ["ordem_exibicao", "machine__nome"]
        constraints = [
            models.CheckConstraint(
                check=models.Q(stale_limit_seconds__gte=1),
                name="chk_prod_machine_stale_limit_gte_1"
            )
        ]

    def __str__(self):
        return f"Config. Produção: {self.machine.nome}"


class ProductionCavityConfig(models.Model):
    machine_config = models.ForeignKey(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        related_name="cavities",
        verbose_name="Configuração da Máquina"
    )
    nome = models.CharField(
        max_length=50,
        verbose_name="Nome da Cavidade",
        help_text="Ex: Cavidade 1, Cavidade A, Esquerda, etc."
    )
    ordem = models.PositiveIntegerField(
        default=1,
        verbose_name="Ordem de Exibição"
    )
    xid_matriz = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Matriz",
        help_text="Código da matriz/produto atualmente instalado, traduzido pelo catálogo canônico do SCADA."
    )
    xid_produto = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Prefixo do Lote do Bladder",
        help_text="Primeira parte do lote completo. Exemplo: no lote 6154 - 161046, este XID fornece 6154."
    )
    xid_lote_bladder = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Número do Lote do Bladder",
        help_text="Segunda parte do lote completo. Exemplo: no lote 6154 - 161046, este XID fornece 161046."
    )
    xid_producao = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Produção Atual"
    )
    meta_producao_manual = models.PositiveIntegerField(
        default=0,
        verbose_name="Meta Manual de Produção",
        help_text="Meta diária de produção cadastrada manualmente pelo PCP / Líder de Produção."
    )
    xid_meta = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Limite de Produção do Bladder (Scada)",
        help_text="Código XID no Scada que fornece o limite de vida produtiva do ciclo do bladder."
    )
    xid_motivo_parada = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Motivo de Parada da Cavidade"
    )

    class Meta:
        verbose_name = "Configuração de Cavidade"
        verbose_name_plural = "Configurações de Cavidades"
        ordering = ["ordem", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["machine_config", "nome"],
                name="uniq_prod_cavity_machine_nome"
            ),
            models.UniqueConstraint(
                fields=["machine_config", "ordem"],
                name="uniq_prod_cavity_machine_ordem"
            ),
        ]

    def __str__(self):
        return f"{self.machine_config.machine.nome} - {self.nome}"


class ProductionGlobalParameter(models.Model):
    nome = models.CharField(
        max_length=100,
        verbose_name="Nome do Parâmetro"
    )
    chave = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Chave Única",
        help_text="Identificador único no sistema (ex: pressao_vacuo, vapor_1_7, pressao_ar)."
    )
    xid = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID no Scada-LTS"
    )
    unidade = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="Unidade de Medida (ex: bar, mmHg)"
    )
    ordem = models.PositiveIntegerField(
        default=0,
        verbose_name="Ordem de Exibição"
    )

    class Meta:
        verbose_name = "Parâmetro Global"
        verbose_name_plural = "Parâmetros Globais"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.chave})"


class ProductionGlobalAlarm(models.Model):
    nome = models.CharField(
        max_length=100,
        verbose_name="Nome do Alarme"
    )
    chave = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Chave Única",
        help_text="Identificador único no sistema (ex: alarme_ar, alarme_vapor, alarme_vacuo)."
    )
    xid = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID no Scada-LTS"
    )
    ordem = models.PositiveIntegerField(
        default=0,
        verbose_name="Ordem de Exibição"
    )

    class Meta:
        verbose_name = "Alarme Global"
        verbose_name_plural = "Alarmes Globais"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.chave})"


class ProductionMachineState(models.Model):
    machine_config = models.OneToOneField(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        related_name="state",
        verbose_name="Configuração da Máquina"
    )
    estado_atual = models.CharField(
        max_length=30,
        default="SEM_COMUNICACAO",
        verbose_name="Estado Atual"
    )
    inicio_estado_atual = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Início do Estado Atual"
    )
    ultima_leitura_scada = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Última Leitura Scada"
    )
    ultimo_timestamp_scada = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Último Timestamp Scada (ms)"
    )
    ultimo_valor_status = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Último Valor Bruto de Status"
    )
    motivo_atual = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Motivo Atual"
    )
    sem_comunicacao = models.BooleanField(
        default=False,
        verbose_name="Sem Comunicação"
    )
    dado_desatualizado = models.BooleanField(
        default=False,
        verbose_name="Dado Desatualizado"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Estado Atual da Máquina"
        verbose_name_plural = "Estados Atuais das Máquinas"

    def __str__(self):
        return f"Estado {self.machine_config.machine.nome}: {self.estado_atual}"


class ProductionDowntimeEvent(models.Model):
    machine_config = models.ForeignKey(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        related_name="downtime_events",
        verbose_name="Configuração da Máquina"
    )
    inicio = models.DateTimeField(
        verbose_name="Início da Parada"
    )
    fim = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fim da Parada"
    )
    duracao_segundos = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Duração (segundos)"
    )
    motivo_geral = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name="Motivo Geral de Parada"
    )
    snapshot_valor_status = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Snapshot Valor Status"
    )
    timestamp_inicial_scada = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Timestamp Inicial Scada (ms)"
    )
    timestamp_final_scada = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Timestamp Final Scada (ms)"
    )
    origem = models.CharField(
        max_length=50,
        default="SCADA",
        verbose_name="Origem do Registro"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Evento de Parada de Produção"
        verbose_name_plural = "Eventos de Parada de Produção"
        ordering = ["-inicio"]
        indexes = [
            models.Index(fields=["machine_config", "inicio"]),
            models.Index(fields=["inicio"]),
            models.Index(fields=["fim"]),
        ]

    def __str__(self):
        status_str = f"até {self.fim.strftime('%d/%m %H:%M')}" if self.fim else "(Em andamento)"
        return f"Parada {self.machine_config.machine.nome} em {self.inicio.strftime('%d/%m %H:%M')} {status_str}"


class ProductionCavityMatrixHistory(models.Model):
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="matrix_history",
        verbose_name="Configuração da Cavidade"
    )
    matrix_value = models.CharField(
        max_length=100,
        verbose_name="Valor da Matriz"
    )
    started_at = models.DateTimeField(
        verbose_name="Data/Hora Inicial"
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora Final"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Histórico de Matriz de Cavidade"
        verbose_name_plural = "Históricos de Matrizes de Cavidades"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["cavity_config", "started_at"]),
            models.Index(fields=["started_at"]),
            models.Index(fields=["ended_at"]),
        ]

    def __str__(self):
        status_str = f"até {self.ended_at.strftime('%d/%m %H:%M')}" if self.ended_at else "(Em uso)"
        return f"Matriz {self.matrix_value} em {self.cavity_config} desde {self.started_at.strftime('%d/%m %H:%M')} {status_str}"


class ProductionMachineStateInterval(models.Model):
    STATE_CHOICES = [
        ("PRODUZINDO", "Produzindo"),
        ("PARADA", "Parada"),
        ("SEM_COMUNICACAO", "Sem comunicação"),
    ]

    machine_config = models.ForeignKey(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        related_name="state_intervals",
        verbose_name="Configuração da Máquina"
    )
    state = models.CharField(
        max_length=30,
        choices=STATE_CHOICES,
        verbose_name="Estado"
    )
    started_at = models.DateTimeField(
        verbose_name="Data/Hora Inicial"
    )
    ended_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data/Hora Final"
    )
    status_raw_value = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="Valor Bruto de Status"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Intervalo de Estado da Máquina"
        verbose_name_plural = "Intervalos de Estados das Máquinas"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["machine_config", "started_at"]),
            models.Index(fields=["state", "started_at"]),
            models.Index(fields=["ended_at"]),
        ]

class ProductionCavityState(models.Model):
    CAVITY_STATE_CHOICES = [
        ("NORMAL", "Normal"),
        ("PARADA", "Parada"),
        ("INDETERMINADO", "Indeterminado"),
    ]

    cavity_config = models.OneToOneField(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="state",
        verbose_name="Configuração da Cavidade"
    )
    estado_atual = models.CharField(
        max_length=50,
        choices=CAVITY_STATE_CHOICES,
        default="NORMAL",
        verbose_name="Estado Atual"
    )
    inicio_estado_atual = models.DateTimeField(
        default=timezone.now,
        verbose_name="Início do Estado Atual"
    )
    ultimo_motivo = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Último Motivo Registrado"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Estado Atual da Cavidade"
        verbose_name_plural = "Estados Atuais das Cavidades"

    def __str__(self):
        return f"Estado {self.cavity_config.nome} ({self.cavity_config.machine_config.machine.nome}): {self.estado_atual}"


class ProductionCavityDowntimeEvent(models.Model):
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="downtime_events",
        verbose_name="Configuração da Cavidade"
    )
    inicio = models.DateTimeField(
        verbose_name="Início da Parada"
    )
    fim = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Fim da Parada"
    )
    duracao_segundos = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name="Duração (segundos)"
    )
    motivo_parada = models.CharField(
        max_length=255,
        verbose_name="Motivo da Parada"
    )
    snapshot_valor_motivo = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Snapshot Valor do Motivo"
    )
    timestamp_inicial_scada = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Timestamp Inicial Scada (ms)"
    )
    timestamp_final_scada = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name="Timestamp Final Scada (ms)"
    )
    origem = models.CharField(
        max_length=50,
        default="SCADA",
        verbose_name="Origem do Registro"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Criado em"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Atualizado em"
    )

    class Meta:
        verbose_name = "Evento de Parada por Cavidade"
        verbose_name_plural = "Eventos de Parada por Cavidade"
        ordering = ["-inicio"]
        indexes = [
            models.Index(fields=["cavity_config", "inicio"]),
            models.Index(fields=["cavity_config", "fim"]),
        ]

    def __str__(self):
        status_str = f"até {self.fim.strftime('%d/%m %H:%M')}" if self.fim else "(Em andamento)"
        return f"Parada Cavidade {self.cavity_config.nome} em {self.inicio.strftime('%d/%m %H:%M')} {status_str}"


class ProductionRateAggregate(models.Model):
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="rate_aggregates",
        verbose_name="Configuração de Cavidade"
    )
    produto = models.CharField(max_length=100, null=True, blank=True, verbose_name="Produto")
    matriz = models.CharField(max_length=100, null=True, blank=True, verbose_name="Matriz")
    inicio_intervalo = models.DateTimeField(verbose_name="Início do Intervalo")
    fim_intervalo = models.DateTimeField(verbose_name="Fim do Intervalo")
    minutos_produzindo = models.PositiveIntegerField(verbose_name="Minutos Produzindo")
    quantidade_produzida = models.PositiveIntegerField(verbose_name="Quantidade Produzida")
    taxa_pneus_hora = models.DecimalField(max_digits=7, decimal_places=2, verbose_name="Taxa (Pneus/Hora)")
    quantidade_amostras = models.PositiveIntegerField(default=1, verbose_name="Quantidade de Amostras")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")

    class Meta:
        verbose_name = "Agregado de Taxa de Produção"
        verbose_name_plural = "Agregados de Taxa de Produção"
        ordering = ["-inicio_intervalo"]
        indexes = [
            models.Index(fields=["cavity_config", "produto", "matriz"]),
            models.Index(fields=["inicio_intervalo"]),
        ]

    def __str__(self):
        return f"{self.cavity_config.nome} ({self.produto or 'S/P'}): {self.taxa_pneus_hora} pneus/h ({self.inicio_intervalo.strftime('%d/%m %H:%M')})"


class ProductionParameterConfig(models.Model):
    nome = models.CharField(max_length=100, verbose_name="Nome do Parâmetro")
    chave = models.CharField(max_length=50, verbose_name="Chave Única")
    xid = models.CharField(max_length=50, verbose_name="XID Scada")
    unidade = models.CharField(max_length=20, default="°C", verbose_name="Unidade de Medida")
    ordem = models.PositiveIntegerField(default=1, verbose_name="Ordem de Exibição")

    machine_config = models.ForeignKey(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="parameter_configs",
        verbose_name="Prensa / Máquina"
    )
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="parameter_configs",
        verbose_name="Cavidade"
    )

    limite_minimo = models.FloatField(null=True, blank=True, verbose_name="Limite Mínimo")
    limite_maximo = models.FloatField(null=True, blank=True, verbose_name="Limite Máximo")
    tolerancia_segundos = models.PositiveIntegerField(default=0, verbose_name="Tolerância (Segundos)")
    histerese = models.FloatField(default=0.0, verbose_name="Histerese de Retorno")
    ativo = models.BooleanField(default=True, verbose_name="Ativo")
    stale_limit_seconds = models.PositiveIntegerField(default=120, verbose_name="Limite Stale (Segundos)")

    class Meta:
        verbose_name = "Configuração de Parâmetro de Processo"
        verbose_name_plural = "Configurações de Parâmetros de Processo"
        ordering = ["ordem", "nome"]

    def __str__(self):
        target = self.cavity_config.nome if self.cavity_config else (self.machine_config.machine.nome if self.machine_config else "Global")
        return f"{self.nome} ({target}) [{self.limite_minimo or '-'} ~ {self.limite_maximo or '-'}{self.unidade}]"


class ProductionParameterAnomalyEvent(models.Model):
    parameter_config = models.ForeignKey(
        ProductionParameterConfig,
        on_delete=models.CASCADE,
        related_name="anomaly_events",
        verbose_name="Parâmetro"
    )
    machine_config = models.ForeignKey(
        ProductionMachineConfig,
        on_delete=models.CASCADE,
        related_name="anomaly_events",
        verbose_name="Máquina"
    )
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="anomaly_events",
        verbose_name="Cavidade"
    )
    inicio = models.DateTimeField(verbose_name="Início da Anomalia")
    inicio_fora_faixa = models.DateTimeField(null=True, blank=True, verbose_name="Início Fora da Faixa")
    fim = models.DateTimeField(null=True, blank=True, verbose_name="Fim da Anomalia")
    duracao_segundos = models.PositiveIntegerField(default=0, verbose_name="Duração (Segundos)")

    menor_valor = models.FloatField(verbose_name="Menor Valor Registrado")
    maior_valor = models.FloatField(verbose_name="Maior Valor Registrado")
    ultimo_valor = models.FloatField(verbose_name="Último Valor Registrado")
    tipo_limite = models.CharField(max_length=10, choices=[("MINIMO", "Mínimo Violado"), ("MAXIMO", "Máximo Violado")], verbose_name="Tipo de Limite")

    produto_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="Produto (Snapshot)")
    matriz_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="Matriz (Snapshot)")
    lote_snapshot = models.CharField(max_length=100, null=True, blank=True, verbose_name="Lote (Snapshot)")
    downtime_event = models.ForeignKey(
        ProductionDowntimeEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="anomaly_events",
        verbose_name="Evento de Parada Relacionado"
    )

    class Meta:
        verbose_name = "Evento de Anomalia de Parâmetro"
        verbose_name_plural = "Eventos de Anomalias de Parâmetros"
        ordering = ["-inicio"]
        indexes = [
            models.Index(fields=["parameter_config", "inicio"]),
            models.Index(fields=["parameter_config", "fim"]),
        ]

    def __str__(self):
        status_str = f"até {self.fim.strftime('%d/%m %H:%M')}" if self.fim else "(Em andamento)"
        return f"Anomalia {self.parameter_config.nome} ({self.tipo_limite}) em {self.inicio.strftime('%d/%m %H:%M')} {status_str}"


# ==============================================================================
# MODELS NÃO GERENCIADOS DO SCADA-LTS (managed=False)

# Roteados exclusivamente para o alias 'scada' (somente leitura).
# Nenhuma migration é gerada para estes modelos.
# ==============================================================================

class ScadaDataPoint(models.Model):
    id = models.AutoField(primary_key=True)
    xid = models.CharField(max_length=50, unique=True)
    data_source_id = models.IntegerField(db_column="dataSourceId")
    point_name = models.CharField(max_length=250, db_column="pointName", null=True, blank=True)
    plc_alarm_level = models.IntegerField(db_column="plcAlarmLevel", null=True, blank=True)

    class Meta:
        managed = False
        db_table = "datapoints"
        verbose_name = "Scada Data Point"
        verbose_name_plural = "Scada Data Points"

    def __str__(self):
        return f"{self.xid} (ID: {self.id})"


class ScadaPointValue(models.Model):
    id = models.BigAutoField(primary_key=True)
    data_point = models.ForeignKey(
        ScadaDataPoint,
        db_column="dataPointId",
        on_delete=models.DO_NOTHING,
        related_name="values"
    )
    data_type = models.IntegerField(db_column="dataType")
    point_value = models.FloatField(db_column="pointValue", null=True, blank=True)
    ts = models.BigIntegerField()

    class Meta:
        managed = False
        db_table = "pointvalues"
        verbose_name = "Scada Point Value"
        verbose_name_plural = "Scada Point Values"
        indexes = [
            models.Index(fields=["data_point", "ts"], name="pointValuesIdx2"),
        ]

    def __str__(self):
        return f"DP {self.data_point_id} @ {self.ts}: {self.point_value}"


class ScadaPointValueAnnotation(models.Model):
    point_value = models.OneToOneField(
        ScadaPointValue,
        db_column="pointValueId",
        primary_key=True,
        on_delete=models.DO_NOTHING,
        related_name="annotation"
    )
    text_point_value_short = models.CharField(
        max_length=128,
        db_column="textPointValueShort",
        null=True,
        blank=True
    )
    text_point_value_long = models.TextField(
        db_column="textPointValueLong",
        null=True,
        blank=True
    )

    class Meta:
        managed = False
        db_table = "pointvalueannotations"
        verbose_name = "Scada Point Value Annotation"
        verbose_name_plural = "Scada Point Value Annotations"

    def __str__(self):
        return self.text_point_value_short or self.text_point_value_long or f"Annotation #{self.point_value_id}"


class ProductionCycle(models.Model):
    CLOSE_REASONS = [
        ("RESET_CONTADOR", "Reset de Contador Scada"),
        ("TROCA_MATRIZ", "Troca de Matriz"),
        ("TROCA_BLADDER", "Troca de Bladder"),
        ("FIM_TURNO", "Fechamento de Turno"),
        ("MANUAL", "Encerramento Manual"),
    ]
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="cycles",
        verbose_name="Cavidade"
    )
    matriz = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Matriz"
    )
    produto = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Produto"
    )
    lote_bladder = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Lote do Bladder"
    )
    started_at = models.DateTimeField(
        verbose_name="Início do Ciclo"
    )
    ended_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Fim do Ciclo"
    )
    initial_counter = models.PositiveIntegerField(
        default=0,
        verbose_name="Contador Inicial"
    )
    final_counter = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Contador Final"
    )
    quantity_produced = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade Produzida no Ciclo"
    )
    close_reason = models.CharField(
        max_length=30,
        choices=CLOSE_REASONS,
        blank=True,
        null=True,
        verbose_name="Motivo do Fechamento"
    )
    last_scada_ts = models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="Último Timestamp Scada (ms)"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ciclo de Produção da Cavidade"
        verbose_name_plural = "Ciclos de Produção de Cavidades"
        ordering = ["-started_at"]

    def __str__(self):
        return f"Ciclo {self.cavity_config.nome} ({self.matriz or 'S/M'}) - {self.started_at.strftime('%d/%m/%Y %H:%M') if self.started_at else ''}"


class ProductionShiftAccumulated(models.Model):
    date = models.DateField(
        verbose_name="Data do Turno"
    )
    shift = models.ForeignKey(
        ProductionShift,
        on_delete=models.CASCADE,
        related_name="accumulated_records",
        verbose_name="Turno"
    )
    cavity_config = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.CASCADE,
        related_name="shift_accumulated",
        verbose_name="Cavidade"
    )
    matriz = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Última Matriz"
    )
    produto = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Último Produto"
    )
    quantity_accumulated = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantidade Acumulada no Turno"
    )
    last_scada_counter = models.PositiveIntegerField(
        default=0,
        verbose_name="Último Contador Lido do Scada"
    )
    last_scada_ts = models.BigIntegerField(
        blank=True,
        null=True,
        verbose_name="Último Timestamp Scada (ms)"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Acúmulo de Produção no Turno"
        verbose_name_plural = "Acúmulos de Produção nos Turnos"
        constraints = [
            models.UniqueConstraint(
                fields=["date", "shift", "cavity_config"],
                name="uniq_prod_shift_accumulated_date_shift_cavity"
            )
        ]

    def __str__(self):
        return f"{self.date} [{self.shift.nome}] {self.cavity_config.nome}: {self.quantity_accumulated} pneus"


class ProductionMatrixCatalog(models.Model):
    codigo_scada = models.PositiveSmallIntegerField(
        unique=True,
        blank=True,
        null=True,
        verbose_name="Código SCADA",
        help_text="Código inteiro único (1 a 43) enviado pelo SCADA."
    )
    nome_scada = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Nome no SCADA"
    )
    nome_exibicao = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="Nome para Exibição"
    )
    codigo = models.CharField(
        max_length=50,
        unique=True,
        verbose_name="Código da Matriz",
        help_text="Código canônico da matriz (ex: 3, 37, M-1024)."
    )
    descricao = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Descrição da Matriz",
        help_text="Descrição detalhada ou especificações."
    )
    produto = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Produto Padronizado",
        help_text="Nome/Código padronizado do pneu/produto."
    )
    aliases_scada = models.TextField(
        blank=True,
        null=True,
        verbose_name="Aliases no Scada",
        help_text="Variações de texto recebidas do Scada separadas por vírgula."
    )
    ativo = models.BooleanField(
        default=True,
        verbose_name="Ativo"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Catálogo de Matriz/Produto"
        verbose_name_plural = "Catálogo de Matrizes e Produtos"
        ordering = ["codigo_scada", "codigo"]

    def __str__(self):
        code_str = f"[{self.codigo_scada}]" if self.codigo_scada else f"{self.codigo}"
        display_name = self.nome_exibicao or self.nome_scada or self.produto or self.descricao or 'Sem descrição'
        return f"{code_str} {display_name}"


class ProductionTarget(models.Model):
    STATUS_CHOICES = [
        ("PLANEJADA", "Planejada"),
        ("AGUARDANDO_INSTALACAO", "Aguardando Instalação"),
        ("EM_PRODUCAO", "Em Produção"),
        ("ATINGIDA", "Atingida"),
        ("CONCLUIDA_PARCIAL", "Concluída Parcial"),
        ("CANCELADA", "Cancelada"),
        ("ATIVO", "Ativo - Legado"),
        ("CONCLUIDO", "Concluído - Legado"),
    ]

    date = models.DateField(
        verbose_name="Data da Meta"
    )
    shift = models.ForeignKey(
        ProductionShift,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="targets",
        verbose_name="Turno"
    )
    matrix_catalog = models.ForeignKey(
        ProductionMatrixCatalog,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="targets",
        verbose_name="Matriz (Catálogo)"
    )
    matriz_codigo = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Código da Matriz",
        help_text="Código da matriz para vínculo da meta."
    )
    produto = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Produto"
    )
    planned_quantity = models.PositiveIntegerField(
        verbose_name="Quantidade Planejada (Meta)"
    )
    priority = models.PositiveSmallIntegerField(
        default=1,
        verbose_name="Prioridade",
        help_text="Ordem de prioridade no plano do turno (1 = Maior prioridade)."
    )
    predicted_machine = models.ForeignKey(
        Machine,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="predicted_targets",
        verbose_name="Máquina Prevista"
    )
    predicted_cavity = models.ForeignKey(
        ProductionCavityConfig,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="predicted_targets",
        verbose_name="Cavidade Prevista"
    )
    observation = models.TextField(
        blank=True,
        null=True,
        verbose_name="Observação / Justificativa"
    )
    change_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name="Motivo da Última Alteração",
        help_text="Justificativa registrada ao alterar meta com turno em andamento."
    )
    status = models.CharField(
        max_length=30,
        choices=STATUS_CHOICES,
        default="PLANEJADA",
        verbose_name="Status da Meta"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="created_production_targets",
        verbose_name="Cadastrado por"
    )
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="updated_production_targets",
        verbose_name="Atualizado por"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Meta de Produção Planejada"
        verbose_name_plural = "Metas de Produção Planejadas"
        ordering = ["-date", "shift__ordem_exibicao", "priority", "matriz_codigo"]

    def __str__(self):
        matrix_name = self.matrix_catalog.nome_exibicao if self.matrix_catalog else (self.matriz_codigo or 'Geral')
        return f"Meta {self.date} [{self.shift.nome if self.shift else 'Geral'}]: {matrix_name} = {self.planned_quantity} pneu(s)"




