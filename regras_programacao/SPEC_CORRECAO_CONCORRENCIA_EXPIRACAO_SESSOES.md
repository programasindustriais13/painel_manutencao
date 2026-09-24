# 🧠 SPEC — Correção de Concorrência na Expiração de Sessões

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:**
  - `/matrizaria/api/tv-data/` (Polling de TV assíncrono do módulo de Matrizaria)
  - `/api/session/status/` (Consulta periódica de tempo restante de inatividade)
  - `/api/session/keep-alive/` (Sinalização de atividade humana via POST)
  - `/tv/` (Painel TV com refresh via XMLHttpRequest)
  - `/login/` e `/logout/` (Fluxos de autenticação)
  - Rotas protegidas gerais em `/management/`, `/dashboard/`, `/producao/`, `/matrizaria/`
- **Contexto(s):**
  - Sessões concorrentes em múltiplas abas, polling assíncrono em background, painéis TV e expiração por inatividade humana.
- **Perfil(s) afetados:**
  - Usuários humanos com timeout de 5 min (Técnicos, Operadores, Líderes, Gestores, Administradores).
  - Contas dedicadas de exibição contínua em TV (`tv`, `tv_matrizaria`, `Visualizador`, etc.) — preservadas integralmente sem timeout.

---

## ❗ 2. PROBLEMA ATUAL

- **O que está acontecendo hoje?**
  1. No arquivo `maintenance/middleware.py`, quando uma sessão humana atinge o tempo limite de inatividade (`elapsed > timeout`), o middleware executa diretamente `logout(request)`.
  2. O método `django.contrib.auth.logout(request)` executa `request.session.flush()`, excluindo imediatamente a linha correspondente da tabela `django_session` no banco de dados.
  3. Simultaneamente, requisições concorrentes da mesma sessão (como polling da Matrizaria `/matrizaria/api/tv-data/`, verificação de status `/api/session/status/` ou requisições de outras abas) que já estavam em trânsito tentam salvar seu estado no final do ciclo de resposta (`SessionMiddleware.process_response`).
  4. Além disso, existe um erro de digitação clássico na lista `exempt_bg_paths` do middleware (`/matrizaria/api/tv/data/` em vez de `/matrizaria/api/tv-data/`), o que fazia com que o polling da TV atualizasse indevidamente `request.session["_last_human_activity"] = now_ts`, forçando a marcação `request.session.modified = True` em toda chamada a cada 15 segundos.
  5. Quando a requisição concorrente tenta executar `UPDATE django_session SET ... WHERE session_key = ...`, 0 linhas são afetadas porque a linha foi apagada pelo `logout(request)`. O Django então lança a exceção crítica:
     ```text
     django.db.utils.DatabaseError: Forced update did not affect any rows.
     django.contrib.sessions.backends.base.UpdateError
     django.contrib.sessions.exceptions.SessionInterrupted: The request's session was deleted before the request completed.
     ```
  6. No frontend (`session_inactivity.html`), ao receber status `401` ou atingir `remainingSecs <= 0`, o script disparava `window.location.href = logoutUrl;`. Havendo múltiplas abas, todas tentavam simultaneamente realizar o logout e destruir a sessão, provocando disputas concorrentes de exclusão e desajuste no token CSRF (`Forbidden (CSRF token from POST incorrect.): /login/`).
- **O que está incorreto ou incompleto?**
  - O descarte físico da sessão (deleção do registro em banco) ocorria antes que requisições concorrentes em trânsito pudessem finalizar.
  - A rota `/matrizaria/api/tv-data/` não constava na lista de isenção de background.
  - Toda requisição HTTP comum gravava `_last_human_activity` no banco sem throttling, aumentando drasticamente a concorrência de escrita.
  - O frontend redirecionava para `/logout/` ao invés de redirecionar para `/login/` quando a sessão já estava expirada.
- **Existe impacto em produção?**
  - Sim. O incidente registrado em produção gerou erros 500 (`SessionInterrupted`), erros 401 e falhas transitórias de CSRF em formulários de login quando sessões expiravam sob concorrência de abas.

---

## 🎯 3. OBJETIVO

- **O que deve passar a acontecer?**
  1. A rota `/matrizaria/api/tv-data/` e `/tv/` (quando requisitada via AJAX) devem ser reconhecidas como consultas de background e NUNCA atualizar `_last_human_activity` nem forçar gravação em sessão.
  2. A expiração por inatividade deve ser **lógica e idempotente**: ao detectar timeout, a sessão é marcada como expirada (`_session_expired = True`) e a requisição é desautenticada no runtime (`request.user = AnonymousUser()`), sem deletar fisicamente o registro de `django_session` na corrida.
  3. Nenhuma requisição concorrente pode sofrer `SessionInterrupted`, `UpdateError` ou `DatabaseError: Forced update did not affect any rows`.
  4. Chamadas AJAX para endpoints de sessão (`/api/session/status/`, `/api/session/keep-alive/`) ou views protegidas com sessão expirada devem responder de forma consistente e limpa com `HTTP 401 JSON`.
  5. Chamadas convencionais (navegação HTML) com sessão expirada são redirecionadas ordenadamente para a tela de login.
  6. No frontend, quando a sessão expira, as abas sincronizam via `localStorage` e são redirecionadas para `/login/` (sem invocar uma tempestade destrutiva de chamadas concorrentes a `/logout/`).
  7. Novo login deve iniciar uma sessão limpa, resetando os marcadores de inatividade.
  8. A isenção perpétua de contas de TV dedicadas (`tv`, `tv_matrizaria`, `Visualizador`) permanece 100% inalterada e segura.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `maintenance/middleware.py`:
  - Correção da rota `/matrizaria/api/tv-data/` e inclusão de `/tv/` AJAX em background exempt.
  - Implementação da expiração lógica sem `flush()` prematuro concorrente.
  - Throttling na atualização de `_last_human_activity` para evitar escritas excessivas no banco em GETs.
  - Signal receiver para `user_logged_in` para limpar `_session_expired` e inicializar `_last_human_activity`.
- `maintenance/views.py`:
  - Ajuste em `api_session_status` para retorno previsível `401 JSON` (sem depender de 302 do `@login_required`).
  - Ajuste em `api_session_keep_alive` para bloquear renovação de sessões já expiradas.
- `templates/components/session_inactivity.html`:
  - Redirecionamento ordenado para `loginUrl` em vez de `logoutUrl`.
  - Tratamento idempotente e sincronização de expiração entre abas via `localStorage` (`freedom_session_expired`).
  - Prevenção de novas requisições AJAX após detecção de expiração.
- `matrizaria/templates/matrizaria/tv.html`:
  - Tratar status 401 no polling de dados redirecionando para login.
- `maintenance/tests.py`:
  - Adição de suíte de testes completa cobrindo os 12 cenários exigidos pela demanda.

### Possíveis módulos:
- `maintenance` (middleware, views, templates, testes)
- `matrizaria` (template da tv)

---

## 🚫 5. FORA DE ESCOPO

- Não alterar regras de negócio operacionais de Manutenção, Produção ou Matrizaria.
- Não alterar models operacionais nem criar novas migrations.
- Não desabilitar CSRF nem usar `@csrf_exempt` para esconder problemas.
- Não capturar ou mascarar silenciosamente `SessionInterrupted` com middleware global de captura cega.
- Não alterar `SESSION_ENGINE`.
- Não criar múltiplos ambientes ou duplicar aplicações.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- Seguir estritamente `constitution.md`.
- Manter compatibilidade total entre SQLite (desenvolvimento/testes) e MySQL (produção).
- Princípio: "Alterar o mínimo possível para resolver o problema com segurança".
- Proteção de permissões e decorators no backend preservada.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Classificação de Requisições de Background:**
   - `/matrizaria/api/tv-data/`
   - `/api/session/status/`
   - `/tv/` com cabeçalho `X-Requested-With: XMLHttpRequest`
   - Estas rotas nunca renovam inatividade e nunca gravam `_last_human_activity`.
2. **Atualização de Atividade Humana:**
   - `POST /api/session/keep-alive/` atualiza explicitamente `_last_human_activity`.
   - Requisições normais (navegação humana) só atualizam `_last_human_activity` se decorridos pelo menos 30 segundos da última gravação, evitando `UPDATE` constante a cada sub-recurso.
3. **Expiração Lógica Segura contra Concorrência:**
   - Ao atingir `elapsed > timeout` ou ao detectar `_session_expired`:
     - Define `request.session["_session_expired"] = True`.
     - Define `request.user = AnonymousUser()`.
     - Retorna `401 JSON` para chamadas AJAX/API.
     - Redireciona para `/login/` para navegações de página inteira.
     - **NÃO** executa `logout(request)` nem `request.session.flush()`, garantindo que a linha no banco permaneça disponível para requisições concorrentes em trânsito concluírem sem erro.
4. **Login e Logout:**
   - No login bem-sucedido, o listener `user_logged_in` limpa `_session_expired` e define `_last_human_activity = time.time()`.
   - O logout voluntário via botão "Sair" continua funcionando normalmente através do fluxo padrão do Django.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Polling `/matrizaria/api/tv-data/` não renova inatividade e não dispara escritas na sessão.
- [ ] `/api/session/status/` não renova inatividade e retorna `401 JSON` consistente se deslogado ou expirado.
- [ ] `/api/session/keep-alive/` renova atividade humana somente em sessões válidas e rejeita sessões expiradas com `401`.
- [ ] Sessão humana com tempo de inatividade superior a `INACTIVITY_TIMEOUT_SECONDS` é bloqueada.
- [ ] Requisições concorrentes durante a expiração NÃO disparam `SessionInterrupted`, `UpdateError` ou `DatabaseError: Forced update did not affect any rows`.
- [ ] Contas dedicadas de TV (`is_dedicated_tv_account`) permanecem isentas de expiração.
- [ ] Novo login pós-expiração funciona sem conflito de CSRF.
- [ ] Todos os 398 testes existentes continuam verdes e os novos testes de concorrência e sessão passam 100%.

---

## ⚠️ 9. RISCOS

- **Risco:** Reativação indevida de sessão expirada se um keep-alive chegar atrasado.
  - *Mitigação:* Validação estrita em `api_session_keep_alive`: se `_session_expired` estiver marcado ou se `elapsed > timeout`, o keep-alive é rejeitado com 401 e a sessão não é renovada.
- **Risco:** Desconexão indevida de TVs.
  - *Mitigação:* `is_dedicated_tv_account()` permanece intocada como primeira checagem prioritária, com sessão de longa duração.
- **Risco:** Resíduo de sessão em novo login.
  - *Mitigação:* `reset_session_inactivity_on_login` registrado no signal `user_logged_in` do Django limpa o estado de expiração e sincroniza o timestamp.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. **Arquiteto:** Mapear o ciclo de vida da requisição e concorrência no Django `SessionMiddleware` e `SessionExpiryByProfileMiddleware`.
2. **Backend:**
   - Atualizar `maintenance/middleware.py`:
     - Corrigir `/matrizaria/api/tv-data/` e incluir `/tv/` AJAX na classificação de background.
     - Substituir o `logout(request)` do middleware pela marcação lógica `_session_expired = True` e `request.user = AnonymousUser()`.
     - Implementar throttling para atualização de `_last_human_activity`.
     - Conectar `reset_session_inactivity_on_login` ao signal `user_logged_in`.
   - Atualizar `maintenance/views.py`:
     - Ajustar `api_session_status` para checagem explícita e resposta `401 JSON` limpa.
     - Ajustar `api_session_keep_alive` para rejeitar renovação de sessões expiradas.
   - Atualizar `templates/components/session_inactivity.html`:
     - Redirecionar para `loginUrl` com flag idempotente e sincronização via `localStorage`.
   - Atualizar `matrizaria/templates/matrizaria/tv.html`:
     - Tratar resposta `401` redirecionando para login.
3. **Testes Automatizados:**
   - Criar classe de teste abrangente em `maintenance/tests.py` cobrindo os 12 requisitos obrigatórios, incluindo teste de reprodução de concorrência com duas requisições simultâneas na mesma sessão.
4. **QA:**
   - Executar `python manage.py check`.
   - Executar `python manage.py test maintenance production matrizaria`.
   - Atualizar `Instrucoes.txt`.

---

## 🧪 11. TESTES MANUAIS

1. Realizar login com usuário operador ou técnico.
2. Abrir duas abas no navegador:
   - Aba 1: Painel de Gerenciamento (`/management/`).
   - Aba 2: TV da Matrizaria (`/matrizaria/tv/`).
3. Observar que o polling da TV a cada 15s em `/matrizaria/api/tv-data/` não renova a inatividade humana.
4. Aguardar o tempo de inatividade chegar próximo ao limite (aviso prévio de 30s surge na tela).
5. Na Aba 1, clicar em "Continuar Conectado" e verificar que a sessão é renovada e o aviso desaparece em ambas as abas.
6. Deixar o tempo expirar totalmente sem interação.
7. Verificar que ambas as abas são conduzidas à tela de login sem mensagens de erro 500 no console do servidor e sem exceção `SessionInterrupted`.
8. Efetuar novo login e confirmar acesso normal e sem erro de CSRF.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

Ao concluir, fornecer relatório detalhado com:
- Arquivos lidos e alterados.
- Explicação da causa raiz e estratégia de concorrência.
- Comandos executados, quantidade de testes e resultados.
- Confirmação de ausência de migrações e riscos residuais.
