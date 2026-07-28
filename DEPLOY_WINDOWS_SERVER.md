# 📘 Manual de Implantação no Windows Server 2019 — Subdomínio Manutenção

Este manual descreve o procedimento passo a passo e seguro para realizar a implantação e a manutenção contínua do **Painel de Manutenção Industrial** no Windows Server 2019 sob o subdomínio `manutencao.freedom.dev.br`.

> [!IMPORTANT]
> **ISOLAMENTO TOTAL DO SISTEMA SST:**
> O sistema SST (`sst.freedom.dev.br`) já se encontra em produção no mesmo servidor. Este procedimento **NÃO PODE** alterar, pausar, sobrescrever ou reutilizar:
> - O processo ou a porta do SST;
> - A rota `sst.freedom.dev.br` ou as regras do Cloudflare Tunnel do SST;
> - A pasta, o `.env` ou o banco de dados do SST.

---

## 📋 Pré-requisitos do Servidor
- **Sistema Operacional:** Windows Server 2019
- **Python Oficial:** 3.11.3 (instalado e disponível no sistema)
- **Node.js:** v20.x ou superior (para o microserviço de WhatsApp)
- **Cloudflare Tunnel (`cloudflared`):** Instalado e operacional para o SST
- **Portas Isoladas:**
  - `SST`: Porta dedicada do SST (ex: 8800 ou similar)
  - `Manutenção Django (Waitress)`: `127.0.0.1:8900`
  - `WhatsApp Microservice`: `127.0.0.1:3000`

---

## 🛠️ Fase A — Auditoria do Servidor (Pré-Implantação)

1. **Verificar a versão do Python:**
   ```powershell
   py -3.11 --version
   # Deve retornar: Python 3.11.3
   ```

2. **Navegar até a pasta do projeto de Manutenção:**
   ```powershell
   cd "C:\Caminho\Do\Projeto\Painel_Manutencao"
   ```

3. **Verificar o status do Git:**
   ```powershell
   git status
   ```
   > [!WARNING]
   > Se o workspace contiver alterações não salvas ou arquivos modificados manualmente no servidor, **PARAR A IMPLANTAÇÃO** até que o ambiente esteja limpo.

4. **Verificar a disponibilidade das portas:**
   ```powershell
   Get-NetTCPConnection -LocalPort 8900 -ErrorAction SilentlyContinue
   Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
   ```
   Garantir que a porta `8900` está livre e que a porta `3000` pertence exclusivamente ao microserviço WhatsApp da Manutenção.

5. **Identificar o processo ativo do SST e do Cloudflare:**
   Confirmar que o processo do SST continua rodando normalmente em sua porta própria sem sofrer interferência.

6. **Realizar Backup Preventivo:**
   Antes de atualizar o código, faça cópia de segurança dos seguintes itens para uma pasta de backup fora do projeto:
   - `db.sqlite3` (ou banco MySQL)
   - Pasta de mídia `media/`
   - Arquivo de configuração `.env`
   - Credenciais do WhatsApp em `whatsapp_service/auth_info_baileys/`

---

## 🔄 Fase B — Atualização do Código via Git

1. **Buscar as últimas alterações do repositório:**
   ```powershell
   git fetch origin
   ```

2. **Verificar o commit a ser implantado:**
   ```powershell
   git log -n 5 --oneline
   ```

3. **Realizar a atualização controlada:**
   ```powershell
   git checkout main
   git pull origin main
   ```

> [!CAUTION]
> O Git jamais deve sobrescrever:
> - O arquivo `.env` de produção
> - O banco de dados (`db.sqlite3`)
> - A pasta de mídia (`media/`)
> - A pasta do ambiente virtual (`.venv`)
> - As sessões autenticadas do WhatsApp (`auth_info_baileys/`)

---

## 🐍 Fase C — Preparação do Ambiente Python no Servidor

1. **Garantir a utilização do ambiente virtual `.venv`:**
   Caso ainda não exista no servidor:
   ```powershell
   py -3.11 -m venv .venv
   ```

2. **Instalar/Atualizar as dependências no `.venv`:**
   ```powershell
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. **Executar a verificação do Django:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py check
   ```

4. **Analisar Migrações (Sem executar `migrate` sem autorização):**
   ```powershell
   .\.venv\Scripts\python.exe manage.py showmigrations
   .\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
   ```
   > [!IMPORTANT]
   > A execução de `migrate` no banco de produção exige autorização expressa, backup atualizado e confirmação prévia do banco utilizado.

5. **Coletar arquivos estáticos para o WhiteNoise:**
   ```powershell
   .\.venv\Scripts\python.exe manage.py collectstatic --noinput
   ```

---

## ⚙️ Fase D — Configuração do Arquivo `.env` de Produção

Garantir que o arquivo `.env` na raiz do projeto contenha as chaves abaixo com os valores reais do servidor (sem expor segredos no Git):

```env
# Configurações Django
DJANGO_SECRET_KEY=SUA_CHAVE_SECRETA_REAL_E_FORTE_AQUI
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=manutencao.freedom.dev.br,127.0.0.1,localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://manutencao.freedom.dev.br

# Suporte a Proxy HTTPS (Cloudflare)
DJANGO_USE_X_FORWARDED_HOST=True
DJANGO_TRUST_PROXY_SSL_HEADER=True
DJANGO_SECURE_SSL_REDIRECT=False
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS=False
DJANGO_SECURE_HSTS_PRELOAD=False

# Configurações do Waitress WSGI
WAITRESS_HOST=127.0.0.1
WAITRESS_PORT=8900
WAITRESS_THREADS=4

# Configurações do Banco de Dados Principal
DATABASE_ENGINE=django.db.backends.sqlite3
DATABASE_NAME=db.sqlite3

# Configurações do Banco SCADA
SCADA_DB_ENGINE=django.db.backends.mysql
SCADA_DB_NAME=scadalts
SCADA_DB_USER=seu_usuario_scada
SCADA_DB_PASSWORD=sua_senha_scada
SCADA_DB_HOST=127.0.0.1
SCADA_DB_PORT=3306

# Microserviço WhatsApp
WHATSAPP_SERVICE_URL=http://127.0.0.1:3000/send
```

---

## 🚀 Fase E — Inicialização Manual e Validação

1. **Executar o script de inicialização:**
   ```powershell
   .\scripts\start_production.ps1
   ```

2. **Validação das Rotas Locais (Smoke Tests):**
   Em um navegador no próprio servidor ou via `curl` / `Invoke-WebRequest`:
   - `http://127.0.0.1:8900/login/` → Deve retornar HTTP 200 e carregar o CSS/JS.
   - `http://127.0.0.1:8900/management/` → Deve redirecionar para login (HTTP 302).
   - `http://127.0.0.1:8900/dashboard/` → Deve redirecionar para login (HTTP 302).
   - `http://127.0.0.1:8900/admin/login/` → Deve retornar HTTP 200.

3. **Verificar os arquivos estáticos:**
   Confirmar no navegador local que estilos, ícones e fontes carregam perfeitamente sem erros 404.

---

## 🌐 Fase F — Configuração do Cloudflare Tunnel e Arquitetura de Mídia Protegida

> [!NOTE]
> **ARQUITETURA CONSOLIDADA SEM IIS / ARR / URL REWRITE:**
> O projeto utiliza arquitetura simplificada diretamente com o Cloudflare Tunnel e Waitress. Não é necessário instalar ou configurar o IIS, URL Rewrite ou ARR no servidor nesta etapa. O IIS e a porta 80 do servidor permanecem intactos atendendo outros serviços (como o Scada).

### Arquitetura de Roteamento:
```text
Cloudflare Tunnel
    → http://127.0.0.1:8900
        → Waitress WSGI
            ├── Django
            ├── WhiteNoise (somente para estáticos em /static/)
            └── View autenticada (para anexos privados em /anexos/alocacoes/<id>/)
```

- **Arquivos Estáticos:** Servidos pelo WhiteNoise via `staticfiles/`.
- **Anexos de Mídia:** Servidos exclusivamente pela view autenticada e autorizada `/anexos/alocacoes/<id>/`.
- **Rota `/media/` pública:** Permanece desativada (retornando HTTP 404 em produção com `DEBUG=False`), garantindo que registros internos da fábrica não fiquem expostos de forma anônima.

### Passo a Passo de Configuração do Cloudflare Tunnel:
1. **Acessar o painel do Cloudflare Zero Trust / Tunnels.**
2. **Localizar o túnel existente** que atende a rede da empresa.
3. **Adicionar uma nova regra de Ingress (Public Hostname):**
   - **Subdomínio:** `manutencao`
   - **Domínio:** `freedom.dev.br`
   - **Hostname completo:** `manutencao.freedom.dev.br`
   - **Tipo de Serviço:** `HTTP`
   - **URL de Origem:** `127.0.0.1:8900`
4. **Salvar a configuração do Ingress.**
5. **Testar o acesso público:**
   Acessar `https://manutencao.freedom.dev.br` no navegador externo.
6. **Confirmar a integridade do SST:**
   Acessar `https://sst.freedom.dev.br` para garantir que o serviço parceiro não foi afetado.

---

## 🛠️ Fase G — Configuração de Serviço em Segundo Plano (Windows Service)

Após os testes manuais serem 100% aprovados, configure a execução contínua via Gerenciador de Serviços do Windows utilizando a opção aprovada pela equipe de infraestrutura (ex: **NSSM - Non-Sucking Service Manager** ou **WinSW**):

### Exemplo com NSSM:
```powershell
nssm install PainelManutencaoDjango "C:\Caminho\Do\Projeto\.venv\Scripts\python.exe" "-m waitress --host=127.0.0.1 --port=8900 --threads=4 maintenance_project.wsgi:application"
nssm set PainelManutencaoDjango AppDirectory "C:\Caminho\Do\Projeto\Painel_Manutencao"
nssm set PainelManutencaoDjango Start SERVICE_AUTO_START
nssm start PainelManutencaoDjango
```

---

## ↺ Fase H — Plano de Rollback de Emergência

Caso ocorra alguma falha crítica durante a publicação:

1. **Parar o serviço da Manutenção:**
   ```powershell
   nssm stop PainelManutencaoDjango
   # Ou encerrar o processo no terminal do Waitress
   ```

2. **Remover/Desativar a rota do Cloudflare Tunnel:**
   No painel do Cloudflare, desative ou remova temporariamente o hostname `manutencao.freedom.dev.br`.  
   *NUNCA altere ou remova a rota do SST.*

3. **Reverter o repositório Git para o commit anterior estável:**
   ```powershell
   git checkout <COMMIT_ANTERIOR_HASH>
   ```

4. **Restaurar o Banco de Dados e a Mídia (se necessário):**
   Restaurar a cópia de backup do `db.sqlite3` ou do banco MySQL salva na Fase A.

5. **Confirmar estabilidade dos demais serviços:**
   Verificar que `sst.freedom.dev.br`, o SCADA e o microserviço de WhatsApp continuam operando normalmente.
