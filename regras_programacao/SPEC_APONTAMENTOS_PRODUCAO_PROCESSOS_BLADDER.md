# SPEC — APONTAMENTOS DE PRODUÇÃO POR PROCESSO NO BLADDER

Início: 16/11/2026; complemento final: 17/11/2026. Abordagem SPEC-DRIVEN. Diagnóstico e plano anteriores à implementação.
Status: arquitetura aprovada antes da implementação; Backend concluído e QA validado em banco temporário. Resultados e falhas preexistentes na seção12. Migration operacional pendente; sem deploy.

## 1. CONTEXTO

Evolução do app Django `bladder` existente em `/bladder/operador/`, para operadores regulares ativos, apoio autorizado no dia e liderança Bladder. Reaproveitar escala, OP, produtos, fechamento único, ledger de pendências e auditoria. A autorização do pedido abrange implementação e testes isolados; não abrange deploy, commit, push, migração de banco operacional nem integrações reais.

Documentos normativos: `constitution.md`, `Instrucoes.txt`, `regras_programacao/SPEC_TEMPLATE.md` e pedido anexado. A regra nova de registrar execução durante o turno substitui, neste escopo, a orientação histórica de manter o quadro somente para consulta. O fechamento único permanece.

## 2. PROBLEMA ATUAL E DIAGNÓSTICO DO ARQUITETO

### 2.1 Modelos existentes e relacionamentos

| Modelo | Papel atual / vínculos |
|---|---|
| ProcessoBladder | Código único, tipo, ordem visual e máquina opcional `maintenance.Machine`. |
| ProdutoBladder | Catálogo ET.029, modelo/medida, parâmetros teóricos; vínculo opcional ao catálogo local de Produção e saldo físico separado. |
| OrdemProducaoBladder | FK processo/produto opcional; data/turma; demanda nova, saldo incorporado, meta e realizado; recursos; estados PENDENTE, EM_EXECUCAO, CONCLUIDA, PARCIAL, CANCELADA. |
| ApontamentoTurnoBladder | FK OP/operador/fechamento opcional; turma/data, início/fim, quantidade inteira e ocorrências. Pode representar início, execução antiga ou consolidado de fechamento; não distingue hoje essas origens. |
| HistoricoApontamentoBladder | Correção de quantidade/situação, anterior/novo, autor, justificativa e momento; faltam parâmetros e amostras. |
| FechamentoTurnoBladder | Cabeçalho único por data/turma, operador, data/hora, status e observações. |
| ItemFechamentoTurnoBladder | Snapshot OP/meta/realizado/saldo/situação, categorias M2M e descrição. Único por fechamento/OP. |
| SaldoPendenteBladder | Ledger FK OP origem/produto/fechamento; quantidade, estado e OP destino; incorporação exclusivamente escolhida pela liderança. |
| AtividadeTurnoBladder | Tarefa flexível FK tipo/processo/máquina/produto, quantidade opcional, pendente/concluída/cancelada, autoria, conclusão e fechamento. Não possui hoje vínculo rastreável com execução de extrusão. |
| HistoricoProgramacaoBladder | Eventos de criação, reprogramação, cancelamento, conclusão e parcial de OP. |
| MovimentacaoEstoqueBladder | Ledger físico com lote textual, quantidade de volumes, idempotência e sincronização DR-201 independente. |

### 2.2 Registros reais dos processos (somente SELECT no `default` local)

Consulta ORM realizada em 16/11/2026; nenhum seed, migrate ou alteração de dados foi executado.

| ID atual | Código estável | Nome | Tipo | Máquina ID / nome | OPs / apontamentos existentes |
|---|---|---|---|---|---|
| 1 | 01 | Prensa de Vulcanização 01 | PRENSA | 408 / PRENSA DE BLADER 01 | 22 / 3 |
| 2 | 02 | Prensa de Vulcanização 02 | PRENSA | 409 / PRENSA DE BLADER 02 | 14 / 4 |
| 3 | 03 | Extrusão de Bladder | EXTRUSAO | 419 / EXTRUSORA DE BLADDER 02 | 7 / 0 |
| 4 | 04 | Extrusão de Apex | EXTRUSAO | Sem vínculo | 6 / 1 |
| 5 | 05 | Anéis de Vedação | ACABAMENTO | Sem vínculo | 1 / 0 |
| 6 | 06 | Manuseio de Tarugo | MANUAL | Sem vínculo | 6 / 3 |

Os IDs coincidem hoje com os números dos códigos, mas não constituem regra. Resolver formulários pelo `ProcessoBladder.codigo` único (`01` a `06`), nunca por PK, nome ou tipo genérico. Tipos não distinguem Bladder de Apex. Processo 06 já tem históricos reais: não apagar, migrar por coincidência de produto/data ou reassociar suas OPs.

### 2.3 Fluxo REAL de fechamento e origem das quantidades

1. A liderança cria a OP em `criar_ordem_producao_com_saldos`; não existe criação automática de OP de manuseio nesse serviço. Saldo só entra por IDs escolhidos pelo líder.
2. Quadro operacional mostra OPs do dia e informações técnicas. O template não oferece o novo formulário de produção.
3. Rotas antigas de início/apontamento ainda existem. `registrar_ou_atualizar_apontamento` soma quantidade na OP e pode marcar CONCLUIDA ao atingir a meta; isso é inadequado para a nova execução, que deve permitir excedente até fechar o turno.
4. `fechamento_turno` lê quantidades totais digitadas. O template inicializa os campos com a META: corrigir para realizado apurado ou zero, sem inventar produção.
5. `executar_fechamento_turno` valida escala/perfil, unicidade data/turma, presença de todas OPs, déficit e categorias/descrição; trava OPs e cria cabeçalho/item/ledger/histórico atomicamente no default.
6. Apesar de docstring antiga mencionar limite, o código permite sobreprodução. Preservar o comportamento real.
7. O fechamento sobrescreve `OP.quantidade_realizada` com o POST e SEMPRE cria um novo `ApontamentoTurnoBladder` consolidado com esse mesmo total. Somar apontamentos novos a esse consolidado duplicaria a produção: este é o principal ponto de integração.
8. Quando não existem detalhes, o fechamento manual é a origem histórica da apuração. Preservar o caminho legado sem atribuir às execuções novas parâmetros que não foram informados.

### 2.4 Dashboard, relatórios e Excel

Dashboard e calendário usam `OP.quantidade_realizada`. Relatório e Excel usam os itens de fechamento quando existem, com fallback para OP por período/turma/produto; nunca somam detalhes com snapshots. Manter OP como cache compatível dos totais de execução e Item como snapshot auditável no fechamento, alimentados pela mesma apuração. Não adicionar os manuseios ao total da extrusão.

Anéis exigem sinalização explícita de quantidade não apurada e exclusão dos indicadores quantitativos relativos aos novos registros sem quantidade; apresentar essa limitação ao leitor. Não converter um registro de qualidade em uma unidade, nem concluir meta/gerar saldo fictício a partir dessa suposição. Históricos quantitativos antigos permanecem como registrados.

### 2.5 Pendências, permissões e auditoria

Déficit quantitativo permanece `max(0, meta-realizado)` por OP. Não alterar demanda/meta automaticamente. Qualidade Bom/IA/Lixo não muda contagem de unidades vulcanizadas nem estoque. Apoio não muda titularidade A/B.

`bladder/decorators.py` distingue liderança, operador com grupo e perfil ativo A/B e apoio ativo; staff genérico não tem acesso. Reutilizar essas funções nas views e validar novamente no serviço: operador regular deve pertencer à turma do dia, apoio deve estar escalado na data, líder mantém exceção administrativa para apontamento. O fechamento operacional mantém restrição atual para líder sem perfil operacional.

Correção antiga valida autoria/data na view mas não impede adequadamente turno já fechado no mesmo dia; o serviço atual não valida perfil nem fechamento e só altera quantidade/OP. Novos detalhes precisam de validação central, histórico integral antes/depois e sincronização de quantidades após correções. Admin atual permite editar/apagar apontamentos; fechar esse caminho para registros novos e preservar histórico imutável.

## 3. OBJETIVO

Registrar dados efetivos por processo diretamente dos cards, com identificação obtida no servidor e sessão, múltiplas execuções parciais, vulcanização unitária e manuseio dependente de extrusão confirmada, sem duplicar produção ou estoque.

## 4. ESCOPO E PROPOSTA DE ARMAZENAMENTO

### 4.1 Reutilização do agregado existente

Ampliar `ApontamentoTurnoBladder`, preservando os registros atuais como LEGADO. Acrescentar discriminador de origem/tipo para identificar execução por processo versus consolidado antigo, código/processo executado e identidade de produto/equipamento obtidos da OP no servidor (FKs opcionais e snapshots quando necessário para preservar a identificação histórica). Para manuseio, OP de origem é a OP03, processo executado é 06 e produto vem da extrusão.

Parâmetros serão campos estruturados opcionais no apontamento, validados por formulários específicos e serviço: tempo, pressão, temperatura, velocidades, TCU1..4, condição, lote produto, volume, matéria-prima, lote material e médias. Não guardar esses dados exclusivamente em observações ou JSON. Valores numéricos `DecimalField` com precisão definida e positivos quando medição exigir; quantidade de peças inteira positiva. Lotes/volume identificador em CharField preservando zeros à esquerda; volume não equivale a quantidade física nem é único por lote.

Quantidade não comprovada precisa de marca explícita (`quantidade_apurada`/equivalente) no apontamento e consolidação; caso se preserve o campo inteiro legado com zero técnico, a marca distingue obrigatoriamente desconhecido de zero produzido. Toda interface, apuração e relatório deve respeitar essa diferença. Alternativa de quantidade nullable pode ser adotada se todos consumidores forem tratados sem quebrar histórico. Não fabricar quantidade para anéis ou contar manuseio como produção.

Chave de idempotência única opcional, nula nos históricos, obrigatória nas novas criações. Formulário recebe chave vinculada à sessão/OP/tipo, mantida após erro. Novo GET gera nova chave. Repetição da mesma chave retorna o registro salvo sem novo incremento; reuso em outro contexto deve ser rejeitado.

### 4.2 Dependência extrusão/manuseio

Adicionar relação OneToOne opcional do apontamento de manuseio ao apontamento de extrusão (`extrusao_origem`, PROTECT). Justifica-se para rastreio inequívoco e exclusividade também no banco. Apenas origem de processo03, execução nova efetivamente salva e quantidade positiva pode liberar manuseio. Apex, apontamento de início/zero, OP sem execução e consolidado legado sem parâmetros de execução não liberam.

Não criar OP nem marcar tarefa executada na liberação. Listar pendências por consulta às extrusões03 sem filho06; a ausência do filho representa pendente, dispensando duplicação em outro modelo de tarefas. Cada parcial libera seu próprio conjunto. O formulário de manuseio usa a relação selecionada no servidor, não uma OP06 escolhida pelo navegador.

Pendências antigas seguem visíveis em lista própria do quadro de turnos seguintes, com data/OP/autor originais e execução no turno atual autorizado, sem reabrir a produção original. Após fechar o turno atual não aceitar novo manuseio nesse turno. OP cancelada não é destino válido; fechamento anterior da extrusão não apaga a pendência de etapa.

### 4.3 Amostras normalizadas e médias

Criar somente um modelo adicional justificado, `AmostraManuseioBladder` (nome final equivalente permitido): FK apontamento, sequência, diâmetro, comprimento e peso decimais; unicidade apontamento/sequência. Uma tabela filha suporta quantidade variável sem campos fixos repetidos.

Número esperado `ceil(quantidade_extrusada/10)`, com mínimo1 para positivo; zero não libera. Arredondamento para cima é proposta provisória EXPRESSAMENTE autorizada no pedido, ainda pendente de confirmação do cliente. Exigir exatamente as N amostras completas e três medições independentes por amostra. Não confiar em TOTAL_FORMS, quantidade herdada, médias nem IDs enviados. Limites de formset devem evitar truncamento silencioso em amostragens grandes.

Backend usa Decimal para recalcular separadamente as três médias e persistir amostras+pai na mesma transação. Exibir média de diâmetro/comprimento com duas casas e peso com precisão compatível (três casas), preservando precisão individual adequada. Unidade comprovada no cadastro: diâmetro mm, comprimento de extrusão cm, peso kg, tempo de vulcanização min. Não atribuir unidade inventada a pressão, velocidade ou temperatura sem cadastro confirmado; rotular somente nome e eventual aviso de unidade não cadastrada. Referência teórica permanece consulta, nunca inicializa execução.

### 4.4 Auditoria e correções

Reaproveitar `HistoricoApontamentoBladder` acrescentando snapshots anteriores/novos opcionais (JSON estruturado de auditoria, com decimais serializados textualmente e amostras completas). A fonte operacional continua os campos relacionais. Guardar autor, momento e justificativa obrigatória, sem apagar registro original ou eventos antigos.

Operador corrige apenas próprio registro no mesmo turno aberto; liderança corrige além desse prazo conforme regras. Não permitir trocar OP/processo/produto/equipamento/origem na correção. Quantidade vulcanizada permanece1; anéis permanece não apurada. Alteração de quantidade de extrusão após manuseio salvo será bloqueada conservadoramente com mensagem clara para não invalidar tamanho/amostras/quantidade herdada. Parâmetros de extrusão e medições de manuseio podem ser corrigidos com auditoria.

Correção quantitativa pós-fechamento autorizada à liderança exige reconciliar cache OP, item e ledger na mesma transação e registrar antes/depois. Se saldo já foi incorporado em outra OP, bloquear alteração quantitativa e orientar acerto pela liderança sem reescrever OP destino automaticamente; não permitir inconsistência silenciosa. Correções de parâmetros sem impacto quantitativo não refazem ledger. Rotas antigas de quantidade devem encaminhar detalhes para o novo fluxo ou rejeitar bypass. Admin dos novos detalhes/amostras é somente leitura e sem exclusão.

## 5. FORA DE ESCOPO

Novo projeto, app ou ambiente virtual; refatoração global; escrita/migration no scada; alteração de DR-201/APPEND/colunas/reconciliação; envio WhatsApp; movimentação automática de estoque; deploy/commit/push; modificação de registros reais nos testes; backfill de parâmetros não conhecidos; vincular históricos06 por produto/data.

## 6. REGRAS OBRIGATÓRIAS

MVT; validações de negócio em forms/services; ORM e transações `default`; CSRF; identidade/autoria no servidor; apenas um fluxo sequencial Arquiteto → Backend → QA, sem implementações paralelas. Migrations aditivas com novos campos opcionais/defaults, preservando históricos. Banco temporário Django nos testes e mocks para integrações externas.

## 7. REGRAS DE NEGÓCIO POR PROCESSO

| Código | Formulário confirmado | Regra de quantidade / dependência |
|---|---|---|
| 01 e 02 | Produto automático; tempo, pressão, condição exatamente Bom/IA/Lixo, lote e volume obrigatórios. | Uma unidade por apontamento, prensa própria; tempo e pressão sempre vazios no novo formulário, exigidos a cada unidade. Não completar OP automaticamente ao atingir meta; permitir sobreprodução enquanto turno aberto. |
| 03 | Quantidade produzida, temperatura, velocidade esteira, velocidade fuso e TCU1..4. | Inteiro positivo efetivo; múltiplos parciais com parâmetros independentes. Após salvar, liberar manuseio específico sem OP nova. |
| 04 | Quantidade produzida, temperatura geral, velocidades e TCU1..4. | Inteiro positivo efetivo; nenhuma dependência06. |
| 05 | Tempo, temperatura, pressão, condição exatamente Bons/Parcialmente Bons/Ruins e observação. Produto automático se existir. | Sem quantidade/granularidade presumida; somente parâmetros e qualidade. Quantidade não apurada deve aparecer explicitamente, sem unidade fictícia. |
| 06 | Produto/quantidade herdados, lote produto, matéria-prima e lote material distintos, N conjuntos diâmetro/comprimento/peso, médias e observações. | Apenas filho único de execução03 válida. Não incrementa quantidade da OP nem produção de Bladders. |

Campos numéricos inválidos, não finitos, negativos e precisão fora dos limites geram erro amigável com valores preservados. Formulário específico é escolhido no backend pelo processo da OP; não aceitar parâmetros de outro processo por manipulação do POST.

### 7.1 Fonte única e fechamento sem duplicação

Para OP quantitativa com novas execuções, total = soma somente dos detalhes quantitativos válidos da própria OP. `OP.quantidade_realizada` é cache atualizado atomicamente na criação/correção. Novo fluxo mantém OP em execução até fechamento, mesmo acima da meta. Não combinar silenciosamente total legado com nova origem: casos de mistura devem ser bloqueados ou reconciliados explicitamente, nunca inferidos.

No fechamento, backend recalcula total de detalhes, compara/rejeita quantidade divergente do navegador e vincula esses apontamentos ao fechamento, criando somente o Item snapshot. Não criar outro apontamento consolidado com a mesma produção. Manuseio continua fora da soma e seu fechamento operacional pode ser diferente da extrusão.

Para OP legada (`exige_execucoes=False`) sem detalhes novos, manter fechamento manual histórico; campo inicia pelo realizado existente/zero, nunca pela meta, e informa a transição. Novas OPs01–05 recebem `exige_execucoes=True` no serviço oficial/Admin, sem opção de rebaixar o marcador. Nelas, fechar sem detalhes significa quantidade zero; qualquer valor positivo exige execuções específicas e não pode vir do formulário manual, serviço legado ou correção de início0. A primeira execução contextual também promove OP legada paraTrue. Esse caminho histórico nunca constitui prova para liberar manuseio novo. OP06 não admite nova execução pelo fallback: apenas consolida exatamente a quantidade positiva previamente comprovada nos registros históricos; novos manuseios exigem a fonte03 e não criam OP06. Para anéis com registro novo não quantitativo, fechamento registra execução operacional e marca quantidade não apurada, sem gerar saldo quantitativo fictício; metas históricas permanecem visíveis como referência sem interpretação inventada. OP05 legada sem registro novo mantém compatibilidade histórica, com ressalva de que o novo formulário não produz quantidade.

Déficit quantitativo continua exigindo categorias e descrição; sobreprodução permitida; idempotência de fechamento e incorporação pelo líder intactas. Consulta de indicadores ignora registros não quantitativos para contas em unidades e sinaliza separadamente tais OPs. Não somar extrusão e manuseio.

### 7.2 Concorrência

Chave única e OneToOne protegem repetições no banco. Serializar criação/correção/fechamento pela mesma OP antes de calcular total e consultar turno fechado, sempre na mesma ordem de locks. `select_for_update` atende MySQL, mas não constitui lock em SQLite: usar escrita ORM prévia no agregado antes das leituras críticas e/ou estratégia de repetição controlada de erro de lock fora da transação, com teste real de conexões concorrentes. Sem SQL específico, lock apenas em memória ou promessa de segurança baseada só em botão desabilitado. Erro de concorrência deve ser claro e permitir reenvio da mesma chave.

## 8. CRITÉRIOS DE ACEITAÇÃO E TESTES AUTOMATIZADOS

Cobrir integralmente cenários A–K do pedido:

- A/B/C: três vulcanizações (Bom/IA/Lixo), total3, tempo/pressão novos vazios e obrigatórios, duas prensas com equipamentos corretos, nenhuma movimentação física/integração externa.
- D/E: extrusão27/meta30, parâmetros e meta preservados, liberação só depois do save; acesso direto sem origem válido negado; nenhuma OP adicional.
- F/G: 30→3 amostras e31→4; médias Decimal corretas; quantidade1,10,20,50,100; zero bloqueado; parciais20+30 com manuseios2/3 e totais50 sem duplicação.
- H/I: Apex sem manuseio; três condições dos anéis, parâmetros/observação e quantidade não apurada; rejeitar classificações trocadas.
- J: fechamento com detalhes sem consolidado duplicado, total imutável contra POST adulterado, déficit3, categorias/descrição, excedente permitido, fallback legado e idempotência.
- K: anônimo/externo/staff/inativo/turma errada/apoio fora de escala, OP ausente, processo adulterado, CSRF, chave repetida, concorrência real, números inválidos, correção própria/alheia/após fechamento, extrusão com manuseio, proteção admin e históricos sem campos novos.
- Regressões: estoque/DR201 mantidos via mocks; relatório/Excel/cache iguais aos snapshots; pendências não incorporadas automaticamente; manutenção, PCP/SCADA e matrizaria preservados.

## 9. RISCOS E REGRAS PENDENTES DO CLIENTE

1. Arredondamento de amostragem para cima é provisório e documentado.
2. Quantidade/granularidade por apontamento de anéis permanece pendente. Implementação registra somente o confirmado e identifica não apurada, sem distribuição por condição.
3. Unidades não cadastradas de pressão, temperaturas e velocidades permanecem pendentes; não inventar etiquetas de engenharia. Diâmetro/comprimento/peso usam unidade do cadastro ET.029.
4. Equipamentos ausentes nos códigos04/05/06 permanecem ausentes; não associar máquina por suposição.
5. Quantidade corrigida com manuseio já salvo ou saldo incorporado é bloqueada conservadoramente; procedimento de retificação dessas dependências requer decisão operacional futura.
6. Não há validação MySQL real autorizada nesta sessão: portabilidade será revisada em ORM/migration, e teste de concorrência local SQLite não equivale a prova em produção MySQL.
7. A documentação registra falhas preexistentes de textos na suíte. Capturar linha de base real antes das mudanças e comparar nomes/resultados, sem declarar suíte global verde indevidamente.

## 10. PLANO SEGURO E LISTA MÍNIMA DE ARQUIVOS

### Complemento aprovado antes da implementação: transição histórica explícita

Revisão final identificou que o fallback manual sem detalhes permitia lançar quantidade em prensa sem parâmetros individuais e concluir OP06 sem extrusão. Dois testes reproduziram o bypass06. O agente principal aprovou este complemento incremental: acrescentar `OrdemProducaoBladder.exige_execucoes` com defaultFalse para preservar OPs históricas na migration aditiva ainda não aplicada; criação pelo serviço oficial/Admin marcaTrue nos códigos01–05; primeira execução contextual também promove uma OP legada paraTrue. O marcador é somente servidor e não pode ser reduzido por formulário ou Admin. OP marcada exige total igual à soma detalhada inclusive quando não há detalhes (zero), e os serviços legados não podem criar quantidade positiva/corrigir início0 para positivo nesse contexto. Início legado0 permanece compatível. Fallback positivo fica restrito a OP legadaFalse sem detalhes e será identificado na tela como transição histórica, sem reinterpretar registros antigos.

Código06 não cria nova OP nem admite nova execução por fechamento/serviço legado. Fechamento pode apenas consolidar quantidade histórica comprovada já existente, sem aumentá-la; correção redutora de histórico permanece auditável, mas aumento não gera nova etapa sem extrusão. Nova programação/Admin orientam criar a etapa a partir da execução03. Testes históricos de fechamento manual usarão fixtures explicitamente legadas com helper nomeado; testes atuais de criação HTTP/serviço/Admin e de registro unitário comprovarão o comportamento novo. Não haverá monkeypatch global do serviço ou enfraquecimento das asserções antigas.

Arquivos adicionais previstos: `models.py`/migration0011 (marcador aditivo), `services.py`/`producao.py` (criação, transição, apuração e bloqueios legados), `forms.py`/`admin.py` (proteção e orientação06), template de fechamento (readonly/aviso transição), testes focados e fixtures históricas explícitas; sem mudança de outros módulos ou banco operacional. Regenerar0011 com o `.venv` existente, executar checks, testes focados, diagnóstico global e ensaio relevante após o complemento.

1. Arquiteto conclui este diagnóstico/SPEC; agente principal revisa tecnicamente e registra decisão antes do Backend. Não exige confirmação humana adicional para implementação reversível já solicitada.
2. Backend amplia modelos e auditoria, cria única tabela filha e migration aditiva após0010. Não aplicar migration no banco operacional nesta tarefa; testes aplicam em banco temporário.
3. Backend adiciona formulários específicos e formset, serviços transacionais/idempotentes de execução, manuseio, correção e apuração, com proteção nos serviços antigos.
4. Backend integra fechamento e cache sem contagem dupla; anéis não quantitativos explicitados; revisão localizada em dashboard, relatório e Excel.
5. Backend adiciona botão nos cards, progresso, formulário contextual responsivo e pendências de manuseio, preservando Ficha Técnica/Recado; PRG de sucesso volta ao card/OP, tempo/pressão sem initial. Manuseio mostra médias ao digitar sem depender delas para salvar.
6. Backend protege admin e apresenta histórico/detalhes/correção para usuários autorizados; atualiza documentação com comportamento real.
7. QA roda testes obrigatórios, compara baseline, testa navegador celular/tablet e fluxo extrusão→manuseio no banco de testes, reporta falhas concretas. Apenas um implementador ativo em cada etapa.

Arquivos previstos (ajuste técnico de nomes permitido, sem expandir domínio):

- `bladder/models.py`: detalhes estruturados, vínculo da extrusão, marca de apuração, histórico e amostras.
- `bladder/migrations/0011_*.py`: adição necessária porque estrutura atual não armazena parâmetros, relação única, idempotência nem amostras. Sem remoção de campos/registros, backfill fictício ou mudanças em estoque.
- `bladder/forms.py` ou arquivo focal de forms no app: formulários por processo e amostras.
- `bladder/services.py` e, para manter foco, módulo próprio dentro do app (`producao.py`/equivalente): execução/apuração/correção/locks, integração pontual no fechamento e guardas legadas.
- `bladder/views.py`, `bladder/urls.py`: rotas contextualizadas e contexto de progresso/pendências; proteção das rotas antigas e relatórios afetados.
- `bladder/admin.py`: somente leitura nos novos registros e auditoria.
- `bladder/templates/bladder/operador_turno.html`, `fechamento_turno.html`, `ordem_detalhe.html`, formulário(s) de execução/correção e detalhes: UX, não apurada, histórico e navegação segura.
- `bladder/templates/bladder/relatorios.html` e, se necessário, dashboard/lista: ressalvas quantitativas compatíveis.
- `bladder/test_apontamentos_producao.py` (ou equivalente), ajustes de testes antigos somente se expectativa tiver sido substituída explicitamente pelo pedido.
- `scripts/validar_apontamentos_bladder.py`: ensaio opcional com `StaticLiveServerTestCase`, banco temporário e Edge/Playwright já existente no .venv.
- `Instrucoes.txt` e esta SPEC: documentação e evidências finais.

## 11. VALIDAÇÃO E ENSAIO DE INTERFACE

Usar exclusivamente `.venv/Scripts/python.exe` existente:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test bladder --noinput
```

Regressão adicional conforme dependências: `maintenance`, `matrizaria` e testes de PCP/router/Bladder do app `production`, sem leituras SCADA reais. O settings existente troca alias scada para SQLite quando `test` consta em argv; preservar isolamento também no ensaio de navegador. Não executar harness DR-201 real nem WhatsApp real. Registrar comandos, contagens, nomes de falhas e logs.

Ensaio em375px e768px (e desktop como referência): card contém três ações, sem overflow; abrir cada processo e conferir campos; salvar vulcanização e reabrir vazia; enviar inválido e preservar valores; salvar extrusão30 e manuseio com3 medições, conferir médias/retorno; repetir POST; extrusão31 com4 medições; Apex sem etapa06; anéis sem unidade presumida; fechar com total apurado e déficit justificado. Conferir `/management/` e `/dashboard/` com usuário de teste autorizado. Capturas/logs somente em `logs/`, dados exclusivamente temporários.

## 12. EVIDÊNCIAS E ENTREGA

### Arquivos lidos pelo Arquiteto

- Pedido anexado `Pasted text.txt` (conteúdo fornecido no contexto principal).
- `constitution.md`, `regras_programacao/SPEC_TEMPLATE.md`, `Instrucoes.txt` (seções Bladder3713–4085 e4317–4405, incluindo regras históricas de fechamento e estoque; índice das demais menções).
- `implementation_plan.md` (plano antigo de outra feature; não será sobrescrito).
- `bladder/models.py`, `services.py`, `views.py` (fluxos operacionais, fechamento, dashboard, relatórios e Excel), `forms.py`, `decorators.py`, `urls.py`, `admin.py`, `tests.py` (fixtures e expectativas relacionadas).
- `bladder/templates/bladder/operador_turno.html`, `fechamento_turno.html`, `ordem_detalhe.html` (blocos relacionados).
- `bladder/management/commands/popular_processos_bladder.py`, `popular_tipos_atividade_bladder.py` (somente leitura, sem executar seeds).
- `bladder/migrations/0001_initial.py`, `0003_fechamentoturnobladder_and_more.py`, `0008_alter_ordemproducaobladder_produto_and_more.py`, `0010_whatsapp_confirmacoes_reais.py` (compatibilidade e dependências).
- `maintenance_project/settings.py` (seleção de banco/testes), `production/routers.py` (proteção SCADA), `scripts/validar_dashboard_matrizaria.py` (padrão de ensaio isolado existente).

### Estado na conclusão da arquitetura

Somente esta SPEC foi criada pelo Arquiteto. Consulta de processos reais somente leitura concluída. Linha de base `test bladder --noinput` já iniciada pelo agente principal com237 testes encontrados; aguardar resultado e anexar evidência. Branch inicial `main`, árvore inicialmente limpa conforme levantamento principal. Nenhum código, dado operacional, integração externa, migration aplicada, commit, push ou deploy realizado nesta etapa.

### Evidências finais

Revisão técnica aprovada pelo agente principal antes do Backend. Implementação e QA registrados abaixo, com inventário, resultados reproduzíveis e limitações; não se declara a suíte global inteiramente aprovada.

### Implementação Backend (16/11/2026)

- Plano aprovado tecnicamente pelo agente principal antes de iniciar o Backend; nenhum outro implementador ativo. Banco operacional não migrado.
- Modelos ampliados conforme proposta; `quantidade_apurada` em OP/apontamento/item distingue zero técnico de quantidade desconhecida. Históricos existentes recebem origem LEGADO e não são reinterpretados. Campos numéricos têm até12 dígitos/3 casas, médias diâmetro/comprimento2 casas e peso3 casas; lotes e volume textuais preservam zeros. Identidade contém FKs e snapshot de código/modelo/processo/equipamento.
- Migration `bladder/0011_apontamentos_producao_processos.py`: somente AddField/CreateModel/AddConstraint; uma tabela nova de amostras, relação OneToOne de manuseio, UUID único opcional nos antigos. Dependências0010 Bladder e0015 Manutenção devido FK equipamento já existente. Aplicada exclusivamente pelo runner no banco temporário de testes.
- Serviços focais em `bladder/producao.py`, formulários em `forms_producao.py`, views focais em `views_producao.py`; rotas registradas em `urls.py`. Os serviços de criação/correção revalidam dados independentemente da view. Formset exige exatamenteN amostras e backend recalcula médias sem usar JavaScript recebido. Aceita vírgula decimal na entrada; HTML type=number renderiza ponto.
- Concorrência: primeira operação crítica é UPDATE ORM `updated_at=F('updated_at')` nas linhas de configuração ativa de escala, sem mudar dados/timestamp. Essa escrita serializa transações de criação, correção e fechamento também em SQLite antes de leituras críticas; MySQL bloqueia as mesmas linhas. Configuração ativa deve existir para operar. Retentativa limitada em lock/deadlock fora da transação, locks de OP e unicidades UUID/OneToOne completam a proteção. Configuração de escala não é alterada pela operação.
- Novos GETs de produção geram token assinado com UUID, sessão, usuário, OP, código e extrusão de origem; mantém o token ao errar; reenvio retorna o registro existente, sem somar novamente. Tempo/pressão de nova vulcanização nunca possuem initial. Após salvar, PRG retorna ao card e seleciona a aba Atividades.
- Fechamento integra detalhes como única fonte; rejeita POST divergente, mantém cache OP e snapshot Item e vincula execuções sem consolidado duplicado. Fallback manual legado inicia no realizado/zero. Anéis sem apuração não geram ledger nem entram em indicadores quantitativos. Dashboard/lista/calendário/detalhe/fechamento explicitam não apurada; relatório exibe ressalva e Excel acrescenta aba específica nesses casos.
- Correção mantém snapshots de parâmetros e amostras, justificativa, autoria e momento. Líder pós-fechamento reconcilia total/item/ledger; saldo zerado fica preservado como CANCELADO, sem apagar ledger. Quantidade de extrusão com manuseio ou saldo já incorporado/encerrado não é alterada. Rotas legadas redirecionam registros novos. Guardas impedem encerramento individual, reprogramação e cancelamento de OP com execução nova, conservando origem/produção real. Essas restrições são decisões técnicas conservadoras para não apagar produção das contas nem criar dois fluxos de encerramento.
- Admin protege edição/exclusão de apontamentos, amostras, auditoria, fechamento e inline; OP e ledger com execução não podem ser editados diretamente. Consulta permanece. Históricos não receberam parâmetros fictícios.

Arquivos lidos pelo Backend: SPEC/pedido/constitution e contexto Instrucoes do arquiteto; `bladder/models.py`, `services.py`, `forms.py`, `decorators.py`, `views.py`, `urls.py`, `admin.py`, `tests.py`, templates operador/fechamento/detalhe/dashboard/lista/calendário/relatórios/base; migrations anteriores para dependências; `maintenance_project/settings.py` e fixture de testes existente via contexto.

Arquivos alterados/criados e motivo:

- `bladder/models.py`, `migrations/0011_apontamentos_producao_processos.py`: estrutura aditiva descrita acima.
- `bladder/forms_producao.py`, `producao.py`, `views_producao.py`, `urls.py`: validação específica, persistência transacional e quatro rotas.
- `bladder/services.py`: integração de fechamento e guardas contra bypass/mistura de fontes.
- `bladder/views.py`: contextos de progresso/etapas/histórico, redirecionamento legado e exclusão explícita de quantidades desconhecidas dos relatórios/Excel.
- `bladder/admin.py`: consulta e proteção dos caminhos de escrita sem auditoria.
- `bladder/templates/bladder/producao_form.html`, `producao_detalhe.html`, `producao_erro.html`: registro contextual, correção, médias, histórico e erros amigáveis.
- `bladder/templates/bladder/operador_turno.html`, `fechamento_turno.html`, `ordem_detalhe.html`: card/botão, etapas pendentes, total apurado e consulta.
- `bladder/templates/bladder/dashboard.html`, `ordens_lista.html`, `cronograma_calendario.html`, `relatorios.html`: quantidade não apurada corretamente identificada.
- `bladder/test_apontamentos_producao.py`: cenários A–K e concorrência com conexões reais.
- `Instrucoes.txt` e esta SPEC: documentação operacional e rastreabilidade da entrega.

Validações Backend finais: `manage.py check` sem problemas; `makemigrations --check --dry-run` sem mudanças; `git diff --check` limpo. `manage.py test bladder.test_apontamentos_producao --noinput`:32 testes aprovados em1,625s, incluindo proteção de cancelamento/reprogramação. Log `logs/apontamentos_bladder/backend_entrega.log`. Baseline original pelo agente principal:237 testes em369,233s,16 falhas sem erros; nenhuma alteração em testes antigos. QA deverá executar suíte completa, comparar falhas, ampliar concorrência e ensaiar navegador móvel/tablet no banco temporário.

### QA independente e decisões finais (16/11/2026)

Somente o QA manteve o fluxo de implementação após a entrega do Backend. Três pontos foram corrigidos e validados:

1. **Decimal após erro:** `NumeroOperacionalInput` normaliza vírgula para ponto também ao reapresentar um POST inválido. Sem isso, o navegador descartava `value="1,250"` em `type=number`. Aceitação de vírgula no backend continua; teste de formulário vinculado e ensaio Edge comprovam preservação de `1.250` e dos lotes com zeros. Números recebem `autocomplete="off"`; tempo/pressão de nova unidade continuam vazios.
2. **Prioridade dos campos:** Observações opcionais ficam após os campos obrigatórios e, no manuseio, após as amostras/médias. Nenhum parâmetro teórico inicializa execução.
3. **Fechamento somente de manuseios:** um turno posterior pode ter manuseio executado de extrusão anterior sem OP programada naquele dia. Nesse caso, o fechamento cria somente o cabeçalho, sem `ItemFechamentoTurnoBladder`, sem quantidade adicional, sem saldo fictício e sem nova OP; vincula os manuseios ao turno de execução. A tela mostra as etapas e permite confirmar. Turno sem OP e sem manuseio efetivamente salvo continua bloqueado. Autorização central complementa as guardas históricas (perfil ativo, turma, apoio escalado e FOLGA), mantendo restrição de líder puro e mensagem informativa da turma divergente. Fechamento passa pela mesma retentativa limitada dos demais serviços, fora da transação; teste força lock transitório sem duplicar registros.

Essa extensão é decisão técnica necessária para cumprir a continuidade de manuseio entre turnos; não altera a apuração quantitativa e não autoriza fechar dias totalmente vazios. Testes cobrem formulário/POST sem OP, vínculo original, turma errada, ausência de itens quantitativos e idempotência.

**Testes e evidências reais:** todos os comandos Python usaram o `.venv` existente.

| Rodada | Comando / escopo | Resultado |
|---|---|---|
| Linha de base original | `manage.py test bladder --noinput` antes do código |237 testes;16 falhas, nenhum erro;369,233s. `baseline_bladder.log`. |
| Backend | `manage.py test bladder.test_apontamentos_producao --noinput` |32 novos testes aprovados;1,625s. `backend_entrega.log`. |
| QA focado | `manage.py test bladder.test_apontamentos_producao bladder.tests.BladderViewsEndToEndTestCase.test_fluxo_operador_iniciar_e_apontar --noinput` |40 testes aprovados;3,952s.39 testes novos ao final e um teste antigo atualizado. `qa_focados_final.log`. O subcaso FOLGA também está confirmado na rodada global final. |
| Bladder padrão, após ajuste do teste legado | `manage.py test bladder --noinput` |272 testes; mesmas16 falhas da linha de base, nenhum erro;381,221s. `qa_bladder_final.log`. Essa rodada iniciou antes dos quatro testes finais de fechamento; eles foram cobertos pelo QA focado e diagnóstico final de276 testes Bladder. |
| Regressões com hash normal | `manage.py test maintenance matrizaria production --noinput` |488 testes;487 aprovados e1 falha de login Produção já existente;290,182s. `qa_regressoes.log`. |
| Estado final completo | `python logs/apontamentos_bladder/qa_suite_diagnostica.py` |764 testes;746 aprovados e18 falhas preexistentes, nenhum erro;36,875s. `qa_suite_diagnostica_final.log`. Hash MD5 somente nas fixtures desse processo temporário; settings e aplicação não foram alterados. |
| Comparação HEAD completa | `python logs/apontamentos_bladder/baseline_head_regressao.py --full` |725 testes originais;707 aprovados e as mesmas18 falhas;38,593s. Python e templates alterados carregados de `git show HEAD` em memória, grafo temporário de migrations até0010, sem copiar projeto. `qa_baseline_head_final.log`. |
| Navegador Edge | `python scripts/validar_apontamentos_bladder.py` |1 ensaio integral aprovado;28,201s. `qa_browser_final.log`;14 capturas de celular375px/tablet768px. |
| Verificações Django/Git | `manage.py check`, `manage.py makemigrations --check --dry-run`, `git diff --check` |Sem problemas, sem migrations faltantes e sem erros de whitespace. Avisos Git LF/CRLF não são falhas de diff. |

As18 falhas globais são as16 do Bladder já observadas antes das mudanças e duas da Produção: `production.tests.ProductionIntegrationTestCase.test_login_redirect_for_production_leader` (espera `/producao/`, recebe `/portal/`, política de múltiplos módulos já existente) e `production.test_pcp_system.PCPAdvancementTestCase.test_http_post_edit_plan_returns_302` (ocorrência intermitente200vs302 também reproduzida no HEAD). A regressão padrão488 não apresentou a ocorrência PCP; as rodadas globais com estado atual e HEAD apresentaram. Nenhum arquivo de Produção, Manutenção ou Matrizaria foi alterado.

`logs/apontamentos_bladder/qa_comparacao_falhas.json` preserva os nomes completos e a comparação automática: **nenhuma falha nova** entre os estados completos e nenhuma nova falha Bladder no comando padrão. Probes iniciais de HEAD com grafo/modelos incompatíveis foram descartados como diagnóstico inválido, não como falhas da aplicação. Os logs finais acima são as referências válidas. A suíte global permanece com falhas e não é declarada inteiramente verde.

Foi substituída somente uma expectativa histórica em `bladder/tests.py`, `test_fluxo_operador_iniciar_e_apontar`, que antes permitia lançar50 Bladders de uma vez e concluir a OP, contrariando expressamente o pedido. Agora comprova que a rota genérica redireciona sem produzir50, preserva início legado e salva uma unidade pelo formulário contextual assinado, mantendo OP em execução. No complemento17/11, as fixtures que exercitam o fechamento manual anterior passaram a ser explicitamente legadas, sem alterar suas asserções. As16 expectativas preexistentes que falham não foram modificadas.

Concorrência real SQLite: mesma chave produz um registro; chaves diferentes produzem dois registros e total correto; manuseios simultâneos com chaves diferentes geram somente um filho; registro versus fechamento não duplica produção. Ensaio Edge comprova os cinco contextos, Ficha Técnica/Recado preservados, campos de tempo/pressão vazios ao reabrir, erro de decimal com valores preservados,30→3 e31→4 amostras, média38,03mm, Apex sem manuseio, anéis sem quantidade, déficit justificado, fechamento sem consolidado duplicado, estoque intocado e HTTP200 em `/management/` e `/dashboard/` como administrador de teste. Nenhum erro JavaScript; sem overflow horizontal nas larguras ensaiadas. Capturas inspecionadas visualmente.

Arquivos adicionais lidos pelo QA: `bladder/forms_producao.py`, `producao.py`, `views_producao.py`, `test_apontamentos_producao.py`, integrações em `services.py`, `views.py`, `admin.py`, `models.py` e templates afetados; `scripts/validar_dashboard_matrizaria.py`; trechos pertinentes de `production/forms.py`, `views.py`, `services.py`, `test_pcp_system.py` e `tests.py` somente para diagnóstico da linha de base; logs originais/finais.

Arquivos adicionais alterados pelo QA e motivo: `forms_producao.py` (renderização decimal/autocomplete), `services.py` (fechamento sómanuseio, autorização e retentativa), `views.py` e `templates/bladder/fechamento_turno.html` (consulta/tela das etapas sem OP), `templates/bladder/producao_form.html` (ordem dos campos), `test_apontamentos_producao.py` (39 testes finais, concorrência e fechamento), `tests.py` (única expectativa substituída), `scripts/validar_apontamentos_bladder.py` (ensaio isolado reexecutável), esta SPEC e `Instrucoes.txt` (evidências).

**Parecer da rodada16/11 e limites:** escopo então aprovado no ambiente de testes SQLite;39 testes novos e ensaio de navegador aprovados, sem regressões novas nos conjuntos comparados. O complemento17/11 abaixo prevalece para comportamento e contagens finais. As pendências de negócio da seção9 permanecem: arredondamento provisório, granularidade dos anéis e unidades/faixas operacionais não cadastradas. Não houve ensaio MySQL real nem instalação no banco operacional. Migration0011 deve ser aplicada no processo autorizado de publicação antes de usar o novo código com dados operacionais. Branch `main`, alterações locais sem commit/push/deploy.

### Complemento final: transição, fechamento e proteção do Admin (17/11/2026)

Revisão final reproduziu dois bypasses06: nova OP sem extrusão podia receber produção positiva no fechamento, e início legado0 podia ser corrigido para positivo. `qa_bypass06_antes.log` contém duas falhas reproduzidas; `qa_bypass06_depois.log` confirma a correção. Foi executado o plano incremental aprovado na seção10:

- `exige_execucoes` é campo booleano aditivo de OP com defaultFalse na migration0011 regenerada, para preservar os registros existentes. Novas OPs oficiais/Admin01–05 recebemTrue; primeira execução contextual promove uma OP anterior. O marcador não participa do formulário nem da edição no Admin e não pode ser rebaixado pelo POST.
- OP marcada fecha somente com o total detalhado, inclusive zero quando não há execução. Os helpers legados não criam quantidade positiva nem convertem início0 em produção nesse contexto. O início0 permanece compatível. Vulcanização nova continua necessariamente unitária e com parâmetros informados a cada unidade.
- Criação de OP06 foi removida da seleção Nova OP/Admin e rejeitada no serviço, com orientação de manuseio dependente da extrusão salva. Históricos06 existentes são preservados: fechamento somente consolida o total já registrado, correções redutoras permanecem auditáveis e aumentos não fabricam nova execução sem origem03. Não houve reassociação por produto/data ou alteração de registros operacionais.
- Na nova OP e em OP marcada antes da primeira execução, o Admin deixa realizado, apuração e status somente para leitura, permitindo editar o planejamento. Não permite trocar processo marcado para06. Depois de haver execução, a edição direta permanece bloqueada. A criação força realizado0/statusPENDENTE e protege os campos contra POST adulterado.
- Compatibilidade é explícita: apenas OP legadaFalse sem detalhes conserva o fechamento manual positivo antigo, identificado na tela como transição histórica. Isso preserva dados e fluxo anteriores sem exigir parâmetros retroativos desconhecidos. Ao começar a registrar pelo novo formulário, a OP passa definitivamente a exigir detalhes. A liderança deve revisar OPs antigas ainda abertas conforme essa limitação de transição; novas programações não recebem o fallback.

As regressões antigas que preparam produção consolidada agora usam `criar_op_legada_para_regressao`/`marcar_fixture_como_op_legada`: o helper chama o serviço real e marca exclusivamente a fixture como histórica.69 chamadas de preparação em métodos de fluxo manual foram identificadas e substituídas explicitamente; o mapa está em `logs/apontamentos_bladder/qa_fixtures_legadas.json`. Não há monkeypatch do serviço de criação nem mudança de asserções para ocultar falhas. Criação HTTP atual e o fluxo unitário continuam usando serviço oficialTrue. O diagnóstico anterior às fixtures (`qa_transicao_antes_fixtures.log`) registrou as incompatibilidades, resolvidas pela identificação correta de dados históricos, não pelo enfraquecimento das regras novas.

Resultados finais do complemento, com o mesmo `.venv` e bancos temporários:

| Validação | Resultado e evidência |
|---|---|
| `manage.py test bladder.test_apontamentos_producao --noinput` |48 testes novos aprovados em2,485s; `qa_transicao_focados_17.log`. Inclui criação oficial01–05, prensas só com unidades detalhadas, HTTP sem rebaixar marcador, promoção de legado, bloqueios06 e proteções do Admin antes de executar. |
| Diagnóstico quatro módulos, hash MD5 só nas fixtures do processo |773 testes;755 aprovados e18 falhas preexistentes, nenhum erro;38,650s. `qa_transicao_apos_fixtures_17.log`; mesmos nomes da baseline HEAD725/18, sem falhas novas. |
| Edge `scripts/validar_apontamentos_bladder.py` |1 ensaio aprovado em29,460s; `qa_browser_transicao_17.log`. As cinco OPs agora são criadas pelo serviço oficial, têm marcadorTrue e fechamento readonly0 antes de qualquer execução; demais fluxos375/768px, parâmetros vazios, erro decimal, extrusão/manuseio, qualidade e fechamento permanecem aprovados.14 capturas atualizadas. |
| `manage.py check`, `makemigrations --check --dry-run`, `git diff --check` |Aprovados após regenerar0011; nenhuma migration adicional ou erro de whitespace. |

O agente principal concluiu o comando padrão final `manage.py test bladder --noinput` com hash normal:285 testes em363,237s,269 aprovados e as mesmas16 falhas da linha de base, nenhum erro. A comparação automática dos nomes confirmou nenhuma falha nova ou ausente. Evidência: `logs/apontamentos_bladder/entrega_bladder_padrao_17.log`. `qa_comparacao_falhas.json` está atualizado para773 casos e48 novos testes, com `novas_falhas=[]`. A suíte global continua com as18 falhas conhecidas e não é declarada inteiramente verde.

Inventário final:25 arquivos locais. Além dos arquivos já enumerados, `bladder/forms.py` restringe a nova programação06; `models.py`/migration0011 armazenam o marcador; `services.py`, `producao.py`, `admin.py` e template de fechamento executam as guardas de transição; `tests.py` identifica fixtures antigas; testes focados e script Edge comprovam o fluxo atual. Nenhum arquivo de outros módulos foi alterado. Branch `main`, sem commit/push/deploy e sem aplicação de migration no banco operacional. Parecer do complemento: aprovado nas validações concluídas, inclusive o comando padrão final; permanecem somente as pendências de negócio e ambiente já explicitadas.

## 13. Complemento visual dos cards ao atingir a meta (17/11/2026)

Na tela `/bladder/operador/`, cada card quantitativo com meta positiva mostra quantas unidades faltam antes do alvo. No total exato, exibe `META ATINGIDA`; acima dele, `META SUPERADA` e o excedente em unidades. Enquanto a OP com registros permanece aberta, o card informa que o fechamento do turno ainda é necessário. O botão Registrar Produção continua disponível até o fechamento; meta não muda status automaticamente. A informação não aparece em anéis com quantidade não apurada, metas zero nem OP histórica de manuseio06. A condição usa os totais reais da OP já persistidos, sem dados novos ou migração.

Validação concluída: `manage.py test bladder.test_apontamentos_producao bladder.test_acompanhamento --noinput` aprovou56/56 casos em4,386s, incluindo os dois novos cenários abaixo/exato/acima, OP ainda aberta, anéis, meta zero e manuseio histórico. O ensaio Edge existente aprovou1/1 em31,561s e conferiu cards em375/768px, sem overflow ou erro JavaScript; capturas `logs/apontamentos_bladder/meta-atingida-375.png` e `meta-atingida-768.png` foram inspecionadas. `manage.py check` e `git diff --check` aprovados. Nenhuma alteração de serviço, apuração ou fechamento.
