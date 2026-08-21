# 🧠 SPEC — CENTRAL DE CONFIGURAÇÃO SCADA E CADASTRO ORGANIZADO DE XIDs

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/producao/configuracao-scada/` (Visão Geral / Dashboard de XIDs)
  - `/producao/configuracao-scada/maquinas/<int:pk>/` (Configuração Individual de Prensa & Cavidades)
  - `/producao/configuracao-scada/globais/` (Configurações Globais: Parâmetros e Alarmes)
  - `/producao/configuracao-scada/api/testar-xid/` (Endpoint Seguro de Teste Somente-Leitura de XID)
  - `/admin/production/` (Django Admin — mantido como contingência técnica)
- **Contexto(s):** Módulo de Produção Industrial / SCADA-LTS / Gestão de Telemetria e Cadastros.
- **Perfil(s) afetados:** Administrador / Superusuário (`request.user.is_superuser is True`).
- **Predecessoras:** 
  - `SPEC_FUNDACAO_PRODUCAO.md`
  - `SPEC_PRODUCAO_03_CADASTRO_XID_ADMIN.md`
  - `SPEC_PRODUCAO_03A_CORRECAO_ROUTER_TESTES_INTEGRIDADE.md`
  - `SPEC_PRODUCAO_04_INTEGRACAO_SCADA_E_PAINEL.md`
  - `SPEC_PRODUCAO_05C_MOTIVOS_PARADA_CAVIDADES.md`
  - `SPEC_PRODUCAO_06B_ESTADO_E_PARADAS_POR_CAVIDADE.md`
  - `SPEC_PRODUCAO_CORRECAO_SEMANTICA_MATRIZ_E_LOTE_BLADDER.md`
  - `SPEC_BLADDER_01_FUNDACAO_RASTREABILIDADE.md`
  - `SPEC_BLADDER_03_VALIDACAO_SETUP_QUALIDADE.md`

---

## ❗ 2. PROBLEMA ATUAL

1. **Dispersão e Complexidade no Django Admin:** Com o amadurecimento do módulo de Produção (estados de prensas, motivos de parada, matrizes, primeira e segunda parte de lote do bladder, códigos BLA reais, motivos de troca de bladder, parâmetros e alarmes globais), o cadastro e manutenção de XIDs pelo `/admin/` tornou-se fragmentado, confuso e propenso a erros operacionais.
2. **Falta de Visibilidade de Pendências:** Não existe uma tela centralizada que mostre rapidamente quais prensas ou cavidades estão com mapeamento de telemetria incompleto, quais XIDs estão preenchidos e quais possíveis duplicidades ou inconsistências existem.
3. **Impossibilidade de Validação Imediata Sem Risco:** Não há como o superusuário testar se um XID cadastrado existe de fato no Scada-LTS e qual seu valor atual sem consultar logs técnicos do coletor ou executar queries manuais.
4. **Risco de Configuração em Ambiente Não Técnico:** O Django Admin expõe formulários crus, sem agrupamentos funcionais de chão de fábrica (ex: agrupar Bladder / Lote / Matriz / Produção por cavidade).
5. **Necessidade de Manter Fonte Única de Verdade:** A solução deve operar diretamente sobre os modelos já existentes (`ProductionMachineConfig`, `ProductionCavityConfig`, `ProductionGlobalParameter`, `ProductionGlobalAlarm`), sem criar tabelas paralelas, sem migrações adicionais e sem quebrar o coletor ou o isolamento estrito de somente-leitura da base `scada`.

---

## 📋 3. INVENTÁRIO REAL DE XIDs E METADADOS

Auditoria exaustiva de todos os campos locais do módulo `production` associados a telemetria SCADA:

| Modelo | Campo Real | Nome Amigável (pt-br) | Escopo | Obrigatório? | Consumidor Atual | Observações / Regras |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| `ProductionMachineConfig` | `xid_status_prensa` | XID Status da Prensa (Produzindo/Parada) | Máquina | Não (`blank=True, null=True`) | `ProductionStateService`, `collect_production_scada` | Define se a máquina está em ciclo produtivo ou parada. Comparado com `produzindo_value`. |
| `ProductionMachineConfig` | `xid_abertura` | XID Sinal de Abertura | Máquina | Não (`blank=True, null=True`) | `ProductionStateService`, `collect_production_scada` | Identifica transição/abertura de molde para ciclo de vulcanização. |
| `ProductionMachineConfig` | `xid_motivo_parada_geral` | XID Motivo de Parada Geral | Máquina | Não (`blank=True, null=True`) | `ProductionStateService`, `collect_production_scada` | Código numérico de parada global da prensa. |
| `ProductionCavityConfig` | `xid_matriz` | XID Matriz | Cavidade | Não (`blank=True, null=True`) | `ProductionStateService`, `ProductionMatrixCatalog` | Código da matriz/modelo (traduzido pelo catálogo canônico de 43 modelos). |
| `ProductionCavityConfig` | `xid_produto` | XID Prefixo do Lote do Bladder | Cavidade | Não (`blank=True, null=True`) | `compose_bladder_lot`, `ProductionBladderUsage` | Prefixo/1ª parte do lote do bladder (ex: `6154`). Correção semântica da SPEC Bladder. |
| `ProductionCavityConfig` | `xid_lote_bladder` | XID Número do Lote do Bladder | Cavidade | Não (`blank=True, null=True`) | `compose_bladder_lot`, `ProductionBladderUsage` | Número/2ª parte do lote do bladder (ex: `161046`). |
| `ProductionCavityConfig` | `xid_bla_real` | XID BLA Real Instalado | Cavidade | Não (`blank=True, null=True`) | `BladderTrackingService`, `ProductionBladderUsage` | Código BLA normalizado (ex: `BLA003`). Utilizado na validação de setup matriz × bladder. |
| `ProductionCavityConfig` | `xid_producao` | XID Produção Atual | Cavidade | Não (`blank=True, null=True`) | `ProductionStateService`, `ProductionCycle`, `ProductionShiftAccumulated` | Contador acumulativo de passadas/pneus vulcanizados na cavidade. |
| `ProductionCavityConfig` | `xid_meta` | XID Limite de Produção do Bladder (Scada) | Cavidade | Não (`blank=True, null=True`) | `ProductionStateService`, `ProductionCycle` | Limite de vida útil produtiva do bladder parametrizado no Scada. |
| `ProductionCavityConfig` | `xid_motivo_parada` | XID Motivo de Parada da Cavidade | Cavidade | Não (`blank=True, null=True`) | `ProductionStateService`, `ProductionCavityDowntimeEvent` | Código numérico do motivo de parada individual da cavidade. |
| `ProductionCavityConfig` | `xid_motivo_troca_bladder` | XID Motivo da Troca do Bladder | Cavidade | Não (`blank=True, null=True`) | `BladderTrackingService`, `ProductionBladderUsage` | Código numérico (0 a 8) do motivo de substituição do bladder. |
| `ProductionGlobalParameter` | `xid` | XID no Scada-LTS | Global | Não (`blank=True, null=True`) | `ProductionStateService` | Telemetria de utilidades globais (pressão de vácuo, vapor prensas 1-7, vapor 8-12, ar comprimido). |
| `ProductionGlobalAlarm` | `xid` | XID no Scada-LTS | Global | Não (`blank=True, null=True`) | `ProductionStateService` | Alarmes globais industriais (falha de vácuo, falha de ar, alarme de vapor). |
| `ProductionParameterConfig` | `xid` | XID Scada | Parâmetro de Processo | Não (`blank=True, null=True`) | `ProductionParameterAnomalyEvent` | Telemetria contínua com faixa de tolerância (temperatura, pressão interna, etc.). |

> **Nota de Não-Ressuscitação:** Os campos legados `xid_status_cavidade` e `valor_cavidade_produzindo` foram removidos em revisões anteriores e **NÃO** fazem parte desta implementação.

---

## 🎯 4. OBJETIVO

1. **Central Unificada:** Criar uma interface moderna, intuitiva e responsiva em `/producao/configuracao-scada/`, acessível estritamente por superusuários (`request.user.is_superuser is True`).
2. **Visão Geral e Diagnóstico:** Exibir o panorama completo da fábrica (total de XIDs configurados vs esperados, percentual de conclusão por prensa, pendências detalhadas por cavidade e detecção de duplicidades).
3. **Edição Estruturada de Prensas:** Configurar cada prensa e suas cavidades em tela dedicada, com formulários agrupados por contexto operacional (Status/Abertura, Matriz/Lote, Bladder/Rastreabilidade, Produção/Parada), salvamento atômico e tratamento de erros inline.
4. **Gestão de Globais:** Permitir visualizar, cadastrar e editar Parâmetros Globais e Alarmes Globais.
5. **Teste Seguro de Leitura do Scada:** Permitir ao superusuário testar a leitura de qualquer XID em tempo real via endpoint protegido (`POST /producao/configuracao-scada/api/testar-xid/`), reutilizando `ScadaReaderService`, sem qualquer escrita no banco `scada` e sem afetar a máquina de estados do coletor.
6. **Zero Migrations:** Implementar 100% da solução reutilizando os models, constraints e tabelas existentes no banco `default`.

---

## 🧩 5. ESCOPO DA ALTERAÇÃO

### Novos Arquivos:
- `regras_programacao/SPEC_CENTRAL_CONFIGURACAO_SCADA_XIDS.md` (Esta especificação)
- `production/services/xid_configuration.py` (Módulo central de registro, introspecção, auditoria de XIDs e serviços da Central)
- `production/templates/production/xid_config_dashboard.html` (Tela 1: Visão Geral e Diagnóstico de XIDs)
- `production/templates/production/xid_machine_config.html` (Tela 2: Configuração Individual da Máquina e Cavidades)
- `production/templates/production/xid_global_config.html` (Tela 3: Parâmetros e Alarmes Globais)
- `production/test_xid_configuration.py` (Suíte completa de testes unitários e de integração da Central)

### Arquivos a Modificar:
- `production/decorators.py` (Adicionar decorator robusto `@superuser_required`)
- `production/forms.py` (Formulários especializados para `ProductionMachineConfig`, `ProductionCavityConfig`, `ProductionGlobalParameter`, `ProductionGlobalAlarm`)
- `production/views.py` (Views da Central: `xid_config_dashboard`, `xid_machine_config`, `xid_global_config`, `xid_test_api`)
- `production/urls.py` (Registro das novas rotas no namespace `production`)
- `production/templates/production/base_production.html` (Inclusão do menu "Configuração SCADA" condicionado a `user.is_superuser`)
- `Instrucoes.txt` (Documentação formal da entrega)

---

## 🚫 6. FORA DE ESCOPO

- ❌ Nenhuma escrita no banco `scada` (sem `INSERT`, `UPDATE`, `DELETE` ou migrações).
- ❌ Não alterar as regras nem o código do `ScadaRouter`.
- ❌ Não gerar nenhuma migration de banco de dados (`0 migrations`).
- ❌ Não escrever em CLPs, inversores ou equipamentos físicos.
- ❌ Não alterar setpoints ou alterar schemas no Scada-LTS.
- ❌ Não criar novo app Django ou segundo ambiente virtual.
- ❌ Não alterar os históricos industriais ou registros de paradas existentes.
- ❌ Não alterar a rotina de cálculo do PCP ou rastreabilidade de bladders.

---

## 🔐 7. REGRAS OBRIGATÓRIAS (CONSTITUTION & SEGURANÇA)

1. **Ambiente Único:** 1 monolito Django, 1 ambiente virtual `.venv`, sem duplicação de pastas.
2. **Controle Estrito de Acesso:**
   - Apenas superusuários (`is_superuser=True`) podem visualizar ou interagir com a Central.
   - `is_staff=True` isoladamente é rejeitado.
   - Operadores, Líderes de Produção, Técnicos e PCP são rejeitados.
   - Endpoints HTML redirecionam para `production:dashboard` com mensagem de erro amigável.
   - Endpoints de API retornam JSON com status `HTTP 403 Forbidden`.
   - Usuários anônimos são redirecionados para a tela de login (`/accounts/login/`).
3. **Isolamento de Banco de Dados:**
   - Todas as alterações de configuração são salvas no banco `default`.
   - O alias `scada` é tratado como estritamente somente-leitura.
4. **Transacionalidade Atômica:** O salvamento de uma máquina e todas as suas cavidades ocorre dentro de `transaction.atomic(using='default')`. Erros em uma cavidade abortam o salvamento integral para evitar dados parciais.
5. **Resiliência a Falhas do Scada:** Se o Scada-LTS estiver indisponível ou offline, a tela de configuração continua 100% funcional para salvar no banco `default`, e o botão de teste de XID exibe uma mensagem amigável sem lançar erro 500.

---

## 🏗️ 8. ARQUITETURA PROPOSTA

### 8.1. Registro Central de Metadados (`production/services/xid_configuration.py`)

Para evitar dispersão de regras e permitir expansões futuras sem retrabalho em templates, criamos um registro central `XIDRegistry`:

```python
class XIDRegistry:
    """
    Componente central de introspecção, agrupamento e metadados de XIDs.
    Fornece as definições de campos, labels amigáveis, categorias operacionais
    e regras de validação para as telas da Central.
    """
    
    @classmethod
    def get_machine_xid_fields(cls) -> List[Dict[str, Any]]: ...
    
    @classmethod
    def get_cavity_xid_fields(cls) -> List[Dict[str, Any]]: ...
    
    @classmethod
    def get_all_registered_xid_fields(cls) -> Dict[str, List[str]]: ...
    
    @classmethod
    def analyze_system_xids(cls) -> Dict[str, Any]:
        """Calcula total esperado, preenchido, pendente, percentuais e duplicidades."""
        ...
```

### 8.2. Metateste de Integridade do Inventário

Um teste automatizado verificará programaticamente todos os campos do Django ORM dos models de configuração que contenham o prefixo `xid_` ou nome `xid`, garantindo que qualquer campo novo adicionado no futuro seja obrigatoriamente registrado na Central.

---

## ⚙️ 9. REGRAS DE NEGÓCIO E VALIDAÇÕES

### 9.1. Normalização de Strings
- Aplicar `.strip()` nos valores de XID antes de validar ou salvar.
- Preservar rigorosamente maiúsculas, minúsculas, números e caracteres especiais (ex: `DP_PR01_C1_MATRIZ`).
- Não converter códigos alfa em inteiros nem remover zeros à esquerda.

### 9.2. Duplicidades
- A Central inspeciona todos os XIDs cadastrados no sistema.
- Se o mesmo XID for reutilizado em mais de um campo, a interface exibe um badge de alerta `Possível duplicidade (N ocorrências)`.
- O salvamento é permitido com aviso (já que alguns compartilhamentos técnicos podem ser intencionais).

### 9.3. Auto-criação Segura de Configurações
- Se uma `Machine` da fábrica ainda não possui registro em `ProductionMachineConfig`, a Central exibe a máquina como "Pendente de Configuração Inicial" e permite criá-la com defaults seguros (`stale_limit_seconds=120`, `produzindo_value='1'`).
- Permite adicionar ou sincronizar a quantidade de cavidades com base na ordem física (1..N).

### 9.4. Invalidação Segura de Cache
- Ao salvar novas configurações de XID, a view invoca `scada_reader.clear_caches()` para limpar os mapeamentos de memória em `ScadaReaderService`.
- Nenhum processo em background é reiniciado de forma forçada.

---

## 🎨 10. DESENHO DAS TELAS

### 10.1. Tela 1 — Visão Geral da Central (`/producao/configuracao-scada/`)

```text
+--------------------------------------------------------------------------------------------------+
| [PRODUÇÃO & PCP]  CENTRAL DE CONFIGURAÇÃO SCADA / XIDs                           [Superusuário]  |
| Gerenciamento e auditoria de pontos de telemetria integrados ao Scada-LTS                        |
+--------------------------------------------------------------------------------------------------+
|  [ TOTAL ESPERADO: 142 ]   [ PREENCHIDOS: 128 (90%) ]   [ PENDENTES: 14 ]   [ DUPLICIDADES: 2 ]  |
+--------------------------------------------------------------------------------------------------+
|  Filtros: (•) Todas as Prensas  ( ) Incompletas  ( ) Completas  ( ) Com Alertas   [ Busca: ____ ]|
+--------------------------------------------------------------------------------------------------+
|  PRENSA 01 (Vulcanização) — 2 Cavidades                                                          |
|  Progresso: [████████████████████░░░░] 85% (12 de 14 XIDs configurados)                          |
|  Pendências:                                                                                     |
|    - Cavidade 2: XID BLA Real Instalado                                                          |
|    - Cavidade 2: XID Motivo da Troca do Bladder                                                  |
|  [⚙️ Configurar Prensa]                                                                          |
+--------------------------------------------------------------------------------------------------+
|  PRENSA 02 (Vulcanização) — 2 Cavidades                                                          |
|  Progresso: [████████████████████████] 100% (14 de 14 XIDs configurados)                         |
|  [⚙️ Configurar Prensa]                                                                          |
+--------------------------------------------------------------------------------------------------+
|  PARÂMETROS & ALARMES GLOBAIS                                                                    |
|  4 Parâmetros Globais cadastrados | 3 Alarmes Globais cadastrados                                |
|  [⚙️ Gerenciar Globais]                                                                          |
+--------------------------------------------------------------------------------------------------+
```

### 10.2. Tela 2 — Configuração Individual da Máquina (`/producao/configuracao-scada/maquinas/<id>/`)

```text
+--------------------------------------------------------------------------------------------------+
| ← Voltar para a Central | Configuração SCADA: PRENSA 01 (Setor: Vulcanização)                    |
+--------------------------------------------------------------------------------------------------+
| ⚙️ CONFIGURAÇÃO GERAL DA PRENSA                                                                  |
| - Ordem de Exibição: [ 1 ]        - Limite Stale (segundos): [ 120 ]                             |
| - Valor que Indica Produzindo: [ 1 ]                                                             |
| - XID Status da Prensa:        [ DP_PR01_STATUS       ] [🔍 Testar] -> [ ✓ OK: 1 (Produzindo) ]  |
| - XID Sinal de Abertura:       [ DP_PR01_ABERTURA     ] [🔍 Testar] -> [ ✓ OK: 0 ]               |
| - XID Motivo de Parada Geral:  [ DP_PR01_MOTIVO_GERAL ] [🔍 Testar] -> [ ✓ OK: 0 (Normal) ]      |
+--------------------------------------------------------------------------------------------------+
| 📦 CAVIDADE 1 (Ordem: 1)                                                                         |
| ┌──────────────────────────────────────────────────────────────────────────────────────────────┐ |
| │ [Parada e Produção]                                                                          │ |
| │ - XID Produção Atual:         [ DP_PR01_C1_PROD       ] [🔍 Testar] -> [ ✓ 142 pneus ]       │ |
| │ - XID Motivo de Parada:       [ DP_PR01_C1_MOTIVO     ] [🔍 Testar] -> [ ✓ 0 (Normal) ]      │ |
| │ [Matriz e Lote do Bladder]                                                                   │ |
| │ - XID Matriz:                 [ DP_PR01_C1_MATRIZ     ] [🔍 Testar] -> [ ✓ 3 (PNEU HOPPER) ] │ |
| │ - XID Prefixo Lote Bladder:   [ DP_PR01_C1_LOTE_PREF  ] [🔍 Testar] -> [ ✓ 6154 ]            │ |
| │ - XID Número Lote Bladder:    [ DP_PR01_C1_LOTE_NUM   ] [🔍 Testar] -> [ ✓ 161046 ]          │ |
| │ [Rastreabilidade do Bladder]                                                                 │ |
| │ - XID BLA Real Instalado:     [ DP_PR01_C1_BLA_REAL   ] [🔍 Testar] -> [ ✓ BLA003 ]          │ |
| │ - XID Limite de Vida Bladder: [ DP_PR01_C1_BLA_META   ] [🔍 Testar] -> [ ✓ 450 ]             │ |
| │ - XID Motivo Troca Bladder:   [ DP_PR01_C1_BLA_MOTIVO ] [🔍 Testar] -> [ ✓ 0 ]               │ |
| └──────────────────────────────────────────────────────────────────────────────────────────────┘ |
| 📦 CAVIDADE 2 (Ordem: 2) ...                                                                     |
+--------------------------------------------------------------------------------------------------+
| [ 💾 Salvar Alterações ]   [ 💾 Salvar e Voltar ]   [ 💾 Salvar e Próxima Máquina ]             |
+--------------------------------------------------------------------------------------------------+
```

### 10.3. Tela 3 — Configurações Globais (`/producao/configuracao-scada/globais/`)

```text
+--------------------------------------------------------------------------------------------------+
| ← Voltar para a Central | Configurações Globais SCADA                                            |
+--------------------------------------------------------------------------------------------------+
| [ Abas: (•) Parâmetros Globais  ( ) Alarmes Globais ]                                            |
|                                                                                                  |
| PARÂMETROS GLOBAIS DE PROCESSO:                                            [ + Novo Parâmetro ]  |
| +---------------------+-----------------+----------+-------------------+-------------+---------+ |
| | Nome                | Chave Única     | Unidade  | XID Scada-LTS     | Teste Leitura| Ações   | |
| +---------------------+-----------------+----------+-------------------+-------------+---------+ |
| | Pressão de Vácuo    | pressao_vacuo   | mmHg     | DP_VACUO_GERAL    | [🔍 Testar] | [Editar]| |
| | Vapor Prensas 1 a 7 | vapor_1_7       | bar      | DP_VAPOR_P1_P7    | [🔍 Testar] | [Editar]| |
| | Vapor Prensas 8 a 12| vapor_8_12      | bar      | DP_VAPOR_P8_P12   | [🔍 Testar] | [Editar]| |
| | Ar Comprimido       | pressao_ar      | bar      | DP_AR_COMPRIMIDO  | [🔍 Testar] | [Editar]| |
| +---------------------+-----------------+----------+-------------------+-------------+---------+ |
+--------------------------------------------------------------------------------------------------+
```

### 10.4. Modal / Tooltip de Teste de XID (Interativo)

```text
+-----------------------------------------------------------+
| 🔍 Resultado do Teste Scada-LTS: DP_PR01_C1_MATRIZ       |
+-----------------------------------------------------------+
| Status:  ✓ Localizado no Scada-LTS                        |
| ID:      1042                                             |
| Tipo:    Multistate (2)                                   |
| Valor:   3 (Normalizado: '3')                             |
| Leitura: 21/08/2026 09:45:12 (Atualizado)                 |
| Significado: PNEUS HOPPER 90/90-18                        |
+-----------------------------------------------------------+
```

---

## 🧪 11. CRITÉRIOS DE ACEITAÇÃO

- [ ] SPEC detalhada aprovada antes da escrita de código.
- [ ] 100% dos campos de XID mapeados no inventário e gerenciáveis pela Central.
- [ ] Central acessível exclusivamente por `request.user.is_superuser is True`.
- [ ] Usuários sem privilégio de superusuário são bloqueados com HTTP 403 (API) ou redirecionamento amigável (HTML).
- [ ] Link "Configuração SCADA" na navbar de `base_production.html` visível somente para superusuários.
- [ ] Edição de prensa e múltiplas cavidades salva com transação atômica (`transaction.atomic`).
- [ ] Teste individual de leitura de XID funciona sem lançar exceções 500 mesmo se o Scada estiver offline.
- [ ] Nenhuma escrita é enviada para a conexão `scada`.
- [ ] `makemigrations --check --dry-run` confirma **0 novas migrations**.
- [ ] Metateste de inventário garante que futuros campos `xid_*` precisem ser registrados.
- [ ] Todos os 254+ testes existentes do projeto permanecem verdes.
- [ ] `Instrucoes.txt` atualizado com registro formal da implementação.

---

## ⚠️ 12. RISCOS E MITIGAÇÕES

| Risco | Probabilidade | Impacto | Mitigação Arquitetural |
| :--- | :---: | :---: | :--- |
| **Escrita Acidental no Scada** | Baixa | Crítico | `ScadaRouter` proíbe escrita via ORM; `ScadaReaderService` executa apenas consultas `using('scada')`; testes automatizados validam tentativa de escrita. |
| **Salvamento Parcial de Cavidades** | Média | Médio | Envolver o POST de máquina + formset de cavidades em bloco `transaction.atomic(using='default')`. |
| **Timeout ou Queda do Scada-LTS** | Média | Baixo | Tratamento de exceções em `ScadaReaderService` com retorno gracioso de erro amigável ao frontend sem quebrar requisições. |
| **Quebra de Caches no Coletor** | Baixa | Baixo | Invalidação cirúrgica de caches via `scada_reader.clear_caches()` sem reinicialização abrupta de processos. |

---

## 🔍 13. PLANO DE IMPLEMENTAÇÃO

### Subagente 1: Arquiteto
- Auditoria integral de código, banco, routers e inventário de XIDs.
- Elaboração e consolidação desta SPEC.
- Definição da arquitetura e contratos de serviços e forms.

### Subagente 2: Backend
1. **Segurança:** Criar decorator `@superuser_required` em `production/decorators.py`.
2. **Serviço Central:** Criar `production/services/xid_configuration.py` contendo `XIDRegistry` e helpers de diagnóstico.
3. **Forms:** Criar formulários e formsets customizados em `production/forms.py` com validações de unicidade e `.strip()`.
4. **Views e Rotas:** Implementar `xid_config_dashboard`, `xid_machine_config`, `xid_global_config` e `xid_test_api` em `production/views.py` e mapear em `production/urls.py`.
5. **Templates:** Criar `xid_config_dashboard.html`, `xid_machine_config.html` e `xid_global_config.html` herdando de `base_production.html`.
6. **Navegação:** Adicionar link de navegação na sidebar de `base_production.html`.
7. **Testes Automatizados:** Implementar `production/test_xid_configuration.py` cobrindo todas as telas, permissões, APIs, atomicidade e inventário.

### Subagente 3: QA
- Executar `manage.py check`, `makemigrations --check --dry-run` e suíte completa de testes (`production` + `maintenance`).
- Validar conformidade estrita com a `constitution.md`.
- Atualizar documentação em `Instrucoes.txt`.

---

## 🧪 14. TESTES AUTOMATIZADOS OBRIGATÓRIOS

1. **Permissões de Acesso (Matriz de 8 Perfis):**
   - Anônimo -> Redireciona para Login
   - Técnico -> 403 / Redireciona com Erro
   - Técnico Líder -> 403 / Redireciona com Erro
   - Operador -> 403 / Redireciona com Erro
   - Líder de Produção -> 403 / Redireciona com Erro
   - PCP -> 403 / Redireciona com Erro
   - Staff não-superuser (`is_staff=True, is_superuser=False`) -> 403 / Redireciona com Erro
   - Superuser (`is_superuser=True`) -> 200 OK
2. **Dashboard de Diagnóstico:**
   - Contagem correta de total esperado, preenchido e pendente.
   - Detecção de duplicidades intencionais/acidentais.
3. **Configuração de Máquinas e Cavidades:**
   - Edição de campos de máquina e cavidades simultâneas.
   - Rollback total em caso de validação inválida em qualquer cavidade.
   - Criação automática de `ProductionMachineConfig` se inexistente.
4. **API de Teste de XID:**
   - XID existente com valor numérico, multistate, binário e textual.
   - XID inexistente.
   - Timeout / Falha de comunicação simulada.
   - Garantia de que a API é somente-leitura.
5. **Metateste de Inventário Completo:**
   - Introspecção nos models de configuração local garantindo que 100% dos campos `xid_*` e `xid` estejam presentes no `XIDRegistry`.

---

## 🧪 15. TESTES MANUAIS

1. Logar como superusuário (`admin`).
2. Acessar menu "Configuração SCADA" na sidebar.
3. Verificar indicadores de progresso das prensas.
4. Abrir configuração da Prensa 01.
5. Testar leitura do XID de status e matriz.
6. Alterar um XID e salvar com sucesso.
7. Simular inserção de dados inválidos e confirmar que não houve salvamento parcial.
8. Acessar Parâmetros Globais e editar um item.
9. Deslogar e tentar acessar `/producao/configuracao-scada/` com usuário comum (verificar bloqueio).

---

## 🔄 16. PLANO DE ROLLBACK

Caso seja necessário reverter a implementação:
1. Nenhuma migration foi executada no banco, portanto nenhum comando `migrate` reverso é necessário.
2. Reverter os arquivos modificados via Git.
3. Os registros existentes em `ProductionMachineConfig` e `ProductionCavityConfig` permanecem 100% íntegros.

---

## 📂 17. EVIDÊNCIAS FINAIS OBRIGATÓRIAS

Ao término, o agente deve fornecer:
1. Lista completa de arquivos lidos, criados e alterados.
2. Relatório de rotas criadas com URLs, métodos e permissões.
3. Saída de `manage.py check`.
4. Saída de `makemigrations --check --dry-run`.
5. Saída da execução da suíte de testes completa.
6. Atualização formal do arquivo `Instrucoes.txt`.
