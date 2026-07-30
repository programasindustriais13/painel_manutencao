# 📘 Resumo do Projeto: Painel de Manutenção Industrial

Este documento centraliza o histórico de desenvolvimento, as funcionalidades implementadas e as decisões de arquitetura do sistema de Painel de Manutenção.

---

## 🏗️ 1. Arquitetura e Base do Sistema
- **Backend Principal:** Desenvolvido em Python com o framework Django.
- **Banco de Dados (Default):** SQLite (focado no armazenamento de perfis, máquinas, alocações e grupos).
- **Controle de Acesso (RBAC):** Sistema estruturado em grupos de permissões nativos do Django (ex: *Operador/Administrador*, *Técnico Líder*, *Técnico*).
- **Interface:** Templates HTML renderizados pelo Django com estilização responsiva.

---

## 🛠️ 2. Gestão de Atendimento e Alocações
- **Cards de Serviço:** Interface dinâmica para iniciar, pausar e concluir manutenções nas máquinas.
- **Cálculo de Tempo Líquido:** Correção do algoritmo de tempo decorrido para serviços pausados. O sistema agora desconta corretamente o histórico de pausas, exibindo a duração real e líquida do trabalho ao retomar um serviço.
- **Restrição de Dashboard:** O acesso à rota `/dashboard/` e a visualização de indicadores e KPIs globais foram bloqueados para o perfil de *Técnico Líder*, tornando-se exclusivos para a gestão (*Operador/Admin*).

---

## 📱 3. Módulo de Relatório de Turno (WhatsApp)
Um dos módulos mais robustos do sistema, responsável por compilar e disparar relatórios de passagem de turno.

- **Filtro de Janela Móvel (12 Horas):** A query de serviços concluídos foi ajustada para utilizar `datetime.timedelta`. O sistema busca as atividades das últimas 12 horas a partir do momento da geração do relatório, garantindo que turnos noturnos/madrugada não tenham suas atividades cortadas pela virada da meia-noite.
- **Assinatura Dinâmica:** O texto do relatório gerado injeta automaticamente o nome do técnico logado no cabeçalho da mensagem.
- **Destinatários Dinâmicos:** 
  - Criação do modelo `WhatsAppGroup` integrado ao painel `/admin/` do Django, dando autonomia para a gestão cadastrar e gerenciar grupos (JIDs terminados em `@g.us`).
  - O técnico pode escolher no momento do envio se deseja mandar para o próprio número (teste/revisão) ou para um dos grupos oficiais da fábrica.

---

## ⚙️ 4. Microserviço Mensageiro (Node.js)
Para viabilizar o envio gratuito e independente de mensagens via WhatsApp, foi criada uma arquitetura de microserviço.

- **Tecnologia:** Node.js, Express e a biblioteca open-source `@whiskeysockets/baileys`.
- **Isolamento:** O microserviço roda isolado na pasta `whatsapp_service/`, escutando requisições HTTP POST do Django e mantendo sua própria sessão de QR Code local.
- **Escudo Anti-Banimento (Segurança):**
  - *Rate Limiter:* Bloqueia requisições em massa (spam) na rota de disparo.
  - *Humanized Delay:* Aplica um atraso aleatório (setTimeout) entre a recepção da requisição e o envio, simulando comportamento humano.
  - *Circuit Breaker:* Monitora falhas de API e desarma temporariamente o sistema caso o WhatsApp recuse conexões seguidas.
  - *Fila Assíncrona:* O servidor responde imediatamente ao Django com `HTTP 202 Accepted` e processa o envio em background, evitando que a tela do usuário congele esperando o delay.

---

## 🛡️ 5. Governança e Boas Práticas (Git / Versionamento)
- **Blindagem do Repositório (`.gitignore`):** Configuração estrita para não versionar arquivos pesados ou sensíveis. Pastas como `node_modules/`, `venv/`, caches do Python e a pasta crítica de sessão do WhatsApp (`auth_info_baileys/`) estão permanentemente ignoradas.
- **Constitution.md:** O projeto segue uma abordagem *Spec-Driven*, utilizando o documento `constitution.md` para forçar a IA e os desenvolvedores a seguirem diretrizes arquiteturais, como atualização obrigatória do `.gitignore` a cada nova dependência inserida.

---

## 🚀 6. Próximos Passos (Em Desenvolvimento)
- **Módulo de Produção e Scada-LTS:** Início da fundação de um novo App isolado (`/producao/`) focado na Liderança de Produção.
- **Múltiplos Bancos de Dados (Database Routing):** Preparação do `settings.py` para conectar o Django nativamente ao MySQL do Scada-LTS como um banco secundário de leitura/escrita, sem misturar os dados de chão de fábrica com o banco da manutenção.