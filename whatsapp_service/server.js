const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const express = require('express');
const rateLimit = require('express-rate-limit');
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const path = require('path');

const app = express();
app.use(express.json());

const PORT = 3000;
let sock = null;
let isConnected = false;

// Configuração do Rate Limit (5 requisições por 1 minuto por IP)
const sendLimiter = rateLimit({
    windowMs: 60 * 1000,
    max: 5,
    message: { error: 'Muitas requisições enviadas em curto período. Por favor, aguarde um momento antes de tentar novamente.' },
    standardHeaders: true,
    legacyHeaders: false
});

// Variáveis do Circuit Breaker
let consecutiveFailures = 0;
let circuitTripped = false;
let circuitTrippedAt = 0;
const FAILURE_THRESHOLD = 3;
const COOLDOWN_MS = process.env.NODE_ENV === 'test' ? 1000 : 60 * 1000; // 60 segundos de bloqueio (1s em teste)

// Fila de mensagens em background
const messageQueue = [];
let isProcessingQueue = false;

async function connectToWhatsApp() {
    console.log('Iniciando conexão com o WhatsApp...');
    const { state, saveCreds } = await useMultiFileAuthState(path.join(__dirname, 'auth_info_baileys'));
    
    // Busca a versão mais recente do WhatsApp Web suportada
    const { version, isLatest } = await fetchLatestBaileysVersion();
    console.log(`Usando WhatsApp Web v${version.join('.')}, é a mais recente: ${isLatest}`);

    sock = makeWASocket({
        version,
        auth: state,
        printQRInTerminal: false,
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

function handleSendFailure() {
    consecutiveFailures++;
    console.warn(`Falha consecutiva no envio. Total: ${consecutiveFailures}`);
    if (consecutiveFailures >= FAILURE_THRESHOLD) {
        circuitTripped = true;
        circuitTrippedAt = Date.now();
        console.error('==================================================');
        console.error('DISJUNTOR DE FALHAS DISPARADO (CIRCUIT BREAKER)!');
        console.error('O envio de mensagens foi bloqueado por 60 segundos.');
        console.error('==================================================');
    }
}

async function processQueue() {
    if (isProcessingQueue) return;
    isProcessingQueue = true;

    while (messageQueue.length > 0) {
        const task = messageQueue.shift();
        
        // Atraso Humano Aleatório (2000ms a 5000ms, ou 1ms a 5ms em teste)
        const delay = process.env.NODE_ENV === 'test' 
            ? Math.floor(Math.random() * (5 - 1 + 1)) + 1 
            : Math.floor(Math.random() * (5000 - 2000 + 1)) + 2000;
        console.log(`Aguardando delay de ${delay}ms antes de enviar para ${task.jid}...`);
        await new Promise(resolve => setTimeout(resolve, delay));

        if (!isConnected || !sock) {
            console.error(`Falha no envio para ${task.jid}: Servidor offline.`);
            handleSendFailure();
            continue;
        }

        try {
            console.log(`Disparando mensagem para: ${task.jid}`);
            await sock.sendMessage(task.jid, { text: task.mensagem });
            console.log(`Mensagem enviada com sucesso em background para: ${task.jid}`);
            
            // Sucesso reseta contador de falhas seguidas
            consecutiveFailures = 0;
        } catch (error) {
            console.error(`Erro ao enviar mensagem para ${task.jid}:`, error);
            handleSendFailure();
        }
    }

    isProcessingQueue = false;
}

// Rota POST /send para envio de mensagens (com Rate Limit)
app.post('/send', sendLimiter, (req, res) => {
    const { numero, mensagem } = req.body;
    
    if (!numero || !mensagem) {
        return res.status(400).json({ error: 'Os campos "numero" e "mensagem" são obrigatórios.' });
    }

    // Verifica Circuit Breaker
    if (circuitTripped) {
        if (Date.now() - circuitTrippedAt > COOLDOWN_MS) {
            circuitTripped = false;
            consecutiveFailures = 0;
            console.log('Circuit breaker resetado após o tempo limite de cooldown.');
        } else {
            return res.status(503).json({ error: 'Serviço temporariamente indisponível' });
        }
    }

    if (!isConnected || !sock) {
        return res.status(503).json({ error: 'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.' });
    }

    // Identificação do Destino (Grupo ou Individual)
    let jid;
    if (numero.includes('@g.us')) {
        jid = numero; // Se for grupo, envia diretamente
    } else {
        // Se for individual, higieniza e formata
        let cleaned = numero.replace(/\D/g, '');
        if (!cleaned.startsWith('55')) {
            cleaned = '55' + cleaned;
        }
        jid = `${cleaned}@s.whatsapp.net`;
    }

    // Adiciona na fila e inicia processamento
    messageQueue.push({ jid, mensagem });
    console.log(`Mensagem para ${jid} adicionada na fila de envio. Tamanho da fila: ${messageQueue.length}`);
    processQueue();

    // Retorna HTTP 202 imediatamente
    return res.status(202).json({
        success: true,
        message: 'Mensagem aceita e enfileirada para envio.'
    });
});

// Rota de status para checar a conexão
app.get('/status', (req, res) => {
    res.json({ connected: isConnected, circuitTripped });
});

// Rota GET /groups para listar os grupos participantes
app.get('/groups', async (req, res) => {
    if (!isConnected || !sock) {
        return res.status(503).json({ error: 'O servidor de WhatsApp está offline ou aguardando leitura do QR Code.' });
    }
    try {
        const groups = await sock.groupFetchAllParticipating();
        const result = Object.keys(groups).map(key => ({
            id: key,
            name: groups[key].subject
        }));
        return res.status(200).json(result);
    } catch (error) {
        console.error('Erro ao buscar grupos:', error);
        return res.status(500).json({ error: 'Falha ao buscar grupos: ' + error.message });
    }
});

if (process.env.NODE_ENV === 'test') {
    app.post('/reset', (req, res) => {
        consecutiveFailures = 0;
        circuitTripped = false;
        circuitTrippedAt = 0;
        messageQueue.length = 0;
        isProcessingQueue = false;
        if (sendLimiter && typeof sendLimiter.resetKey === 'function') {
            sendLimiter.resetKey(req.ip);
        }
        console.log('Reset de estado solicitado via API de teste.');
        res.json({ success: true });
    });
}

app.listen(PORT, () => {
    console.log(`Serviço de WhatsApp rodando em http://localhost:${PORT}`);
});

// Inicializa a conexão
if (process.env.NODE_ENV === 'test') {
    isConnected = true;
    sock = {
        sendMessage: async (jid, content) => {
            if (content.text && content.text.includes('FAIL_TRIGGER')) {
                throw new Error('Mock send failure');
            }
            console.log(`[MOCK SEND] Enviada mensagem para ${jid}: ${content.text}`);
            return { key: { id: 'mock_id' } };
        }
    };
    console.log('Serviço rodando em MODO TESTE com WhatsApp mockado.');
} else {
    connectToWhatsApp();
}
