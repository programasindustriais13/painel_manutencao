"""Ensaio explícito da DR-201 real; não executado por manage.py test.

Usa apenas APPEND e movimentos compensatórios: preserva linhas e saldo inicial.
Os testes unitários correspondentes ficam em bladder.tests.
"""
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maintenance_project.settings')
django.setup()

import gspread
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from bladder.models import ProdutoBladder
from bladder.services import (
    registrar_movimentacao_multipla_estoque,
    sincronizar_lote_movimentacoes_dr201,
    sincronizar_movimentacao_dr201,
)


def extrair_linhas_do_range(range_str):
    match = re.search(r'A(\d+)(?::[A-Za-z]+(\d+))?', range_str)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2) or match.group(1))


def run_tests():
    ws = gspread.service_account(filename=str(settings.BASE_DIR / 'credentials.json')).open_by_key(
        '1lMXlQIpxTIkTYC0kCQir029Vrvb2M1l4hWvbxvDv0YM').worksheet('DR201')
    usuario = User.objects.filter(is_superuser=True, is_active=True).first()
    produto = ProdutoBladder.objects.get(codigo='BLA003', ativo=True)
    if usuario is None:
        raise RuntimeError('É necessário um superusuário ativo para o ensaio explícito.')

    historico = ws.get_all_values()
    saldo_inicial = produto.estoque_atual
    prefixo = f"TESTE-BATELADA-{timezone.localdate():%Y%m%d}-{uuid.uuid4().hex[:8]}"
    lote1, lote2 = prefixo + '-01', prefixo + '-02'
    criadas = []

    def registrar(tipo, quantidade, lote, async_sync=False):
        movs, saldo = registrar_movimentacao_multipla_estoque(
            produto=produto, tipo=tipo, quantidade=quantidade, usuario=usuario,
            lote_etiqueta=lote, destino='VALIDACAO SPEC',
            justificativa='Ensaio explícito de volumes; compensado sem apagar histórico.',
            disparar_sync=async_sync,
        )
        criadas.extend(movs)
        assert len(movs) == 1 and movs[0].quantidade == quantidade
        print(f'Django: {tipo} | {lote} | {produto.codigo} | {quantidade} volumes | saldo={saldo}')
        return movs[0]

    def sincronizar(mov):
        sucesso, mensagem = sincronizar_movimentacao_dr201(mov)
        assert sucesso, mensagem
        inicio, fim = extrair_linhas_do_range(mensagem)
        assert inicio is not None and inicio == fim, mensagem
        linha = ws.row_values(inicio)
        assert linha[6:9] == [mov.lote_etiqueta, produto.codigo, str(mov.quantidade)], linha[6:9]
        mov.refresh_from_db()
        assert mov.sincronizado_dr201 and mov.data_sincronizacao_dr201
        assert not mov.erro_sincronizacao_dr201
        print(f'DR-201: lote={mov.lote_etiqueta} modelo={produto.codigo} quantidade={mov.quantidade} | {mensagem}')
        return inicio

    try:
        entrada1 = registrar('ENTRADA', 20, lote1)
        # Falha antes do APPEND: deve manter pendência, para retentativa segura.
        with patch('gspread.service_account', side_effect=ConnectionError('Falha simulada antes de enviar')):
            assert not sincronizar_movimentacao_dr201(entrada1)[0]
        entrada1.refresh_from_db()
        assert not entrada1.sincronizado_dr201 and entrada1.erro_sincronizacao_dr201
        linha1 = sincronizar(entrada1)
        entrada2 = registrar('ENTRADA', 15, lote2)
        linha2 = sincronizar(entrada2)
        assert linha1 != linha2
        print('OK: entradas consecutivas 20/15, dois eventos e duas linhas distintas.')

        produto.refresh_from_db()
        quantidade_anterior = produto.movimentacoes_estoque.count()
        try:
            registrar('SAIDA', produto.estoque_atual + 1, lote1)
        except ValueError:
            pass
        else:
            raise AssertionError('Saída acima do saldo deveria ser rejeitada.')
        produto.refresh_from_db()
        assert produto.movimentacoes_estoque.count() == quantidade_anterior
        assert produto.estoque_atual == saldo_inicial + 35
        print('OK: saldo negativo bloqueado sem efeitos.')

        parcial = registrar('SAIDA', 5, lote1, async_sync=True)
        limite = time.monotonic() + 30
        while time.monotonic() < limite:
            parcial.refresh_from_db()
            if parcial.sincronizado_dr201:
                break
            time.sleep(0.25)
        assert parcial.sincronizado_dr201, parcial.erro_sincronizacao_dr201
        linhas_parciais = [r for r in ws.get_all_values() if len(r) > 8 and r[6:9] == [lote1, produto.codigo, '5']]
        assert len(linhas_parciais) == 1
        print('OK: saída parcial de 5 volumes pelo fluxo assíncrono, exatamente uma linha.')

        compensacoes = [registrar('SAIDA', 15, lote1), registrar('SAIDA', 15, lote2)]
        with ThreadPoolExecutor(max_workers=2) as executor:
            linhas = list(executor.map(sincronizar, compensacoes))
        assert len(set(linhas)) == 2
        print('OK: sincronizações concorrentes em linhas distintas, saldo de teste compensado.')

        # Reenvio confirmado não pode produzir duplicação.
        assert sincronizar_movimentacao_dr201(entrada1)[0]
        final = ws.get_all_values()
        assert final[:len(historico)] == historico, 'Linhas históricas foram modificadas.'
        assert len([r for r in final if len(r) > 6 and r[6] in (lote1, lote2)]) == 5
        print('OK: cinco movimentações, cinco linhas DR-201; histórico anterior preservado.')
    finally:
        # Em erro intermediário, encerrar volumes remanescentes por novos eventos auditáveis.
        for lote in (lote1, lote2):
            restante = sum(m.quantidade if m.tipo == 'ENTRADA' else -m.quantidade
                           for m in criadas if m.lote_etiqueta == lote)
            if restante > 0:
                compensacao = registrar('SAIDA', restante, lote)
                sucesso, mensagem = sincronizar_lote_movimentacoes_dr201(
                    [m.pk for m in criadas if m.lote_etiqueta == lote])
                print(f'Compensação de encerramento: {sucesso} | {mensagem}')
                assert sucesso, mensagem
        produto.refresh_from_db()
        assert produto.estoque_atual == saldo_inicial, 'Saldo inicial não foi recomposto.'
        print(f'Estoque recomposto por movimentações: {saldo_inicial} -> {produto.estoque_atual}.')


if __name__ == '__main__':
    run_tests()
