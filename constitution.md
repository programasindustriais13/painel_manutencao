# CONSTITUIÇÃO E GUIA DE ESTILO PERMANENTE
## Diretrizes de Blindagem do Sistema - Painel de Manutenção

Este documento estabelece as regras fundamentais e diretrizes de desenvolvimento para o sistema de Painel de Manutenção. O agente de IA (Antigravity) e qualquer outro desenvolvedor devem seguir rigorosamente e respeitar estas diretrizes em todas as interações e modificações do código para evitar alterações destrutivas, perda de dados ou quebra de regras de negócio.

---

### 1. Princípio da Não-Destruição de Dados (Data Preservation)

*   **Migrações Seguras:** É expressamente proibido deletar tabelas, colunas ou alterar tipos de dados que possam causar a perda de informações existentes no banco de dados (`IntegrityError`, perda de dados legados ou incompatibilidade de esquemas).
*   **Campos Opcionais:** Sempre que um novo campo for adicionado a um modelo (model) Django existente, ele deve, obrigatoriamente, ser definido como `null=True, blank=True` ou possuir um valor padrão (`default`) seguro e consistente, para não invalidar nem quebrar os registros já salvos.
*   **Múltiplas Alocações/Pausas:** Nunca reverter a estrutura relacional de tabelas como `HistoricoPausa` e `HistoricoEscala` para campos planos (colunas simples na tabela principal). O histórico de eventos de pausas e de escalas deve ser sempre incremental e estruturado em tabelas próprias relacionadas (1-para-N).

---

### 2. Preservação das Regras de Negócio Críticas

*   **Concorrência de Técnicos:** Um técnico só pode ter, no máximo, **UMA** alocação ativa com o status `'EM_ATENDIMENTO'` por vez. Novas alocações sob esse status devem ser rejeitadas ou bloquear a operação caso o técnico já possua uma ativa.
*   **Histórico de Pausas:** O sistema deve permitir infinitas pausas e retornos por alocação de técnico, registrando sempre de forma detalhada o timestamp de início da pausa, o timestamp de retorno e o motivo associado a cada pausa na tabela de histórico (`HistoricoPausa`).
*   **Modo TV (42") Otimizado:** A tela `/tv/` (Painel de TV) deve permanecer limpa, sem barra de navegação superior (navbar), sem barra de rolagem vertical (CSS `overflow` escondido), com um grid CSS/Bootstrap autoajustável e fontes legíveis à distância. Quando o técnico estiver com o status `'OCIOSO'`, o card correspondente na TV deve manter o título do técnico e o badge com destaque em vermelho.
*   **Rastreabilidade (Auditoria):** Toda criação ou início de alocação de serviço, bem como qualquer alteração de escala ou disponibilidade de técnicos, deve, obrigatoriamente, registrar no banco de dados o usuário logado (`request.user`) responsável pela execução da ação.

---

### 3. Limitações de Escopo Técnico

*   **Arquitetura Isolada:** Não devem ser criados novos aplicativos (apps) Django ou novos ambientes virtuais de execução (`venv`) no projeto, a menos que haja uma ordem direta e explícita do usuário.
*   **Fallback de Arquivos:** Nenhuma view ou template do sistema deve quebrar caso um upload de foto ou anexo seja enviado em branco/nulo. Todos os fluxos de arquivos devem tratar campos nulos com segurança.
*   **Filtro Unificado no Dashboard:** O filtro de intervalo de datas (período) do Dashboard deve comandar de forma centralizada e unificada tanto a renderização dos dados nos gráficos interativos (Chart.js) quanto a query de geração e exportação do arquivo Excel.

---

### 4. Protocolo de Documentação (`Instrucoes.txt`)

*   **Registro de Alterações:** Toda e qualquer alteração realizada no código-fonte, novas rotas criadas em `urls.py`, novos modelos adicionados em `models.py` ou novas bibliotecas externas adicionadas ao projeto (ex: `openpyxl`, `pandas`, `select2`) devem ser obrigatoriamente registradas e detalhadas de forma resumida e organizada no arquivo `Instrucoes.txt` localizado na raiz do projeto ao final de cada tarefa.

---

### RECONHECIMENTO DO AGENTE:
> [!IMPORTANT]
> **Você deve ler este arquivo antes de gerar qualquer código. Se a solicitação do usuário violar qualquer regra deste documento, alerte-o antes de prosseguir.**
