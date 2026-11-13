// Serviço isolado e socket simulado: nenhum acesso à rede do WhatsApp.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const { setTimeout: delay } = require('node:timers/promises');

async function startService(t) {
    const listener = net.createServer();
    await new Promise(resolve => listener.listen(0, '127.0.0.1', resolve));
    const port = listener.address().port;
    await new Promise(resolve => listener.close(resolve));
    const child = spawn(process.execPath, [path.join(__dirname, 'server.js')], {
        env: { ...process.env, NODE_ENV: 'test', WHATSAPP_TEST_PORT: String(port) },
        stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });
    let logs = '';
    child.stdout.on('data', data => { logs += data; });
    child.stderr.on('data', data => { logs += data; });
    t.after(async () => {
        if (child.exitCode === null) {
            const closed = new Promise(resolve => child.once('exit', resolve));
            child.kill();
            await closed;
        }
    });
    const base = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let i = 0; i < 100; i++) {
        try {
            const status = await fetch(`${base}/status`);
            if (status.ok) { ready = true; break; }
        } catch (_) { /* aguardando processo isolado */ }
        await delay(100);
    }
    assert.ok(ready, logs);
    return { base, logs: () => logs };
}

test('contrato legado e acompanhamento Bladder compartilham a fila sem duplicar', async (t) => {
    const { base, logs } = await startService(t);
    const send = body => fetch(`${base}/send`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const health = await (await fetch(`${base}/status`)).json();
    assert.equal(health.tracking_version, 2);
    assert.equal(health.connected, true);

    // Contrato dos módulos existentes continua retornando 202.
    assert.equal((await send({ numero: '5585999999999', mensagem: 'Contrato legado' })).status, 202);
    const id = 'bladder-00000000-0000-0000-0000-000000000001';
    const payload = { numero: '5585999999999', mensagem: 'Resumo Bladder simulado', origem: 'bladder', message_id: id };
    assert.equal((await send(payload)).status, 202);
    assert.equal((await send(payload)).status, 200);
    await delay(80);
    const record = await (await fetch(`${base}/messages/${id}`)).json();
    assert.equal(record.status, 'server_ack');
    assert.equal((logs().match(/\[MOCK SEND\].*Resumo Bladder simulado/g) || []).length, 1);
    const another = { ...payload, message_id: 'bladder-00000000-0000-0000-0000-000000000002' };
    assert.equal((await send(another)).status, 429);

    // Um módulo legado ainda pode enviar enquanto o Bladder está limitado.
    assert.equal((await send({ numero: '123456@g.us', mensagem: 'Outro modulo' })).status, 202);
    assert.equal((await fetch(`${base}/messages/bladder-desconhecido`)).status, 404);
});

test('sem confirmação real o serviço HTTP não informa sucesso', async t => {
    const { base } = await startService(t);
    const id = 'bladder-00000000-0000-0000-0000-000000000001';
    const response = await fetch(`${base}/send`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ numero: '5585999999999', mensagem: 'NO_ACK resumo', origem: 'bladder', message_id: id }),
    });
    assert.equal(response.status, 202);
    await delay(80);
    const record = await (await fetch(`${base}/messages/${id}`)).json();
    assert.equal(record.status, 'submitted');
});

test('consulta de disponibilidade libera proteção após o intervalo sem exigir novo envio', async t => {
    const { base } = await startService(t);
    for (let i = 0; i < 3; i++) {
        const response = await fetch(`${base}/send`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ numero: '5585999999999', mensagem: 'FAIL_TRIGGER' }),
        });
        assert.equal(response.status, 202);
        await delay(30);
    }
    assert.equal((await (await fetch(`${base}/status`)).json()).circuitTripped, true);
    await delay(1100);
    assert.equal((await (await fetch(`${base}/status`)).json()).circuitTripped, false);
});
