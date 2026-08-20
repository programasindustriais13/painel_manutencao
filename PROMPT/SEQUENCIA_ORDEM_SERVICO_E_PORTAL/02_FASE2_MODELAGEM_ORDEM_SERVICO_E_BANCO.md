# PROMPT — FASE 2: MODELAGEM DE DADOS DA ORDEM DE SERVIÇO & MIGRAÇÕES

## 📌 Contexto & Objetivo
Para suportar o fluxo completo de Ordens de Serviço (OSs) físicas digitalizadas, prevenção de duplicidade, rastreabilidade de fotos e suporte a múltiplos técnicos na mesma intervenção, precisamos estruturar o modelo de dados `OrdemServico` e conectá-lo ao modelo `Allocation` existente.

Nesta Fase 2, vamos implementar:
1. **Novo Modelo `OrdemServico` em `maintenance/models.py`.**
2. **Atualização do Modelo `Allocation` com chave estrangeira para `OrdemServico`.**
3. **Geração e aplicação segura de migrações aditivas (100% compatíveis com SQLite e MySQL).**
4. **Registro e configuração no Django Admin com visualização completa, filtros e inlines.**

---

## 🔒 Regras da Constituição a Seguir
- Não perder ou quebrar dados existentes na tabela `Allocation`.
- Novos campos adicionados a modelos existentes devem ser obrigatoriamente opcionais (`null=True, blank=True`) ou possuir `default`.
- Compatibilidade estrita entre SQLite e MySQL usando ORM padrão Django.
- Registrar resumo das alterações em `Instrucoes.txt`.

---

## 🛠️ Especificações Técnicas Detalhadas

### 1. Novo Modelo `OrdemServico` (`maintenance/models.py`)

```python
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
        ('PREDITIVA', 'Preditiva'),
        ('MELHORIA', 'Melhoria / Instalação'),
        ('OUTRO', 'Outro'),
    ]

    CRITICIDADE_CHOICES = [
        ('BAIXA', 'Baixa (Normal)'),
        ('MEDIA', 'Média'),
        ('ALTA', 'Alta (Urgente / Parada de Máquina)'),
    ]

    numero_os = models.CharField(
        max_length=50, 
        unique=True, 
        verbose_name="Número da OS Física",
        help_text="Número impresso na folha física. Deve ser único para evitar duplicidades."
    )
    maquina = models.ForeignKey(
        'Machine', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name="ordens_servico", 
        verbose_name="Máquina"
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
        verbose_name="Solicitante / Líder de Produção"
    )
    tipo_manutencao = models.CharField(
        max_length=20, 
        choices=TIPO_MANUTENCAO_CHOICES, 
        default='CORRETIVA', 
        verbose_name="Tipo de Manutenção"
    )
    criticidade = models.CharField(
        max_length=15, 
        choices=CRITICIDADE_CHOICES, 
        default='MEDIA', 
        verbose_name="Criticidade"
    )
    descricao_falha = models.TextField(
        verbose_name="Descrição do Defeito / Solicitação"
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='PENDENTE', 
        verbose_name="Status da OS"
    )
    
    # Fotos Obrigatórias
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
    
    # Responsabilidade e Atribuição
    criado_por = models.ForeignKey(
        'auth.User', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='os_abertas',
        verbose_name="Usuário que Cadastrou"
    )
    tecnico_designado = models.ForeignKey(
        'Technician', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='os_designadas', 
        verbose_name="Técnico Designado (Opcional)"
    )

    # Auditoria e Prazos
    data_abertura = models.DateTimeField(
        default=timezone.now, 
        verbose_name="Data/Hora de Abertura"
    )
    data_conclusao = models.DateTimeField(
        null=True, 
        blank=True, 
        verbose_name="Data/Hora de Conclusão"
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
```

### 2. Atualização do Modelo `Allocation` (`maintenance/models.py`)
Adicionar o campo de relacionamento:
```python
    ordem_servico = models.ForeignKey(
        'OrdemServico',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='allocations',
        verbose_name="Ordem de Serviço Vinculada"
    )
```

### 3. Propriedades e Métodos no Modelo `OrdemServico`
- `tecnicos_envolvidos`: Retorna lista única de técnicos que trabalharam nas alocações ligadas a esta OS.
- `tempo_total_intervencao`: Calcula o tempo total acumulado de homem-hora e tempo líquido de máquina parada.
- `pode_ser_iniciada`: Retorna `True` se o status for `PENDENTE` ou `EM_ANDAMENTO`.

### 4. Configuração no Django Admin (`maintenance/admin.py`)
- Adicionar `AllocationInline` dentro de `OrdemServicoAdmin`.
- Filtros por `status`, `tipo_manutencao`, `criticidade`, `setor`, `data_abertura`.
- Busca (`search_fields`) por `numero_os`, `solicitante`, `descricao_falha`, `maquina__nome`.
- Exibição de miniaturas das fotos de abertura e conclusão quando presentes.

---

## 🧪 Critérios de Aceite e Validação
1. Execução de `python manage.py makemigrations` e `python manage.py migrate` sem conflitos ou erros.
2. Todas as alocações históricas pré-existentes continuam intactas no banco (`ordem_servico` fica `NULL` para elas).
3. Teste de criação manual de uma `OrdemServico` no Django Admin:
   - Cadastrar OS com número `OS-1001`.
   - Tentar cadastrar outra OS com o mesmo número `OS-1001` -> O banco e o form devem barrar por unicidade (`IntegrityError`/ValidationError).
4. Vincular 2 alocações de técnicos diferentes à mesma OS e verificar se a relação funciona perfeitamente.
5. Atualização registrada em `Instrucoes.txt`.
