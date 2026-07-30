from django.db import models
from django.core.validators import MinValueValidator
from maintenance.models import Machine

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
    xid_producao = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Produção Atual"
    )
    xid_meta = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="XID Meta de Produção"
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

    def __str__(self):
        status_str = f"até {self.fim.strftime('%d/%m %H:%M')}" if self.fim else "(Em andamento)"
        return f"Parada {self.machine_config.machine.nome} em {self.inicio.strftime('%d/%m %H:%M')} {status_str}"


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

