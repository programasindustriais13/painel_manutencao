# Proposta — Dashboard gerencial da Matrizaria

Data: 13/11/2026. Situação: proposta aprovada e implementada no código local, com migração de permissões aplicada no banco local. Publicação em produção pendente do deploy habitual.

Nova tela sugerida: `/matrizaria/dashboard/`, com o nome **Dashboard da Matrizaria** no menu do módulo. O objetivo é ajudar a liderança a decidir o que atender primeiro, onde reduzir espera e quais ferramentas concentram intervenções e retrabalho.

## Organização da tela

```text
Dashboard da Matrizaria                         Atualizado em: dd/mm hh:mm
[Últimos 7 dias | 30 dias | Mês atual | Personalizado]
[Prensa / Serviço interno] [Tipo de serviço] [Matriz física] [Prioridade]

RESULTADOS DO PERÍODO
[Abertas] [Concluídas] [Tempo até liberação] [Reprovações na conferência]

[Evolução diária: entradas e conclusões] [Prensas com mais intervenções]
[Tipos de serviço mais demandados]      [Matrizes com mais retrabalho]

FILA ATUAL — posição no momento da consulta, independente do período acima
[Pendentes] [Urgentes pendentes] [Aguardando conferência] [Mais antiga]
[Distribuição por etapa]                [Pendências que exigem ação]
```

O bloco do período responde como o setor está evoluindo. A fila atual mostra o que exige ação agora, inclusive solicitações abertas antes do intervalo selecionado. Filtros de prensa, tipo, matriz e prioridade se aplicam aos dois blocos; o filtro de datas se aplica somente aos resultados do período. Cada bloco deve apresentar claramente sua referência temporal.

## Indicadores e decisões

| Indicador | Regra sugerida | Decisão apoiada |
| --- | --- | --- |
| Solicitações abertas | Solicitações distintas pela data de abertura no período | Avaliar a entrada de demanda |
| Serviços concluídos | Solicitações distintas com aprovação da conferência no período | Acompanhar entregas efetivamente liberadas |
| Tempo até liberação | Mediana e percentil 90 do intervalo entre abertura e aprovação, para serviços concluídos no período | Identificar demora típica e casos extremos |
| Reprovações na conferência | Eventos de devolução para retrabalho / total de eventos de aprovação e devolução no período | Direcionar ações de qualidade; mostrar também numerador e denominador |
| Pendentes agora | Solicitações nos estados Solicitado, Em execução, Aguardando conferência ou Aguardando retrabalho | Dimensionar o volume a atender |
| Urgentes pendentes | Pendentes com prioridade Urgente | Priorizar atendimento |
| Aguardando conferência | Quantidade atual e idade da espera desde a última finalização técnica | Mobilizar a liderança para liberar os serviços |
| Solicitação pendente mais antiga | Tempo desde a abertura da pendência mais antiga, com protocolo e estado atual | Evitar que solicitações fiquem esquecidas |

Sem dados suficientes, apresentar “Sem dados”; uma taxa sem conferências no período deve aparecer como “—”, nunca como 0%. Cancelamentos ficam separados das conclusões.

## Gráficos

| Gráfico | Apresentação | Utilidade |
| --- | --- | --- |
| Entradas × conclusões | Linhas diárias; cada série usa a data do respectivo evento | Perceber se a demanda está crescendo mais rápido que as entregas |
| Distribuição da fila atual | Barras por etapa, com quantidade e idade da pendência mais antiga de cada etapa | Identificar concentração na execução, conferência ou retrabalho |
| Prensas com mais intervenções | Pareto por quantidade de solicitações distintas com execução no período; duração da intervenção como informação adicional | Direcionar investigação e manutenção preventiva |
| Tipos de serviço mais demandados | Barras horizontais por solicitações abertas no período | Planejar materiais, ferramentas e capacitação |
| Matrizes com mais retrabalho | Top 10 por devoluções no período; mostrar também solicitações distintas afetadas | Identificar ferramental que exige revisão e investigar causas |

Nos gráficos por prensa, serviços internos devem aparecer separadamente como “Matrizaria / serviço interno”. Nos gráficos por matriz, agrupar pela identidade do exemplar físico; registros sem identificação ficam em “Matriz não informada”. Rótulos iguais ou variantes de produto com/sem câmara não devem misturar exemplares diferentes nem duplicar o mesmo ferramental.

## Lista de ação da liderança

Tabela com protocolo, prensa ou serviço interno, matriz, tipo, prioridade, estado, responsável, idade da solicitação e tempo na etapa atual. Destacar urgentes, retrabalhos e serviços aguardando conferência; permitir ordenar pelos maiores tempos.

Cada linha oferece **Ver detalhes**. Cliques nos gráficos abrem a lista correspondente com os mesmos filtros. A lista precisa explicar sua seleção, por exemplo: “Solicitações com execução entre 01/11 e 13/11 na Prensa 01”. Filtros ainda inexistentes no relatório, como matriz e prioridade, precisarão ser suportados na futura implementação para que o detalhamento corresponda aos totais.

## Acesso dos perfis de líder

Propor uma permissão específica, `matrizaria.view_dashboard_matrizaria`, concedida aos grupos **Liderança de Produção** e **Tecnicos_Lideres**, cobrindo liderança de produção e técnico líder. Superusuários mantêm acesso. Outras contas administrativas precisam receber a permissão explicitamente.

Hoje o acesso aos relatórios da matrizaria contempla `Liderança de Produção`, `Operadores`, `Operador`, staff e superusuário; `Tecnicos_Lideres` sozinho não está nessa regra. Portanto, reutilizar diretamente a autorização atual dos relatórios não atenderia todos os perfis de líder.

A futura implementação deve:

- Exibir o link do dashboard para quem tiver a permissão e validar o acesso também na rota e em eventuais endpoints de dados e exportação.
- Permitir que o técnico líder autorizado encontre o módulo pelo portal, mesmo que não tenha acesso operacional ao Kanban.
- Garantir que links de detalhamento estejam acessíveis aos líderes autorizados, sem conceder ações de execução, cancelamento ou aprovação além das permissões existentes.
- Manter operadores de vulcanização, matrizeiros e contas TV sem essa visão gerencial, salvo atribuição explícita da permissão. Usuários com vários perfis acumulam a autorização de líder.

Essa autorização será específica da Matrizaria. A restrição já existente ao dashboard geral da Manutenção permanece independente.

## Dados disponíveis e cuidados de cálculo

A proposta usa dados já registrados em `SolicitacaoServicoMatrizaria`, `CicloExecucaoMatrizaria` e `HistoricoTransicaoServicoMatrizaria`: abertura, prioridade, destino, prensa, matriz, tipo, ciclos de execução, finalizações técnicas, aprovações, devoluções e cancelamentos.

- Usar o histórico para contar aprovações e devoluções na data em que ocorreram. O contador acumulado de retrabalhos não representa necessariamente o período selecionado.
- Para tempos por etapa, reconstruir os intervalos do histórico, incluindo todas as passagens por retrabalho e conferência. Registros sem histórico suficiente devem ser identificados como incompletos.
- Somar a interseção dos ciclos com o intervalo consultado ao apresentar duração de intervenção no período. A duração entre início e fim de um ciclo não mede trabalho líquido em bancada nem indisponibilidade da prensa.
- Contar solicitações distintas nos gráficos de demanda e eventos nos indicadores de conferência; múltiplos ciclos não podem inflar a quantidade de chamados.
- Usar dias inclusivos no fuso configurado da aplicação e comparar períodos de igual duração quando houver comparação com o intervalo anterior.
- Se houver análise por executante, considerar as transferências de responsabilidade do histórico. Não atribuir toda a duração ao usuário que iniciou o ciclo.

Não propor nesta primeira versão eficiência individual, custo do retrabalho, OEE ou perda de produção: os registros analisados não oferecem, sozinhos, a base necessária para esses cálculos. Metas e prazos de atendimento devem ser definidos pela gestão antes de criar alertas de atraso ou indicadores de cumprimento de SLA.

## Entrega futura sugerida

Primeira versão: filtros, oito indicadores, cinco gráficos e lista de ação, com detalhamento por clique e acesso dos líderes validado no backend. Organizar os cálculos em serviço do app `matrizaria`, com agregações compatíveis com SQLite/MySQL e consultas sem crescimento por linha. Nenhuma nova aplicação Django é necessária.

Critérios de aceitação: reconciliar totais com os relatórios e eventos; testar serviços que atravessam dias, vários retrabalhos, cancelamentos, transferências, serviço interno e matriz não informada; validar intervalos vazios/inválidos, navegação móvel, paginação dos detalhes e acesso permitido/negado, inclusive para usuários com múltiplos perfis.

## Implementação entregue em 13/11/2026

- `/matrizaria/dashboard/`: oito indicadores, cinco gráficos interativos e lista paginada das pendências. Os gráficos usam SVG e barras HTML, sem dependência de uma biblioteca externa de gráficos.
- `/matrizaria/dashboard/detalhes/`: detalhamento próprio para aberturas, conclusões, execução, retrabalho, conferências, cancelamentos, urgentes e fila atual. Os filtros de matriz e prioridade são aplicados nessa rota, sem alterar as regras do relatório de auditoria existente.
- Filtros de 7/30 dias inclusivos, mês atual e intervalo personalizado de até 366 dias. Filtros por prensa/serviço interno/máquina não informada, tipo, exemplar físico/matriz não informada e prioridade. Ordenação por prioridade, idade ou tempo na etapa.
- `matrizaria/dashboard.py`: cálculos em quatro consultas por carregamento normal, sem consultas por linha. Ciclos são limitados ao período e ao momento da consulta; conferências usam os eventos. Transferências e ajustes cadastrais não reiniciam o tempo na etapa. Ausência de histórico é indicada na lista e não remove chamados dos totais.
- Migração `matrizaria.0005_dashboard_matrizaria`: adiciona a permissão `view_dashboard_matrizaria` e a atribui a `Liderança de Produção` e `Tecnicos_Lideres`. O comando `provisionar_grupos_matrizaria` também provisiona essa atribuição de forma idempotente. Outras contas precisam de atribuição explícita; ser staff não concede essa visão.
- Portal, entrada pós-login e menus desktop/móvel levam os líderes ao dashboard. O módulo de Manutenção continua respeitando suas próprias restrições. A permissão do dashboard permite consultar detalhes e não concede ações operacionais.
- Testes de domínio, filtros, permissões, identidade dos exemplares, limites temporais, segurança dos rótulos, quantidade de consultas e paginação em `matrizaria/test_dashboard.py`. Ensaio opcional em Edge: `python scripts/validar_dashboard_matrizaria.py`, com banco temporário de testes e capturas em `logs/dashboard_matrizaria/`.

Para publicar no servidor, usar o fluxo habitual documentado em `Instrucoes.txt`: atualizar o código e executar `scripts/deploy_production.ps1`, que aplica migrações e coleta os arquivos estáticos. Não foi realizado deploy remoto nesta implementação.
