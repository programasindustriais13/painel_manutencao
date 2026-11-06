# 🧠 SPEC — CORREÇÃO CRÍTICA DE CONCORRÊNCIA E SOBRESCRITA DR-201 (GOOGLE SHEETS APPEND)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/bladder/estoque/movimentar/` (Movimentação física múltipla de Entrada e Saída de Bladders)
  - `/bladder/estoque/sincronizar-dr201/` (Sincronização manual de contingência pela Liderança)
  - Chamadas de segundo plano disparadas após confirmação de transação (`transaction.on_commit`)
- **Contextos:**
  - Gestão de Estoque de Bladders Acabados no Chão de Fábrica (Tablet Operador e Terminal Líder)
  - Sincronização assíncrona em segundo plano (`threading.Thread`) com Google Sheets (DR-201)
- **Perfis afetados:**
  - Operador Bladder (Turma A / Turma B)
  - Líder Bladder
  - Formulário Google Forms externo (coexistência simultânea na mesma planilha)

---

## ❗ 2. PROBLEMA ATUAL

1. **Condição de Corrida (Race Condition) no Cálculo de Linhas:**
   - O código em `bladder/services.py` (`sincronizar_lote_movimentacoes_dr201`) obtém a última linha via `col_carimbos = ws.col_values(1)` e calcula `proxima_linha = len(col_carimbos) + 1`, executando em seguida `ws.update(values=..., range_name=f"A{proxima_linha}:J{linha_fim}")`.
   - Como a sincronização é disparada de forma assíncrona via `threading.Thread` em resposta a eventos HTTP ou chamadas simultâneas, duas threads paralelas (Thread A e Thread B) podem ler o mesmo comprimento de coluna (ex: 2940), calcular a mesma próxima linha (2941) e gravar em `A2941:J2941`, fazendo com que a segunda sobrescreva o registro da primeira.
2. **Conflito com Google Forms Externo:**
   - O Google Forms grava continuamente na mesma planilha através de inserção de novas linhas (`INSERT_ROWS`).
   - Se uma submissão de formulário ocorrer durante o intervalo entre a leitura da coluna pelo Django e o `ws.update()`, o Django sobrescreve a linha recém-adicionada pelo Google Forms.
3. **Falta de Idempotência em Disparos Concorrentes:**
   - Se o mesmo lote ou ID de movimentação for despachado para sincronização em duas threads simultâneas antes do término da primeira, ambas tentam sincronizar o registro duplicadamente.

---

## 🎯 3. OBJETIVO

- Eliminar definitivamente qualquer cálculo de próxima linha no lado Python (`col_values(1)`, `len()`, `proxima_linha`, `update()`).
- Implementar a gravação server-side através de `ws.append_rows(...)` com `insert_data_option='INSERT_ROWS'`, `table_range='A:J'`, `value_input_option='USER_ENTERED'`, delegando o gerenciamento atômico da linha ao Google Sheets.
- Proteger as threads internas do processo Django com um Lock de sincronização (`_dr201_sync_lock`), garantindo serialização das chamadas de rede e impedindo envio duplicado (idempotência intra-processo).
- Registrar log estruturado e auditável com IDs, quantidade de linhas, range retornado pela API e status.
- Garantir que o banco de dados registre `sincronizado_dr201=True`, `data_sincronizacao_dr201` e limpe `erro_sincronizacao_dr201` somente após a confirmação do Sheets, ou mantenha `sincronizado_dr201=False` com o erro em caso de falha.
- Coexistir pacificamente com os registros do Google Forms sem alterar ou sobrescrever dados históricos.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos a alterar:
- `bladder/services.py`:
  - Adição do lock de processo `_dr201_sync_lock = threading.Lock()`.
  - Refatoração da função `sincronizar_lote_movimentacoes_dr201()`:
    - Uso de `close_old_connections()` no início para garantir consistência em threads.
    - Aquisição de `_dr201_sync_lock`.
    - Verificação idempotente dentro do lock (`filter(id__in=movimentacoes_ids, sincronizado_dr201=False)`).
    - Chamada atômica de `ws.append_rows(novas_linhas, value_input_option='USER_ENTERED', insert_data_option='INSERT_ROWS', table_range='A:J', include_values_in_response=True)`.
    - Extração do range gravado e log estruturado.
    - Atualização atômica de status no banco.
- `Instrucoes.txt`:
  - Registro formal da alteração e das decisões técnicas.

---

## 🚫 5. FORA DE ESCOPO

- ❌ NÃO alterar a estrutura visual da tela de estoque ou dos formulários.
- ❌ NÃO alterar regras de saldo, reservas ou modelos de produto (`ProdutoBladder`).
- ❌ NÃO alterar formulários Google Forms ou apagar/editar dados históricos da DR-201.
- ❌ NÃO modificar scripts de deploy (`executar_deploy_servidor.bat`, etc.).
- ❌ NÃO alterar outras funcionalidades do módulo Bladder ou de outros apps (`maintenance`, `production`).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Seguir estritamente `constitution.md`.
- Apenas 1 ambiente virtual (.venv), 1 projeto Django, 1 base ativa.
- Usar ORM do Django sempre, sem SQL direto.
- Compatibilidade total entre SQLite (dev local) e MySQL (produção).
- Nunca expor credenciais em logs ou comitá-las desnecessariamente.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Append Server-side:**
   - O Google Sheets API deve receber `values_append` com `insertDataOption='INSERT_ROWS'`. Ele insere a linha na tabela `A:J` de forma atômica no servidor do Google.
2. **Serialização no Processo:**
   - O lock `_dr201_sync_lock` impede que duas threads locais executem requests simultâneos para a mesma planilha, evitando sobreposição de buffers ou leituras desatualizadas de conexão.
3. **Idempotência:**
   - Ao adquirir o lock, a função reconsulta o banco. Se os registros já foram sincronizados por outra thread que concluiu momentos antes, o envio é abortado com log informativo e retorno de sucesso sem duplicar linhas.
4. **Resiliência:**
   - Se ocorrer erro de rede ou API, os registros permanecem com `sincronizado_dr201=False` e a mensagem de erro é persistida em `erro_sincronizacao_dr201`. O botão manual `/bladder/estoque/sincronizar-dr201/` continuará funcional para reprocessar pendências.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Eliminação completa de `ws.col_values(1)`, `len(col_carimbos)` e `ws.update` para cálculo de linhas na sincronização da DR-201.
- [ ] Uso de `ws.append_rows` com `insert_data_option='INSERT_ROWS'`, `table_range='A:J'`, `value_input_option='USER_ENTERED'`.
- [ ] Implementação de Lock de concorrência (`_dr201_sync_lock`) e proteção de idempotência.
- [ ] Formato de log estruturado: `DR201 sync OK | mov_ids=[...] | rows=... | range=...`.
- [ ] TESTE 1 (Sequencial): Dois registros sequenciais ocupam duas linhas consecutivas distintas (ex: N+1 e N+2).
- [ ] TESTE 2 (Concorrente): Dois registros sincronizados simultaneamente via `ThreadPoolExecutor` criam duas linhas distintas na DR-201 sem sobrescrita.
- [ ] TESTE 3 (Lote): Movimentação de quantidade > 1 (ex: 3 peças) gera exatamente 3 linhas consecutivas na DR-201, com seus respectivos lotes.
- [ ] TESTE 4 (Fluxo Real Assíncrono): Execução de `registrar_movimentacao_multipla_estoque(..., disparar_sync=True)` assíncrona conclui com sucesso gravando no Google Sheets e atualizando o banco.
- [ ] TESTE 5 (Banco): Validação de `sincronizado_dr201=True`, `data_sincronizacao_dr201!=None`, `erro_sincronizacao_dr201=None` no sucesso, e simulação de falha mantendo `sincronizado_dr201=False` com mensagem de erro.
- [ ] Registro em `Instrucoes.txt`.
- [ ] `manage.py check` sem erros.
- [ ] Git commit e push para `main` com hash documentado.

---

## ⚠️ 9. RISCOS

- **Rate Limit da Google Sheets API:** O lock de processo serializa requisições locais e evita requisições em rajada. O lote agrupa N movimentações em 1 única requisição HTTP.
- **Latência no Google Sheets:** As chamadas rodam em background daemon thread, não bloqueando a resposta HTTP do usuário (<50ms).
- **Planilha com linhas vazias no grid:** `table_range='A:J'` orienta a busca pela tabela preenchida e insere na primeira linha posterior aos dados preenchidos.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. **Subagente Arquiteto / Análise:** Mapear parâmetros de `append_rows` no `gspread 6.2.1` e a estrutura do retorno.
2. **Subagente Backend / Implementação:**
   - Modificar `bladder/services.py`:
     - Instanciar `_dr201_sync_lock = threading.Lock()`.
     - Substituir o bloco `col_values(1) / update()` por `ws.append_rows(...)`.
     - Implementar idempotência dentro do lock.
     - Implementar log estruturado com range retornado.
3. **Subagente QA / Testes Rigorosos:**
   - Executar os 5 testes obrigatórios contra o ambiente real / banco e registrar os ranges exatos da planilha DR-201.
4. **Documentação & Finalização:**
   - Atualizar `Instrucoes.txt`.
   - Gerar commit e push para `main`.

---

## 🧪 11. TESTES MANUAIS E AUTOMATIZADOS OBRIGATÓRIOS

- **Teste 1:** Duas sincronizações sequenciais -> Verificar N+1 e N+2.
- **Teste 2:** Concorrência com `ThreadPoolExecutor(max_workers=2)` -> Verificar que nenhum sobrescreve o outro.
- **Teste 3:** Lote de 3 peças -> Verificar 3 linhas consecutivas.
- **Teste 4:** Fluxo real `registrar_movimentacao_multipla_estoque(..., disparar_sync=True)`.
- **Teste 5:** Verificação dos campos no banco de dados (sucesso e falha simulada).

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- Arquivos lidos e alterados.
- Causa raiz detalhada.
- Códigos anterior e novo.
- Logs e resultados individuais dos testes 1 a 5.
- Ranges retornados pela API Google Sheets.
- Commit, SHA e status do push.
