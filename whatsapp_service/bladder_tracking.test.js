const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createBladderTracking } = require('./bladder_tracking');

test('a mesma identidade não cria outro envio, inclusive após o intervalo', () => {
    let time = Date.UTC(2026, 10, 13, 12);
    const tracking = createBladderTracking(() => time);
    tracking.reserve('one');
    tracking.update('one', 'server_ack');
    time += 11 * 60 * 1000;
    assert.equal(tracking.reserve('one').existing.status, 'server_ack');
    assert.equal(tracking.reserve('two').record.status, 'queued');
});

test('bloqueia rajadas e limita quatro mensagens por dia', () => {
    let time = Date.UTC(2026, 10, 13, 12);
    const tracking = createBladderTracking(() => time);
    assert.ok(tracking.reserve('one').record);
    assert.equal(tracking.reserve('two').code, 429);
    for (let i = 2; i <= 4; i++) {
        time += 10 * 60 * 1000;
        assert.ok(tracking.reserve(String(i)).record);
    }
    time += 10 * 60 * 1000;
    assert.equal(tracking.reserve('five').code, 429);
    time += 24 * 60 * 60 * 1000;
    assert.ok(tracking.reserve('next-day').record);
});

test('acompanha falha sem expor conteúdo nem destinatário', () => {
    const tracking = createBladderTracking();
    tracking.reserve('one');
    tracking.update('one', 'failed');
    assert.equal(tracking.lookup('one').status, 'failed');
    assert.equal(tracking.lookup('one').mensagem, undefined);
    assert.equal(tracking.lookup('one').numero, undefined);
    assert.equal(tracking.lookup('unknown'), undefined);
});

test('remove acompanhamento após 48 horas', () => {
    let time = Date.UTC(2026, 10, 13, 12);
    const tracking = createBladderTracking(() => time);
    tracking.reserve('one');
    time += 49 * 60 * 60 * 1000;
    assert.equal(tracking.lookup('one'), undefined);
});
