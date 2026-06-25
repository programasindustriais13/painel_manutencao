# 📞 Manual de Configuração e Execução: Serviço de WhatsApp (Baileys)

Este manual descreve o passo a passo para instalar, configurar e manter em execução o microserviço Node.js de WhatsApp que realiza a ponte de comunicação com o Painel de Manutenção Django.

---

## 📌 Requisitos Prévios

1. **Node.js instalado**:
   - Faça o download da versão LTS mais recente do Node.js (recomenda-se v20 ou superior) em [nodejs.org](https://nodejs.org/).
   - Execute o instalador e prossiga com as opções padrão.
   - Para verificar se a instalação foi bem-sucedida, abra um terminal (PowerShell ou Prompt de Comando) e digite:
     ```bash
     node -v
     npm -v
     ```

2. **Celular com WhatsApp**:
   - Um dispositivo móvel com WhatsApp ativo para ler o QR Code de autenticação.

---

## ⚙️ Configuração Inicial (Primeira Execução)

Siga os passos abaixo para configurar o serviço no seu ambiente local ou servidor:

1. **Acessar a pasta do microserviço**:
   Abra o terminal do Windows, navegue até a pasta raiz do projeto de manutenção e entre na pasta `whatsapp_service`:
   ```powershell
   cd "c:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao\whatsapp_service"
   ```

2. **Instalar as dependências**:
   Execute o instalador de pacotes do Node para baixar as bibliotecas necessárias definidas no `package.json` (Express, Baileys, etc.):
   ```bash
   npm install
   ```
   *Nota: Esse comando criará uma pasta chamada `node_modules` com todas as dependências locais.*

3. **Iniciar o microserviço**:
   Execute o script de inicialização do servidor:
   ```bash
   npm start
   ```
   *Ou diretamente: `node server.js`*

4. **Ler o QR Code**:
   - Na primeira execução, o terminal exibirá um **QR Code em formato de caracteres de texto**.
   - No seu celular, abra o WhatsApp > Menu (três pontinhos no Android ou Ajustes no iOS) > **Aparelhos Conectados** > **Conectar um Aparelho**.
   - Aponte a câmera do celular para o terminal e escaneie o QR Code.
   - Assim que a conexão for concluída, o terminal exibirá a mensagem: `WhatsApp conectado e pronto para enviar mensagens!`.

---

## 💾 Persistência de Sessão

- As credenciais de login e as informações da sessão do WhatsApp Web serão salvas localmente no diretório `whatsapp_service/auth_info_baileys/`.
- **Você não precisará ler o QR Code toda vez que o servidor for reiniciado**. Ele lerá automaticamente os arquivos salvos nessa pasta e se reconectará.
- Se você quiser trocar o número de celular conectado ou deslogar o dispositivo, basta apagar a pasta `auth_info_baileys` e reiniciar o microserviço para que um novo QR Code seja gerado.

---

## 🖥️ Como Manter o Serviço Rodando no Windows Server

Em um ambiente de produção (como o Windows Server), o microserviço do WhatsApp não deve rodar em um terminal comum que possa ser fechado acidentalmente por um usuário. Existem duas abordagens recomendadas para garantir que ele permaneça ativo:

### Opção A: Gerenciador de Processos PM2 (Recomendada)
O PM2 é um gerenciador de processos de Node.js que mantém o serviço ativo em segundo plano e o reinicia automaticamente se houver falhas ou se o servidor Windows for reiniciado.

1. **Instalar o PM2 globalmente no Windows**:
   ```bash
   npm install -g pm2
   ```

2. **Iniciar o servidor com o PM2** (dentro da pasta `whatsapp_service`):
   ```bash
   pm2 start server.js --name "whatsapp-service"
   ```

3. **Salvar a lista de processos ativos**:
   ```bash
   pm2 save
   ```

4. **Configurar inicialização automática com o Windows**:
   Instale o utilitário de inicialização automática de serviços para PM2 no Windows:
   ```bash
   npm install -g pm2-windows-startup
   pm2-startup install
   ```

### Opção B: Script de Inicialização .BAT (Alternativa Simples)
Uma alternativa direta é criar um arquivo `.bat` no Windows que inicie o serviço e colocá-lo na pasta "Inicializar" (Startup) do Windows:

1. Crie um arquivo chamado `iniciar_whatsapp.bat` com o seguinte conteúdo:
   ```bat
   @echo off
   cd "C:\Users\Unicompo\Documents\03_PYTHON1\07 - Painel Manutencao\whatsapp_service"
   npm start
   pause
   ```
2. Coloque um atalho deste arquivo na pasta de Inicialização do Windows (pressione `Win + R`, digite `shell:startup` e cole o atalho lá). A janela do terminal abrirá minimizada ou em segundo plano ao iniciar o sistema.

---

## 🧪 Resolução de Problemas

1. **Mensagem "O servidor de WhatsApp está offline" na tela do Django**:
   - Verifique se o terminal do Node.js está aberto e rodando na porta `3000`.
   - Se o microserviço acabou de ser reiniciado, certifique-se de que ele não está aguardando uma nova leitura de QR Code no terminal.

2. **Números de WhatsApp não recebendo as mensagens**:
   - Os números cadastrados no perfil do técnico devem possuir DDD (ex: `11987654321` ou `31988887777`). O sistema automaticamente higienizará o número, removendo traços, parênteses e espaços, e adicionará o código do Brasil (`55`).
