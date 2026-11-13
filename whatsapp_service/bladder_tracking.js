// Apenas Bladder: os demais módulos continuam usando a fila e o contrato existentes.
const TTL = 48 * 60 * 60 * 1000;
const INTERVAL = 10 * 60 * 1000;

function createBladderTracking(now = Date.now) {
    const messages = new Map();
    const whatsappIds = new Map();
    let lastAccepted = null;
    let acceptedDay = '';
    let dailyCount = 0;

    function lookup(id) {
        const current = now();
        for (const [key, value] of messages) {
            if (current - value.created_at > TTL) {
                if (value.whatsapp_message_id) whatsappIds.delete(value.whatsapp_message_id);
                messages.delete(key);
            }
        }
        return messages.get(id);
    }

    function reserve(id) {
        const existing = lookup(id);
        if (existing) return { existing };
        const current = now();
        const day = new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date(current));
        if (day !== acceptedDay) {
            acceptedDay = day;
            dailyCount = 0;
        }
        if ((lastAccepted !== null && current - lastAccepted < INTERVAL) || dailyCount >= 4) {
            return { error: 'Limite do Bladder: dez minutos entre mensagens e no máximo quatro mensagens aceitas por dia.', code: 429 };
        }
        if (messages.size >= 2000) return { error: 'Acompanhamento temporariamente indisponível.', code: 503 };
        lastAccepted = current;
        dailyCount++;
        const record = { message_id: id, status: 'queued', created_at: current, updated_at: current };
        messages.set(id, record);
        return { record };
    }

    function update(id, status, metadata = {}) {
        if (!id) return;
        const record = messages.get(id);
        if (record) {
            const rank = { queued: 0, submitted: 1, server_ack: 2, delivered: 3, read: 4 };
            if (record.status === 'failed' && status !== 'delivered' && status !== 'read') return;
            if (rank[status] !== undefined && rank[record.status] > rank[status]) return;
            if (status === 'failed' && rank[record.status] >= rank.delivered) return;
            Object.assign(record, metadata);
            record.status = status;
            record.updated_at = now();
        }
    }

    function bind(id, whatsappMessageId, resolvedJid) {
        const record = lookup(id);
        if (!record) return;
        record.whatsapp_message_id = whatsappMessageId;
        record.resolved_jid = resolvedJid;
        whatsappIds.set(whatsappMessageId, id);
    }

    function applyMessageUpdates(updates) {
        for (const { key, update: change } of updates) {
            const id = whatsappIds.get(key?.id);
            if (!id || key.fromMe === false) continue;
            // WebMessageInfo.Status: ERROR=0, PENDING=1, SERVER_ACK=2,
            // DELIVERY_ACK=3, READ=4, PLAYED=5. Só eventos confirmam sucesso.
            const status = { 0: 'failed', 2: 'server_ack', 3: 'delivered', 4: 'read', 5: 'read' }[change?.status];
            if (status) update(id, status, status === 'failed' ? { error_code: 'WHATSAPP_REJEITOU' } : {});
        }
    }

    function applyReceipts(receipts) {
        for (const { key, receipt } of receipts) {
            const id = whatsappIds.get(key?.id);
            if (!id || key.fromMe === false) continue;
            const status = receipt?.readTimestamp || receipt?.playedTimestamp ? 'read' : receipt?.receiptTimestamp ? 'delivered' : null;
            if (status) update(id, status, { delivery_scope: key.remoteJid?.endsWith('@g.us') ? 'participant' : 'recipient' });
        }
    }

    return { lookup, reserve, update, bind, applyMessageUpdates, applyReceipts };
}

module.exports = { createBladderTracking };
