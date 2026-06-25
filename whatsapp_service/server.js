const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const express = require('express');
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const path = require('path');

const app = express();
app.use(express.json());

const PORT = 3000;
let sock = null;
let isConnected = false;

async function connectToWhatsApp() {
    console.log('Iniciando conexão com o WhatsApp...');
    const { state, saveCreds } = await useMultiFileAuthState(path.join(__dirname, 'auth_info_baileys'));
    
    // Busca a versão mais recente do WhatsApp Web suportada
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`Usando WhatsApp Web v${version.join('.')}, é a mais recente: ${isLatest}`);

    sock = makeWASocket({
        version,
        auth: state,
        printQRInTerminal: false, // We will handle printing with connection.update and qrcode-terminal manually
        logger: pino({ level: 'warn' }),
        browser: ["Ubuntu", "Chrome", "20.0.04"]
    });

    sock.ev.on('connection.update', (update) => {
        const { connection, lastDisconnect, qr } = update;
        
        if (qr) {
            console.log('\n==================================================');
            console.log('SCAN NESTE QR CODE NO SEU CELULAR PARA CONECTAR:');
            console.log('==================================================\n');
            qrcode.generate(qr, { small: true });
        }
        
        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`Conexão fechada. Código de status: ${statusCode}. Tentando reconectar: ${shouldReconnect}`);
            isConnected = false;
            
            if (shouldReconnect) {
                setTimeout(connectToWhatsApp, 5000); // Tenta reconectar após 5 segundos
            } else {
                console.log('Deslogado do WhatsApp. Delete a pasta auth_info_baileys para gerar um novo QR Code.');
            }
        } else if (connection === 'open') {
            console.log('==================================================');
            console.log('WhatsApp conectado e pronto para enviar mensagens!');
            console.log('==================================================');
            isConnected = true;
        }
    });

    sock.ev.on('creds.update', saveCreds);
}

// Rota POST /send para envio de mensagens
app.post('/send', async (req, res) => {
    const { numero, mensagem } = req.body;
    
    if (!numero || !mensagem) {
        return res.status(400).json({ error: 'Os campos "numero" e "mensagem" são obrigatórios.' });
    }

    if (!isConnected || !sock) {
        return res.status(503).json({ error: 'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.' });
    }

    try {
        // Higieniza o número
        let cleaned = numero.replace(/\D/g, '');
        if (!cleaned.startsWith('55')) {
            cleaned = '55' + cleaned;
        }
        
        const jid = `${cleaned}@s.whatsapp.net`;
        console.log(`Enviando mensagem para: ${jid}`);
        
        // Dispara a mensagem
        const response = await sock.sendMessage(jid, { text: mensagem });
        
        return res.status(200).json({
            success: true,
            message: 'Mensagem enviada com sucesso.',
            messageId: response.key.id
        });
    } catch (error) {
        console.error('Erro ao enviar mensagem:', error);
        return res.status(500).json({ error: 'Falha ao enviar mensagem: ' + error.message });
    }
});

// Rota de status para checar a conexão
app.get('/status', (req, res) => {
    res.json({ connected: isConnected });
});

app.listen(PORT, () => {
    console.log(`Serviço de WhatsApp rodando em http://localhost:${PORT}`);
});

// Inicializa a conexão
connectToWhatsApp();
