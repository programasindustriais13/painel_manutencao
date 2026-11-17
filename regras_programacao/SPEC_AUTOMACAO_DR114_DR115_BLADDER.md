# Automação DR.114 / DR.115 — Bladder

Autorização: pedido de implementação após definições do usuário em 17/11/2026.
Implementação no app existente; sem publicação, escrita nas DRs reais ou migração
do banco operacional durante o desenvolvimento. Sem novas colunas, abas ou notas
nas planilhas. DR-201, estoque, Apex e anéis permanecem independentes.

## Contrato

- DR.115 / gid161109830 / aba `VUCANIZAÇÃO`, A:J: carimbo original,
  operador, tempo em minutos, lote, modelo, prensa, observações, pressão,
  temperatura, condição. Bom→BOM; IA (Imperfeição Aparente)→IMPERFEIÇÕES DE
  VULCANIZAÇÃO; Lixo→LIXO. Uma linha por execução01/02. Não cadastrar prensa3.
- DR.114 / gid832094045 / aba `DR.114`, A:U: carimbo e operador da extrusão,
  matéria-prima/fornecedor (texto como TORTUGA - FBB0001), lote material,
  lote produto, modelo, processamento (livre), médias peso/comprimento/diâmetro,
  TCU1..4=zonas1..4, temperatura, velocidades fuso/esteira, coluna18 vazia,
  resfriamento (livre), quantidade produzida, observações de ambas as etapas.
  Uma linha por extrusão03, liberada somente após manuseio06 vinculado completo.
- Temperatura é obrigatória para novas vulcanizações; reutilizar campo existente.
  Processamento e resfriamento são obrigatórios somente na extrusão de Bladder.
  Não preencher novos parâmetros dos registros antigos por suposição.
- Correção auditada de qualquer etapa recalcula a projeção. Fechamento não
  reenvia nem soma manuseio. Exportação local inclui os novos parâmetros.

## Integração

Fila persistida na mesma transação da produção, com uma projeção por execução
de origem, revisão, payload desejado, último confirmado e tentativa em andamento.
Comando Django periódico e instalador de tarefa Windows (IgnoreNew). Credenciais
existentes credentials.json; timeout finito. Configuração de destino no código,
validação de gid e cabeçalhos antes da escrita; somente A:J / A:U. RAW conserva
lotes textuais/zeros, medições são números. Nunca salvar dados externos no request.
Uma concessão de execução por destino no banco impede trabalhadores concorrentes.

Sem chave remota, não existe promessa de exatamente uma gravação para toda falha
distribuída. Persistir ENVIANDO antes de escrever. Após reinício/timeout, comparar
linha completa da tentativa. Se única e não atribuída a outro registro, reconciliar;
se ausente/duplicada/alterada, manter CONFERIR, sem APPEND automático. Correções
localizam o último conteúdo confirmado, tolerando mudança de linha; ambiguidades
bloqueiam UPDATE. Preservar coluna18 também na correção (nunca usá-la). Liderança
pode liberar nova tentativa após confirmar ausência e justificar; registrar auditoria.
Falhas anteriores à escrita permitem retentativa automática com intervalo crescente.
Correções concorrentes mantêm revisão mais recente pendente após confirmação antiga.

## Validação

Mocks para Google, bancos Django temporários. Cobrir mapeamento completo, campos
obrigatórios, zeros, IA, autor de extrusão, espera de manuseio posterior, parciais,
idempotência local, correções e revisões concorrentes, recuperação de timeout/reinício,
duplicidade/linha movida/alterada, cabeçalhos errados, coluna18 preservada, permissões,
CSRF, comando e concessão de trabalhador. Regressões focadas e ensaio Edge existente.
Linha de base:293 testes,18 falhas de asserções de interface (turno anterior).

## Entrega e verificação

Implementado em `bladder/sincronizacao_drs.py`, com campos/forms/migration0012,
integração transacional em `producao.py`, status na consulta e no detalhe,
recuperação auditada por POST restrito à liderança, Admin somente leitura,
exportação local e comando/tarefa Windows dedicados. Nenhuma dependência nova.
Histórico registra tentativa, confirmação, conferência e liberação manual.
Payloads de inserções cuja ausência foi declarada permanecem guardados no banco:
antes de reapendar, o trabalhador verifica também essas versões, detectando
uma gravação tardia de conteúdo anterior. UPDATE incerto só pode ser repetido
após reconferência explícita e localização única do conteúdo já confirmado.

Resultados em bancos temporários, sem APIs Google reais:

- `manage.py test bladder.test_sincronizacao_drs bladder.test_apontamentos_producao bladder.test_acompanhamento --noinput`:
  **88/88 aprovados**, incluindo32 novos testes de integração e concorrência real
  entre conexões para a concessão por destino. `logs/drs_bladder/focados.log`.
- Suíte completa executada durante a implementação: **317 testes / 299 aprovados /
  18 falhas conhecidas / nenhum erro**;370,069s. Nesse momento havia24 testes novos;
  os8 casos adicionais foram incluídos na validação focada final acima. Comparação
  dos nomes com as16 falhas históricas mais as2 de título do dashboard já registradas
  no checkpoint anterior: `novas=[]`, `ausentes=[]`. Evidências:
  `logs/drs_bladder/suite_completa.log` e `comparacao_falhas.json`.
- `manage.py check`, `makemigrations --check --dry-run` e `git diff --check`
  aprovados; migration0012 somente aditiva. Sintaxe dos dois scripts PowerShell
  validada com Parser nativo, sem instalar/executar tarefas.
- Edge: formulários375/768px, temperatura obrigatória e vazia em nova prensa,
  novos textos apenas no03, IA com significado, manuseio/médias, fechamento,
  consulta/Excel e HTTP200 em `/management/` e `/dashboard/`, em banco temporário.
  Primeiro ensaio aprovado1/1 em31,379s; ensaio final aprovado1/1 em31,191s também verifica statusDR.114,
  link da DR e ausência de controles de reenvio para operador. Logs e capturas em
  `logs/drs_bladder/` e `logs/apontamentos_bladder/`. Capturas de formulários
  375/768px e detalhe da DR inspecionados visualmente, sem overflow.

Migration0012 não aplicada ao banco operacional; tarefa não instalada; nenhum
envio real, deploy ou alteração de planilha. Publicação exige deploy normal e
instalação única de `scripts/instalar_sincronizacao_drs_bladder.ps1` como
administrador no servidor (DEBUG=False), com acesso de edição da conta de serviço
às duas DRs. Compatibilidade MySQL revisada no ORM, sem ensaio de servidor MySQL.
Limitação inerente à ausência de identificador remoto: edições/ordenações externas
durante a escrita não têm comparação e gravação atômicas no Google Sheets;
ambiguidades detectadas são bloqueadas para conferência, sem prometer exactly-once.
