import os
import tempfile
import openpyxl
from io import StringIO
from django.test import TestCase
from django.core.management import call_command, CommandError
from django.db import transaction

from production.models import ProductionMatrixCatalog
from matrizaria.models import MatrizFisica, LoteImportacaoMatrizFisica


def create_test_excel(rows_data, sheet_name="Inventario") -> str:
    """Cria arquivo temporário Excel simulando a planilha Inventario com cabeçalhos padrão."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name

    # Linhas de título prévias
    ws.append(["INVENTÁRIO DE TESTE"])
    ws.append(["Prévia de teste"])
    ws.append([""])
    ws.append([""])

    # Linha 5: Cabeçalhos
    headers = [
        "ID da linha",
        "Medida lida na foto",
        "Medida proposta",
        "Modelo lido",
        "Quantidade total",
        "Com dote",
        "Sem dote",
        "Dote não informado",
        "Última coluna original",
        "Revisão da leitura",
        "Aprovar dados",
        "ID no catálogo",
        "Observações / limitações",
        "Fonte",
    ]
    ws.append(headers)

    for r in rows_data:
        ws.append(r)

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    wb.save(tmp.name)
    return tmp.name


class ImportacaoMatrizesFisicasTestCase(TestCase):
    def setUp(self):
        # Obter ou criar catálogo canônico para os testes (já populado pelas migrations de production)
        self.cat_hopper_410, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=6,
            defaults={
                "codigo": "6",
                "nome_scada": "PNEUS HOPPER 4.10-18",
                "nome_exibicao": "PNEU HOPPER 4.10-18",
                "produto": "PNEU HOPPER 4.10-18",
                "variante_sc": False,
                "ativo": True,
            }
        )
        self.cat_wings_80100, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=9,
            defaults={
                "codigo": "9",
                "nome_scada": "PNEUS WINGS 80/100-14",
                "nome_exibicao": "PNEU WINGS 80/100-14",
                "produto": "PNEU WINGS 80/100-14",
                "variante_sc": False,
                "ativo": True,
            }
        )
        self.cat_hopper_9090, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=3,
            defaults={
                "codigo": "3",
                "nome_scada": "PNEUS HOPPER 90/90-18",
                "nome_exibicao": "PNEU HOPPER 90/90-18",
                "produto": "PNEU HOPPER 90/90-18",
                "variante_sc": False,
                "ativo": True,
            }
        )
        self.cat_hopper_9090_sc, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=37,
            defaults={
                "codigo": "37",
                "nome_scada": "PNEU HOPPER 90/90-18 S/C",
                "nome_exibicao": "PNEU HOPPER 90/90-18 S/C",
                "produto": "PNEU HOPPER 90/90-18 S/C",
                "variante_sc": True,
                "ativo": True,
            }
        )
        self.cat_hopper_9090_19, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=8,
            defaults={
                "codigo": "8",
                "nome_scada": "PNEU HOPPER 90/90-19",
                "nome_exibicao": "PNEU HOPPER 90/90-19",
                "produto": "PNEU HOPPER 90/90-19",
                "variante_sc": False,
                "ativo": True,
            }
        )
        self.cat_hopper_480, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=15,
            defaults={
                "codigo": "15",
                "nome_scada": "PNEUS HOPPER 4.80/4.00-8",
                "nome_exibicao": "PNEU HOPPER 4.80/4.00-8",
                "produto": "PNEU HOPPER 4.80/4.00-8",
                "variante_sc": False,
                "ativo": True,
            }
        )
        self.cat_hopper_12080, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=22,
            defaults={
                "codigo": "22",
                "nome_scada": "PNEU HOPPER 120/80-18",
                "nome_exibicao": "PNEU HOPPER 120/80-18",
                "produto": "PNEU HOPPER 120/80-18",
                "variante_sc": False,
                "ativo": True,
            }
        )

    def tearDown(self):
        # Limpar arquivos temporários se houver
        pass

    def test_01_expansao_quantidade_unidades_individuais(self):
        """Testa expansão correta de quantidade (ex: 3 unidades geram 3 instâncias com sequencial 1, 2, 3)."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 3, 3, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "Teste", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out)
            
            # Verificar unidades geradas
            mats = MatrizFisica.objects.filter(modelo=self.cat_hopper_410).order_by("numero_sequencial")
            self.assertEqual(mats.count(), 3)
            self.assertEqual([m.numero_sequencial for m in mats], [1, 2, 3])
            self.assertEqual(mats[0].identificador_estavel, "MF-6-001")
            self.assertEqual(mats[1].identificador_estavel, "MF-6-002")
            self.assertEqual(mats[2].identificador_estavel, "MF-6-003")
            self.assertEqual(mats[0].chave_unidade_origem, "P1-22-U01")
            self.assertEqual(mats[1].chave_unidade_origem, "P1-22-U02")
            self.assertEqual(mats[2].chave_unidade_origem, "P1-22-U03")
        finally:
            os.remove(fpath)

    def test_02_grupo_todo_com_dote(self):
        """Testa grupo com todas as matrizes marcadas com dote (possui_dote='SIM')."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "Teste", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mats = MatrizFisica.objects.filter(modelo=self.cat_hopper_410)
            self.assertEqual(mats.count(), 2)
            self.assertTrue(all(m.possui_dote == "SIM" for m in mats))
        finally:
            os.remove(fpath)

    def test_03_grupo_todo_sem_dote(self):
        """Testa grupo sem dote (possui_dote='NAO')."""
        data = [
            ["P1-26", "90/90-19", "90/90-19", "HOPPER", 2, 0, 2, 0, "Não", "LEITURA DIRETA", "APROVADO", None, "Sem dote", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mats = MatrizFisica.objects.filter(modelo=self.cat_hopper_9090_19)
            self.assertEqual(mats.count(), 2)
            self.assertTrue(all(m.possui_dote == "NAO" for m in mats))
        finally:
            os.remove(fpath)

    def test_04_grupo_misto_wings_80100_14(self):
        """Testa caso misto WINGS 80/100-14: 2 unidades, 1 com dote e 1 sem dote."""
        data = [
            ["P2-06", "80/100-14", "80/100-14", "WINGS", 2, 1, 1, 0, "1 Não / 1 Sim", "MISTO", "APROVADO", None, "Caso misto", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mats = list(MatrizFisica.objects.filter(modelo=self.cat_wings_80100).order_by("numero_sequencial"))
            self.assertEqual(len(mats), 2)
            # Unidade 1: Com dote
            self.assertEqual(mats[0].numero_sequencial, 1)
            self.assertEqual(mats[0].possui_dote, "SIM")
            self.assertEqual(mats[0].situacao_identificacao, "PENDENTE")
            # Unidade 2: Sem dote
            self.assertEqual(mats[1].numero_sequencial, 2)
            self.assertEqual(mats[1].possui_dote, "NAO")
            self.assertEqual(mats[1].situacao_identificacao, "PENDENTE")
        finally:
            os.remove(fpath)

    def test_05_dote_nao_informado(self):
        """Testa dote não informado (possui_dote='NAO_INFORMADO'). Não transforma em 'Não'."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 1, 0, 0, 1, "Em branco", "DOTE NI", "APROVADO", None, "Dote vazio", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mat = MatrizFisica.objects.get(modelo=self.cat_hopper_410)
            self.assertEqual(mat.possui_dote, "NAO_INFORMADO")
        finally:
            os.remove(fpath)

    def test_06_preservacao_numeros_fisicos_vazios(self):
        """Garante que número físico confirmado permanece None (não assume sequencial como físico)."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 1, 1, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "Teste", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mat = MatrizFisica.objects.get(modelo=self.cat_hopper_410)
            self.assertIsNone(mat.numero_fisico_confirmado)
            self.assertEqual(mat.situacao_identificacao, "PENDENTE")
            self.assertFalse(mat.identificacao_confirmada)
        finally:
            os.remove(fpath)

    def test_07_matriz_compartilhada_entre_variantes_com_e_sem_camara(self):
        """
        Regra Definitiva: A mesma matriz física atende produtos com câmara ou sem câmara (S/C).
        10 matrizes HOPPER 90/90-18 geram 10 matrizes vinculadas à referência canônica (sem S/C),
        sendo localizáveis a partir de qualquer uma das duas versões do produto (com câmara e S/C).
        """
        data = [
            # HOPPER 90/90-18 existe como SCADA 3 (normal) e SCADA 37 (S/C)
            ["P1-01", "90/90-18", "90/90-18", "HOPPER", 10, 10, 0, 0, "Sim", "DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out)

            # Exatamente 10 matrizes criadas no modelo canônico (sem duplicar para 20)
            mats = MatrizFisica.objects.filter(modelo=self.cat_hopper_9090)
            self.assertEqual(mats.count(), 10)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_9090_sc).count(), 0)

            # Consulta por qualquer uma das duas variantes retorna o mesmo conjunto de 10 matrizes
            mats_via_normal = MatrizFisica.objects.for_produto(self.cat_hopper_9090)
            mats_via_sc = MatrizFisica.objects.for_produto(self.cat_hopper_9090_sc)
            self.assertEqual(mats_via_normal.count(), 10)
            self.assertEqual(mats_via_sc.count(), 10)
            self.assertEqual(list(mats_via_normal), list(mats_via_sc))

            # Cada exemplar atende a ambas as variantes
            mat = mats.first()
            self.assertTrue(mat.is_compativel_com_produto(self.cat_hopper_9090))
            self.assertTrue(mat.is_compativel_com_produto(self.cat_hopper_9090_sc))
            # Rótulo operacional limpo sem "(Câmara/SC)"
            self.assertNotIn("(Câmara/SC)", mat.rotulo_completo)
            self.assertEqual(mat.rotulo_completo, mat.nome_exibicao)
        finally:
            os.remove(fpath)

    def test_08_quantidades_invalidas_e_soma_inconsistente(self):
        """Bloqueia linhas com erro de matemática (soma de dotes != total)."""
        data = [
            ["P1-ERR", "4.10-18", "4.10-18", "HOPPER", 5, 2, 1, 0, "Sim", "DIRETA", "APROVADO", None, "Soma dá 3 e não 5", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 0)
            self.assertIn("Inconsistentes", out.getvalue())
        finally:
            os.remove(fpath)

    def test_09_simulacao_sem_gravacao(self):
        """No modo padrão de simulação (sem --aplicar), nenhuma matriz é gravada."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 1, 1, 0, 0, "Sim", "DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            # Chama sem --aplicar
            call_command("importar_matrizes_fisicas", fpath, stdout=out)
            self.assertEqual(MatrizFisica.objects.count(), 0)
            self.assertEqual(LoteImportacaoMatrizFisica.objects.count(), 0)
            self.assertIn("SIMULACAO CONCLUIDA", out.getvalue())
        finally:
            os.remove(fpath)

    def test_10_reexecucao_sem_duplicacao_idempotencia(self):
        """Executar o mesmo lote duas vezes não duplica registros (unidades preservadas)."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            # 1ª execução
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)

            # 2ª execução com o mesmo lote
            out2 = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out2)
            # Não deve duplicar
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            self.assertIn("Matrizes físicas preservadas: 2", out2.getvalue())
        finally:
            os.remove(fpath)

    def test_11_conflito_com_cadastro_existente(self):
        """Se já existirem matrizes manuais para o modelo com colisão de numeração, o lote bloqueia."""
        # Criar cadastro manual pré-existente com sequencial 1
        MatrizFisica.objects.create(
            modelo=self.cat_hopper_410,
            identificador_estavel="MF-6-001",
            numero_sequencial=1,
            origem_cadastro="MANUAL",
            situacao_identificacao="CONFIRMADA",
            numero_fisico_confirmado="MF-REAL-99",
        )

        # Planilha tenta carregar o modelo com 2 unidades
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out)
            # Bloqueou por colisão
            self.assertIn("Conflito", out.getvalue())
            # Apenas o manual existia e permaneceu intocado
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 1)
            self.assertEqual(MatrizFisica.objects.get(modelo=self.cat_hopper_410).numero_fisico_confirmado, "MF-REAL-99")
        finally:
            os.remove(fpath)

    def test_12_auditoria_de_lote_gravada(self):
        """Verifica que a aplicação com sucesso cria o registro de auditoria LoteImportacaoMatrizFisica."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 1, 1, 0, 0, "Sim", "DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            lote = LoteImportacaoMatrizFisica.objects.first()
            self.assertIsNotNone(lote)
            self.assertEqual(lote.responsavel, "Operador Teste")
            self.assertFalse(lote.simulacao)
            self.assertEqual(lote.quantidade_unidades_criadas, 1)
            self.assertEqual(lote.status, "SUCESSO")
        finally:
            os.remove(fpath)

    def test_13_correspondencia_unica_com_fonte_pendente_continua_bloqueada(self):
        """P2-23 (HOPPER 4.80/400-8) tem correspondência única (SCADA 15), mas revisão da leitura é pendente ('CONFERIR MEDIDA').
        Não pode ser aprovada por --aprovar-linhas-seguras e nenhuma matriz deve ser gravada."""
        data = [
            ["P2-23", "4.80/400-8", "4.80/4.00-8", "HOPPER", 1, 1, 0, 0, "Sim", "CONFERIR MEDIDA", "PENDENTE", None, "Pendente conferência", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, aprovar_linhas_seguras=True, responsavel="Operador Teste", stdout=out)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_480).count(), 0)
            self.assertIn("BLOQUEADA", out.getvalue())
            self.assertIn("pendência na fonte", out.getvalue())
        finally:
            os.remove(fpath)

    def test_14_escolha_explicita_id_incompativel_recusada(self):
        """Se o usuário preencher um ID de catálogo incompatível (ex: ID de WINGS 80/100-14 para linha HOPPER 4.10-18), a carga recusa e bloqueia."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", self.cat_wings_80100.id, "ID incompatível", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=out)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 0)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_wings_80100).count(), 0)
            self.assertIn("INCOMPAT", out.getvalue().upper())
        finally:
            os.remove(fpath)

    def test_15_arquivo_regravado_preserva_unidades_sem_duplicar(self):
        """Arquivo com novo hash/nome regravado não recria unidades nem duplica (idempotência por identidade de unidade)."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste1.jpeg"],
        ]
        fpath1 = create_test_excel(data)
        fpath2 = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath1, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            u_ids_originais = list(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).values_list("id", flat=True))

            out2 = StringIO()
            call_command("importar_matrizes_fisicas", fpath2, aplicar=True, responsavel="Operador Teste", stdout=out2)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            u_ids_apos = list(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).values_list("id", flat=True))
            self.assertEqual(u_ids_originais, u_ids_apos)
            self.assertIn("Matrizes físicas preservadas: 2", out2.getvalue())
        finally:
            os.remove(fpath1)
            os.remove(fpath2)

    def test_16_carga_parcial_seguida_das_linhas_restantes(self):
        """Carga de lote parcial (apenas linha P1-22) seguida por execução posterior com linha restante (P1-23)."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
            ["P1-23", "120/80-18", "120/80-18", "HOPPER", 1, 1, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            # Executa apenas P1-22
            call_command("importar_matrizes_fisicas", fpath, linhas="P1-22", aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_12080).count(), 0)

            # Executa apenas P1-23
            call_command("importar_matrizes_fisicas", fpath, linhas="P1-23", aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_12080).count(), 1)
            self.assertEqual(MatrizFisica.objects.count(), 3)
        finally:
            os.remove(fpath)

    def test_17_mudanca_quantidade_apos_carga_exige_reconciliacao(self):
        """Se a quantidade de uma linha já importada for alterada posteriormente (ex: de 2 para 3), o sistema bloqueia e exige reconciliação humana."""
        data_orig = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath_orig = create_test_excel(data_orig)
        try:
            call_command("importar_matrizes_fisicas", fpath_orig, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
        finally:
            os.remove(fpath_orig)

        # Planilha posterior alterando total para 3
        data_mod = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 3, 3, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath_mod = create_test_excel(data_mod)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath_mod, aplicar=True, responsavel="Operador Teste", stdout=out)
            # Permanece 2 no banco; a 3ª não foi criada pois a linha foi bloqueada
            self.assertEqual(MatrizFisica.objects.filter(modelo=self.cat_hopper_410).count(), 2)
            self.assertIn("Divergência de inventário", out.getvalue())
        finally:
            os.remove(fpath_mod)

    def test_18_falha_durante_aplicacao_provoca_rollback_do_lote(self):
        """Verifica que qualquer erro inesperado dentro da transação atômica executa rollback integral de todas as matrizes do lote."""
        from unittest.mock import patch
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 2, 2, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            with patch("matrizaria.models.LoteImportacaoMatrizFisica.objects.create", side_effect=RuntimeError("Falha simulada no banco")):
                with self.assertRaises(RuntimeError):
                    call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())

            # Transação atômica reverteu: nenhuma matriz gravada
            self.assertEqual(MatrizFisica.objects.count(), 0)
            self.assertEqual(LoteImportacaoMatrizFisica.objects.count(), 0)
        finally:
            os.remove(fpath)

    def test_19_identificacao_fisica_nao_confirmada_automaticamente(self):
        """Assegura que unidades criadas em lote nunca recebem identificação confirmada e apresentam rótulo claro de pendência."""
        data = [
            ["P1-22", "4.10-18", "4.10-18", "HOPPER", 1, 1, 0, 0, "Sim", "LEITURA DIRETA", "APROVADO", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, responsavel="Operador Teste", stdout=StringIO())
            mat = MatrizFisica.objects.get(modelo=self.cat_hopper_410)
            self.assertEqual(mat.situacao_identificacao, "PENDENTE")
            self.assertIsNone(mat.numero_fisico_confirmado)
            self.assertFalse(mat.identificacao_confirmada)
            self.assertEqual(mat.origem_cadastro, "INVENTARIO_LOTE")
            # Rótulo operacional limpo sem sufixos de pendência
            self.assertNotIn("[ID Física Pendente", mat.rotulo_completo)
            self.assertEqual(mat.rotulo_completo, mat.nome_exibicao)
        finally:
            os.remove(fpath)

    def test_20_carga_inicial_cadastra_modelos_ausentes_em_lote(self):
        """Sob --carga-inicial, modelos ausentes são cadastrados em lote no catálogo com código interno, sem código SCADA e tempos zerados."""
        data = [
            ["P1-05", "90/90-18", "90/90-18", "RIVER", 1, 1, 0, 0, "Sim", "DIRETA", "PENDENTE", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, carga_inicial=True, responsavel="Operador Teste", stdout=out)

            # Modelo ausente cadastrado automaticamente no catálogo
            cat = ProductionMatrixCatalog.objects.filter(codigo="INT-RIVER-909018").first()
            self.assertIsNotNone(cat)
            self.assertIsNone(cat.codigo_scada)
            self.assertEqual(cat.tempo_producao_segundos, 0)
            self.assertEqual(cat.tempo_vulcanizacao_segundos, 0)
            self.assertTrue(cat.ativo)
            self.assertEqual(cat.nome_exibicao, "PNEU RIVER 90/90-18")

            # Matriz física criada vinculada a este modelo
            mat = MatrizFisica.objects.filter(modelo=cat).first()
            self.assertIsNotNone(mat)
            self.assertEqual(mat.identificador_estavel, "MF-INT-RIVER-909018-001")
            self.assertEqual(mat.numero_sequencial, 1)
            self.assertEqual(mat.possui_dote, "SIM")
            self.assertEqual(mat.situacao_identificacao, "PENDENTE")
            self.assertIsNone(mat.numero_fisico_confirmado)
        finally:
            os.remove(fpath)

    def test_21_carga_inicial_preserva_ressalvas_e_caso_misto_wings(self):
        """Garante que as ressalvas da fonte (rasura, dote misto WINGS, medida proposta P2-23, dote em branco WINTER) são fielmente preservadas."""
        data = [
            # P2-06: WINGS 80/100-14 caso misto (1 com dote, 1 sem dote)
            ["P2-06", "80/100-14", "80/100-14", "WINGS", 2, 1, 1, 0, "1 Sim, 1 Nao", "DIRETA", "PENDENTE", None, "Caso misto", "teste.jpeg"],
            # P1-07: HOPPER 2.75-18 (5 un rasura)
            ["P1-07", "2/75-18", "2.75-18", "HOPPER", 5, 5, 0, 0, "Sim", "CONFERIR RASURA", "PENDENTE", None, "Rasura", "teste.jpeg"],
            # P2-23: HOPPER 4.80/400-8
            ["P2-23", "4.80/400-8", "4.80/4.00-8", "HOPPER", 1, 1, 0, 0, "Sim", "CONFERIR MEDIDA", "PENDENTE", None, "Medida barra", "teste.jpeg"],
            # P1-25: WINTER 120/100-18 (dote em branco -> NAO_INFORMADO)
            ["P1-25", "120/100-18", "120/100-18", "WINTER", 1, 0, 0, 1, "", "DOTE EM BRANCO", "PENDENTE", None, "Dote não inf", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, carga_inicial=True, responsavel="Operador Teste", stdout=out)

            # P2-06 WINGS 80/100-14 (2 unidades: U01 com dote, U02 sem dote)
            mats_wings = list(MatrizFisica.objects.filter(modelo=self.cat_wings_80100).order_by("numero_sequencial"))
            self.assertEqual(len(mats_wings), 2)
            self.assertEqual(mats_wings[0].possui_dote, "SIM")
            self.assertEqual(mats_wings[1].possui_dote, "NAO")
            self.assertIn("Ref 01 com dote para diferenciação interna", mats_wings[0].observacao_identificacao)
            self.assertIn("Ref 02 sem dote para diferenciação interna", mats_wings[1].observacao_identificacao)

            # P1-07 HOPPER 2.75-18 (5 unidades adotadas)
            cat_hopper_275 = ProductionMatrixCatalog.objects.get(codigo_scada=4)
            mats_hopper_275 = MatrizFisica.objects.filter(modelo=cat_hopper_275)
            self.assertEqual(mats_hopper_275.count(), 5)
            self.assertIn("rasura na folha física preservada", mats_hopper_275.first().observacao_identificacao)

            # P2-23 HOPPER 4.80/4.00-8
            mats_hopper_480 = MatrizFisica.objects.filter(modelo=self.cat_hopper_480)
            self.assertEqual(mats_hopper_480.count(), 1)
            self.assertIn("4.80/4.00-8 adotada a partir da transcrição de 4.80/400-8", mats_hopper_480.first().observacao_identificacao)

            # P1-25 WINTER 120/100-18
            cat_winter = ProductionMatrixCatalog.objects.get(codigo="INT-WINTER-12010018")
            mat_winter = MatrizFisica.objects.get(modelo=cat_winter)
            self.assertEqual(mat_winter.possui_dote, "NAO_INFORMADO")
            self.assertIn("dote não informado", mat_winter.observacao_identificacao)
        finally:
            os.remove(fpath)

    def test_22_fidelidade_p1_06_option_nao_robot(self):
        """Garante que a linha P1-06 corresponde fielmente a OPTION 90/90-18 (SCADA 14) sem dote, e jamais a ROBOT."""
        cat_option, _ = ProductionMatrixCatalog.objects.get_or_create(
            codigo_scada=14,
            defaults={
                "codigo": "14",
                "nome_scada": "PNEU OPTION 90/90-18",
                "nome_exibicao": "PNEU OPTION 90/90-18",
                "produto": "PNEU OPTION 90/90-18",
                "variante_sc": False,
                "ativo": True,
            }
        )
        data = [
            ["P1-06", "90/90-18", "90/90-18", "OPTION", 1, 0, 1, 0, "Não", "LEITURA DIRETA", "PENDENTE", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            out = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, carga_inicial=True, responsavel="Operador Teste", stdout=out)

            mats_option = MatrizFisica.objects.filter(modelo=cat_option)
            self.assertEqual(mats_option.count(), 1)
            mat = mats_option.first()
            self.assertEqual(mat.possui_dote, "NAO")
            self.assertEqual(mat.linha_origem, "P1-06")
            self.assertIn("OPTION 90/90-18, 1 un sem dote", mat.observacao_identificacao)

            # Assegura que nenhum modelo ROBOT foi criado para esta linha
            self.assertFalse(ProductionMatrixCatalog.objects.filter(nome_exibicao__icontains="ROBOT 90/90-18").exists())
        finally:
            os.remove(fpath)

    def test_23_reexecucao_carga_inicial_preserva_unidades_e_modelos(self):
        """Idempotência com --carga-inicial: reexecução preserva os modelos criados e as matrizes já persistidas."""
        data = [
            ["P1-05", "90/90-18", "90/90-18", "RIVER", 1, 1, 0, 0, "Sim", "DIRETA", "PENDENTE", None, "", "teste.jpeg"],
        ]
        fpath = create_test_excel(data)
        try:
            # 1ª execução
            out1 = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, carga_inicial=True, responsavel="Operador Teste", stdout=out1)
            self.assertIn("Modelos novos criados no catálogo: 1", out1.getvalue())
            self.assertIn("Matrizes físicas criadas: 1", out1.getvalue())

            # 2ª execução
            out2 = StringIO()
            call_command("importar_matrizes_fisicas", fpath, aplicar=True, carga_inicial=True, responsavel="Operador Teste", stdout=out2)
            self.assertIn("Modelos novos criados no catálogo: 0", out2.getvalue())
            self.assertIn("Matrizes físicas criadas: 0", out2.getvalue())
            self.assertIn("Matrizes físicas preservadas: 1", out2.getvalue())
        finally:
            os.remove(fpath)

    def test_24_rotulos_operacionais_limpos_nos_seletores(self):
        """Valida que rótulos operacionais mostram apenas modelo, medida e número do exemplar sem poluição."""
        from matrizaria.forms import format_matriz_fisica_label, SolicitacaoServicoForm

        mat1 = MatrizFisica.objects.create(
            modelo=self.cat_wings_80100,
            identificador_estavel="MF-TEST-WINGS-001",
            numero_sequencial=1,
            possui_dote="SIM",
            situacao_identificacao="PENDENTE",
        )
        mat2 = MatrizFisica.objects.create(
            modelo=self.cat_wings_80100,
            identificador_estavel="MF-TEST-WINGS-002",
            numero_sequencial=2,
            possui_dote="NAO",
            situacao_identificacao="PENDENTE",
        )

        # Rótulos limpos e distintos
        lbl1 = format_matriz_fisica_label(mat1)
        lbl2 = format_matriz_fisica_label(mat2)
        self.assertEqual(lbl1, f"{self.cat_wings_80100.nome_exibicao} #001")
        self.assertEqual(lbl2, f"{self.cat_wings_80100.nome_exibicao} #002")
        self.assertNotEqual(lbl1, lbl2)

        # Sem complementos nem colchetes
        for lbl in (lbl1, lbl2):
            self.assertNotIn("ID Física Pendente", lbl)
            self.assertNotIn("Com Dote", lbl)
            self.assertNotIn("Sem Dote", lbl)
            self.assertNotIn("(Câmara/SC)", lbl)
            self.assertNotIn("[", lbl)
            self.assertNotIn("]", lbl)

        # Valida que o form preserva os IDs reais
        form = SolicitacaoServicoForm()
        field_choices = list(form.fields["matriz_fisica"].choices)
        choice_dict = dict(field_choices)
        self.assertEqual(choice_dict.get(mat1.id), lbl1)
        self.assertEqual(choice_dict.get(mat2.id), lbl2)


