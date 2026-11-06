import os
import sys
import time
import re
import django
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maintenance_project.settings')
django.setup()

from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import User
import gspread

from bladder.models import ProdutoBladder, MovimentacaoEstoqueBladder
from bladder.services import (
    sincronizar_lote_movimentacoes_dr201,
    registrar_movimentacao_multipla_estoque,
)


def extrair_linhas_do_range(range_str):
    """Extrai (linha_inicio, linha_fim) de strings como 'DR201'!A2942:J2943 ou A2942."""
    m = re.search(r'A(\d+)(?::[A-Za-z]+(\d+))?', range_str)
    if m:
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        return start, end
    return None, None


def run_tests():
    print("=" * 70)
    print("INICIANDO SUÍTE DE TESTES OBRIGATÓRIOS — GOOGLE SHEETS DR-201")
    print("=" * 70)

    # Autenticação Google Sheets
    cred_path = os.path.join(settings.BASE_DIR, 'credentials.json')
    gc = gspread.service_account(filename=cred_path)
    sh = gc.open_by_key('1lMXlQIpxTIkTYC0kCQir029Vrvb2M1l4hWvbxvDv0YM')
    ws = sh.worksheet('DR201')

    # Usuário e Produto base
    admin = User.objects.filter(is_superuser=True).first()
    produto = ProdutoBladder.objects.filter(ativo=True, codigo__startswith='BLA').first()
    print(f"Usuário de teste: {admin.username} (ID: {admin.id})")
    print(f"Produto de teste: {produto.codigo} (ID: {produto.id}, Estoque Atual: {produto.estoque_atual})")

    # Linha inicial e registros históricos de referência (garantir que não serão tocados)
    col1_inicial = ws.col_values(1)
    n_inicial = len(col1_inicial)
    reg_2938 = ws.row_values(2938)
    reg_2939 = ws.row_values(2939)
    print(f"\n[ESTADO INICIAL] Total de linhas preenchidas antes dos testes: N = {n_inicial}")
    print(f"[ESTADO INICIAL] Histórico linha 2938: {reg_2938[:5]}")
    print(f"[ESTADO INICIAL] Histórico linha 2939: {reg_2939[:5]}")

    results = {}

    # --------------------------------------------------------------------------
    # TESTE 1 — Duas sincronizações sequenciais
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("TESTE 1 — Duas sincronizações sequenciais")
    print("-" * 70)
    m1 = MovimentacaoEstoqueBladder.objects.create(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        saldo_anterior=produto.estoque_atual,
        saldo_posterior=produto.estoque_atual + 1,
        usuario=admin,
        turma='TURMA_A',
        data_turno=timezone.localdate(),
        destino="Estoque Central Bladder",
        lote_etiqueta="TEST-SEQ-1",
        justificativa="Teste automatizado sequencial 1",
        sincronizado_dr201=False
    )
    m2 = MovimentacaoEstoqueBladder.objects.create(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        saldo_anterior=produto.estoque_atual + 1,
        saldo_posterior=produto.estoque_atual + 2,
        usuario=admin,
        turma='TURMA_A',
        data_turno=timezone.localdate(),
        destino="Estoque Central Bladder",
        lote_etiqueta="TEST-SEQ-2",
        justificativa="Teste automatizado sequencial 2",
        sincronizado_dr201=False
    )

    suc1, msg1 = sincronizar_lote_movimentacoes_dr201([m1.id])
    print(f"Sincronização 1 (ID {m1.id}): sucesso={suc1} | msg={msg1}")
    l1_start, l1_end = extrair_linhas_do_range(msg1)

    suc2, msg2 = sincronizar_lote_movimentacoes_dr201([m2.id])
    print(f"Sincronização 2 (ID {m2.id}): sucesso={suc2} | msg={msg2}")
    l2_start, l2_end = extrair_linhas_do_range(msg2)

    # Verificar no Google Sheets
    row1 = ws.row_values(l1_start)
    row2 = ws.row_values(l2_start)
    print(f"Linha {l1_start}: Lote={row1[6]} | Modelo={row1[7]}")
    print(f"Linha {l2_start}: Lote={row2[6]} | Modelo={row2[7]}")

    # Checar se linhas históricas 2938 e 2939 foram 100% preservadas
    assert ws.row_values(2938) == reg_2938, "FALHA: Histórico 2938 foi alterado!"
    assert ws.row_values(2939) == reg_2939, "FALHA: Histórico 2939 foi alterado!"
    assert row1[6] == "TEST-SEQ-1", f"FALHA: Linha {l1_start} não contém TEST-SEQ-1"
    assert row2[6] == "TEST-SEQ-2", f"FALHA: Linha {l2_start} não contém TEST-SEQ-2"
    assert l1_start != l2_start, "FALHA: Ambos foram gravados na mesma linha!"
    print(f">> TESTE 1 PASSOU: Duas sincronizações sequenciais alocadas em linhas distintas ({l1_start} e {l2_start}) sem sobrescrever histórico.")
    results['TESTE 1 (Sequencial)'] = f"OK (Linhas {l1_start} e {l2_start})"

    # --------------------------------------------------------------------------
    # TESTE 2 — Concorrência (Threads simultâneas via ThreadPoolExecutor)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("TESTE 2 — Concorrência simultânea (ThreadPoolExecutor max_workers=2)")
    print("-" * 70)

    m3 = MovimentacaoEstoqueBladder.objects.create(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        saldo_anterior=produto.estoque_atual + 2,
        saldo_posterior=produto.estoque_atual + 3,
        usuario=admin,
        turma='TURMA_A',
        data_turno=timezone.localdate(),
        destino="Estoque Central Bladder",
        lote_etiqueta="TEST-CONC-1",
        justificativa="Teste concorrente ThreadPool 1",
        sincronizado_dr201=False
    )
    m4 = MovimentacaoEstoqueBladder.objects.create(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        saldo_anterior=produto.estoque_atual + 3,
        saldo_posterior=produto.estoque_atual + 4,
        usuario=admin,
        turma='TURMA_A',
        data_turno=timezone.localdate(),
        destino="Estoque Central Bladder",
        lote_etiqueta="TEST-CONC-2",
        justificativa="Teste concorrente ThreadPool 2",
        sincronizado_dr201=False
    )

    t_start = time.time()
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(sincronizar_lote_movimentacoes_dr201, [m3.id])
        f2 = executor.submit(sincronizar_lote_movimentacoes_dr201, [m4.id])
        r1 = f1.result()
        r2 = f2.result()
    t_end = time.time()

    print(f"Thread 1 (ID {m3.id}): {r1}")
    print(f"Thread 2 (ID {m4.id}): {r2}")
    print(f"Tempo decorrido: {t_end - t_start:.2f}s")

    l_c1_start, _ = extrair_linhas_do_range(r1[1])
    l_c2_start, _ = extrair_linhas_do_range(r2[1])

    # Verificar no Google Sheets
    row_conc1 = ws.row_values(l_c1_start)
    row_conc2 = ws.row_values(l_c2_start)
    lotes_encontrados = {row_conc1[6], row_conc2[6]}
    print(f"Linha {l_c1_start}: Lote={row_conc1[6]} | Modelo={row_conc1[7]}")
    print(f"Linha {l_c2_start}: Lote={row_conc2[6]} | Modelo={row_conc2[7]}")

    assert lotes_encontrados == {"TEST-CONC-1", "TEST-CONC-2"}, f"FALHA: Lotes esperados não conferem! Encontrados: {lotes_encontrados}"
    assert l_c1_start != l_c2_start, "FALHA: Ambos os registros foram gravados na mesma linha ou sobrescritos!"
    print(f">> TESTE 2 PASSOU: Execução concorrente gravou dois registros em linhas distintas ({l_c1_start} e {l_c2_start}) sem sobrescrever!")
    results['TESTE 2 (Concorrente)'] = f"OK (Linhas {l_c1_start} e {l_c2_start}, lotes={lotes_encontrados})"

    # --------------------------------------------------------------------------
    # TESTE 3 — Lote (Quantidade > 1, ex: 3 Bladders)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("TESTE 3 — Lote (3 Bladders com lotes individuais)")
    print("-" * 70)

    m_lote = []
    for i in range(1, 4):
        m = MovimentacaoEstoqueBladder.objects.create(
            produto=produto,
            tipo='ENTRADA',
            quantidade=1,
            saldo_anterior=produto.estoque_atual + 4 + (i - 1),
            saldo_posterior=produto.estoque_atual + 4 + i,
            usuario=admin,
            turma='TURMA_A',
            data_turno=timezone.localdate(),
            destino="Estoque Central Bladder",
            lote_etiqueta=f"TEST-LOTE-0{i}",
            justificativa=f"Teste lote peça {i}/3",
            sincronizado_dr201=False
        )
        m_lote.append(m)

    suc3, msg3 = sincronizar_lote_movimentacoes_dr201([m.id for m in m_lote])
    print(f"Sincronização lote (IDs {[m.id for m in m_lote]}): sucesso={suc3} | msg={msg3}")
    l3_start, l3_end = extrair_linhas_do_range(msg3)
    print(f"Range do lote: Linhas {l3_start} a {l3_end} (total {l3_end - l3_start + 1} linhas)")

    rows_lote = [ws.row_values(r) for r in range(l3_start, l3_end + 1)]
    for idx, r_vals in enumerate(rows_lote, 1):
        print(f"Linha {l3_start + idx - 1}: Lote={r_vals[6]}")
        assert r_vals[6] == f"TEST-LOTE-0{idx}", f"FALHA no lote {idx}"

    assert (l3_end - l3_start + 1) == 3, "FALHA: Quantidade de linhas gravadas diferente de 3"
    print(">> TESTE 3 PASSOU: 3 linhas consecutivas criadas com sucesso na DR-201 com seus respectivos lotes!")
    results['TESTE 3 (Lote 3 un)'] = f"OK (Linhas {l3_start} a {l3_end})"

    # --------------------------------------------------------------------------
    # TESTE 4 — Integração pelo fluxo usado pela tela (registrar_movimentacao_multipla_estoque)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("TESTE 4 — Fluxo real da tela (registrar_movimentacao_multipla_estoque + async)")
    print("-" * 70)

    movs_tela, saldo_final = registrar_movimentacao_multipla_estoque(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        usuario=admin,
        lotes=['TEST-ASYNC-FLOW'],
        justificativa="Teste integração fluxo da tela assíncrono",
        disparar_sync=True
    )
    mov_tela = movs_tela[0]
    print(f"Movimentação criada: ID={mov_tela.id}, Lote={mov_tela.lote_etiqueta}")

    # Aguardar thread em background terminar (polling de até 15s)
    print("Aguardando background thread concluir...")
    concluido = False
    for attempt in range(30):
        time.sleep(0.5)
        mov_tela.refresh_from_db()
        if mov_tela.sincronizado_dr201:
            concluido = True
            print(f"Thread assíncrona sincronizou com sucesso em {(attempt+1)*0.5:.1f}s!")
            break

    assert concluido, "FALHA: Background thread não sincronizou no tempo limite!"

    # Localizar a linha no Sheets
    col_lotes = ws.col_values(7)
    linha_tela = None
    for idx, lote in enumerate(col_lotes, 1):
        if lote == 'TEST-ASYNC-FLOW':
            linha_tela = idx
            break

    print(f"Registro encontrado na DR-201 na Linha {linha_tela}!")
    row_tela = ws.row_values(linha_tela)
    print(f"Linha {linha_tela}: Lote={row_tela[6]} | Modelo={row_tela[7]} | Resp={row_tela[3]}")
    assert row_tela[6] == "TEST-ASYNC-FLOW"
    print(">> TESTE 4 PASSOU: Fluxo real assíncrono concluiu e gravou no Google Sheets!")
    results['TESTE 4 (Fluxo Real Assíncrono)'] = f"OK (Linha {linha_tela})"

    # --------------------------------------------------------------------------
    # TESTE 5 — Banco de Dados (Sucesso vs Erro Simulado)
    # --------------------------------------------------------------------------
    print("\n" + "-" * 70)
    print("TESTE 5 — Banco de Dados (Campos após sucesso e após erro simulado)")
    print("-" * 70)

    # 5.1 Verificar sucesso nas movimentações anteriores
    mov_tela.refresh_from_db()
    print("Verificando campos de sucesso no banco:")
    print(f"  sincronizado_dr201: {mov_tela.sincronizado_dr201}")
    print(f"  data_sincronizacao_dr201: {mov_tela.data_sincronizacao_dr201}")
    print(f"  erro_sincronizacao_dr201: {mov_tela.erro_sincronizacao_dr201}")
    assert mov_tela.sincronizado_dr201 is True
    assert mov_tela.data_sincronizacao_dr201 is not None
    assert mov_tela.erro_sincronizacao_dr201 is None

    # 5.2 Simular erro de sincronização (falha de conexão simulada)
    m_fail = MovimentacaoEstoqueBladder.objects.create(
        produto=produto,
        tipo='ENTRADA',
        quantidade=1,
        saldo_anterior=produto.estoque_atual,
        saldo_posterior=produto.estoque_atual + 1,
        usuario=admin,
        turma='TURMA_A',
        data_turno=timezone.localdate(),
        destino="Estoque Central Bladder",
        lote_etiqueta="TEST-FAIL-SIM",
        justificativa="Teste simulação de falha",
        sincronizado_dr201=False
    )

    original_open = gspread.Client.open_by_key
    def mock_fail(*args, **kwargs):
        raise ConnectionError("Simulação de indisponibilidade temporária de rede / timeout Google Sheets")

    gspread.Client.open_by_key = mock_fail
    try:
        suc_fail, msg_fail = sincronizar_lote_movimentacoes_dr201([m_fail.id])
        print(f"Resultado falha simulada: sucesso={suc_fail} | msg={msg_fail}")
        assert suc_fail is False, "Deveria ter retornado False"
    finally:
        gspread.Client.open_by_key = original_open

    m_fail.refresh_from_db()
    print("Verificando campos de falha no banco:")
    print(f"  sincronizado_dr201: {m_fail.sincronizado_dr201}")
    print(f"  data_sincronizacao_dr201: {m_fail.data_sincronizacao_dr201}")
    print(f"  erro_sincronizacao_dr201: {m_fail.erro_sincronizacao_dr201}")
    assert m_fail.sincronizado_dr201 is False
    assert m_fail.erro_sincronizacao_dr201 is not None
    assert "Simulação de indisponibilidade" in m_fail.erro_sincronizacao_dr201
    print(">> TESTE 5 PASSOU: Banco de dados reflete fielmente sucesso e falha!")
    results['TESTE 5 (Banco de Dados)'] = "OK (Sucesso e Falha validados)"

    # Limpeza do estoque do produto alterado pelo Teste 4
    produto.refresh_from_db()
    produto.estoque_atual -= 1
    produto.save(update_fields=['estoque_atual'])
    print(f"\n[ESTOQUE RESTAURADO] Saldo de {produto.codigo} restaurado para: {produto.estoque_atual}")

    print("\n" + "=" * 70)
    print("RESUMO FINAL DOS TESTES:")
    for t_name, t_res in results.items():
        print(f"  - {t_name}: {t_res}")
    print("=" * 70)


if __name__ == '__main__':
    run_tests()
