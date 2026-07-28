# 🧠 SPEC — PREPARAÇÃO PARA IMPLANTAÇÃO EM SUBDOMÍNIO (MANUTENÇÃO)

---

## 📌 1. CONTEXTO

- **URL pública planejada:** `https://manutencao.freedom.dev.br`
- **Origem local pretendida:** `http://127.0.0.1:8900`
- **Ambiente de Servidor:** Windows Server 2019 (Python 3.11.3, Django 4.2.27, Cloudflare Tunnel já operando com subdomínio `sst.freedom.dev.br`).
- **Contexto:** Preparação completa e segura no repositório local para futura implantação no Windows Server, sem efetuar alterações no servidor ou no Cloudflare nesta etapa.
- **Perfil(s) afetados:** Todos (Infraestrutura, Operadores, Técnicos, Visualização TV, Liderança de Produção).

---

## ❗ 2. PROBLEMA ATUAL

- O projeto é executado localmente via `manage.py runserver` e não possui servidor WSGI pronto para produção configurado (`Waitress`).
- Não há estratégia de arquivos estáticos configurada para produção (ausência de `STATIC_ROOT` e middleware de arquivos estáticos como `WhiteNoise`).
- Faltam configurações e variáveis para operar com segurança atrás de um proxy reverso HTTPS (Cloudflare Tunnel), como `SECURE_PROXY_SSL_HEADER`, `USE_X_FORWARDED_HOST`, e cookies de sessão/CSRF seguros.
- O microserviço Node.js do WhatsApp faz bind padrão em todas as interfaces (`0.0.0.0`) em vez de ficar restrito a `127.0.0.1`.
- Faltam scripts PowerShell de inicialização com verificações prévias de ambiente e porta ocupada.
- Falta manual sequencial de implantação e plano de rollback no Windows Server 2019 sem afetar a aplicação parceira SST.

---

## 🎯 3. OBJETIVO

1. Incluir e configurar o `Waitress` como servidor WSGI de produção para o Django, escutando exclusivamente em `127.0.0.1:8900` (configurável via `.env`).
2. Configurar o `WhiteNoise` no Django para servir arquivos estáticos em produção com `STATIC_ROOT`.
3. Mapear e documentar a estratégia para arquivos de mídia enviados por usuários (`MEDIA_ROOT` / `MEDIA_URL`), declarando que WhiteNoise não serve mídia e indicando IIS ou solução dedicada para o servidor.
4. Ajustar as configurações do Django (`settings.py`) para suporte seguro a Cloudflare Tunnel e HTTPS (`X-Forwarded-Proto`, `USE_X_FORWARDED_HOST`, cookies seguros, HSTS zerado inicialmente para evitar loops).
5. Corrigir o bind do microserviço Node.js/Baileys (`whatsapp_service/server.js`) para `127.0.0.1:3000`.
6. Criar script de inicialização segura em PowerShell (`scripts/start_production.ps1`) que valide `.venv`, Python 3.11, `.env`, porta livre e `manage.py check` antes de subir o Waitress.
7. Criar manual de implantação e rollback para Windows Server 2019 (`DEPLOY_WINDOWS_SERVER.md`).
8. Atualizar `.env.example` e `Instrucoes.txt` com todas as novas variáveis e diretrizes.
9. Executar suíte de testes unitários, `makemigrations --check --dry-run`, `collectstatic`, `check --deploy` e smoke tests locais com Waitress e `DEBUG=False`.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos a criar:
- `regras_programacao/SPEC_PREPARACAO_IMPLANTACAO_SUBDOMINIO_MANUTENCAO.md` [NOVO]
- `scripts/start_production.ps1` [NOVO]
- `DEPLOY_WINDOWS_SERVER.md` [NOVO]

### Possíveis arquivos a alterar:
- `requirements.txt` (inclusão de `waitress>=3.0.0` e `whitenoise>=6.5.0`)
- `maintenance_project/settings.py` (configuração do WhiteNoise, `STATIC_ROOT`, suporte a proxy SSL e flags de segurança via env vars)
- `whatsapp_service/server.js` (bind estrito em `127.0.0.1`)
- `.env.example` (documentação de `WAITRESS_*`, `DJANGO_USE_X_FORWARDED_HOST`, `DJANGO_TRUST_PROXY_SSL_HEADER`, etc.)
- `.gitignore` (inclusão de `staticfiles/` se necessário)
- `Instrucoes.txt` (registro documental)

---

## 🚫 5. FORA DE ESCOPO

- Acessar, alterar ou executar comandos no Windows Server de produção.
- Alterar, configurar ou interagir com o Cloudflare Tunnel ou registros DNS.
- Modificar, reutilizar ou interromper o serviço, porta, banco de dados ou `.env` do SST (`sst.freedom.dev.br`).
- Criar novos apps Django, novos projetos ou novos ambientes virtuais.
- Alterar modelos, regras de negócio, tabelas do banco de dados ou criar/aplicar migrações.
- Atualizar versões do Python (permanecer em 3.11.3) ou do Django (permanecer em 4.2.27).
- Criar serviços do Windows (NSSM/WinSW) ou instalar softwares globais no sistema.
- Inserir segredos, chaves reais, IPs privados ou senhas em arquivos versionados no Git.
- Executar `git commit` ou `git push`.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ❌ Não alterar a aplicação SST nem interferir em suas portas/bancos.
- ❌ Não expor o Waitress ou o microserviço WhatsApp em `0.0.0.0`.
- ❌ Não executar `migrate` nem alterar modelos/banco de dados.
- ✅ Utilizar exclusivamente o ambiente virtual `.venv` na raiz.
- ✅ Manter paridade total com Python 3.11.3 e Django 4.2.27.
- ✅ Reutilizar a estrutura atual do projeto sem monkey patches.

---

## ⚙️ 7. ARQUITETURA E VARIÁVEIS DE AMBIENTE

### A. Waitress WSGI
- **Módulo WSGI:** `maintenance_project.wsgi:application`
- **Host Padrão:** `127.0.0.1`
- **Porta Padrão:** `8900`
- **Threads Padrão:** `4`

Variáveis no `.env.example`:
```env
WAITRESS_HOST=127.0.0.1
WAITRESS_PORT=8900
WAITRESS_THREADS=4
```

### B. Arquivos Estáticos e Mídia
- **Estáticos:** `STATIC_URL = "static/"`, `STATIC_ROOT = BASE_DIR / "staticfiles"`. Middleware `WhiteNoiseMiddleware` posicionado após `SecurityMiddleware`.
- **Mídia:** `MEDIA_URL = "/media/"`, `MEDIA_ROOT = BASE_DIR / "media"`. Mídia dinâmica não é servida pelo WhiteNoise nem por `django.views.static.serve` em produção (Waitress + `DEBUG=False` retorna HTTP 404 para `/media/`).
  ```text
  BLOQUEIO DE IMPLANTAÇÃO: estratégia de mídia depende da auditoria do Windows Server.
  ```
  A preparação do repositório está APROVADA, mas a implantação pública permanece BLOQUEADA até a definição da arquitetura de mídia no Windows Server (IIS front-proxy ou regras separadas no Cloudflare Tunnel).


### C. Proxy HTTPS (Cloudflare Tunnel)
- **Forwarded Host:** `DJANGO_USE_X_FORWARDED_HOST=True` (`USE_X_FORWARDED_HOST = True`)
- **SSL Header:** `DJANGO_TRUST_PROXY_SSL_HEADER=True` (`SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`)
- **SSL Redirect:** `DJANGO_SECURE_SSL_REDIRECT=False` (o término TLS é feito pelo Cloudflare)
- **Cookies Seguros:** `DJANGO_SESSION_COOKIE_SECURE=True`, `DJANGO_CSRF_COOKIE_SECURE=True`
- **HSTS:** `DJANGO_SECURE_HSTS_SECONDS=0`, `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False`, `DJANGO_SECURE_HSTS_PRELOAD=False`

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] SPEC e Plano de Implementação criados e aprovados antes do código.
- [ ] `waitress` e `whitenoise` adicionados ao `requirements.txt`.
- [ ] `settings.py` atualizado com WhiteNoise, `STATIC_ROOT` e configurações de proxy/segurança via `.env`.
- [ ] `whatsapp_service/server.js` atualizado para realizar bind exclusivo em `127.0.0.1:3000`.
- [ ] Script `scripts/start_production.ps1` criado com todas as 14 verificações prévias ativas.
- [ ] Manual `DEPLOY_WINDOWS_SERVER.md` criado com todas as Fases de A a H totalmente descritas.
- [ ] `.env.example` atualizado com todas as novas variáveis documentadas.
- [ ] `manage.py check` e `manage.py test` executados com 100% de aprovação.
- [ ] `manage.py makemigrations --check --dry-run` confirma 0 alterações de banco/migração.
- [ ] `manage.py collectstatic --noinput` executa com sucesso.
- [ ] Teste local com Waitress e `DEBUG=False` valida rotas `/management/`, `/dashboard/`, `/admin/login/` e estáticos.
- [ ] Testes do script PowerShell executados cobrindo cenários de sucesso e falhas controladas.
- [ ] `.gitignore` auditado (`.env`, `.venv`, `staticfiles/`, `media/`, `db.sqlite3`, `whatsapp_service/node_modules/` ignorados).
- [ ] Nenhuma alteração efetuada no servidor de produção, SST ou Cloudflare.
- [ ] `Instrucoes.txt` atualizado.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

1. **Risco:** Loops de redirecionamento HTTPS no Cloudflare Tunnel.  
   **Mitigação:** Manter `DJANGO_SECURE_SSL_REDIRECT=False` no Django, delegando o redirecionamento HTTPS ao Cloudflare Edge.
2. **Risco:** Conflito de portas com o SST no servidor.  
   **Mitigação:** Isolar a porta da Manutenção em `8900` (configurável via env) e incluir checagem prévia no script PowerShell.
3. **Risco:** Exposição inadvertida do microserviço Node.js ou Waitress na rede local.  
   **Mitigação:** Garantir bind estrito em `127.0.0.1` em ambos os serviços.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. **Arquiteto:** Criar SPEC e `implementation_plan.md` e apresentar ao usuário.
2. **Backend:**
   - Adicionar dependências em `requirements.txt`.
   - Atualizar `settings.py` (WhiteNoise, static root, proxy ssl, cookies).
   - Ajustar bind de `whatsapp_service/server.js` para `127.0.0.1`.
   - Criar `scripts/start_production.ps1`.
   - Criar `DEPLOY_WINDOWS_SERVER.md`.
   - Atualizar `.env.example`, `.gitignore` e `Instrucoes.txt`.
3. **QA:**
   - Executar `check`, `test`, `makemigrations --check --dry-run`, `collectstatic`.
   - Testar `start_production.ps1` com testes de borda.
   - Executar teste de fumaça local no Waitress em `127.0.0.1:8900` com `DEBUG=False`.
   - Verificar `git status` e `git check-ignore`.

---

## 🧪 11. TESTES MANUAIS E AUTOMATIZADOS

1. `.\.venv\Scripts\python.exe manage.py check`
2. `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`
3. `.\.venv\Scripts\python.exe manage.py test`
4. `.\.venv\Scripts\python.exe manage.py collectstatic --noinput`
5. `.\.venv\Scripts\python.exe manage.py check --deploy`
6. Testes do script PowerShell em `scripts/start_production.ps1` (cenários válidos e inválidos).
7. Teste do servidor Waitress escutando em `127.0.0.1:8900`.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

- Lista de arquivos lidos e alterados.
- Relatório de testes automatizados e de fumaça.
- Confirmação de ausência de migrações e de não intervenção no servidor remoto.
