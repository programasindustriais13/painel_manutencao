# 🧠 SPEC — IMPORTAÇÃO E PRÉ-CADASTRO EM LOTE DE MATRIZES FÍSICAS (REVISADA)

---

## 📌 1. CONTEXTO

- **Módulo:** Matrizaria Industrial (`matrizaria`) e Catálogo de Produção (`production`).
- **Arquivos/Fontes de Dados:**
  - Planilha Excel de levantamento físico: `C:\Users\Unicompo\Documents\03_PYTHON1\07 - Manutencao_estudo\MATRIZES_PRE_CADASTRO_LOTE.xlsx`.
  - Anotações manuscritas digitalizadas: `Lista_mariz_pg1.jpeg` e `Lista_mariz_pg2.jpeg`.
  - Planilha de Reconciliação Gerada: `C:\Users\Unicompo\Documents\03_PYTHON1\07 - Manutencao_estudo\relatorio_reconciliacao_inventario.xlsx`.
- **Contextos de Uso:**
  - Terminal operacional via Django Management Command (`importar_matrizes_fisicas`).
  - Django Admin (`/admin/matrizaria/matrizfisica/` e `/admin/matrizaria/loteimportacaomatrizfisica/`).
  - Formulários operacionais de serviços de matrizaria (`SolicitacaoServicoForm`, `FinalizarExecucaoForm`).
- **Perfis Afetados:** Líderes de Produção, Matrizeiros, Gestão da Fábrica e Administradores do Sistema.

---

## ❗ 2. PROBLEMA E DIRETRIZES DA REVISÃO PONTUAL

1. **Separação das Dimensões de Decisão:**
   Uma correspondência única no catálogo não pode ser confundida com confirmação física ou conferência da anotação da folha. Devem ser separadas em:
   - `status_cat`: Correspondência no catálogo (`UNICA`, `AMBIGUA`, `AUSENTE`, `ID_INCOMPATIVEL`).
   - `status_fonte`: Conferência da anotação da folha (`CONFERIDO`, `PENDENTE_CONFERENCIA`).
   - `aprovado`: Autorização formal para importação.
2. **Caso Concreto P2-23 (HOPPER 4.80/400-8):**
   A medida proposta `4.80/4.00-8` tem correspondência única no catálogo (código SCADA 15), porém a coluna de revisão da leitura registra `CONFERIR MEDIDA`. Não pode ser tratada como aprovável automaticamente.
3. **Bloqueio de Linhas Ambíguas (18 linhas / 36 unidades):**
   Modelos que possuem versões com câmara e Sem Câmara (`S/C`) permanecem bloqueados até confirmação negocial se a matriz física é compartilhada ou distinta.
4. **Modelos Ausentes (17 linhas / 17 unidades):**
   Proposta técnica de cadastro em lote em `ProductionMatrixCatalog` sem inventar códigos SCADA (`codigo_scada=None`, `codigo="INT-MOD-MED"`), alinhada com as rotinas de produção.
5. **Idempotência Independente de Hash SHA-256:**
   Planilhas regravadas pelo Excel, arquivos renomeados ou cargas parciais não podem duplicar unidades nem perder integridade; quantidade declarada significa total inventariado, e qualquer alteração de quantidade após uma carga exige reconciliação humana explícita.
6. **Preservação de Integridade Operacional:**
   Unidades indistinguíveis não recebem número físico inventado nem induzem seleção aleatória; o histórico anterior é preservado por snapshots imutáveis em `SolicitacaoServicoMatrizaria`.

---

## 🎯 3. OBJETIVO

1. Executar simulação estrita (dry-run) recalculando o conjunto realmente elegível para `--aprovar-linhas-seguras`: **13 linhas e 18 unidades** (em vez de 17 linhas/25 unidades).
2. Manter bloqueadas as 4 linhas com pendência de leitura/normalização (`P2-23`, `P2-12`, `P2-13`, `P2-14`), as 18 linhas ambíguas e os 17 modelos ausentes.
3. Gerar a planilha de reconciliação em duas abas (`Reconciliacao_Inventario` e `Proposta_Novos_Modelos`) sem modificar o arquivo original.
4. Expandir a suíte de testes com 7 novos cenários obrigatórios (totalizando 19 testes específicos do importador e 38 no app `matrizaria`).
5. Garantir que **zero** matrizes físicas reais sejam gravadas nesta rodada (`MatrizFisica.objects.count() == 0`).

---

## ⚙️ 4. REGRAS DE NEGÓCIO E ARQUITETURA

### 4.1. As Três Dimensões Independentes
- **Catálogo (`status_cat`):**
  - `UNICA`: Um único registro canônico corresponde ao modelo e medida.
  - `AMBIGUA`: Duas ou mais variantes S/C encontradas.
  - `AUSENTE`: Modelo inexistente no catálogo de 55 códigos SCADA.
  - `ID_INCOMPATIVEL`: O `id_catalogo` fornecido manualmente na planilha não corresponde ao modelo/medida da linha.
  - `INCONSISTENTE_MATEMATICA`: A soma das parcelas de dote diverge do total.
- **Fonte (`status_fonte`):**
  - `CONFERIDO`: Anotação manuscrita direta, sem rasura, sem "CONFERIR", sem dote não informado e sem normalização pendente.
  - `PENDENTE_CONFERENCIA`: Apresenta anotações como "CONFERIR MEDIDA", rasuras com quantidade a confirmar, dote não informado ou normalização pendente (ex: `P2-23`, `P2-12/13/14`).
- **Autorização (`aprovado`):**
  - Sob `--aprovar-linhas-seguras`: apenas linhas `status_cat == "UNICA"` **E** `status_fonte == "CONFERIDO"` tornam-se elegíveis.
  - Aprovação manual na planilha: exige que a pendência não seja impeditiva (ex: aceita dote não informado, mas não aceita erro de catálogo ou leitura inconclusiva).

### 4.2. Cenários A e B para Variantes (Com Câmara vs Sem Câmara)
As 18 linhas ambíguas dependem de alinhamento com a Engenharia/Produção:
- **Cenário A (Ferramental Compartilhado):** A mesma matriz física atende tanto o pneu com câmara quanto o pneu S/C (ex: molde com perfil comum ou inserto intercambiável).
  - *Ajuste Mínimo:* Vincular a matriz ao modelo base no catálogo e associar a variante S/C como compatível, sem duplicar o exemplar físico.
- **Cenário B (Ferramental Distinto):** Existem matrizes físicas distintas na fábrica para pneus com câmara e pneus S/C.
  - *Ajuste Mínimo:* O usuário deve distribuir a quantidade total no inventário informando quantas unidades físicas pertencem ao código normal e quantas ao código S/C (preenchendo a coluna `ID no catálogo`).

### 4.3. Cadastro de Modelos Ausentes sem Telemetria SCADA
- O modelo `ProductionMatrixCatalog` foi auditado e comprovadamente permite:
  - `codigo_scada = None` (`null=True, blank=True`).
  - `codigo` alfanumérico único obrigatório: padrão proposto `INT-{MODELO}-{MEDIDA}` (ex: `INT-RIVER-909018`).
  - As rotinas de PCP, apontamento e templates usam `codigo_scada|default:codigo` e fallback textual limpo.
  - Proposta de 17 modelos ausentes estruturada na aba `Proposta_Novos_Modelos` da planilha de reconciliação.

### 4.4. Uso Operacional e Rastreabilidade (`exige_matriz_fisica`)
- `MatrizFisica` armazena:
  - `possui_dote`: `SIM`, `NAO`, `NAO_INFORMADO`.
  - `numero_fisico_confirmado`: `None` até confirmação em campo.
  - `situacao_identificacao`: `PENDENTE` por padrão para carga em lote.
  - `rotulo_completo`: exibe `[ID Física Pendente - Com Dote]` ou `[ID Física Pendente - Sem Dote]`.
- As ordens de serviço (`SolicitacaoServicoMatrizaria` e `CicloExecucaoServicoMatrizaria`) gravam `matriz_identificador_snapshot` imutável. Uma confirmação futura da peça não adultera o histórico retroativo de chamados anteriores.
- Unidades indistinguíveis sem numeração física não devem ser atribuídas aleatoriamente para simular histórico individual. A regra `exige_matriz_fisica` deve ser cumprida mediante decisão operacional documentada.

### 4.5. Idempotência e Prevenção de Duplicações
- A prevenção de duplicações é ancorada na chave de rastreabilidade única `chave_unidade_origem` (ex: `P1-22-U01`) e na tupla canônica `(modelo, numero_sequencial)`.
- Arquivos com nomes diferentes ou regravados pelo Excel preservam as unidades já cadastradas sem duplicá-las.
- Cargas parciais (`--linhas`) aplicam estritamente o subconjunto solicitado sem afetar as demais.
- Caso uma linha já importada sofra alteração de quantidade em planilha posterior, o sistema bloqueia a execução por divergência cadastral.
- Erros de gravação disparam rollback integral via `transaction.atomic()`.

---

## 📊 5. RESULTADO REVISADO DA SIMULAÇÃO

- **Total de Linhas Lidas:** 52  |  **Unidades Totais:** 78
- **Correspondência Única no Catálogo:** 17 linhas (25 unidades)
  - **Fonte 100% Conferida (Linhas Seguras Elegíveis):** **13 linhas (18 unidades)**
    - `P1-22` (HOPPER 4.10-18, 1 un)
    - `P1-23` (HOPPER 120/80-18, 1 un)
    - `P1-24` (READY 110/90-18, 1 un)
    - `P1-26` (HOPPER 90/90-19, 1 un)
    - `P1-27` (RIVER 24x10-11, 1 un)
    - `P1-28` (RIVER 24x8-12, 1 un)
    - `P2-05` (HOPPER 80/100-14, 3 un)
    - `P2-06` (WINGS 80/100-14, 2 un - misto: 1 com dote, 1 sem)
    - `P2-11` (READY 110/80-14, 1 un)
    - `P2-15` (WINGS 60/100-17, 1 un)
    - `P2-20` (HOPPER 110/90-17, 3 un)
    - `P2-21` (HOPPER 90/90-21, 1 un)
    - `P2-22` (WINTER 90/90-21, 1 un)
  - **Fonte com Pendência de Leitura (Bloqueadas):** **4 linhas (7 unidades)**
    - `P2-23` (HOPPER 4.80/400-8, 1 un - Revisão da leitura indica `CONFERIR MEDIDA`)
    - `P2-12` (HOPPER 2/75-17, 1 un - Notação com barra a confirmar)
    - `P2-13` (READY 2/75-17, 2 un - Notação com barra a confirmar)
    - `P2-14` (HOPPER 2/50-17, 3 un - Notação com barra a confirmar)
- **Correspondência Ambígua (Variantes S/C - Bloqueadas):** **18 linhas (36 unidades)**
- **Ausentes no Catálogo SCADA (Bloqueadas):** **17 linhas (17 unidades)**
- **Inconsistências Matemáticas:** 0 linhas
- **Aprovadas no Escopo com `--aprovar-linhas-seguras`:** **13 linhas (18 unidades)**
- **Registros Gravados no Banco Real:** **0 (zero)**

---

## 🧪 6. COBERTURA DE TESTES

A suíte automatizada `matrizaria.test_importacao_matrizes` contém 19 testes em banco de testes isolado:
1. `test_01_expansao_quantidade_unidades_individuais`
2. `test_02_grupo_todo_com_dote`
3. `test_03_grupo_todo_sem_dote`
4. `test_04_grupo_misto_wings_80100_14`
5. `test_05_dote_nao_informado`
6. `test_06_preservacao_numeros_fisicos_vazios`
7. `test_07_variantes_ambiguas_permanecem_bloqueadas`
8. `test_08_quantidades_invalidas_e_soma_inconsistente`
9. `test_09_simulacao_sem_gravacao`
10. `test_10_reexecucao_sem_duplicacao_idempotencia`
11. `test_11_conflito_com_cadastro_existente`
12. `test_12_auditoria_de_lote_gravada`
13. `test_13_correspondencia_unica_com_fonte_pendente_continua_bloqueada` (P2-23 bloqueado mesmo com `--aprovar-linhas-seguras`)
14. `test_14_escolha_explicita_id_incompativel_recusada` (ID incompatível rejeitado)
15. `test_15_arquivo_regravado_preserva_unidades_sem_duplicar` (Arquivo regravado não duplica unidades)
16. `test_16_carga_parcial_seguida_das_linhas_restantes` (Carga parcial e posterior conclusão)
17. `test_17_mudanca_quantidade_apos_carga_exige_reconciliacao` (Alteração de quantidade após carga bloqueada)
18. `test_18_falha_durante_aplicacao_provoca_rollback_do_lote` (Rollback integral em caso de falha)
19. `test_19_identificacao_fisica_nao_confirmada_automaticamente` (Identificação física permanece pendente)

**Resultado:** 19/19 testes de importação aprovados (100%).
**Resultado Geral da Matrizaria:** 38/38 testes aprovados (100%).
