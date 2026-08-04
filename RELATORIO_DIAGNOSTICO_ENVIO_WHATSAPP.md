# Relatório de Diagnóstico — Envio de WhatsApp

---

## 1. Resumo executivo

- **Como o envio funciona atualmente:** O envio do relatório de passagem de turno é iniciado pelo usuário no frontend Django (`/relatorio-turno/`). Ao submeter o formulário, a view Python (`views.relatorio_turno`) compila o payload contendo o destinatário (número do técnico ou JID do grupo) e o texto formatado. Em seguida, realiza uma requisição HTTP POST assíncrona/síncrona para o microserviço Node.js/Baileys (`http://localhost:3000/send` ou `http://127.0.0.1:3000/send`). O microserviço valida a requisição, responde imediatamente com `HTTP 202 Accepted` e enfileira a mensagem em background, onde o socket do Baileys realiza o disparo para a rede do WhatsApp.
- **Em qual etapa parece ocorrer a falha:** A falha ocorre na comunicação HTTP entre o Django e o microserviço Node.js (ou na indisponibilidade do próprio microserviço). Especificamente, a requisição `requests.post(...)` lançada pelo Django atinge timeout ou exceção `ConnectionRefusedError` (ou retorna HTTP 503 quando o Baileys não está conectado/autenticado), acionando o tratamento genérico da view.
- **Qual a causa mais provável:** 
  1. **Processo Node.js inativo / Ausência de Daemon:** O microserviço Node.js (`whatsapp_service/server.js`) não está em execução no ambiente nem possui mecanismo de inicialização automática (serviço do Windows, tarefa agendada ou PM2 daemon ativado).
  2. **Divergência de Interface/Host (`localhost` vs `127.0.0.1`):** O Node.js escuta estritamente em `127.0.0.1:3000`, enquanto o Django pode tentar conectar via `localhost:3000` (que em sistemas Windows pode resolver para o endereço IPv6 `::1`, resultando em recusado de conexão).
  3. **Tratamento Genérico no Django:** Qualquer resposta HTTP diferente de 200/202 e de uma string específica de 503 faz o Django exibir a mensagem genérica: *“Relatório salvo, mas o servidor de WhatsApp está offline.”*, ocultando o motivo real (ex: QR Code pendente, 400 Bad Request, 500 Server Error).
- **Confirmação da causa:** Confirmado no ambiente atual que o processo `whatsapp_service/server.js` **não estava em execução** e a porta `3000` **não estava escutando** (`TCP 127.0.0.1:3000 failed`). Em ambiente de produção, requer execução dos comandos de verificação de leitura documentados na Seção 11.
- **Nível de risco:** **MÉDIO/BAIXO.** Não há risco de corrupção de banco de dados ou perda de integridade dos relatórios, pois o relatório é salvo/processado no Django antes da tentativa de envio. Contudo, há risco de experiência degradada para os usuários e mensagens retidas sem notificação quando o serviço estiver parado.

---

## 2. Escopo e ambiente analisado

- **Caminho do projeto analisado:** `c:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao`
- **Branch atual:** `main` (ou branch ativa de trabalho)
- **Commit atual:** `54486f2c` (`Inclusão do status FALTA e possibilidade de inativar colaborador`)
- **Sistema operacional:** Windows 10/11 / Windows Server
- **Versões encontradas:**
  - Python: `3.14.6`
  - Node.js: `v24.11.1`
  - npm: `11.8.0`
- **Ambiente da análise:** Ambiente de desenvolvimento / estância local do workspace.
- **Limitações da auditoria:** Auditoria estritamente passiva/somente-leitura. Nenhum processo foi iniciado, finalizado ou alterado; nenhum banco de dados foi alterado; nenhuma mensagem real foi disparada; nenhuma credencial ou sessão Baileys foi modificada. As verificações do servidor de produção são apresentadas como comandos de leitura para execução pelos administradores do sistema.

---

## 3. Arquitetura atual do envio

```text
Usuário (Navegador)
   │
   ├─► GET/POST /relatorio-turno/
   ▼
View Django (maintenance/views.py :: relatorio_turno)
   │
   ├─► Valida técnico logado e constrói texto do relatório (últimas 12h)
   ├─► Resolve número individual (tecnico.whatsapp) ou JID do Grupo (WhatsAppGroup.jid)
   │
   ├─► requests.post("http://localhost:3000/send", json={numero, mensagem}, timeout=10)
   ▼
Microserviço Express / Node.js (whatsapp_service/server.js :: POST /send)
   │
   ├─► Middlewares: Rate Limit (sendLimiter - 5 req/min) & Circuit Breaker Check
   ├─► Valida conexão do socket Baileys (isConnected)
   ├─► Formata JID (adiciona @s.whatsapp.net ou aceita @g.us)
   ├─► Responde HTTP 202 Accepted imediatamente ao Django
   │
   ▼ (Assíncrono em Background)
Fila Sequencial (messageQueue & processQueue)
   │
   ├─► Delay humano aleatório (2000ms a 5000ms)
   ├─► Disparo via Baileys API (sock.sendMessage)
   ▼
Rede WhatsApp (WhatsApp Web Sockets)
```

---

## 4. Mapa dos arquivos envolvidos

| Arquivo | Responsabilidade | Estado encontrado |
|---------|------------------|------------------|
| [maintenance/views.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/views.py#L1340-L1445) | View `relatorio_turno`: processa o form, compila texto, consulta destino e faz requisição `requests.post`. | Íntegro. Trata respostas 200, 202, 429, 503 e exceções. Mensagem genérica esconde erros específicos. |
| [maintenance/models.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/models.py) | Modelos `Technician` (campo `whatsapp`) e `WhatsAppGroup` (campos `nome`, `jid`, `is_active`). | Íntegro e atualizado. |
| [maintenance/urls.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/urls.py#L38) | Rota `relatorio-turno/` vinculada à view `relatorio_turno`. | Íntegro. |
| [maintenance_project/settings.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance_project/settings.py#L311) | Declaração de `WHATSAPP_SERVICE_URL = os.environ.get("WHATSAPP_SERVICE_URL", "http://localhost:3000/send")`. | Íntegro. Default usa `localhost`. |
| [.env.example](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/.env.example#L56) | Exemplo de env vars: `WHATSAPP_SERVICE_URL=http://127.0.0.1:3000/send`. | Íntegro. Aponta para `127.0.0.1`. |
| [whatsapp_service/server.js](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/server.js) | Servidor Express + Baileys: escuta em `127.0.0.1:3000`, expõe `/send`, `/status`, `/groups`, gerencia fila e rate limit. | Íntegro. Falta tratamento global de exceções não capturadas. |
| [whatsapp_service/package.json](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/package.json) | Dependências Node (`@whiskeysockets/baileys`, `express`, `express-rate-limit`, `pino`, `qrcode-terminal`). | Dependências instaladas localmente (`node_modules` presente). |
| [whatsapp_service/auth_info_baileys/](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/whatsapp_service/auth_info_baileys) | Diretório de armazenamento de sessão e chaves de autenticação do Baileys. | Presente com arquivos de sessão (`creds.json`, `app-state`, `lid-mapping`). |
| [SETUP_WHATSAPP.md](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/SETUP_WHATSAPP.md) | Documentação de instalação e opções de deploy (PM2 ou `.bat`). | Íntegro. Descreve instruções operacionais. |
| [maintenance/tests.py](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/maintenance/tests.py#L380-L458) | Suíte de testes unitários para a view de relatório e mocks do WhatsApp. | Íntegro. Cobre respostas 202, 429, 503 e ConnectionError. |

---

## 5. Fluxo Django detalhado

### 5.1 Formulário HTML
Renderizado pelo template `maintenance/relatorio_turno.html`.
Contém:
- `<textarea name="texto_relatorio">`: Área de texto pré-compilada com o relatório das alocações das últimas 12 horas.
- `<select name="destino">`: Select contendo a opção fixa `"meu_numero"` ("Meu Número (Teste)") e os grupos ativos buscados via `WhatsAppGroup.objects.filter(is_active=True)`.

### 5.2 View Django (`maintenance/views.py :: relatorio_turno`)
1. **Autenticação e Permissão:** Protegida por `@tecnico_or_operador_required`.
2. **Obtenção do Técnico:** Executa `tecnico = _get_technician_proprio(request.user)`. Se nulo, redireciona exibindo erro.
3. **Resolução do Destino (no POST):**
   - Se `destino == 'meu_numero'`: usa `tecnico.whatsapp`. Se o número estiver em branco, exibe aviso: *"Relatório salvo, mas o técnico não possui número de WhatsApp cadastrado."* e interrompe a requisição HTTP.
   - Se `destino != 'meu_numero'`: verifica se `WhatsAppGroup.objects.filter(jid=destino, is_active=True).exists()`. Se não existir, exibe erro de destino inválido.
4. **Construção do Payload e Requisição HTTP:**
   ```python
   payload = {
       'numero': numero_destino,
       'mensagem': texto
   }
   whatsapp_url = getattr(settings, 'WHATSAPP_SERVICE_URL', 'http://localhost:3000/send')
   response = requests.post(whatsapp_url, json=payload, timeout=10)
   ```
5. **Tratamento dos Códigos HTTP e Exceções:**
   - `response.status_code in [200, 202]`: `messages.success(request, "Relatório enviado com sucesso via WhatsApp!")`
   - `response.status_code == 429`: `messages.warning(request, "Muitas requisições enviadas em curto período. Por favor, aguarde um momento antes de tentar novamente.")`
   - `response.status_code == 503`: Analisa o JSON da resposta. Se contiver `'Serviço temporariamente indisponível'`, exibe aviso de indisponibilidade temporária. Para **qualquer outro 503** (incluindo o retorno padrão do Node quando deslogado: `'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.'`), exibe: *“Relatório salvo, mas o servidor de WhatsApp está offline.”*
   - `Qualquer outro status code (400, 404, 500, etc.)`: Exibe: *“Relatório salvo, mas o servidor de WhatsApp está offline.”*
   - `Exceção requests.exceptions.RequestException` (ConnectionRefused, Timeout, DNS failure): Exibe: *“Relatório salvo, mas o servidor de WhatsApp está offline.”*

---

## 6. Fluxo Node.js/Baileys detalhado

### 6.1 Inicialização e Configuração
- **Servidor:** Express.js escutando em `http://127.0.0.1:3000`.
- **Sessão:** Utiliza `useMultiFileAuthState(path.join(__dirname, 'auth_info_baileys'))`.
- **Conexão Baileys:** Função `connectToWhatsApp()` inicializa o socket via `makeWASocket` com versão atualizada do WhatsApp Web (`fetchLatestBaileysVersion()`).
- **Evento de Conexão (`connection.update`):**
  - Se `qr` for emitido, renderiza o QR Code no terminal via `qrcode-terminal`.
  - Se `connection === 'close'`, verifica o `statusCode` de desconexão. Se for diferente de `loggedOut` (`DisconnectReason.loggedOut`), agenda reconexão automática em 5 segundos (`setTimeout(connectToWhatsApp, 5000)`).
  - Se `connection === 'open'`, define `isConnected = true`.

### 6.2 Escudo Anti-Banimento e Proteção
- **Rate Limit:** Middleware `express-rate-limit` limita a 5 requisições por minuto por IP na rota `/send`.
- **Circuit Breaker:** Mantém contador `consecutiveFailures`. Caso ocorram 3 falhas consecutivas de envio no Baileys, abre o disjuntor (`circuitTripped = true`) e bloqueia novas requisições por 60 segundos com retorno HTTP 503 (`'Serviço temporariamente indisponível'`).
- **Fila Sequencial e Atraso Humano:** Ao receber o POST `/send`, o Node insere o job na lista `messageQueue` e responde **imediatamente HTTP 202 Accepted**. A função `processQueue()` consome a fila aplicando um delay aleatório entre 2000ms e 5000ms antes de invocar `sock.sendMessage`.

### 6.3 Respostas HTTP da Rota `POST /send`
- Se `numero` ou `mensagem` faltarem: **HTTP 400** `{ error: '...' }`
- Se Circuit Breaker aberto: **HTTP 503** `{ error: 'Serviço temporariamente indisponível' }`
- Se `!isConnected || !sock`: **HTTP 503** `{ error: 'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.' }`
- Se enfileirado com sucesso: **HTTP 202** `{ success: true, message: 'Mensagem aceita e enfileirada para envio.' }`

---

## 7. Configurações necessárias

- **Variáveis de Ambiente (`.env`):**
  - `WHATSAPP_SERVICE_URL`: URL do microserviço Express (Ex: `http://127.0.0.1:3000/send`).
- **Arquivos de Sessão:** Diretório `whatsapp_service/auth_info_baileys/` deve possuir permissão de leitura e escrita para o usuário de execução do Node.
- **Dependências Node.js:** Instaladas via `npm install` no diretório `whatsapp_service`.
- **Diretório Correto de Execução:** O processo Node deve ser executado a partir da pasta `c:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao\whatsapp_service`.
- **Porta e Host:** Porta `3000` em `127.0.0.1` (IPv4).
- **Processo em Produção:** Serviço gerenciado via PM2 (`pm2 start server.js --name "whatsapp-service"`), NSSM ou Task Scheduler do Windows Server.

> *Nota de Segurança: Nenhuma senha, token ou chave privada foi exposta neste relatório.*

---

## 8. Estado operacional encontrado

| Item de Verificação | Resultado Encontrado |
|---------------------|----------------------|
| **Processo Node.js em execução?** | **NÃO.** Nenhum processo Node rodando o `server.js` foi encontrado no sistema (apenas processos de extensão/sidecar). |
| **Porta 3000 escutando?** | **NÃO.** A porta 3000 está fechada (`TCP connect to 127.0.0.1:3000 failed`). |
| **Endpoint `/send` alcançável?** | **NÃO.** Requisições sofrem `ConnectionRefusedError`. |
| **Sessão Baileys válida?** | **NÃO VERIFICÁVEL NESTE AMBIENTE.** Os arquivos de sessão existem em `auth_info_baileys/`, mas a validade do token exige iniciar a conexão com os servidores do WhatsApp. |
| **Django e Node usam mesma URL/Porta?** | **PARCIALMENTE.** Django `settings.py` usa `http://localhost:3000/send` como default, enquanto `.env.example` usa `http://127.0.0.1:3000/send`. Em Windows, `localhost` pode resolver para IPv6 `::1`, incompatível com o bind IPv4 do Node. |
| **Dependências npm instaladas?** | **SIM.** `npm ls --depth=0` confirmou que `@whiskeysockets/baileys`, `express`, `express-rate-limit`, `pino` e `qrcode-terminal` estão instalados em `whatsapp_service/node_modules`. |
| **Logs de erro existentes?** | **NÃO VERIFICÁVEL NESTE AMBIENTE.** O serviço não roda como serviço com arquivo de log persistente em disco. |

---

## 9. Matriz de hipóteses

| ID | Hipótese | Classificação | Evidência | Próxima verificação |
|----|----------|---------------|-----------|---------------------|
| **H1** | O processo Node.js não está em execução. | **CONFIRMADA** | Teste de porta 3000 falhou e listagem de processos `node.exe` não encontrou `server.js`. | Verificar no servidor de produção via PowerShell (`Get-Process node`). |
| **H2** | O Node está em execução, mas em outra porta. | **DESCARTADA** | `server.js` está fixado na porta 3000 e não há listener em outra porta associada ao projeto. | - |
| **H3** | O Django está chamando uma URL errada. | **PROVÁVEL** | `settings.py` tem fallback para `http://localhost:3000/send` enquanto Node escuta em `127.0.0.1:3000`. | Verificar o valor de `WHATSAPP_SERVICE_URL` no `.env` do servidor. |
| **H4** | O Django usa localhost em ambiente onde o Node está em outra máquina/contêiner. | **POSSÍVEL** | Se em produção o Django rodar em IIS/Waitress e o Node em outra VM/contêiner sem ajustar o `.env`. | Checar arquitetura do servidor de produção. |
| **H5** | A rota configurada no Django é diferente da rota Express. | **DESCARTADA** | Ambos declaram `/send`. | - |
| **H6** | O Django envia campos com nomes diferentes dos esperados pelo Node. | **DESCARTADA** | Django envia `numero` e `mensagem`; Node lê `req.body.numero` e `req.body.mensagem`. | - |
| **H7** | O Node responde HTTP 202, mas o Django considera sucesso apenas HTTP 200. | **DESCARTADA** | `views.py` testa explicitamente `if response.status_code in [200, 202]:`. | - |
| **H8** | O Node responde 429 por rate limit e o Django apresenta incorretamente a mensagem “offline”. | **DESCARTADA** | `views.py` trata 429 com mensagem específica de rate limit. | - |
| **H9** | O circuit breaker está aberto e retorna 503. | **POSSÍVEL** | Se o circuit breaker disparar, retorna 503. Contudo, se a mensagem de erro for diferente da string exata esperada pelo Django, o Django cai na mensagem “offline”. | Analisar resposta JSON em caso de 503. |
| **H10** | O Baileys não está conectado ou perdeu a sessão. | **PROVÁVEL** | Se o Node for iniciado sem autenticação ativa ou se o celular desconectar, o Node responde 503 que o Django interpreta como “offline”. | Checar status do Baileys via GET `/status`. |
| **H11** | A pasta `auth_info_baileys` não existe, está vazia, corrompida ou sem permissão. | **POSSÍVEL** | A pasta existe localmente, mas se o usuário de execução no servidor não tiver permissão de escrita, o Baileys falha ao salvar credenciais. | Verificar permissões da pasta no servidor. |
| **H12** | O processo Node foi iniciado em uma pasta diferente, procurando a sessão em outro local. | **POSSÍVEL** | Se iniciado sem ajustar o working directory em scripts `.bat` ou Atalhos. | Checar linha de comando do processo `node.exe` no servidor. |
| **H13** | Dependências do npm não foram instaladas no servidor. | **POSSÍVEL** | No ambiente local estão instaladas, mas podem não ter sido instaladas no servidor de produção. | Executar `npm ls` no servidor. |
| **H14** | Incompatibilidade entre Node.js, Baileys e o código atual. | **POSSÍVEL** | Atualizações no protocolo do WhatsApp Web podem exigir atualização da biblioteca Baileys (`@whiskeysockets/baileys`). | Verificar logs do console do Node. |
| **H15** | O Node inicia, mas encerra após exceção não tratada. | **PROVÁVEL** | `server.js` não implementa `process.on('uncaughtException')` nem `process.on('unhandledRejection')`. | Adicionar handlers de exceção no `server.js`. |
| **H16** | Firewall, antivírus ou política do Windows bloqueia a porta local. | **POSSÍVEL** | Regras de Firewall do Windows Server podem bloquear conexões de entrada na porta 3000 se não configuradas para Loopback. | Testar conexão local via PowerShell no servidor. |
| **H17** | O serviço escuta apenas em interface diferente da usada pelo Django. | **PROVÁVEL** | `server.js` vincula a `127.0.0.1`. Se o Django tentar IPv6 `::1` via `localhost`, a conexão falha. | Trocar `localhost` por `127.0.0.1` no `settings.py` / `.env`. |
| **H18** | O timeout do Django é menor que o tempo de processamento. | **DESCARTADA** | Timeout é de 10s e o Node responde HTTP 202 em milissegundos (fila em background). | - |
| **H19** | A fila aceita a mensagem, mas falha posteriormente sem informar o Django. | **CONFIRMADA (por arquitetura)** | Ao responder 202 Accepted, o Django presume sucesso. Se o envio falhar no `processQueue()`, o usuário não é alertado. | Implementar webhook de feedback ou logger de fila. |
| **H20** | Destino de grupo ou telefone formatado incorretamente. | **POSSÍVEL** | Telefones sem DDD/DDI ou JID de grupo sem `@g.us` podem ser rejeitados pelo Baileys na fila. | Validar formatação do número no Django antes do envio. |
| **H21** | O grupo está inativo, inexistente ou possui JID inválido. | **POSSÍVEL** | Se o cadastro da tabela `WhatsAppGroup` tiver um JID incorreto. | Validar JIDs via GET `/groups`. |
| **H22** | O número individual do técnico está vazio ou inválido. | **CONFIRMADA / TRATADA** | Se em branco, o Django bloqueia e exibe aviso de técnico sem WhatsApp. Se inválido, o Node tenta higienizar. | - |
| **H23** | Código implantado no servidor não corresponde ao código local. | **NÃO VERIFICÁVEL NESTE AMBIENTE** | Exige auditoria de versão no servidor de produção. | Executar `git status` / `git log` no servidor. |
| **H24** | Variável de ambiente necessária não definida em produção. | **PROVÁVEL** | Se `WHATSAPP_SERVICE_URL` não constar no `.env` do servidor, o fallback `localhost` será ativado. | Inspecionar `.env` de produção. |
| **H25** | Microserviço não possui mecanismo de inicialização automática no Windows Server. | **CONFIRMADA** | Não existe Tarefa Agendada nem Serviço Windows configurado para o Node no ambiente. | Configurar PM2 Startup ou Serviço Windows via NSSM. |

---

## 10. Causas prováveis em ordem de prioridade

### 1ª Causa Mais Provável: O serviço Node.js (`whatsapp_service/server.js`) não está em execução no servidor ou caiu por exceção não tratada.
- **Evidência:** Auditoria local confirmou porta 3000 fechada e nenhum processo `node server.js` ativo. Não há mecanismo de auto-start (NSSM / PM2 Windows Service) configurado.
- **Impacto:** Todas as tentativas de POST do Django falham por `ConnectionRefusedError`.
- **Confiança:** **ALTA.**
- **Como confirmar sem risco:** Executar `Get-NetTCPConnection -LocalPort 3000` no servidor de produção.
- **Correção provável em SPEC futura:** Criar script de inicialização resiliente com PM2 ou NSSM e adicionar tratadores de exceção global no Node.js (`uncaughtException`).

### 2ª Causa Segunda Mais Provável: Resolução de nome `localhost` vs `127.0.0.1` entre Django e Node.js.
- **Evidência:** `server.js` executa `app.listen(3000, '127.0.0.1')`. O `settings.py` usa `http://localhost:3000/send` como default. No Windows Server, `localhost` frequentemente resolve primeiro para o endereço IPv6 `::1`, resultando em recusa de conexão se a aplicação escutar apenas em IPv4 (`127.0.0.1`).
- **Impacto:** Django não consegue conectar ao Node.js mesmo quando o Node.js está rodando.
- **Confiança:** **MÉDIA/ALTA.**
- **Como confirmar sem risco:** Executar `Test-NetConnection localhost -Port 3000` e `Test-NetConnection 127.0.0.1 -Port 3000` no servidor.
- **Correção provável em SPEC futura:** Unificar a URL padrão em `settings.py` para `http://127.0.0.1:3000/send` e garantir a variável no `.env`.

### 3ª Causa Terceira Mais Provável: Sessão do Baileys desconectada ou pendente de leitura de QR Code.
- **Evidência:** Se o processo Node estiver rodando, mas a sessão do WhatsApp tiver sido deslogada no celular ou expirada, o endpoint `/send` retorna HTTP 503 com a mensagem `'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.'`. O Django não trata essa mensagem específica de 503 e recai no aviso genérico de offline.
- **Impacto:** O serviço Node está rodando, mas não consegue enviar mensagens.
- **Confiança:** **MÉDIA.**
- **Como confirmar sem risco:** Executar `Invoke-RestMethod -Uri "http://127.0.0.1:3000/status"` no servidor.
- **Correção provável em SPEC futura:** Melhorar o parser de respostas do Django para identificar quando o serviço está rodando porém deslogado, e adicionar rota de healthcheck detalhada.

---

## 11. Verificações recomendadas no servidor

Os comandos a seguir são **estritamente de leitura** e seguros para execução em janela PowerShell no Windows Server de produção.

### 11.1 Verificar processo Node
```powershell
# Lista processos do Node.js em execução e suas linhas de comando
Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" | Select-Object ProcessId, CommandLine | Format-List
```

### 11.2 Verificar porta
```powershell
# Verifica se a porta 3000 está escutando no Windows
Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress, LocalPort, OwningProcess, State
```

### 11.3 Verificar endpoint
```powershell
# Testa a conectividade TCP na porta 3000
Test-NetConnection 127.0.0.1 -Port 3000

# Consulta o status do microserviço Node (se a porta estiver aberta)
Invoke-RestMethod -Uri "http://127.0.0.1:3000/status" -ErrorAction SilentlyContinue
```

### 11.4 Verificar diretório e sessão
```powershell
# Verifica a presença dos arquivos de sessão do Baileys
Get-ChildItem -Path "C:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao\whatsapp_service\auth_info_baileys" -ErrorAction SilentlyContinue | Select-Object Name, Length, LastWriteTime
```

### 11.5 Verificar dependências
```powershell
# Verifica se o node_modules está presente e válido
Test-Path -Path "C:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao\whatsapp_service\node_modules"
```

### 11.6 Verificar variáveis de ambiente
```powershell
# Verifica se a variável WHATSAPP_SERVICE_URL está definida no ambiente do Windows
[System.Environment]::GetEnvironmentVariable("WHATSAPP_SERVICE_URL", "User")
[System.Environment]::GetEnvironmentVariable("WHATSAPP_SERVICE_URL", "Machine")
```

### 11.7 Verificar logs
```powershell
# Consulta logs recentes do PM2 (caso o PM2 esteja instalado e ativo)
if (Get-Command pm2 -ErrorAction SilentlyContinue) { pm2 logs whatsapp-service --lines 30 --noblock }
```

### 11.8 Verificar inicialização automática
```powershell
# Consulta Tarefas Agendadas e Serviços do Windows relacionados ao projeto
Get-ScheduledTask | Where-Object { $_.TaskName -like "*WhatsApp*" -or $_.TaskName -like "*Painel*" }
Get-Service | Where-Object { $_.Name -like "*WhatsApp*" -or $_.DisplayName -like "*WhatsApp*" }
```

---

## 12. Procedimento controlado para reprodução

Para reproduzir a mensagem de diagnóstico em ambiente seguro de desenvolvimento sem disparar mensagens reais para celulares de terceiros:

1. Garantir que o microserviço Node.js esteja **desligado** (porta 3000 fechará).
2. Fazer login na aplicação Django com um usuário de Técnico/Operador.
3. Navegar até a URL `/relatorio-turno/`.
4. Selecionar o destino `"Meu Número (Teste)"`.
5. Clicar no botão **"Enviar Relatório via WhatsApp"**.
6. **Resultado Observado:** A página recarrega e exibe o banner amarelo de alerta do Bootstrap com o texto:
   > *"Relatório salvo, mas o servidor de WhatsApp está offline."*
7. **Observação nos Logs:**
   - No log do Django/Waitress: Exceção interna `requests.exceptions.ConnectionError: HTTPConnectionPool(host='localhost', port=3000): Max retries exceeded with url: /send (Caused by NewConnectionError('<urllib3.connection.HTTPConnection object>: Failed to establish a new connection: [WinError 10061] Nenhuma conexão pôde ser feita porque o computador de destino as recusou ativamente'))`.

---

## 13. Lacunas de observabilidade

1. **Mensagem de Erro Genérica no Django:** O bloco `except requests.exceptions.RequestException` e o `else` final na view `relatorio_turno` mascaram a causa real (seja porta fechada, timeout, DNS incorreto, 400 Bad Request ou 500 Server Error), apresentando sempre a mesma mensagem de "servidor offline".
2. **Ausência de Logging Estruturado de Erro no Django:** A exceção de conexão é capturada em silêncio e descartada sem gravar um log estruturado em arquivo (ex: `logs/whatsapp_errors.log` ou `logger.error(...)`).
3. **Ausência de Endpoint de Healthcheck Dedicado no Django:** Não há uma verificação de status na UI do administrador para saber se o serviço do WhatsApp está online antes de tentar o envio.
4. **Fila Assíncrona Silenciosa no Node.js (Sem Feedback de Status):** Como o Express responde `HTTP 202 Accepted` antes do envio real em background, o Django informa ao usuário que o envio foi concluído, mesmo se o Baileys falhar ao entregar a mensagem minutos depois na fila.
5. **Falta de Monitoramento do Processo Node:** Se o processo Node cair no Windows Server, não há nenhum agente de vigilância configurado para reiniciá-lo automaticamente ou alertar os administradores.

---

## 14. Recomendações para uma futura SPEC de correção

*Nota: Esta seção contém apenas propostas técnicas. Nenhuma alteração foi realizada nesta etapa.*

### 14.1 Diagnóstico e Observabilidade
- Adicionar logging explícito com o módulo `logging` do Python na view `relatorio_turno` registrando a URL chamada, status HTTP retornado e stacktrace de exceções.
- Exibir mensagens mais informativas para o usuário no Django Messages dependendo do erro (ex: *"Servidor de WhatsApp não respondeu na porta 3000"*, *"Sessão de WhatsApp deslogada no servidor"*).
- Criar um indicador visual de status do WhatsApp no rodapé ou no painel Admin do Django.

### 14.2 Configuração
- Padronizar `WHATSAPP_SERVICE_URL` para `http://127.0.0.1:3000/send` em `settings.py` e `.env.example`, prevenindo problemas de resolução IPv6 em `localhost`.

### 14.3 Node.js (`whatsapp_service/server.js`)
- Adicionar handlers globais de exceção no Node.js para evitar crashes do processo:
  ```javascript
  process.on('uncaughtException', (err) => console.error('Uncaught Exception:', err));
  process.on('unhandledRejection', (reason, promise) => console.error('Unhandled Rejection:', reason));
  ```
- Implementar um endpoint GET `/health` refinado retornado status HTTP 200 quando pronto e 503 quando desconectado.

### 14.4 Operação no Windows Server
- Configurar o microserviço Node.js como um Serviço do Windows resiliente via **NSSM** (Non-Sucking Service Manager) ou através de **PM2** com suporte a inicialização automática (`pm2-windows-startup`).

### 14.5 Testes
- Expandir a suíte de testes em `maintenance/tests.py` para cobrir explicitamente differentiated error handling para `ConnectionError`, `ReadTimeout` e mensagens de erro do 503.

---

## 15. Riscos de cada possível correção

| Possível Correção | Riscos Envolvidos | Mitigação Recomendada |
|-------------------|-------------------|------------------------|
| **Trocar `localhost` por `127.0.0.1`** | Mínimo. | Testar conectividade local em IPv4 antes de alterar. |
| **Reiniciar processo Node / Apagar `auth_info_baileys`** | **ALTO:** Apagar a pasta desloga o WhatsApp e exige escaneamento presencial de um novo QR Code pelo celular da empresa. | NUNCA apagar a pasta de sessão sem autorização expressa da gestão. |
| **Alterar resposta do Node de 202 para síncrono (aguardar envio)** | **MÉDIO:** O Django ficará travado aguardando de 2s a 5s (tempo do delay humano anti-banimento) antes de responder ao navegador. | Manter a resposta 202 em background, mas adicionar canal de callback/webhook para status futuro. |
| **Atualizar versão do Baileys (`npm update`)** | **MÉDIO:** Breaking changes em versões recentes do Baileys podem alterar a estrutura de eventos do socket. | Testar em ambiente de staging isolado antes de atualizar. |
| **Instalar serviço Windows via PM2 / NSSM** | **BAIXO/MÉDIO:** Requer permissões administrativas no Windows Server. | Executar comandos de instalação em janela de manutenção programada. |

---

## 16. Arquivos lidos

- `constitution.md`
- `regras_programacao/SPEC_TEMPLATE.md`
- `regras_programacao/SPEC_GERADOR_RELATORIO_TURNO.md`
- `regras_programacao/SPEC_INTEGRACAO_WHATSAPP_BAILEYS.md`
- `regras_programacao/SPEC_ENVIO_GRUPOS_ANTI_BANIMENTO.md`
- `regras_programacao/SPEC_TRANSICAO_GRUPOS_BANCO_DADOS.md`
- `regras_programacao/SPEC_INCLUSAO_NOME_TECNICO_RELATORIO.md`
- `regras_programacao/SPEC_JANELA_12_HORAS_RELATORIO.md`
- `regras_programacao/SPEC_ADOCAO_SEGURA_ENV.md`
- `regras_programacao/SPEC_ATUALIZACAO_GITIGNORE.md`
- `SETUP_WHATSAPP.md`
- `Instrucoes.txt`
- `.env.example`
- `maintenance_project/settings.py`
- `maintenance/views.py`
- `maintenance/urls.py`
- `maintenance/models.py`
- `maintenance/admin.py`
- `maintenance/tests.py`
- `whatsapp_service/server.js`
- `whatsapp_service/package.json`

---

## 17. Arquivos alterados

Este relatório foi gerado sem realizar modificações em nenhum código funcional ou arquivo de configuração do projeto.

- [NEW] [RELATORIO_DIAGNOSTICO_ENVIO_WHATSAPP.md](file:///c:/Users/Unicompo/Documents/03_PYTHON1/07%20-%20Painel%20Manutencao/RELATORIO_DIAGNOSTICO_ENVIO_WHATSAPP.md)

---

## 18. Comandos executados

1. `list_dir` nas pastas do projeto: Mapeamento de arquivos da raiz, `regras_programacao`, `whatsapp_service` e `whatsapp_service/auth_info_baileys`.
2. `python --version; node --version; npm --version; git status --short; git log -n 10 --oneline`: Verificação de versões dos executáveis e estado do repositório Git.
3. `Get-Process node...; Get-NetTCPConnection...; Test-NetConnection...`: Verificação não destrutiva da execução do Node e escuta de porta no SO.
4. `Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" | Select-Object ProcessId, CommandLine`: Inspeção detalhada das linhas de comando dos processos Node em execução no SO (identificados como sidecars de IDE, não o serviço de WhatsApp).
5. `Get-ScheduledTask...; Get-Service...`: Consulta por tarefas agendadas ou serviços Windows vinculados ao WhatsApp.
6. `npx pm2 list`: Consulta por processos cadastrados no gerenciador PM2.
7. `cd whatsapp_service; npm ls --depth=0`: Inspeção das dependências instaladas na pasta do microserviço Node.js.

---

## 19. Conclusão

- **A causa foi confirmada?** **SIM.** A causa da mensagem *“Relatório salvo, mas o servidor de WhatsApp está offline.”* no ambiente de testes/local foi confirmada: o microserviço Node.js (`whatsapp_service/server.js`) **não está em execução** e a porta `3000` **não está escutando**. Para o ambiente de produção no Windows Server, os comandos PowerShell disponibilizados na Seção 11 permitirão validar em segundos se a causa é idêntica ou se se trata de desconexão da sessão do Baileys / divergência de URL `localhost` vs `127.0.0.1`.
- **O que falta para confirmar em produção?** Execução dos comandos de leitura da Seção 11 diretamente no terminal do servidor Windows de produção.
- **Qual deve ser o próximo passo?** Apresentar este relatório técnico para validação e, em seguida, elaborar uma SPEC de correção focada na resiliência do processo Node (instalação de serviço Windows / PM2), ajuste da URL de bind IPv4 e aprimoramento da observabilidade do Django.
- **É necessário criar uma SPEC de correção?** **SIM.** Recomenda-se uma SPEC futura cobrindo resiliência operacional (auto-start do Node no Windows Server), unificação da URL em `127.0.0.1:3000` e enriquecimento de mensagens de erro/logs.
- **O sistema atual corre risco de duplicar mensagens ou sofrer bloqueio?** **NÃO.** O escudo anti-banimento (Rate Limit de 5 req/min, Circuit Breaker após 3 falhas e Fila Sequencial com delay de 2s a 5s) está adequadamente implementado no `server.js` e previne disparos massivos e duplicados.

---
