const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, generateMessageIDV2 } = require('@whiskeysockets/baileys');
const express = require('express');
const rateLimit = require('express-rate-limit');
const qrcode = require('qrcode-terminal');
const pino = require('pino');
const path = require('path');
const { createBladderTracking } = require('./bladder_tracking');
const bladderTracking = createBladderTracking();
const { sendBladderMessage, attachBladderTracking } = require('./bladder_delivery');

const app = express();
app.use(express.json());

const PORT = process.env.NODE_ENV === 'test' ? Number(process.env.WHATSAPP_TEST_PORT || 3000) : 3000;
let sock = null;
let isConnected = false;
let reconnectTimer = null;
let connecting = false;

function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectToWhatsApp();
    }, 5000);
}

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
    if (connecting) return;
    connecting = true;
    try {
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
            browser: ["Ubuntu", "Chrome", "20.0.04"],
            shouldIgnoreJid: jid => jid === 'status@broadcast'
        });

        const connectionSock = sock;
        connectionSock.ev.on('connection.update', (update) => {
            if (sock !== connectionSock) return;
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
                    scheduleReconnect();
                } else {
                    if (reconnectTimer) clearTimeout(reconnectTimer);
                    reconnectTimer = null;
                    console.log('Sessao encerrada pelo WhatsApp. Confira Aparelhos conectados antes de refazer a vinculacao.');
                }
            } else if (connection === 'open') {
                if (reconnectTimer) clearTimeout(reconnectTimer);
                reconnectTimer = null;
                console.log('==================================================');
                console.log('WhatsApp conectado e pronto para enviar mensagens!');
                console.log('==================================================');
                isConnected = true;
            }
        });

        connectionSock.ev.on('creds.update', saveCreds);
        attachBladderTracking(connectionSock, bladderTracking);
    } catch (error) {
        isConnected = false;
        console.error('Falha ao conectar WhatsApp; nova verificacao em cinco segundos. Codigo:', error?.output?.statusCode || error?.code || 'indisponivel');
        scheduleReconnect();
    } finally {
        connecting = false;
    }
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

function resetCircuitIfExpired() {
    if (circuitTripped && Date.now() - circuitTrippedAt > COOLDOWN_MS) {
        circuitTripped = false;
        consecutiveFailures = 0;
        console.log('Protecao de falhas liberada apos o intervalo de espera.');
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
            bladderTracking.update(task.message_id, 'failed');
            continue;
        }

        try {
            console.log(`Disparando mensagem para: ${task.jid}`);
            if (task.message_id) {
                await sendBladderMessage(sock, task, bladderTracking, generateMessageIDV2);
                const result = bladderTracking.lookup(task.message_id);
                if (result?.status === 'failed') {
                    console.warn(`Bladder ${task.message_id}: ${result.error_code}. Sem repeticao automatica.`);
                    handleSendFailure();
                    continue;
                }
                console.log(`Bladder ${task.message_id}: ${result?.status}; aguardando eventos de confirmacao do WhatsApp.`);
            } else {
                await sock.sendMessage(task.jid, { text: task.mensagem });
                console.log(`Solicitacao processada para: ${task.jid}. Entrega nao confirmada por este retorno.`);
            }
            
            // Sucesso reseta contador de falhas seguidas
            consecutiveFailures = 0;
        } catch (error) {
            console.error(`Erro ao enviar mensagem para ${task.jid}:`, error);
            handleSendFailure();
            bladderTracking.update(task.message_id, 'failed');
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

    const isBladder = req.body.origem === 'bladder';
    const messageId = isBladder ? req.body.message_id : null;
    if (isBladder) {
        if (typeof numero !== 'string' || typeof mensagem !== 'string' ||
            typeof messageId !== 'string' || !/^bladder-[0-9a-f-]{36}$/.test(messageId)) {
            return res.status(400).json({ error: 'Identificador ou dados do Bladder inválidos.' });
        }
        const existing = bladderTracking.lookup(messageId);
        if (existing) return res.status(200).json({ success: true, ...existing });
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
    if (isBladder) {
        const reservation = bladderTracking.reserve(messageId);
        if (reservation.error) return res.status(reservation.code).json({ error: reservation.error });
    }
    messageQueue.push({ jid, mensagem, message_id: messageId });
    console.log(`Mensagem para ${jid} adicionada na fila de envio. Tamanho da fila: ${messageQueue.length}`);
    processQueue();

    // Retorna HTTP 202 imediatamente
    return res.status(202).json({
        success: true,
        ...(isBladder ? { message_id: messageId, status: 'queued' } : {}),
        message: 'Mensagem aceita e enfileirada para envio.'
    });
});

// Rota de status para checar a conexão
app.get('/status', (req, res) => {
    resetCircuitIfExpired();
    res.json({ connected: isConnected, circuitTripped, tracking_version: 2 });
});

app.get('/messages/:messageId', (req, res) => {
    const record = bladderTracking.lookup(req.params.messageId);
    if (!record) return res.status(404).json({ error: 'Mensagem não encontrada; confira o WhatsApp antes de reenviar.' });
    return res.json(record);
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

app.listen(PORT, '127.0.0.1', () => {
    console.log(`Serviço de WhatsApp rodando em http://127.0.0.1:${PORT}`);
});

// Inicializa a conexão
if (process.env.NODE_ENV === 'test') {
    isConnected = true;
    sock = {
        user: { id: '5585000000000@s.whatsapp.net' },
        onWhatsApp: async number => [{ exists: true, jid: `${number}@s.whatsapp.net` }],
        sendMessage: async (jid, content, options = {}) => {
            if (content.text && content.text.includes('FAIL_TRIGGER')) {
                throw new Error('Mock send failure');
            }
            console.log(`[MOCK SEND] Enviada mensagem para ${jid}: ${content.text}`);
            if (options.messageId && !content.text.includes('NO_ACK')) {
                setTimeout(() => bladderTracking.applyMessageUpdates([
                    { key: { id: options.messageId, fromMe: true }, update: { status: 2 } }
                ]), 10);
            }
            return { key: { id: options.messageId || 'mock_id' } };
        }
    };
    console.log('Serviço rodando em MODO TESTE com WhatsApp mockado.');
} else {
    connectToWhatsApp();
}
