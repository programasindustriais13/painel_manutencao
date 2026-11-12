# 🧠 SPEC — LOTE POR BATELADA E VOLUMES DE BLADDERS ACABADOS

---

## 📌 1. CONTEXTO

- Data: 12/11/2026 (America/Fortaleza).
- URLs: `/bladder/estoque/`, `/bladder/estoque/movimentar/`, `/bladder/operador/`, `/bladder/operador/fechar-turno/`, `/bladder/relatorios/`, `/bladder/relatorios/exportar-excel/`, `/bladder/estoque/sincronizar-dr201/` e administração do ledger.
- Contextos: estoque físico de Bladders acabados, modal compartilhado entre estoque e turno, histórico, indicadores, reconciliação DR-201 e sincronização Google Sheets.
- Perfis: liderança Bladder, operadores regulares ativos, apoio ativo e superusuário, preservando as permissões existentes.
- Implementação no app `bladder` existente, banco `default`; sem alterações no SCADA.

---

## ❗ 2. PROBLEMA ATUAL

Regra antiga: **1 peça = 1 lote = 1 movimentação = 1 linha DR-201**. Ela deixou de representar a produção: um lote identifica uma batelada com N volumes.

- `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`: `atualizarLotesModal()` recria N inputs `name="lotes"`, rotulados Peça 1..N; badge afirma N peças = N linhas. Quantidade está limitada arbitrariamente a 50.
- `bladder/services.py`, `registrar_movimentacao_multipla_estoque()`: `for i in range(qtd)` salva o saldo e cria N registros `quantidade=1`, consumindo lotes por posição.
- `bladder/views.py`, `estoque_movimentar()`: lê lista `lotes`, transforma quantidade ausente/inválida/não positiva em 1 e anuncia `len(movs)` como unidades; o formulário existente não é utilizado para validar o POST.
- `sincronizar_lote_movimentacoes_dr201()` já faz uma linha por registro e APPEND server-side corretamente, mas preenche coluna I com `justificativa`.
- `auditar_planilha_dr201()` conta uma unidade por linha, inclusive nos modelos desconhecidos: subcontaria novos movimentos de vários volumes e afetaria o comando de carga inicial que consome o relatório.

Há impacto operacional imediato: quantidade 20 gera 20 campos, registros e linhas, quando o cliente precisa informar apenas um lote e 20 volumes.

---

## 🎯 3. OBJETIVO

**1 lote + quantidade N → 1 movimentação → 1 linha DR-201**, para ENTRADA e SAIDA.

Exemplos: saldo 10 + entrada LOT001/20 = 30; saída LOT001/5 = 25. A movimentação registra quantidade numérica, lote, saldos anterior/posterior e responsável. A DR recebe G=lote, H=modelo, I=quantidade numérica. Observações internas permanecem em `justificativa` e deixam de ocupar I.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos previstos

- `bladder/services.py`: validação comum de quantidade/lote; serviços entrada/saída; adaptação mínima do serviço múltiplo; mapeamento DR coluna I; reconciliação de volumes.
- `bladder/forms.py`: lote obrigatório normalizado, quantidade de volumes, aliases necessários sem aceitar ambiguidades.
- `bladder/views.py`: validar POST com formulário, usar único lote e quantidade e corrigir mensagem de sucesso.
- `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`: único input, rótulos, dicas e JavaScript mínimo de quantidade/leitor, mantendo responsividade.
- `bladder/tests.py`: testes específicos de estoque, formulário/view, históricos e integração simulada.
- `test_dr201_suite.py`: adaptar o harness existente de integração real à nova regra, evitando testes antigos inconsistentes que criem saldos fictícios.
- `Instrucoes.txt`: documentar antes/agora, validações, compatibilidade, sincronização, cabeçalho e evidências.
- Esta SPEC. Ajustes pontuais de texto no histórico/admin são admitidos se necessários para clareza, sem mudar estrutura de dados.

### Mapa de dependências e banco

| Área | Análise de impacto |
|---|---|
| `MovimentacaoEstoqueBladder` | `quantidade` já é PositiveIntegerField; `lote_etiqueta` não é único; saldos, data, usuário e destino já existem. Suporta quantidade 1 ou N. |
| `ProdutoBladder` | Estoque é inteiro; `consumo_medio_diario()` já usa Sum(quantidade); cobertura/semáforo/sugestão de OP continuam válidos. |
| Serviços entrada/saída | Já criam um registro com N, mantêm `select_for_update`, atomicidade, autorização e on_commit; acrescentar validações estritas e reutilizar. |
| Serviço múltiplo | Único ponto produtivo que exige um registro por peça. Converter em compatibilidade que retorna `[mov]` e saldo, delegando ao serviço correto sem duplicar motor de estoque. |
| View de movimentação | `len(movs)` representa número de eventos, não volumes; corrigir. |
| Histórico estoque e turno | Já apresentam `mov.quantidade`; registros antigos e novos podem coexistir sem migração. |
| Fechamento de turno | View soma quantidade por tipo; comprimento mostrado em template identifica movimentos, não unidades. Sem ajuste de cálculo. |
| Relatórios e Excel | Relatórios atuais são de OP/apontamento e não inferem volumes contando movimentos de estoque. Não alterar produção/PCP. Validar abertura/exportação com histórico misto. |
| Admin | list_display inclui quantidade e saldos, busca lote; não impõe unicidade nem quantidade=1. |
| Reconciliação DR | Adaptar leitura da coluna I com fallback histórico unitário. `importar_estoque_dr201` reutiliza essa função; não executar aplicação de saldos durante testes. |
| Sync individual/lote/async/pendências | Todos convergem no mesmo APPEND de uma linha por objeto. Não expandir pela quantidade. Preservar lock/status/log/retorno de range. |
| Rastreabilidade | ORM por produto+lote+tipo e Sum(quantidade) permite entradas, saídas e saldo, datas e responsáveis. Saída parcial do mesmo lote é permitida; sem nova tabela. |
| Outros apps | Busca por nome do modelo, lote e serviço não encontrou consumidores produtivos fora de bladder; referências no harness e documentação são específicas. |

**Migration não é necessária**: não alterar campos nem metadados do model; rótulo visível pode ser definido no formulário. Não tocar migrations ou converter dados antigos. `AJUSTE` e `CARGA_INICIAL` continuam podendo existir sem lote, pois não são ENTRADA/SAIDA operacionais novas.

---

## 🚫 5. FORA DE ESCOPO

- Google Forms, perguntas, cabeçalhos e estrutura da planilha; exclusão/reescrita de linhas históricas.
- Migração, consolidação ou alteração de movimentações históricas, tabelas ou campos novos.
- Nova gestão de lotes ou bloqueio adicional por saldo do lote; a regra solicitada bloqueia pelo estoque total disponível do modelo. O ledger preserva rastreabilidade para futura consulta.
- Manutenção, PCP, SCADA, autenticação/permissões, deploy, refatorações gerais e mudanças em WhatsApp.
- Novo projeto, app, ambiente virtual ou cópia da base de código.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

Seguir `constitution.md` e `regras_programacao/constitution.md`: um fluxo ativo, projeto e `.venv` existentes; MVT; regras nos services/forms; ORM sem SQL direto; compatibilidade SQLite/MySQL; CSRF e autorização no backend preservados; mensagens em português; documentação em `Instrucoes.txt`.

Nenhum envio WhatsApp nem alteração SCADA durante validação. Não exibir credenciais. Testes automatizados mockam Google Sheets para evitar gravações acidentais. Teste externo explícito é separado e usa APPEND com lote de teste claramente identificável.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. Quantidade obrigatória, inteira e >0, validada no Form e em chamadas diretas de serviço. Não truncar frações, converter booleano em unidade ou assumir 1 para dado inválido.
2. Lote obrigatório e sem espaços nas extremidades para novas ENTRADAS/SAIDAS; vazio/só espaços rejeitado; máximo de 60 caracteres conforme model.
3. Uma submissão representa um lote e N volumes. Se mantido alias antigo `lotes`, aceitar somente um lote sem ambiguidade; listas com lotes diferentes devem ser rejeitadas, nunca ignoradas silenciosamente ou expandidas.
4. Atualização atômica do estoque e criação de apenas uma movimentação. Saída > saldo bloqueada sem efeitos; manter proteção por produto e on_commit.
5. Preservar APIs entrada/saída e idempotency_key existentes. Adaptar múltiplo como compatibilidade que retorna lista unitária e saldo; preservar data/turma/turno e disparar apenas um callback após commit.
6. Manter destino/responsável conforme comportamento atual. Entrada envia responsável pela retirada vazio à DR; saída envia destino em maiúsculas. Preservar observações em `justificativa` no banco.
7. DR: A carimbo; B data turno; C turno; D responsável Bladder; E entrada/saída; F responsável retirada; G lote; H código modelo; I **inteiro `m.quantidade`**; J foto conforme regra atual (vazio na integração existente).
8. Preservar exatamente APPEND server-side `append_rows(..., value_input_option='USER_ENTERED', insert_data_option='INSERT_ROWS', table_range='A:J', include_values_in_response=True)`. Não descobrir próxima linha via col_values/len/update. Quantidade não determina número de linhas.
9. Preservar lock, filtro de pendências, status de sucesso/erro, on_commit e logs com IDs/linhas/`updatedRange`; callbacks individual e lote continuam convergindo no mesmo motor.
10. Reconciliação: coluna I com inteiro positivo representa volumes; vazio/texto legado representa 1. Linhas válidas permanecem contadas como eventos; entradas/saídas/saldo são volumes. Aplicar também a modelos desconhecidos. Não reescrever planilha ou banco para adaptar histórico.
11. Compatibilidade histórica: quantidade=1 permanece válida; lote antigo opcional não exige saneamento; sincronização de pendência histórica gera uma linha com quantidade original.
12. Lote não é único. Entrada de 20 e saída de 5 com mesmo lote são dois eventos e saldo rastreável de 15. Saldo global continua independente da implementação futura de módulo de lotes.

### Cabeçalho e Google Forms: evidência anterior à implementação

Leitura real, somente leitura, em 12/11/2026 usando o gspread já instalado e `credentials.json` (sem imprimir segredos): planilha **DR.201 - CONTROLE DE ESTOQUE DE BLADDERS (respostas)**, aba DR201, 3.059 linhas incluindo cabeçalho.

- Cabeçalho I encontrado: **Volumes**, já diferente do nome Observações citado na demanda. Não há necessidade de renomear.
- G: Lote do Bladder Vulcanizado; H: Modelo Bladder; J: Fotos Etiquetas.
- Nenhuma das 3.058 linhas históricas apresenta em I um valor formado somente por dígitos; fallback unitário não reinterpreta observações históricas numéricas desse conjunto observado.
- A SPEC de APPEND anterior e o template de auditoria registram que é uma planilha de respostas Google Forms. A API de Sheets consultada não prova propriedade da pergunta pelo Forms; tratá-la conservadoramente como vinculada e preservar o cabeçalho existente.
- Se outra implantação ainda tiver I=Observações: **"Alterar o cabeçalho da coluna I de Observações para Quantidade de Volumes"** somente manualmente pelo responsável, após verificar o vínculo com Forms. Não faz parte da escrita automática desta mudança.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [x] Entrada: saldo 10, LOT001/20 → uma movimentação quantidade=20, saldo 30.
- [x] Saída: saldo 30, LOT001/5 → uma movimentação quantidade=5, saldo 25.
- [x] Saída 10 com saldo 5 rejeitada; saldo e ledger inalterados.
- [x] Quantidade ausente, inválida, fracionária, zero ou negativa e lote vazio/espaços bloqueados no backend.
- [x] Quantidades 1, 5, 20 e 100 mantêm exatamente um input de lote; sem Peça N ou geração dinâmica.
- [x] Mensagens relatam volumes reais e sincronização encaminhada/pendente, sem afirmar sucesso remoto antes da confirmação.
- [x] DR: quantidade 20 gera exatamente uma linha; G/H/I corretos, I numérico, justificativa preservada internamente.
- [x] LOT001/20 e LOT002/15 criam dois eventos e duas linhas distintas por APPEND; histórico preservado.
- [x] Histórico misto quantidade 1/N abre em estoque/turno/relatórios/Excel e somas de consumo/fechamento continuam corretas.
- [x] Reconciliação mistura linhas antigas sem quantidade com novas quantidades; usa volumes, sem contar eventos como unidades.
- [x] Permissões e CSRF preservados; nenhuma nova migration; ORM compatível SQLite/MySQL.
- [x] Testes automatizados obrigatórios passam; `manage.py check`, `manage.py test` e `makemigrations --check --dry-run` executados e resultados registrados.
- [x] Teste manual real de entrada/saída parcial, saldo/histórico e Sheets registrado com lote/modelo/quantidade/range retornado, ou limitação de ambiente declarada explicitamente sem inventar aprovação.
- [x] `Instrucoes.txt` atualizado; diff mínimo revisado após testes, sem falhas críticas relacionadas; publicação autorizada e resultado Git a informar na resposta final.

---

## ⚠️ 9. RISCOS

- **Subcontagem em reconciliação**: leitura antiga soma 1; corrigir junto ao produtor da linha, com testes de histórico misto.
- **Observações numéricas legadas**: o formato antigo não possui marcador de versão. A leitura atual não encontrou valores históricos só dígitos, mas importações futuras podem ser ambíguas; documentar e não aplicar saldos automaticamente.
- **POST legado com múltiplos lotes**: rejeitar ambiguidade; nunca selecionar primeiro lote descartando restantes.
- **Concorrência**: preservar transação/select_for_update e APPEND; lock existente é intra-processo e não fornece exatamente uma vez entre múltiplos processos ou após timeout ambíguo. Não ampliar escopo da arquitetura de integração.
- **Histórico**: não executar migração de dados, bulk_update ou saneamento em dados antigos.
- **Forms/cabeçalho**: preservar nomes/estrutura já existentes; I real já se chama Volumes.
- **Harness real antigo**: cria movimentos diretamente e restaura saldo por atribuição, podendo produzir eventos de teste inconsistentes. Adaptar minimamente para operações reais de entrada/saída que se compensam, com lotes únicos identificáveis e sem apagar histórico.
- **Suíte pré-existente**: o agente principal detectou falhas na baseline antes desta implementação. Registrar causas/resultados separadamente; falhas críticas desta alteração impedem commit/conclusão, e regressões não devem ser escondidas.
- **Navegador**: não há Playwright/Selenium instalado inicialmente. Verificar ferramentas disponíveis; se necessário usar instalação no `.venv` existente sem criar ambiente/projeto; registrar evidência real ou impedimento.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

1. **Arquiteto**: ler constituições, template, demanda, produtor/consumidores de ledger e DR; inspecionar cabeçalho e ambiguidade histórica em modo somente leitura; criar esta SPEC antes de editar código. Etapa realizada.
2. **Backend**: criar validação reutilizada para quantidade e lote, aplicar nos serviços entrada/saída; substituir expansão do múltiplo por delegação que cria uma movimentação, mantendo contrato de retorno e metadados/turno/callback.
3. Usar `MovimentacaoEstoqueForm` na view; normalizar aliases necessários sem ambiguidade e rejeitar dados inválidos; mensagens por quantidade, não len(movs).
4. No modal compartilhado, trocar seção dinâmica por único `lote_etiqueta` obrigatório; remover geração, listeners de expansão, rótulos Peça N, badge antigo e teto 50; manter +/- e experiência touch/leitor sem perda de dados.
5. Alterar somente mapeamento de I no sync para inteiro `quantidade`; manter APPEND e caminhos async/pendências. Atualizar reconciliação com fallback histórico.
6. Adicionar testes A–G e extras de validação/permissões/observação/consumo/pendência/idempotência. Adaptar harness real para batelada e movimentos compensados, sem editar linhas antigas.
7. Atualizar `Instrucoes.txt` com ANTES/AGORA e restrição de cabeçalho. Rodar testes específicos e checagens, depois suíte completa; entregar a **QA** para validação independente, em sequência, nunca implementação paralela.
8. Realizar teste de tela com quantidade 20, BLA003, entrada e saída parcial do mesmo lote; conferir histórico/saldo e uma linha por evento na DR. Salvar evidências/`updatedRange` sem segredos. Toda linha nova de teste deve ser identificável; não apagar linhas antigas nem sincronizar pendências de terceiros durante ensaio.
9. Depois dos testes, `git status`, `git diff`, revisão de escopo; stage explícito apenas dos arquivos necessários, commit `Bladder: adaptar estoque para lote por batelada e volumes` e `git push origin main` conforme autorização da demanda. Informar SHA, branch e resultado real do push. Não publicar se testes críticos relacionados falharem.

### Aprovação técnica interna

**APROVADO PELO SUBAGENTE ARQUITETO EM 12/11/2026, ANTES DE QUALQUER ALTERAÇÃO DE CÓDIGO.** O model existente atende lote por batelada e saída parcial sem migration. O plano mínimo acima libera a etapa Backend, seguido de QA; a aprovação não equivale à validação final dos testes.

---

## 🧪 11. TESTES MANUAIS

1. Acessar estoque como usuário autorizado; abrir Movimentação de Bladders Acabados. Conferir também modal do turno e viewport de celular/tablet.
2. Escolher BLA003/ENTRADA e quantidade 20; confirmar exatamente um campo de lote. Repetir visualmente quantidades 1/5/100 e botões +/- sem recriar input/perder lote.
3. Informar lote de teste único e observação interna. Registrar; verificar um evento quantidade 20 e saldo anterior +20.
4. Conferir DR G/H/I, uma linha, observação interna ausente de I, status sincronizado e range da API; garantir linhas anteriores intactas.
5. Fazer saída parcial do mesmo lote com responsável; confirmar um evento, -5 no saldo e uma nova linha DR com I=5 e F=responsável.
6. Para ensaio externo sem efeito líquido no estoque, realizar saída compensatória dos 15 volumes restantes do lote de teste e registrar explicitamente essa movimentação de validação, em vez de apagar histórico ou corrigir saldo por atribuição.
7. Submeter lote em branco/espaços e quantidade inválida por POST, e saída acima do saldo; verificar mensagens e ausência de alterações. Confirmar negação para usuário sem permissão.
8. Abrir histórico com registros antigos quantidade=1 e novos N; abrir relatórios e exportar Excel; verificar indicadores baseados em quantidade e acesso local a `/management/` e `/dashboard/` conforme constituição.
9. Testes automatizados obrigatórios: A entrada 20; B saída 5; C saldo negativo; D único input; E uma linha DR e I numérica; F histórico antigo; G dois movimentos consecutivos sem sobrescrita. Usar mocks para Sheets e callbacks controlados, sem rede na suíte padrão.
10. Executar no ambiente existente: `.\.venv\Scripts\python.exe manage.py check`, `.\.venv\Scripts\python.exe manage.py test`, `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`. Registrar falhas anteriores à mudança e resultados dos testes afetados individualmente.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

### Arquivos lidos pelo Arquiteto

Leituras completas ou de trechos relevantes e buscas de dependências:

- `constitution.md`
- `regras_programacao/constitution.md`
- `regras_programacao/SPEC_TEMPLATE.md`
- Demanda anexada: `C:/Users/Unicompo/.codex/attachments/164dd93c-8b9d-4d89-b691-49dfa8aa67c2/Pasted text.txt`
- `regras_programacao/SPEC_CORRECAO_CONCORRENCIA_DR201_APPEND.md`
- `regras_programacao/SPEC_REESTRUTURACAO_BLADDER_ESTOQUE_DR201.md`
- `bladder/models.py`
- `bladder/services.py`
- `bladder/forms.py`
- `bladder/views.py`
- `bladder/urls.py`
- `bladder/decorators.py`
- `bladder/admin.py`
- `bladder/tests.py`
- `bladder/migrations/0006_tipoatividadebladder_and_more.py`
- `bladder/management/commands/importar_estoque_dr201.py`
- `bladder/management/commands/sincronizar_estoque_dr201.py`
- `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`
- `bladder/templates/bladder/estoque_lista.html`
- `bladder/templates/bladder/estoque_auditoria_dr201.html`
- `bladder/templates/bladder/operador_turno.html`
- `bladder/templates/bladder/fechamento_turno.html`
- `bladder/templates/bladder/dashboard.html`
- `bladder/templates/bladder/relatorios.html` (busca de consumidores; nenhum cálculo por contagem de movimentos)
- `maintenance_project/settings.py` (trecho banco/isolamento de testes)
- `requirements.txt`
- `test_dr201_suite.py`
- `Instrucoes.txt` (seções de estoque/DR e referências)

Busca global por `MovimentacaoEstoqueBladder`, `lote_etiqueta`, `movimentacoes_estoque`, serviço múltiplo e `.quantidade`: dependências relevantes discriminadas acima. O arquivo de credenciais é consumido exclusivamente pelo cliente Google para autenticação, sem leitura/exibição manual do conteúdo.

### Arquivos alterados pelo Arquiteto

- Apenas `regras_programacao/SPEC_LOTE_BATELADA_VOLUMES_BLADDER.md`, para estabelecer contexto, regras, impacto e plano aprovado antes de codificar.

### Evidências a completar por Backend/QA/agente principal

- Lista integral adicional de arquivos lidos/alterados e justificativa por arquivo.
- Modelos analisados e resultado de ausência de migrations.
- Regra anterior encontrada e novo fluxo; elementos HTML/JS removidos.
- Saldos antes/quantidade/depois e número de eventos.
- Testes A–G individualmente, validações/permissões e histórico/relatórios.
- DR real: lote/modelo/quantidade/range retornado pela API, status e histórico preservado.
- Resultado real dos comandos Django; limitações de baseline/ambiente separadas de falhas introduzidas.
- Revisão Git, mensagem/SHA/branch e confirmação de push, ou impedimento explícito.

### Evidências da etapa Backend (12/11/2026)

**Implementação entregue para QA, sem commit/push nesta etapa.** Regra antiga removida do serviço múltiplo (`for i in range(qtd)` e `quantidade=1`) e do gerador `atualizarLotesModal`. Agora o wrapper valida e delega aos motores existentes, retornando `[mov]` com quantidade=N e um callback; DR usa quantidade numérica em I e APPEND intacto.

Arquivos lidos pelo Backend (integrais ou trechos relevantes): `constitution.md`, `regras_programacao/constitution.md`, esta SPEC, demanda anexada identificada acima, `bladder/services.py`, `bladder/forms.py`, `bladder/views.py`, `bladder/models.py`, `bladder/admin.py`, `bladder/tests.py`, `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`, `bladder/management/commands/importar_estoque_dr201.py`, `bladder/management/commands/sincronizar_estoque_dr201.py`, `test_dr201_suite.py`, `Instrucoes.txt`.

Arquivos alterados pelo Backend e justificativas:

- `bladder/services.py`: validação comum quantidade/lote, único movimento por batelada, reconciliação de volumes e mapeamento I numérico.
- `bladder/forms.py`: campos/rótulos/limite lote e validação de aliases antes dos fields; quantidade estrita e rejeição de lotes ambíguos.
- `bladder/views.py`: usar Form validado; remover quantidade inválida → 1, lista por peça e mensagem por `len(movs)`.
- `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`: um input obrigatório, ajuda por lote/volumes, remover geração dinâmica/teto50 e preservar leitor/touch.
- `bladder/tests.py`: 19 testes isolados da nova regra sem rede Google.
- `test_dr201_suite.py`: atualizar o harness real existente para bateladas com saldo compensado por eventos, sem falsificar ledger ou apagar histórico; continua sob `__main__` e **não foi executado pelo Backend**.
- `Instrucoes.txt`: documentar antes/agora, compatibilidade, campos DR, cabeçalho, validações e testes.
- Esta SPEC: registrar evidências técnicas e testes.

Modelos analisados: `MovimentacaoEstoqueBladder` (quantidade inteira, lote não único, saldos, data, autor/destino); `ProdutoBladder` (saldo/consumo via soma). **Nenhum model ou migration alterado**. `manage.py makemigrations --check --dry-run` retornou **No changes detected**; `manage.py check` retornou **System check identified no issues (0 silenced)**. Compilação Python dos cinco arquivos .py alterados passou.

Comando direcionado: `.\.venv\Scripts\python.exe manage.py test bladder.tests.EstoqueLoteBateladaVolumesTestCase --noinput -v 2` → **19 testes, 0,821 s, OK**, banco SQLite de testes em memória. Individualmente:

| Evidência | Teste | Resultado |
|---|---|---|
| A | `test_a_entrada_20_volumes_uma_movimentacao` | 10 +20 =30; um evento LOT001/20 |
| B | `test_b_saida_parcial_5_volumes_uma_movimentacao` | 30 -5 =25; um evento de saída, mesmo lote |
| C | `test_c_saldo_negativo_bloqueia_sem_efeitos` | 5 -10 bloqueado; sem evento/saldo alterado |
| D | `test_d_interface_um_input_lote_nos_dois_modais` | Estoque/operador: um input, sem gerador antigo |
| E | `test_e_dr201_20_volumes_exatamente_uma_linha` | Uma linha, G/H/I=LOT001/BLA003/20; APPEND e reenvio confirmados |
| F | `test_f_historico_antigo_e_novo_relatorios_e_excel` | Antigo1/novo20 coexistem; estoque/operador/relatório/Excel abrem |
| G | `test_g_movimentos_consecutivos_20_e_15_duas_linhas_distintas` | Dois eventos/APPENDs/ranges distintos simulados |
| Extras (12) | Serviços diretos, wrapper, Form, view sucesso/erro, permissões/CSRF, idempotência, DR saída/pendentes/falha, reconciliação, rastreio/consumo/fechamento | Todos passaram |

A suíte completa anterior à alteração foi iniciada pelo agente principal e já apresentava falhas; o resultado completo e a comparação posterior serão registrados pelo agente principal/QA, sem alterar módulos alheios para ocultá-las. Teste de navegador/Sheets real e ranges permanecem sob responsabilidade do agente principal; nenhum valor simulado acima é apresentado como range real.

---

### Evidências da etapa QA (12/11/2026)

**Parecer: aprovado no escopo desta alteração; nenhuma correção produtiva exigida pelo QA.** A conclusão da comparação da suíte completa posterior e a publicação Git permanecem com o agente principal. A baseline anterior continha 16 falhas em 622 testes, todas relacionadas a assertions de textos antigos das telas operador/dashboard/recados; não foram ocultadas ou corrigidas ampliando o escopo.

Verificação independente: `manage.py test bladder.tests.EstoqueLoteBateladaVolumesTestCase --noinput -v 1` → **19 testes, 0,784 s, OK**; `manage.py check` → sem problemas; `manage.py makemigrations --check --dry-run` → **No changes detected**; `git diff --check` → sem erros. Os avisos LF/CRLF do Git não representam alteração de conteúdo ou falha de teste.

Revisão do diff confirmou:

- Nenhum model, migration, app, configuração, permissão, script de deploy ou módulo externo foi alterado. O único motor permanece nos serviços de entrada/saída; o wrapper não duplica atualização de saldo.
- Uma transação e um registro com quantidade N; saída acima do saldo falha antes da escrita; validações compartilhadas impedem quantidades inválidas, lote vazio e listas ambíguas. Autorização nos serviços/view e CSRF preservados.
- Os dois modais compartilham um único input obrigatório de lote; geração dinâmica e teto 50 removidos. Alterar quantidade não reconstrói nem descarta o lote.
- A linha DR mantém dez colunas e I numérica. Nenhum caminho de sincronização expande pela quantidade ou calcula próxima linha; APPEND/INSERT_ROWS, lock, filtro de pendências, status, callbacks e retorno de range foram preservados.
- Histórico e turno mostram `mov.quantidade`; consumo e fechamento somam quantidades. Admin já exibe quantidade/saldos e pesquisa lote. Importação de estoque consome a reconciliação corrigida; nenhuma carga de saldos foi executada.
- Os sete testes A–G e os doze extras passaram individualmente na classe direcionada, incluindo observações internas, idempotência, falha/retentativa e reconciliação de dados antigos/novos.
- `test_dr201_suite.py` foi revisado sem executá-lo nesta etapa: guardado por `__main__`, usa lotes UUID identificáveis, APPEND e cinco eventos balanceados (+20/+15/-5/-15/-15); verifica histórico, reenvio, concorrência e compensação por novos eventos. Liberado ao agente principal para o ensaio externo autorizado.

QA conferiu também o artefato real `logs/spec_volumes_manual_evidence.json`: lote `TESTE-SPEC-20261112-TELA20`, BLA003, entrada20 em `'DR201'!A3060:J3060`, saída5 em `'DR201'!A3061:J3061` e saída compensatória15 em `'DR201'!A3062:J3062`; saldo 0→20→15→0. O artefato registra um input em quantidades 1/5/20/100 e larguras 375/768 px, sem erro JavaScript, histórico Django/Sheets intacto e HTTP 200 nas páginas operador/relatórios/management/dashboard. Esses ensaios foram executados pelo agente principal; QA não realizou novas escritas externas.

Arquivos lidos/revisados pelo QA (conteúdo, trechos relevantes ou diff): `constitution.md`, `regras_programacao/constitution.md`, esta SPEC, demanda anexada recebida no contexto, `bladder/services.py`, `bladder/forms.py`, `bladder/views.py`, `bladder/models.py`, `bladder/decorators.py`, `bladder/admin.py`, `bladder/tests.py`, `bladder/management/commands/importar_estoque_dr201.py`, `bladder/management/commands/sincronizar_estoque_dr201.py`, `bladder/templates/bladder/includes/modal_movimentacao_estoque.html`, `bladder/templates/bladder/estoque_lista.html`, `bladder/templates/bladder/operador_turno.html`, `bladder/templates/bladder/fechamento_turno.html` (busca de consumidores), `test_dr201_suite.py`, `Instrucoes.txt` e `logs/spec_volumes_manual_evidence.json`. Busca global adicional não encontrou outros consumidores produtivos que exijam um evento por peça. QA alterou **somente esta SPEC**, para registrar as evidências, sem commit/push.

---

### Evidências do agente principal: navegador e Google Sheets reais (12/11/2026)

Ensaio em Edge real, executado com Playwright instalado somente no `.venv` já existente como ferramenta de validação; nenhuma dependência de execução foi adicionada a `requirements.txt`. Servidor local temporário em `127.0.0.1:8765`, sessão de usuário autorizado criada apenas para o ensaio e excluída ao terminar. Nenhuma senha, permissão ou configuração de autenticação foi modificada.

**Tela real:** BLA003, lote `TESTE-SPEC-20261112-TELA20`. Quantidades 1, 5, 20 e 100 verificadas em larguras 375 e 768 px: exatamente um input `lote_etiqueta`, nenhum `lotes`, lote preenchido preservado e nenhum overflow horizontal no modal. Zero erros JavaScript. Captura visual inspecionada em `logs/spec_volumes_tela_20.png`.

| Evento Django | Operação | Quantidade | Saldo anterior → posterior | G / H / I conferidos na planilha | updatedRange real retornado pelo APPEND |
|---|---|---:|---|---|---|
| 23 | ENTRADA | 20 | 0 → 20 | TESTE-SPEC-20261112-TELA20 / BLA003 / 20 | `'DR201'!A3060:J3060` |
| 24 | SAIDA parcial | 5 | 20 → 15 | mesmo lote / BLA003 / 5 | `'DR201'!A3061:J3061` |
| 25 | SAIDA compensatória | 15 | 15 → 0 | mesmo lote / BLA003 / 15 | `'DR201'!A3062:J3062` |

Cada evento foi submetido pelo formulário real com CSRF e sincronizado pelo callback assíncrono normal. O range acima foi extraído do log da resposta da API, não calculado a partir de contagem de linhas. Comparação de todos os registros Django existentes antes do ensaio e de todas as 3.059 linhas anteriores do Sheets confirmou histórico intacto. A planilha passou a 3.062 linhas, exatamente três novas linhas. Todos os eventos ficaram `sincronizado_dr201=True`. Saldo inicial e final BLA003 = 0. A observação do teste permaneceu em `justificativa`; I contém volumes.

Histórico, operador, relatórios e páginas constitucionais verificadas: `/bladder/estoque/`, `/bladder/operador/`, `/bladder/relatorios/`, `/management/` e `/dashboard/` responderam HTTP 200. Exportação Excel e coexistência de histórico antigo quantidade=1/novo20 também aprovadas no teste F.

**Harness real existente:** `python test_dr201_suite.py` executou dois lotes, cinco eventos e cinco linhas por rodada. Primeira rodada `TESTE-BATELADA-20261112-65d1ff1e-01/-02`: cenários passaram nas linhas 3063–3067, mas a impressão final da seta Unicode falhou no console Windows cp1252. Corrigido exclusivamente o texto de saída para `->`; nenhuma regra produtiva mudou. Segunda rodada terminou com **exit 0**, lotes `TESTE-BATELADA-20261112-5988cfd5-01/-02`:

| Operação | Lote final | Quantidade | Saldo posterior | Range real |
|---|---|---:|---:|---|
| ENTRADA | ...5988cfd5-01 | 20 | 20 | `'DR201'!A3068:J3068` |
| ENTRADA consecutiva | ...5988cfd5-02 | 15 | 35 | `'DR201'!A3069:J3069` |
| SAIDA parcial assíncrona | ...5988cfd5-01 | 5 | 30 | linha 3070, conferida por leitura; callback não retorna range ao chamador |
| SAIDA compensatória, sync concorrente | ...5988cfd5-01 | 15 | 15 | `'DR201'!A3071:J3071` |
| SAIDA compensatória, sync concorrente | ...5988cfd5-02 | 15 | 0 | `'DR201'!A3072:J3072` |

Falha simulada antes do APPEND manteve a pendência; retentativa sincronizou. Saída acima do estoque foi bloqueada sem criar evento. Reenvio de evento já confirmado não criou linha extra. APPENDs concorrentes retornaram ranges distintos; comparação do prefixo da planilha confirmou ausência de sobrescrita. Nenhuma linha de teste foi apagada e nenhum saldo foi restaurado por atribuição direta. Consulta final: 13 eventos de teste = 13 linhas novas (3 da tela + 5 de cada rodada), todos sincronizados; BLA003 saldo 0. Agrupamento ORM por lote/tipo confirmou entrada20, saídas5+15 e saldo0, e lote2 entrada15/saída15/saldo0.

Artefatos locais de evidência em `logs/`, ignorados pelo Git: `spec_volumes_manual_evidence.json`, `spec_volumes_tela_20.png`, `spec_volumes_server.err.log`, `spec_volumes_server.out.log`, `spec_volumes_dr201_real.log`, `spec_volumes_dr201_real_retry.log` e `spec_volumes_test_full_after.log`. Scripts transitórios do ensaio: `spec_volumes_manual.py` e `spec_volumes_server_entry.py`; não integram a aplicação ou o commit.

Arquivos adicionais lidos/inspecionados pelo agente principal, além das listas dos subagentes: `manage.py`, `requirements.txt`, `.gitignore`, `maintenance_project/settings.py`, `bladder/templates/bladder/base_bladder.html`, todos os oito arquivos entregues abaixo e os artefatos locais citados. `credentials.json` foi consumido exclusivamente pelo SDK Google, sem exposição do conteúdo.

**Lista completa dos arquivos entregues/alterados no repositório:**

1. `regras_programacao/SPEC_LOTE_BATELADA_VOLUMES_BLADDER.md` — plano aprovado, impactos, critérios e evidências.
2. `bladder/services.py` — validações, delegação para um evento, volumes na DR e reconciliação.
3. `bladder/forms.py` — validação do POST e lote único normalizado.
4. `bladder/views.py` — utilizar formulário e anunciar quantidade real de volumes.
5. `bladder/templates/bladder/includes/modal_movimentacao_estoque.html` — um campo de lote e ajuda/JS por volumes.
6. `bladder/tests.py` — 19 testes A–G e complementares.
7. `test_dr201_suite.py` — ensaio real atualizado, balanceado e compatível com console Windows.
8. `Instrucoes.txt` — regra operacional antes/agora, execução e evidências.

Não há alterações em models, migrations, Google Forms, cabeçalho da DR, deploy, permissões ou outros módulos. Os bancos/linhas de teste acima são evidência operacional local/remota e não são arquivos versionados.

### Suíte completa: baseline anterior à implementação

`python manage.py test --noinput` executado antes de qualquer alteração de código: **622 testes em 594,409 s, 16 falhas, nenhum erro**. As falhas são expectativas de textos antigos das telas, em testes preexistentes; não envolvem a movimentação por lote/volumes e não foram modificadas para mascarar o resultado. Lista integral observada na saída dessa execução:

- `bladder.tests.BladderBloco1ChaoDeFabricaTestCase.test_apenas_um_botao_fechar_turno_no_topo`
- `bladder.tests.BladderBloco1ChaoDeFabricaTestCase.test_cards_grid_tablet_e_detalhes_tecnicos`
- `bladder.tests.BladderBloco1ChaoDeFabricaTestCase.test_menu_lider_completo`
- `bladder.tests.BladderBloco1ChaoDeFabricaTestCase.test_menu_operador_simplificado`
- `bladder.tests.BladderBloco3OrdensTestCase.test_fluxo_integrado_completo_16_passos`
- `bladder.tests.BladderComplementarPermissoesPerfisTestCase.test_04_operador_acessa_operador_turno`
- `bladder.tests.BladderEtapa3OperadorBoardTestCase.test_detalhes_tecnicos_modal_exibe_parametros_et029_reais`
- `bladder.tests.BladderEtapa3OperadorBoardTestCase.test_operador_visualiza_quadro_operacional_do_turno`
- `bladder.tests.BladderEtapa5DashboardTestCase.test_dashboard_indicadores_principais_e_simplificacao`
- `bladder.tests.BladderViewsEndToEndTestCase.test_operador_turno_view_200`
- `bladder.tests.HomologacaoChaoDeFabricaFichaTecnicaTestCase.test_01_operador_acessa_chao_de_fabrica`
- `bladder.tests.HomologacaoChaoDeFabricaFichaTecnicaTestCase.test_05_card_operacional_simplificado_e_especificacoes_na_ficha_tecnica`
- `bladder.tests.HomologacaoChaoDeFabricaFichaTecnicaTestCase.test_08_fechamento_unico_do_turno_no_topo`
- `bladder.tests.PassagemTurnoBladderTestCase.test_33_fechamento_turno_integracao_e_independencia_producao`
- `bladder.tests.PassagemTurnoBladderTestCase.test_34_responsividade_e_tablet_touch_friendly`
- `bladder.tests.PassagemTurnoBladderTestCase.test_35_operador_acessa_tela_recados_criados`

**Execução padrão posterior:** `python manage.py test --noinput` → 641 testes em 586,366 s, **17 falhas e nenhum erro**: as mesmas 16 acima mais `production.test_pcp_system.PCPAdvancementTestCase.test_http_post_edit_plan_returns_302` (HTTP 200 em vez de 302). Esse teste passou isolado (1 teste/0,148 s) e combinado com os novos testes (34 testes/1,297 s), sem alterar qualquer arquivo do PCP.

**Diagnóstico completo adicional:** todos os 641 testes foram repetidos em 21,529 s, acelerando somente o hash de senhas das fixtures para MD5 dentro do processo temporário de teste, sem mudar settings, autenticação ou dependências do produto. Resultado: **16 falhas, nenhum erro**, exatamente os mesmos nomes da baseline; zero falhas adicionais e nenhum erro de formulário PCP capturado. Não se atribui causa confirmada à ocorrência PCP não reproduzida. O comando padrão com 17 falhas continua registrado e não foi substituído pelo resultado do diagnóstico.

Comparação programática dos nomes confirmou os resultados. Não há falhas críticas reproduzidas da nova regra: 19/19 testes passaram no Backend, QA e execução combinada; ensaios reais passaram. A suíte global permanece com falhas e não é declarada verde. QA aprovou a publicação neste escopo com essa ressalva, preservando o PCP conforme solicitação.

Checagens finais do agente principal: `python manage.py check` sem problemas; `python manage.py makemigrations --check --dry-run` sem mudanças. Revisão de diff limitada aos oito arquivos listados, sem erros de whitespace. Branch `main`; `git fetch origin main` confirmou alinhamento antes do commit. Publicação solicitada: mensagem `Bladder: adaptar estoque para lote por batelada e volumes`, stage explícito desses oito arquivos e `git push origin main`; SHA e confirmação efetiva serão informados na resposta final.

Artefatos adicionais locais: `logs/spec_volumes_diagnostic_suite.py` e `logs/spec_volumes_test_diagnostic.log`. O diagnóstico instrumenta somente a resposta de edição PCP em testes, para exibir erros se HTTP200; o produto não foi modificado. O servidor temporário de validação foi encerrado, e a sessão temporária foi excluída. Arquivos adicionais lidos na investigação: `production/test_pcp_system.py`, `production/views.py`, `production/forms.py` e trechos de `production/services.py`, sem qualquer alteração.

---

### Adendo QA — comparação da suíte completa e diagnóstico PCP

A suíte padrão posterior executada pelo agente principal rodou **641 testes em 586,366 s**, com **17 falhas e nenhum erro**: as mesmas 16 assertions de textos da baseline e uma falha adicional em `production.test_pcp_system.PCPAdvancementTestCase.test_http_post_edit_plan_returns_302` (HTTP 200 em vez de 302). Essa ocorrência adicional não foi tratada como falha preexistente comprovada nem escondida.

O agente principal repetiu o teste PCP isolado (**1 teste, 0,148 s, OK**) e a combinação dos 19 testes novos com os 15 da classe PCP (**34 testes, 1,297 s, OK**). A revisão QA não encontrou alteração global de timezone, settings ou cache, mocks não restaurados ou threads de sincronização pendentes nos novos testes; eles usam `TestCase` e patches limitados ao teste. O form e os serviços de edição PCP não foram alterados nesta demanda.

Para repetir a ordem global sem os custos de hash de senha, o agente principal executou os **641 testes novamente**, com MD5PasswordHasher somente no processo temporário de diagnóstico (sem alterar configuração, código produtivo ou dependências). Resultado: **21,529 s, mesmas 16 falhas da baseline, nenhuma falha PCP**. `logs/spec_volumes_test_diagnostic.log` foi conferido pelo QA. A causa da ocorrência PCP não foi determinada; classificá-la como **não reproduzida**, sem afirmar uma causa temporal ou atribuí-la à mudança de estoque. A suíte completa não está inteiramente verde devido às 16 falhas anteriores documentadas.

**Parecer QA mantido para publicação no escopo:** 19 testes críticos da alteração aprovados, integração real aprovada, nenhuma falha nova reproduzida nos ensaios complementares. Não há justificativa para modificar PCP, expressamente fora do escopo. Arquivos adicionais lidos pelo QA nesta investigação: `production/test_pcp_system.py`, `production/forms.py`, `production/views.py`, `production/services.py` e `logs/spec_volumes_test_diagnostic.log`; busca de isolamento de testes em `production/tests.py` e `maintenance/tests.py`.

---

# 🤖 USO COM SUBAGENTES

## Ordem obrigatória

### 1. Arquiteto

Ler código e constituições, mapear impacto, criar esta SPEC e aprovar tecnicamente o plano mínimo. Não implementar código. Aprovação acima registrada.

### 2. Backend

Implementar somente o plano aprovado, reutilizando serviços e o ambiente existentes; alterar o mínimo e fornecer evidências.

### 3. QA

Validar duplicações, permissões, consistência, histórico, reconciliação, APPEND e regressões após Backend. Comunicar falhas e exigir correção de testes críticos antes de publicação.

---

## 🚨 REGRA DE PARADA

Se detectar duplicação de código, múltiplos ambientes/projetos ou implementação paralela: parar imediatamente e corrigir. Os três papéis são sequenciais.

---

# 🧠 PRINCÍPIO FINAL

> Alterar o mínimo possível para resolver o problema com segurança.

Segurança > velocidade. Clareza > complexidade. Consistência > criatividade.
