# 🧠 CONSTITUIÇÃO.md — Painel de Manutenção Industrial

## 🎯 OBJETIVO DO SISTEMA
Sistema Django para monitoramento e gestão de manutenção industrial em tempo real:
- **Painel TV (Modo TV):** Exibição contínua na fábrica para acompanhamento visual do status dos técnicos.
- **Controle Técnico:** Painel interativo para técnicos e operadores iniciarem, pausarem e concluírem atendimentos.
- **Dashboard de Gestão:** Gráficos e indicadores analíticos com exportação de relatórios em Excel.
- **Cadastros (CRUDs):** Gerenciamento de setores, máquinas e técnicos.

O sistema deve ser:
- Seguro e auditável.
- Consistente e resiliente no chão de fábrica.
- Compatível com produção (MySQL) e desenvolvimento local (SQLite).
- De fácil usabilidade para operadores e técnicos (UI limpa e termos simples).

---

# 🚨 REGRA GLOBAL CRÍTICA (OBRIGATÓRIA)

## ❗ Execução Controlada de Agentes
- Apenas **UM fluxo de implementação ativo por vez**.
- Subagentes NÃO podem:
  - Criar múltiplos ambientes virtuais.
  - Criar cópias ou duplicatas do projeto.
  - Criar ou duplicar aplicações Django.

### ✅ Estrutura obrigatória:
- Apenas **1 ambiente virtual (.venv)** na raiz.
- Apenas **1 projeto Django**.
- Apenas **1 base de código ativa**.

---

# 🏗️ ARQUITETURA

- Seguir o padrão **Django MVT** (Model-View-Template).
- Separação clara de responsabilidades:
  - `maintenance` (aplicação principal contendo regras de negócio, templates e gerenciamento).
  - `maintenance_project` (configurações do projeto e URLs principais).

### Regras:
- ❌ **PROIBIDO** lógica de negócio complexa ou queries SQL diretas em templates.
- ❌ **PROIBIDO** lógica de negócio pesada ou decisões complexas diretamente nas views.
- ✅ Lógica deve ficar em:
  - **Models** (com propriedades e métodos auxiliares para consultas e regras simples).
  - **Forms** (validações e salvamento customizado).
  - **Services / Utils** (para lógicas de integração ou processamento pesado).

---

# 🔐 SEGURANÇA E PERMISSÕES (PRIORIDADE MÁXIMA)

- **Nunca confiar em dados do frontend.** Sempre validar permissões no backend.
- Toda view ou action sensível deve ser protegida com decorators de controle de acesso:
  - `@operador_required`: Acesso total a configurações e cadastros (CRUDs).
  - `@lider_ou_operador_required`: Acesso a dashboard, KPIs e exportações de relatórios.
  - `@tecnico_or_operador_required`: Acesso à tela de gerenciamento (/management/).
- **Validação de Card Próprio:** Técnicos com perfil `TECNICO` só podem realizar ações (iniciar, pausar, concluir) no seu próprio card de técnico.

### Obrigatório:
- CSRF Token em todos os formulários.
- Filtros de query robustos no banco para impedir vazamento de contexto ou ações indevidas.
- Fallback seguro para arquivos e fotos opcionais (o sistema nunca deve quebrar caso um upload de anexo falhe ou venha em branco).

---

# 🗄️ BANCO DE DADOS

## Compatibilidade obrigatória:
- **SQLite** (ambiente de desenvolvimento local).
- **MySQL** (ambiente de produção / servidor real).

### Regras:
- ❌ **Evitar features específicas de banco** que não sejam compatíveis entre SQLite e MySQL.
- ✅ Usar **ORM do Django sempre** para garantir a portabilidade do banco.
- ❌ Não usar SQL puro ou métodos obsoletos (ex: `.extra()`).
- **Campos Opcionais:** Novos campos adicionados a modelos existentes devem conter `null=True, blank=True` ou valor padrão (`default`) definido para não quebrar registros antigos no banco.

---

# ⚙️ REGRAS DE NEGÓCIO CRÍTICAS

## 1. Concorrência de Técnicos
- Um técnico só pode ter, no máximo, **UMA** alocação com status `'EM_ATENDIMENTO'` (ativo) por vez.
- O técnico pode possuir **ILIMITADAS** alocações abertas sob o status `'EM_PAUSA'` ao mesmo tempo.
- Se o técnico possuir um atendimento ativo, qualquer tentativa de iniciar outro serviço deve ser bloqueada até que o ativo seja pausado ou concluído.

## 2. Histórico Relacional de Pausas
- As pausas de uma alocação devem ser salvas na tabela relacionada `HistoricoPausa` (relação 1-para-N).
- Toda pausa deve registrar obrigatoriamente a `data_pausa` e o `motivo_pausa`.
- Ao retomar o serviço, a data de retorno deve ser preenchida na respectiva pausa da tabela de histórico.

## 3. Disponibilidade e Escalas (Ausência)
- O status de disponibilidade de um técnico (`Technician.status`) pode ser alterado para os estados de ausência:
  - `AUSENTE_FOLGA` (Folga/Escala)
  - `AUSENTE_FERIAS` (Férias)
  - `AUSENTE_MEDICO` (Licença Médica)
  - `EXTERNO_PLANTAO` (Plantão Externo)
- Técnicos marcados como ausentes **não podem** ser alocados em novas ordens de serviço.
- Toda alteração de escala ou disponibilidade feita pelo operador deve registrar um evento na tabela de auditoria `HistoricoEscala`, identificando o usuário responsável (`request.user`).

---

# 🎨 UI / UX E MODO TV

- Interface completamente em **Português Brasileiro (pt-br)**.
- Mensagens de erro claras e amigáveis para os usuários finais no chão de fábrica (evitar termos técnicos e stacktraces).
- **Painel TV (Modo TV - /tv/):**
  - Otimizado para exibição contínua sem necessidade de interação do usuário.
  - Ocultar barras de rolagem vertical (`overflow: hidden`) e navbar superior.
  - Tempo de refresh configurado estritamente em **10 segundos**.
  - Cartões de técnicos com status `OCIOSO` devem ser destacados visualmente com coloração de alerta vermelho escuro para chamar a atenção.

---

# 🧪 TESTES E VALIDAÇÃO
Antes de considerar qualquer alteração como concluída:
- Verificar o funcionamento local em `/management/` e `/dashboard/`.
- Garantir que as migrações foram geradas de forma segura e não destrutiva.
- Realizar teste de validação do formulário (enviar dados incorretos e em branco e validar a exibição de erros).

---

# 📦 PROTOCOLO DE DOCUMENTAÇÃO (`Instrucoes.txt`)
- Toda alteração realizada no código-fonte, novas rotas, novos modelos ou novas bibliotecas externas devem ser registradas de forma resumida e organizada no arquivo `Instrucoes.txt` localizado na raiz do projeto.

---

# 🤖 ORQUESTRAÇÃO DE SUBAGENTES
1. **Subagente Arquiteto:** Analisa a estrutura e propõe plano mínimo de alteração (sem reescrever ou duplicar código).
2. **Subagente Backend:** Implementa o plano e mantém a compatibilidade SQLite e MySQL.
3. **Subagente QA:** Valida contra regressões, duplicações de lógica, permissões e consistência geral.