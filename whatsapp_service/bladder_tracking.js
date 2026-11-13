// Apenas Bladder: os demais módulos continuam usando a fila e o contrato existentes.
const TTL = 48 * 60 * 60 * 1000;
const INTERVAL = 10 * 60 * 1000;

function createBladderTracking(now = Date.now) {
    const messages = new Map();
    let lastAccepted = null;
    let acceptedDay = '';
    let dailyCount = 0;

    function lookup(id) {
        const current = now();
        for (const [key, value] of messages) {
            if (current - value.created_at > TTL) messages.delete(key);
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

    function update(id, status) {
        if (!id) return;
        const record = messages.get(id);
        if (record) {
            record.status = status;
            record.updated_at = now();
        }
    }

    return { lookup, reserve, update };
}

module.exports = { createBladderTracking };
