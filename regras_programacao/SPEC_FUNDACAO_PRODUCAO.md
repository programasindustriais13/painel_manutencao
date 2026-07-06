# 🧠 SPEC — FUNDAÇÃO DO MÓDULO DE PRODUÇÃO E INTEGRAÇÃO SCADA-LTS

---

## 📌 1. CONTEXTO

- **URL(s) envolvidas:** `/producao/` (Nova raiz do módulo)
- **Contexto(s):** Criação de ambiente isolado para monitoramento de chão de fábrica via Scada-LTS.
- **Perfil(s) afetados:** Novo grupo de usuários: "Liderança de Produção".

---

## ❗ 2. PROBLEMA ATUAL

- O sistema atual é focado exclusivamente na Manutenção. 
- A liderança de produção precisa de um painel para fiscalizar máquinas paradas e consultar dados de produção extraídos do Scada-LTS (via MySQL), mas **NÃO DEVE** ter acesso às telas e ferramentas da manutenção (e vice-versa).
- O sistema atual já está em produção, logo, qualquer alteração estrutural deve ser feita de forma paralela e cirúrgica para não quebrar o que já funciona.
- O Django precisa ser preparado para integrar com o banco MySQL do Scada-LTS sem tentar executar migrações ou criar tabelas padrão do Django (auth, sessions, etc.) nele.

---

## 🎯 3. OBJETIVO

- Analisar a viabilidade e os dados descritos em `DOCUMENTACAO_MYSQL_SCADALTS_PAINEL_SINOTICO.md`.
- Criar um novo App Django chamado `production`.
- Criar a casca do novo Dashboard isolado para a liderança.
- Configurar o redirecionamento de login: se for Líder de Produção (grupo "Liderança de Produção"), vai para `/producao/`; se for Manutenção, vai para as rotas atuais.
- Configurar o controle de acesso (permissões): usuários de manutenção não entram em `/producao/`, e líderes de produção não entram na manutenção.
- Preparar a base de configuração no `settings.py` para suportar o banco de dados MySQL secundário (`scada`), configurando um Database Router para evitar migrações indesejadas nesse banco.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Novos arquivos:
- `production/`
  - `production/apps.py` (Registro do app)
  - `production/urls.py` (Definição da rota `/producao/`)
  - `production/views.py` (Dashboard e controle de acesso)
  - `production/routers.py` (Database Router para isolamento do MySQL `scada`)
  - `production/decorators.py` (Decorators de segurança para o novo módulo)
  - `production/templates/production/base_production.html` (Base layout do dashboard de produção)
  - `production/templates/production/dashboard.html` (Template do dashboard de produção)

### Arquivos existentes a alterar:
- `maintenance_project/settings.py` (Adicionar `production`, registrar `DATABASE_ROUTERS` e definir `DATABASES['scada']`)
- `maintenance_project/urls.py` (Incluir rotas de `production`)
- `maintenance/views.py` (Ajustar redirecionamento de `home_redirect` e os decorators `@operador_required`, `@lider_ou_operador_required` e `@tecnico_or_operador_required` para redirecionar líderes de produção para `/producao/` se tentarem acessar a manutenção)
- `maintenance_project/__init__.py` (Adicionar monkey-patch para `pymysql` para facilitar conexões em sistemas Windows locais)
- `requirements.txt` (Adicionar `pymysql` caso não esteja instalado)

---

## 🚫 5. FORA DE ESCOPO

- NÃO implementar agora os gráficos, tabelas e lógicas complexas de leitura/escrita do Scada-LTS.
- NÃO alterar a lógica de funcionamento de nenhuma tela do app `maintenance`.
- NÃO alterar NENHUM arquivo que esteja fora do diretório atual de trabalho (workspace do projeto).

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION)

⚠️ Esta implementação DEVE seguir o `constitution.md`

### Regras críticas:
- ✅ **RISCO ZERO À PRODUÇÃO:** O app atual de manutenção deve continuar intacto. 
- ✅ **Isolamento de Banco de Dados:** O Django deve ser configurado com múltiplos bancos de dados (Database Routing). O SQLite continua sendo o `default` para o sistema, e o MySQL será um banco secundário chamado `scada`.
- ✅ **Segurança de Acesso:** Proteger as rotas de `/producao/` para que técnicos de manutenção não acessem, e proteger as rotas de `/management/` (e outras de manutenção) para que líderes de produção não acessem.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

1. **Criação do App:** O novo app `production` será criado e registrado em `INSTALLED_APPS`.
2. **Grupo de Usuários:** O administrador criará o grupo "Liderança de Produção" no Django Admin.
3. **Login Condicional:** Ao realizar login, a view `home_redirect` verifica os grupos do usuário:
   - Se pertencer à "Liderança de Produção", redireciona para `/producao/`.
   - Caso contrário, mantém o comportamento atual.
4. **Dashboard Vazio:** A view `production_dashboard` exibe o template `production/dashboard.html` herdando de `base_production.html`, mostrando a mensagem "Bem-vindo ao Painel de Produção".
5. **Configuração MySQL:** No `settings.py`, adicionar a estrutura `DATABASES['scada']` configurada para conectar no MySQL do Scada-LTS usando o backend `django.db.backends.mysql`. Adicionar `pymysql` em `requirements.txt` e inicializá-lo em `__init__.py`.
6. **Database Router:** Implementar `ScadaRouter` para garantir que o Django não tente rodar migrações (django auth, admin, contenttypes, sessions, etc.) na conexão `scada`.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Consigo rodar o servidor normalmente sem erros no app antigo.
- [ ] O app `production` existe e possui rotas próprias `/producao/`.
- [ ] Um usuário do grupo Liderança de Produção é direcionado corretamente para o novo painel, e tem acesso negado às rotas da manutenção.
- [ ] O `settings.py` possui o esboço/configuração correta para conectar no MySQL do Scada-LTS futuramente.
- [ ] O comando `python manage.py migrate` funciona sem tentar interagir com a base `scada`.

---

## ⚠️ 9. RISCOS

- **Múltiplos Bancos (Routers):** O Django tentará rodar as migrações padrão do sistema no banco MySQL se não houver um `DatabaseRouter`. Garanta que a configuração defina que as tabelas padrão do Django vão apenas para o `default` (SQLite).
- **Pacotes do MySQL:** A instalação de `mysqlclient` pode falhar no Windows. Utilizaremos o pacote `pymysql` como driver MySQL fallback de forma declarativa e transparente.

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO (OBRIGATÓRIO)

### Passos:
1. Adicionar `pymysql` ao `requirements.txt`.
2. Habilitar o monkeypatch do `pymysql` em `maintenance_project/__init__.py`.
3. Criar a pasta do app `production` e os arquivos estruturais (`apps.py`, `urls.py`, `views.py`, `routers.py`, `decorators.py`).
4. Criar a estrutura de templates sob `production/templates/production/`.
5. Modificar `maintenance_project/settings.py` para incluir o app `production`, o banco `scada` e o `DATABASE_ROUTERS`.
6. Modificar `maintenance_project/urls.py` para incluir a rota do app `production`.
7. Ajustar `maintenance/views.py` para gerenciar o redirecionamento condicional de login no `home_redirect` e nos decorators de acesso da manutenção.
8. Criar testes unitários para validar a lógica de redirecionamento e proteção de rotas.

---

## 🧪 11. TESTES MANUAIS

1. Criar o grupo "Liderança de Produção" e um usuário associado a este grupo.
2. Efetuar o login com o usuário da Liderança de Produção e validar o redirecionamento para `/producao/`.
3. Validar se o usuário da Liderança de Produção é impedido de acessar `/management/`, `/dashboard/` ou `/cruds/`.
4. Efetuar o login com um Técnico e validar que ele continua sendo direcionado para `/management/`, e se tentar acessar `/producao/` recebe acesso negado.
5. Rodar as migrações locais para verificar a segurança do banco `scada`.
