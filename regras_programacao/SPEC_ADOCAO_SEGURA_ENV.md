# 🧠 SPEC — ADOÇÃO SEGURA DE VARIÁVEIS DE AMBIENTE (.ENV)

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** N/A (Configuração global de infraestrutura e ambiente)
- **Contexto(s):** Configurações do projeto Django (`maintenance_project/settings.py`) e integrações auxiliares.
- **Perfil(s) afetados:** Todos (desenvolvimento local, preparação para ambiente de produção em subdomínio `freedom.dev.br`).

---

## ❗ 2. PROBLEMA ATUAL

- O projeto não possui um arquivo `.env` para gestão de variáveis de ambiente.
- Parâmetros de ambiente como `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, credenciais do banco secundário `scada` (MySQL) e URL do microserviço de WhatsApp (`http://localhost:3000/send`) encontram-se hardcoded no código-fonte (`settings.py` e `views.py`).
- Isso impede a publicação segura do sistema no ambiente de servidor/produção e exige alteração no código-fonte a cada mudança de ambiente.

---

## 🎯 3. OBJETIVO

- Implementar o carregamento seguro e padronizado de variáveis de ambiente no Django a partir do arquivo `.env` via `python-dotenv`.
- Criar `.env` funcional para o ambiente de desenvolvimento local (mantendo SQLite por padrão).
- Criar `.env.example` documental, seguro, contendo apenas chaves e valores fictícios/exemplo.
- Garantir a retenção do `.env` fora do versionamento Git (já configurado no `.gitignore`).
- Manter 100% de retrocompatibilidade com o ambiente de desenvolvimento local atual através de fallbacks seguros.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos:
- `regras_programacao/SPEC_ADOCAO_SEGURA_ENV.md` (SPEC criada)
- `.env` (novo arquivo local funcional, ignorado pelo git)
- `.env.example` (novo arquivo modelo seguro)
- `maintenance_project/settings.py` (leitura de env vars para SECRET_KEY, DEBUG, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DATABASES, TIME_ZONE, LANGUAGE_CODE e WHATSAPP_SERVICE_URL)
- `maintenance/views.py` (uso de `settings.WHATSAPP_SERVICE_URL` na chamada HTTP ao microserviço)
- `requirements.txt` (inclusão da dependência `python-dotenv>=1.0.0`)
- `Instrucoes.txt` (registro documental das alterações)

---

## 🚫 5. FORA DE ESCOPO

- Configuração de Cloudflare, túneis, DNS, IIS, serviços do Windows ou servidores Web.
- Alteração do banco `db.sqlite3` local ou execução de migrações (`makemigrations`/`migrate`).
- Alteração do banco de dados `scada` (MySQL).
- Refatoração ampla do `settings.py` ou criação de múltiplos arquivos de settings (`settings_dev.py`, `settings_prod.py`).
- Alterações em regras de negócio dos modelos ou views (exceto a URL configurável do WhatsApp).
- Commits ou envios de código ao repositório remoto (GitHub).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

- ❌ Não criar múltiplos ambientes virtuais.
- ❌ Não duplicar projeto ou aplicações Django.
- ❌ Não expor credenciais reais no `.env.example` nem em relatórios.
- ✅ Reutilizar a estrutura atual do Django.
- ✅ Manter total compatibilidade local com SQLite.
- ✅ Alterar o mínimo de código possível.

---

## ⚙️ 7. REGRAS DE NEGÓCIO E VARIÁVEIS DE AMBIENTE

As seguintes variáveis serão padronizadas para leitura em `settings.py`:

| Variável de Ambiente | Descrição | Valor Padrão (Local) |
|---|---|---|
| `SECRET_KEY` | Chave secreta da aplicação | `django-insecure-m5=fgwb0=lmm(#!_2%*v!j-1v%du!y++6nhoplf1vfttbthz14` |
| `DEBUG` | Modo de depuração | `True` |
| `ALLOWED_HOSTS` | Hosts permitidos (separados por vírgula) | `*` |
| `CSRF_TRUSTED_ORIGINS` | Origens confiáveis para CSRF (separadas por vírgula) | *(vazio)* |
| `DATABASE_ENGINE` | Engine do banco principal | `django.db.backends.sqlite3` |
| `DATABASE_NAME` | Nome/Caminho do banco principal | `db.sqlite3` |
| `DATABASE_USER` | Usuário do banco principal | *(vazio)* |
| `DATABASE_PASSWORD` | Senha do banco principal | *(vazio)* |
| `DATABASE_HOST` | Host do banco principal | `127.0.0.1` |
| `DATABASE_PORT` | Porta do banco principal | `3306` |
| `SCADA_DB_ENGINE` | Engine do banco secundário SCADA | `django.db.backends.mysql` |
| `SCADA_DB_NAME` | Nome do banco secundário SCADA | `scadalts` |
| `SCADA_DB_USER` | Usuário do banco secundário SCADA | `scada_monitor_ro` |
| `SCADA_DB_PASSWORD` | Senha do banco secundário SCADA | `SENHA_FORTE_LEITURA` |
| `SCADA_DB_HOST` | Host do banco secundário SCADA | `127.0.0.1` |
| `SCADA_DB_PORT` | Porta do banco secundário SCADA | `3306` |
| `TIME_ZONE` | Fuso horário da aplicação | `America/Sao_Paulo` |
| `LANGUAGE_CODE` | Idioma da aplicação | `pt-br` |
| `WHATSAPP_SERVICE_URL` | URL de envio do microserviço WhatsApp | `http://localhost:3000/send` |

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] `.env` criado localmente com os valores funcionais do ambiente de desenvolvimento.
- [ ] `.env.example` criado com valores fictícios/documentais e sem dados sensíveis.
- [ ] `.env` ignorado pelo Git (`git check-ignore -v .env` confirma a exclusão).
- [ ] `python manage.py check` passa sem erros.
- [ ] O projeto carrega corretamente com `.env` presente ou ausente (fallback local mantido).
- [ ] Nenhuma migração criada ou aplicada.
- [ ] `Instrucoes.txt` atualizado com as modificações efetuadas.

---

## ⚠️ 9. RISCOS

- Quebra de inicialização caso `python-dotenv` não seja importado com tratamento defensivo. *(Mitigação: usar bloco `try...except ImportError` em `settings.py` e fallbacks explícitos).*
- Exposição acidental de credenciais em `.env.example`. *(Mitigação: auditoria prévia detalhada e substituição de todas as credenciais por placeholders no `.env.example`).*

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO

1. Instalar `python-dotenv` no `.venv` e incluir em `requirements.txt`.
2. Atualizar `maintenance_project/settings.py` com a inicialização do `dotenv` e leitura de variáveis de ambiente.
3. Atualizar `maintenance/views.py` para utilizar `settings.WHATSAPP_SERVICE_URL`.
4. Criar `.env` na raiz do projeto com as configurações locais ativas.
5. Criar `.env.example` na raiz do projeto com placeholders documentais seguros.
6. Atualizar `Instrucoes.txt`.
7. Executar validação técnica (`manage.py check`, `git status`, `git check-ignore`).

---

## 🧪 11. TESTES MANUAIS E AUTOMATIZADOS

1. Executar `python manage.py check` para validar integridade das configurações.
2. Executar `git status` e `git check-ignore -v .env` para garantir segurança do Git.
3. Verificar inicialização sem o arquivo `.env` para atestar resiliência dos fallbacks.

---

## 📂 12. EVIDÊNCIAS OBRIGATÓRIAS DO AGENTE

### Evidências da Validação de QA e Endurecimento (2026-07-22):
- **Suíte de Testes:** `py manage.py test` executou 12 testes com 100% de aprovação (0 erros, 0 falhas).
- **Validação de Migrações:** `py manage.py makemigrations --check --dry-run` não detectou nenhuma alteração pendente de modelo/migração.
- **Checagem de Implantação:** `py manage.py check --deploy` executou com sucesso (0 erros, 4 avisos esperados de SSL/HSTS a serem ativados na SPEC de implantação).
- **Proteção em Produção (`DEBUG=False`):**
  - Tentativa sem `DJANGO_SECRET_KEY` válida dispara `ImproperlyConfigured` imediatamente.
  - Tentativa com `DJANGO_ALLOWED_HOSTS` vazio ou `*` dispara `ImproperlyConfigured` imediatamente.
- **Rotas de Smoke Test:** `/management/`, `/dashboard/`, `/admin/login/` e `/relatorio-turno/` validadas com respostas HTTP 200/302 corretas.
- **Git Security:** `.env` validado como ignorado pelo Git via `git check-ignore -v .env`.

---

## 🛑 13. ALINHAMENTO DE AMBIENTE E REMOÇÃO DE MONKEY PATCH (2026-07-22)

- **Remoção de Monkey Patch:** O monkey patch de compatibilidade para `BaseContext`, `Context`, `Context.__copy__` e o módulo `copy` foi 100% removido de `maintenance_project/settings.py`.
- **Causa Raiz do Patch:** O patch havia sido inserido temporariamente devido à execução local sob Python 3.14.
- **Padronização do Ambiente:**
  - O servidor de produção utiliza **Python 3.11.3**.
  - O ambiente oficial deste projeto foi padronizado em **Python 3.11** para paridade total entre desenvolvimento local e servidor Windows.
  - Desenvolvimento e produção devem permanecer na mesma versão major/minor (`Python 3.11.x`).
  - Nenhuma modificação interna no Django é permitida para contornar incompatibilidades de versões experimentais/não suportadas do Python.
  - Futuras atualizações do Python ou do Django devem ser tratadas em uma SPEC independente.
- **Status do Ambiente Local (Concluído em 2026-07-28):**
  - Python 3.11.3 instalado localmente, alcançando paridade exata 1:1 com o Windows Server de produção.
  - A pasta legada quebrada `venv` foi removida/sanada, restando unicamente o ambiente oficial `.venv` na raiz.
  - O `.venv` foi criado com Python 3.11.3 (`.\.venv\Scripts\python.exe --version` = `Python 3.11.3`).
  - Dependências reinstaladas e fixadas no `.venv`, incluindo Django 4.2.27 (`.\.venv\Scripts\python.exe -m django --version` = `4.2.27`).
  - Nenhuma alteração funcional ou monkey patch restou no código do projeto (`settings.py` limpo).

---

## 🚀 14. RELATÓRIO DE QA E CONSOLIDAÇÃO DO AMBIENTE (2026-07-28)

- **Paridade de Ambiente:**
  - Python local oficial: `3.11.3`
  - Python do servidor: `3.11.3`
  - Django no `.venv`: `4.2.27`
- **Gestão de Ambientes Virtuais:**
  - Ambiente legado `venv`: Removido / Inexistente.
  - Ambiente oficial `.venv`: Criado e mantido como único ambiente virtual na raiz do projeto.
- **Auditoria de Monkey Patch:**
  - Auditado 100% do codebase para `BaseContext`, `Context`, `_base_context_copy`, `_context_copy` e compatibilidades com Python 3.14. Nenhuma ocorrência funcional encontrada.
- **Suíte de Testes Automatizados:**
  - `manage.py check`: 0 erros (System check identified no issues).
  - `manage.py makemigrations --check --dry-run`: No changes detected (Nenhuma migração gerada/necessária).
  - `manage.py test`: 12 testes executados, 12 aprovados (100% de sucesso, 0 falhas, 0 erros, ~13.7s de duração).
- **Validação de Produção (`manage.py check --deploy`):**
  - Executado temporariamente com `DEBUG=False`, `DJANGO_ALLOWED_HOSTS=manutencao.freedom.dev.br`, `DJANGO_CSRF_TRUSTED_ORIGINS=https://manutencao.freedom.dev.br` e chave forte temporária.
  - Erros: 0.
  - Avisos: 4 (`security.W004`, `security.W008`, `security.W012`, `security.W016`), todos a serem tratados na futura SPEC de Implantação no Windows Server (HTTPS/HSTS/SSL/Cookies seguros).
- **Smoke Tests de Rotas:**
  - `/management/` (sem autenticação): HTTP 302 (Redirecionamento para `/login/`).
  - `/management/` (autenticado): HTTP 200 (OK).
  - `/dashboard/` (sem autenticação): HTTP 302 (Redirecionamento para `/login/`).
  - `/dashboard/` (autenticado): HTTP 200 (OK).
  - `/admin/login/`: HTTP 200 (OK).
  - `/relatorio-turno/` (sem autenticação): HTTP 302 (Redirecionamento para `/login/`).
  - `/relatorio-turno/` (autenticado como admin sem turno): HTTP 302 (Redirecionamento para `/management/`).
- **Validação Git & Segurança:**
  - `git check-ignore -v .env`: Confirmado ignorado (.gitignore:16).
  - `git check-ignore -v .venv`: Confirmado ignorado (.gitignore:17).
  - Nenhuma migration criada ou aplicada.
  - Nenhum segredo ou dependência de ambiente expostos no Git.
- **Diretriz Futura:**
  - Qualquer eventual atualização futura do Python ou do Django no servidor/ambiente local deve ser planejada e executada através de SPEC independente.



