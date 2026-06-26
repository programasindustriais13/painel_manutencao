# 🧠 SPEC — FASE 3: ENVIO PARA GRUPOS E ESCUDO ANTI-BANIMENTO (WHATSAPP)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/relatorio-turno/` e `whatsapp_service/server.js`
- **Contexto(s):** Disparo de Relatório de Passagem de Turno.
- **Perfil(s) afetados:** Técnico Líder e Operador/Administrador.

---

## ❗ 2. PROBLEMA ATUAL

- O envio atual suporta apenas o envio para o próprio número do técnico cadastrado (`@s.whatsapp.net`), sem a possibilidade de enviar o relatório finalizado para os grupos oficiais de manutenção da fábrica.
- O microserviço em Node.js não possui mecanismos de defesa. Se houver um bug de loop no frontend ou múltiplos técnicos dispararem relatórios no mesmo segundo, o WhatsApp detectará um comportamento de "spam/bot" e banirá o número do chip da fábrica instantaneamente.

---

## 🎯 3. OBJETIVO

- **Django (Frontend/Backend):** Adicionar um campo de seleção (Dropdown) na tela de relatório, permitindo ao usuário escolher o destino do envio: O próprio número (para revisão) ou um Grupo predefinido (cujo ID será fixado no código/configuração).
- **Node.js (Anti-banimento):** Implementar um escudo de segurança no `server.js` contendo: Atraso Humano (Delay aleatório), Limitador de Requisições (Rate Limit) e um Disjuntor de Falhas (Circuit Breaker) básico.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- [views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py) (Adicionar dicionário de grupos e lógica de POST/destinos)
- [relatorio_turno.html](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/templates/maintenance/relatorio_turno.html) (Adicionar dropdown)
- [server.js](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/server.js) (Escudo anti-banimento e lógica de JID de grupos)
- [package.json](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/package.json) (Dependência `express-rate-limit` se necessário)
- [tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/tests.py) (Ajustar testes do envio de relatório de turno)

### Possíveis módulos:
- `maintenance`
- `whatsapp_service`

---

## 🚫 5. FORA DE ESCOPO

- NÃO criar modelos de banco de dados (`models.py`) para armazenar os grupos. Os IDs e nomes dos grupos devem ser estruturas de dados "hardcoded" (dicionários/listas) na `views.py` ou `settings.py`.
- NÃO alterar a lógica de geração do texto do relatório construída na Fase 1.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ O Node.js deve continuar isolado. A comunicação entre o Django e o Node deve continuar sendo apenas via requisição HTTP POST.
- ✅ O sistema não deve travar se o serviço do WhatsApp demorar a responder devido ao "delay" de segurança. O Django deve fazer o POST de forma assíncrona ou aguardar o tempo limite adequadamente.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Os Grupos Fixos (Django):**
   - Na `views.py`, defina um dicionário de grupos disponíveis. Exemplo estrutural: `{'meu_numero': 'Meu Número (Teste)', 'grupo_geral': '123456789@g.us', 'grupo_lideranca': '987654321@g.us'}`.
   - O `<select>` no template deve exibir os nomes amigáveis.
   - Ao receber o POST, a view define se enviará a variável de `telefone` do banco (se escolheu "Meu Número") ou o ID do grupo selecionado.
2. **Identificação de Destino (Node.js):**
   - O `server.js` deve checar o número recebido. Se contiver `@g.us`, envia como grupo (não adiciona o DDI 55). Se não contiver, trata como número individual formatando com o `55` e o sufixo `@s.whatsapp.net`.
3. **Escudo Anti-Banimento (Node.js):**
   - **Rate Limit:** Implementar um middleware bloqueando se a mesma rota receber mais de 5 requisições em uma janela de 1 minuto. Retornar status HTTP 429.
   - **Humanized Delay:** Antes de chamar a função de envio do Baileys, adicionar um temporizador (setTimeout) com um atraso aleatório entre 2000ms e 5000ms (2 a 5 segundos).
   - **Circuit Breaker:** Criar uma variável contadora de falhas seguidas. Se a API de envio falhar 3 vezes seguidas, rejeitar automaticamente as próximas requisições nos próximos 60 segundos com uma mensagem de erro ("Serviço temporariamente indisponível").
   - **Background Queue Processing:** Para evitar bloqueio/timeout do Django, o Node.js responde `202 Accepted` assim que recebe e valida a requisição, e processa os envios em background com uma fila sequencial.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] A tela de relatório apresenta as opções de destino antes do envio.
- [ ] O envio para o próprio número (individual) continua funcionando normalmente.
- [ ] O backend bloqueia corretamente envios de "spam" muito rápidos, e o Django captura esse erro (HTTP 429) e avisa o usuário sem dar crash na tela.
- [ ] O console do Node.js exibe o delay simulado antes de confirmar o disparo da mensagem.

---

## ⚠️ 9. RISCOS

- **Delay vs. Timeout no Django:** Se o Node.js esperar 5 segundos para processar e responder a requisição HTTP, a chamada `requests.post()` no Django pode sofrer timeout ou deixar a tela do usuário travada carregando. Resolvido pelo envio em background (202 Accepted).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Adicionar o middleware `express-rate-limit` ao `package.json` do whatsapp_service e instalá-lo ou implementar lógica customizada equivalente.
2. Atualizar o `server.js` para receber requisições de mensagens, enfileirá-las e processá-las em background com um delay randômico de 2 a 5 segundos.
3. Adicionar lógica de Rate Limit e Circuit Breaker ao `server.js`.
4. Tratar grupos (`@g.us`) e números individuais de forma distinta.
5. Alterar a view `relatorio_turno` no Django para passar a lista de opções de destino para o template e processar o POST do campo `destino`.
6. Ajustar a requisição no Django para enviar ao Node.js o valor do destino e tratar os retornos `202`, `429` e `503`.
7. Injetar o campo `<select>` no `relatorio_turno.html`.
8. Atualizar e testar com `tests.py`.

---

## 🧪 11. TESTES MANUAIS

1. Acessar a tela `/relatorio-turno/`.
2. Verificar se o dropdown de destino é exibido com "Meu Número (Teste)" e as outras opções de grupo.
3. Submeter um relatório para "Meu Número" e checar se o Node.js enfileirou e processou após um delay aleatório.
4. Fazer envios frequentes para disparar o Rate Limit (HTTP 429) e verificar se o Django exibe o aviso apropriadamente.
5. Simular falhas no Baileys para disparar o Circuit Breaker e verificar se o erro 503 é retornado e tratado pelo Django.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

(Será preenchido no final)
