const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createBladderTracking } = require('./bladder_tracking');
const { sendBladderMessage, attachBladderTracking } = require('./bladder_delivery');

function fixture() {
    const tracking = createBladderTracking();
    tracking.reserve('bladder-test');
    const sends = [];
    const socket = {
        ev: new EventEmitter(), ws: new EventEmitter(),
        onWhatsApp: async () => [{ exists: true, jid: '5585999998888@s.whatsapp.net' }],
        sendMessage: async (...args) => { sends.push(args); return { key: { id: args[2].messageId }, status: 1 }; },
    };
    attachBladderTracking(socket, tracking);
    const task = { message_id: 'bladder-test', jid: '5585999999999@s.whatsapp.net', mensagem: 'Resumo' };
    return { tracking, socket, sends, task, send: () => sendBladderMessage(socket, task, tracking, () => 'wa-id') };
}

test('retorno de sendMessage sem ACK permanece pendente, usando o endereço confirmado', async () => {
    const f = fixture();
    await f.send();
    assert.equal(f.sends.length, 1);
    assert.equal(f.sends[0][0], '5585999998888@s.whatsapp.net');
    assert.equal(f.tracking.lookup('bladder-test').status, 'submitted');
    assert.equal(f.tracking.lookup('bladder-test').whatsapp_message_id, 'wa-id');
});

test('contato não confirmado não recebe mensagem nem tentativa com número alternativo', async () => {
    const f = fixture();
    let queries = 0;
    f.socket.onWhatsApp = async () => { queries++; return []; };
    await f.send();
    assert.equal(queries, 1);
    assert.equal(f.sends.length, 0);
    assert.equal(f.tracking.lookup('bladder-test').error_code, 'DESTINO_NAO_CONFIRMADO');
});

test('consulta indisponível não transmite mensagem', async () => {
    const f = fixture();
    f.socket.onWhatsApp = async () => { throw new Error('Connection Closed'); };
    await f.send();
    assert.equal(f.sends.length, 0);
    assert.equal(f.tracking.lookup('bladder-test').error_code, 'CONSULTA_DESTINO_FALHOU');
});

test('ACK do servidor, entrega e leitura são etapas distintas e não regridem', async () => {
    const f = fixture();
    await f.send();
    f.socket.ws.emit('CB:ack,class:message', { attrs: { id: 'wa-id' } });
    assert.equal(f.tracking.lookup('bladder-test').status, 'server_ack');
    f.socket.ev.emit('messages.update', [{ key: { id: 'wa-id', fromMe: true }, update: { status: 3 } }]);
    assert.equal(f.tracking.lookup('bladder-test').status, 'delivered');
    f.socket.ev.emit('messages.update', [{ key: { id: 'wa-id', fromMe: true }, update: { status: 4 } }]);
    f.socket.ws.emit('CB:ack,class:message', { attrs: { id: 'wa-id' } });
    assert.equal(f.tracking.lookup('bladder-test').status, 'read');
    assert.equal(f.sends.length, 1);
});

test('confirmação anterior ao retorno de sendMessage não se perde', async () => {
    const f = fixture();
    f.socket.sendMessage = async (_jid, _content, options) => {
        f.socket.ev.emit('messages.update', [{ key: { id: options.messageId, fromMe: true }, update: { status: 3 } }]);
        return { key: { id: options.messageId } };
    };
    await f.send();
    assert.equal(f.tracking.lookup('bladder-test').status, 'delivered');
});

test('rejeição do WhatsApp vira falha e não provoca outra transmissão', async () => {
    const f = fixture();
    await f.send();
    f.socket.ws.emit('CB:ack,class:message', { attrs: { id: 'wa-id', error: '479' } });
    assert.equal(f.tracking.lookup('bladder-test').status, 'failed');
    assert.equal(f.tracking.lookup('bladder-test').error_code, 'WHATSAPP_REJEITOU');
    assert.equal(f.sends.length, 1);
});

test('grupo mantém seu endereço e distingue confirmação de participante', async () => {
    const f = fixture();
    f.task.jid = '123456@g.us';
    f.socket.onWhatsApp = async () => { throw new Error('Não deve consultar telefone de grupo'); };
    await f.send();
    assert.equal(f.sends[0][0], f.task.jid);
    f.socket.ev.emit('message-receipt.update', [{ key: { id: 'wa-id', fromMe: true, remoteJid: f.task.jid }, receipt: { receiptTimestamp: 123 } }]);
    assert.equal(f.tracking.lookup('bladder-test').status, 'delivered');
    assert.equal(f.tracking.lookup('bladder-test').delivery_scope, 'participant');
});

test('eventos de mensagens não rastreadas são ignorados', async () => {
    const f = fixture();
    await f.send();
    f.socket.ws.emit('CB:ack,class:message', { attrs: { id: 'outro-modulo' } });
    assert.equal(f.tracking.lookup('bladder-test').status, 'submitted');
});
