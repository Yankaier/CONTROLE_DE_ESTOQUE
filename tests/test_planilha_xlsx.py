import io
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from estoque.banco import conectar
from estoque.servico import Almoxarifado
from estoque.sincronizar import enviar_para_planilha, trazer_da_planilha
from estoque.xlsx import Planilha

from tests.planilha_exemplo import gerar


class TestPlanilhaXlsx(unittest.TestCase):
    def setUp(self):
        self.alm = Almoxarifado(conectar(":memory:"))
        self.addCleanup(self.alm.db.close)
        self.dados = gerar()

    def test_trazer_itens_e_saldos(self):
        r = trazer_da_planilha(self.alm, self.dados)
        self.assertEqual((r["itens_novos"], r["movimentos"]), (2, 4))
        self.assertEqual(self.alm.item("CB-06").saldo, 4)
        self.assertEqual(self.alm.item("LT-01").seriais, ["818EZ001", "818EZ002"])
        self.assertEqual(trazer_da_planilha(self.alm, self.dados)["movimentos"], 0)   # não duplica

    def test_enviar_grava_tudo_e_nao_quebra_o_arquivo(self):
        trazer_da_planilha(self.alm, self.dados)
        self.alm.saida("818EZ001", solicitante="luan", area="Montagem")
        self.alm.cadastrar_item("Fonte 12V", sku="FN-9", estante="5", pt="PT3", saldo_inicial=20)
        self.alm.corrigir_item("CB-06", descricao="Cabo de rede cat6 azul")
        self.alm.descartar("queimado", "joao", ref="CB-06", qtd=1)
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "CONTROLE DE ESTOQUES 2.0.xlsx"
            arq.write_bytes(self.dados)
            res = enviar_para_planilha(self.alm, arq)
            self.assertEqual((res["linhas"], res["itens_novos"], res["correcoes"], res["descartes"]), (3, 1, 1, 1))
            self.assertEqual(len(list((Path(d) / "backups-estoque").iterdir())), 1)
            novo = arq.read_bytes()
        with zipfile.ZipFile(io.BytesIO(novo)) as z:
            for nome in z.namelist():
                if nome.endswith(".xml") or nome.endswith(".rels"):
                    ET.fromstring(z.read(nome))          # todo XML continua válido
            self.assertIn('ref="A4:N11"', z.read("xl/tables/table1.xml").decode())
        lido = Planilha(novo).ler()
        self.assertEqual([i["descricao"] for i in lido["itens"]],
                         ["CABO DE REDE CAT6 AZUL", "LEITOR DE CARTÃO", "FONTE 12V"])
        ultima = lido["movimentos"][-1]
        self.assertEqual((ultima["linha"], ultima["area"], ultima["unid"]), (11, "Descarte", "-1"))
        self.assertTrue(lido["descartes"][0]["baixa"].startswith("Sim, Movimentação linha 11"))
        self.assertEqual(self.alm.pendentes(), {"lancamentos": 0, "itens_novos": 0, "correcoes": 0})

        outro = Almoxarifado(conectar(":memory:"))
        self.addCleanup(outro.db.close)
        trazer_da_planilha(outro, novo)
        self.assertEqual(outro.item("CB-06").saldo, 3)
        self.assertEqual(outro.item("LT-01").seriais, ["818EZ002"])
        self.assertEqual(outro.item("FN-9").saldo, 20)

    def test_nada_pendente_nao_mexe_no_arquivo(self):
        trazer_da_planilha(self.alm, self.dados)
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "p.xlsx"
            arq.write_bytes(self.dados)
            enviar_para_planilha(self.alm, arq)
            self.assertEqual(arq.read_bytes(), self.dados)
