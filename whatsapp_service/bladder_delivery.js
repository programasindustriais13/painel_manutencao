// Consulta um único contato. Não tenta variantes de número nem transmite mais de uma vez.
async function sendBladderMessage(sock, task, tracking, generateMessageId) {
    let destination = task.jid;
    if (!destination.endsWith('@g.us')) {
        let contacts;
        try {
            contacts = await sock.onWhatsApp(destination.split('@')[0]);
        } catch (_) {
            tracking.update(task.message_id, 'failed', { error_code: 'CONSULTA_DESTINO_FALHOU' });
            return;
        }
        const contact = Array.isArray(contacts) ? contacts.find(item => item.exists === true && typeof item.jid === 'string') : null;
        if (!contact || !/^[0-9]+@(s\.whatsapp\.net|lid)$/.test(contact.jid)) {
            tracking.update(task.message_id, 'failed', { error_code: 'DESTINO_NAO_CONFIRMADO' });
            return;
        }
        destination = contact.jid; // usa o endereço confirmado pelo próprio WhatsApp
    }
    const whatsappMessageId = generateMessageId(sock.user?.id);
    // Registra antes do await: a confirmação pode chegar antes do retorno de sendMessage.
    tracking.bind(task.message_id, whatsappMessageId, destination);
    try {
        const result = await sock.sendMessage(destination, { text: task.mensagem }, { messageId: whatsappMessageId });
        if (result?.key?.id !== whatsappMessageId) {
            tracking.update(task.message_id, 'submitted', { error_code: 'ID_NAO_CONFIRMADO' });
            return;
        }
        tracking.update(task.message_id, 'submitted');
        // O retorno isolado permanece pendente. ACK/entrega/leitura chegam pelos eventos.
    } catch (_) {
        tracking.update(task.message_id, 'failed', { error_code: 'TRANSMISSAO_FALHOU' });
    }
}

function attachBladderTracking(sock, tracking) {
    sock.ev.on('messages.update', tracking.applyMessageUpdates);
    sock.ev.on('message-receipt.update', tracking.applyReceipts);
    sock.ws.on('CB:ack,class:message', node => {
        if (!node?.attrs?.id) return;
        tracking.applyMessageUpdates([{
            key: { id: node.attrs.id, fromMe: true },
            update: { status: node.attrs.error ? 0 : 2 },
        }]);
    });
}

module.exports = { sendBladderMessage, attachBladderTracking };
