# PROMPT PARA O AGENTE — EVOLUÇÃO SEGURA DO MÓDULO DE PRODUÇÃO / SCADA-LTS

Leia primeiro, nesta ordem:

1. `constitution.md`
2. `SPEC_TEMPLATE.md`
3. `SPEC_FUNDACAO_PRODUCAO.md`
4. `resumo_gemini.md`
5. `DOCUMENTACAO_MYSQL_SCADALTS_PAINEL_SINOTICO.md`
6. `Instrucoes.txt`
7. Todo o código atual relacionado ao app `production`, ao app `maintenance`, ao login/permissões, ao Django Admin, às configurações de banco e aos testes.

## Contexto da demanda

O sistema Django de Manutenção já roda localmente e em produção no Windows Server. A rota pública do módulo é:

- `https://manutencao.freedom.dev.br/producao/`

Existe outro projeto Django, o Painel Sinótico, que lê dados reais do Scada-LTS por MySQL usando XIDs cadastrados pelo Django Admin. O novo módulo de produção deve trazer para o projeto de Manutenção, de forma isolada e segura, as mesmas informações iniciais já exibidas pelo Painel Sinótico, porém com uma interface operacional mais simples e adequada a usuários com pouca familiaridade com tecnologia.

A implementação não deve copiar o layout de TV. O objetivo é uma tela de consulta e acompanhamento, com busca por máquina, filtros simples e telas individuais.

## Dados iniciais desejados

Para cada prensa/máquina:

- nome e ordem de exibição;
- status atual: produzindo, parada ou sem comunicação;
- tempo atual de parada;
- sinal de abertura;
- motivo geral de parada;
- quantidade de cavidades;
- nome de cada cavidade;
- motivo de parada por cavidade;
- produção atual por cavidade;
- meta de produção por cavidade.

Dados globais:

- pressão de vácuo;
- vapor lado prensas 1 a 7;
- vapor lado prensas 8 a 12;
- pressão de ar pneumático;
- alarmes globais de ar, vapor e vácuo.

O cadastro dos XIDs deve continuar disponível e organizado no `/admin/`, com uma tela geral e uma tela individual por máquina. A solução pode melhorar a modelagem do Painel Sinótico, mas deve manter a mesma facilidade de configuração.

## Requisito crítico de histórico de paradas

Quando uma máquina deixa o estado configurado como “produzindo”, deve ser iniciado um evento de parada no banco `default` do projeto de Manutenção. Quando ela volta a produzir, o evento deve ser encerrado.

O histórico precisa permitir filtrar por:

- data inicial e final;
- uma máquina específica ou todas;
- status/eventos encerrados e parada ainda em andamento.

O banco MySQL do Scada-LTS é fonte somente de leitura. O histórico derivado de paradas será salvo no banco `default` existente do projeto de Manutenção. Não copiar continuamente todas as amostras do Scada para o SQLite/MySQL local; persistir somente estados derivados necessários, especialmente transições e períodos de parada.

## Segurança de produção — regras obrigatórias

- Não perder, apagar, renomear ou reclassificar dados existentes.
- Não criar projeto paralelo, app duplicado ou novo ambiente virtual.
- Usar apenas a `.venv` existente.
- Preferir Python 3.11 nas validações locais, por paridade com o servidor.
- Não executar migration automaticamente no servidor.
- Não escrever no banco do Scada-LTS.
- A conexão `scada` deve usar usuário MySQL somente leitura e `allow_migrate=False`.
- Credenciais somente em `.env`; nunca hardcoded ou versionadas.
- Toda migration no banco `default` deve ser aditiva e reversível, sem remoção de campos ou tabelas existentes.
- Antes de migrations: auditar `showmigrations`, gerar backup do `db.sqlite3` de produção e testar em cópia local representativa.
- Se o Scada ficar indisponível ou o dado estiver antigo, mostrar “Sem comunicação”/“Dados desatualizados”; não classificar automaticamente como máquina parada e não abrir/fechar evento falso.
- Não usar dados simulados como se fossem reais em produção.
- Toda rota deve validar permissões no backend.
- Atualizar `Instrucoes.txt` em cada etapa executada.

## Decisões arquiteturais a validar

O Arquiteto deve inspecionar o código atual e validar estas direções antes de implementar:

1. Reutilizar o model `Machine` já existente no app `maintenance`, se ele representar as mesmas máquinas físicas. Evitar criar uma segunda tabela de máquinas duplicada.
2. Se compatível, criar uma configuração 1:1 no app `production`, por exemplo `ProductionMachineConfig`, vinculada a `Machine`.
3. Modelar cavidades em tabela filha/inlines do Admin, por exemplo `ProductionCavityConfig`, para permitir 2 ou 4 cavidades sem quatro blocos de lógica duplicados.
4. Manter parâmetros e alarmes globais em models locais administráveis pelo `/admin/`.
5. Mapear as tabelas `datapoints`, `pointvalues` e `pointvalueannotations` como models Django não gerenciados (`managed=False`) ou usar a abstração já existente no projeto, sempre roteados para `scada`.
6. Centralizar a leitura em services/repositories do app `production`, com leitura em lote, normalização por `dataType`, cache curto para valores e cache maior para XID → ID.
7. Para histórico de paradas, não iniciar thread dentro de `AppConfig.ready()` nem dentro de cada worker web. Criar um processo explícito e único, preferencialmente um management command executado como serviço separado no Windows Server, com lock cross-process e desligamento seguro.
8. O coletor deve ser idempotente e gravar apenas transições. Avaliar um estado 1:1 por máquina e uma tabela de eventos de parada, evitando eventos duplicados em reinício ou retry.
9. Guardar timestamp do valor no Scada e timestamp da coleta. Dados fora do limite de frescor configurado não podem produzir transições.
10. O cronômetro exibido na tela deve ser derivado de `inicio_da_parada` persistido, não depender apenas de JavaScript ou memória do processo.

## UX obrigatória

Não copiar o painel de TV. Criar uma experiência simples:

### `/producao/`

- busca por nome da máquina;
- filtros rápidos: Todas, Produzindo, Paradas, Sem comunicação;
- resumo simples: total, produzindo, paradas e sem comunicação;
- lista/cards compactos com nome, status, tempo parada, motivo e cavidades;
- botão claro “Ver detalhes e histórico”.

### `/producao/maquinas/<id>/`

- estado atual em destaque;
- horário da última atualização;
- cavidades e produção/meta;
- filtro de período com valores padrão simples;
- resumo no período: tempo total parado, quantidade de paradas, maior parada e parada média;
- tabela cronológica de paradas com início, fim, duração e motivo;
- sem excesso de gráficos na primeira entrega.

Mensagens devem ser em português simples e adequadas ao chão de fábrica.

## Sequência obrigatória de trabalho

Não implementar toda a demanda em uma única SPEC. Trabalhar em etapas pequenas e dependentes:

### Etapa 0 — Auditoria de estado atual

Somente leitura. Confirmar:

- branch, HEAD e `git status`;
- quais partes da `SPEC_FUNDACAO_PRODUCAO.md` já existem no código;
- app `production`, rotas, decorators, templates e testes atuais;
- configuração real dos bancos `default` e `scada`;
- router e garantias de `allow_migrate=False`;
- dependências/driver MySQL existentes;
- model `Machine` e possibilidade de reutilização;
- estado atual do `/admin/`;
- migrations aplicadas no banco local;
- se há qualquer coletor/thread/polling já criado;
- como o projeto inicia localmente e via Waitress no servidor;
- riscos de deploy e rollback.

Criar um relatório de auditoria. Não alterar código nessa etapa.

### Etapa 1 — Criar índice e SPECs

Com base na auditoria, criar um índice sequencial e as SPECs separadas, no mínimo:

1. cadastro local de máquinas/XIDs, cavidades, parâmetros e alarmes no `/admin/`;
2. models não gerenciados e camada de leitura em lote do Scada-LTS;
3. tela `/producao/` com dados atuais e estados de comunicação;
4. coletor único e persistência idempotente do histórico de paradas no banco `default`;
5. tela individual e filtros de histórico por data/máquina;
6. hardening, testes de carga/falha, backup, deploy e rollback.

Cada SPEC deve caber em uma única conversa/limite de uso, declarar predecessora, migration, arquivos permitidos, gate de saída e regra de parada.

### Etapa 2 — Implementar somente a primeira SPEC liberada

Somente após a auditoria e aprovação do desenho, implementar a primeira SPEC executável. Não antecipar coletor, histórico, telas futuras ou refatorações fora do escopo.

## Regras funcionais do histórico

- Estado “produzindo” deve ser configurável por máquina, sem assumir que todos os XIDs usam o mesmo valor bruto.
- Transição Produzindo → Não produzindo: abre uma parada se não houver uma já aberta.
- Permanência em Não produzindo: não cria novo evento; apenas mantém o evento atual.
- Transição Não produzindo → Produzindo: encerra a parada aberta.
- Falha de conexão/dado stale: não abre nem encerra parada.
- Reinício do coletor: recupera o estado persistido e continua sem duplicar eventos.
- Alteração de XID/configuração no Admin: invalidar cache correspondente e registrar claramente a mudança, sem modificar o histórico antigo.
- Eventos antigos devem manter o nome/motivo relevante por snapshot ou por relação preservada, sem perder legibilidade após edição do cadastro.
- Todos os cálculos usam timezone aware e o fuso configurado pelo Django.

## Testes mínimos esperados nas SPECs futuras

- XID válido, inexistente e sem valor histórico;
- tipos booleano, multistate, numérico e texto;
- leitura em lote sem N+1;
- conexão MySQL indisponível;
- valor stale;
- abertura, manutenção e encerramento de parada;
- retry e reinício sem duplicação;
- duas instâncias do coletor: somente uma ativa;
- filtros por máquina e período;
- usuário sem permissão;
- banco `scada` sem qualquer escrita/migration;
- migration aditiva no banco `default` preservando todos os registros existentes;
- regressão de `/management/`, `/dashboard/`, `/tv/`, login e relatórios.

## Uso de subagentes

Ordem obrigatória:

1. **Arquiteto** — auditoria, inventário, riscos, desenho mínimo e divisão das SPECs.
2. **Backend** — somente a SPEC liberada, sem ampliar escopo.
3. **QA** — valida segurança de bancos, duplicação, idempotência, permissões, regressões, migrations e rollback.

## Regra de parada

Parar imediatamente e relatar, sem improvisar, se ocorrer qualquer um destes casos:

- a fundação existente divergir do documento;
- conexão `scada` possuir permissões de escrita;
- router permitir migrations no Scada;
- necessidade de apagar/renomear dados existentes;
- dúvida sobre qual valor representa “produzindo”;
- model `Machine` atual não puder ser reutilizado sem risco e a criação de outro model gerar duplicação conceitual;
- polling duplicado ou thread iniciada por worker web;
- migration destrutiva ou sem backup/rollback;
- testes de regressão falharem.

## Entrega obrigatória da primeira execução

1. Resultado da auditoria e classificação: APROVADO, APROVADO COM BLOQUEIOS ou REPROVADO.
2. Arquivos lidos.
3. Estado de Git e migrations.
4. Arquitetura atual confirmada.
5. Riscos e bloqueios encontrados.
6. Índice sequencial das SPECs propostas.
7. Arquivos SPEC criados.
8. Nenhum código implementado antes da aprovação explícita da primeira SPEC.
