import tempfile
import unittest
from pathlib import Path

from estoque.banco import conectar
from estoque.planilha import exportar_dia, importar_dia
from estoque.servico import Almoxarifado, ErroEstoque, hoje


class Base(unittest.TestCase):
    def setUp(self):
        self.alm = Almoxarifado(conectar(":memory:"))
        self.addCleanup(self.alm.db.close)
        self.cabo = self.alm.cadastrar_item("cabo de rede cat6", sku="CB-06", estante="3", pt="PT2",
                                            caixa="12", minimo=5, saldo_inicial=10)
        self.leitor = self.alm.cadastrar_item("leitor de cartão", sku="LT-01", estante="1", pt="PT1",
                                              seriais=["818EZ001", "818EZ002", "818EZ003"])


class TestItens(Base):
    def test_cadastro_gera_saldo_inicial(self):
        self.assertEqual(self.cabo.descricao, "CABO DE REDE CAT6")
        self.assertEqual(self.cabo.saldo, 10)
        l = self.alm.historico(self.cabo.id)[0]
        self.assertEqual((l["movim"], l["area"]), ("Saldo Inicial", "Estoque Inicial"))

    def test_seriais_contam_no_saldo(self):
        self.assertEqual(self.leitor.saldo, 3)

    def test_acha_por_sku_e_serial(self):
        self.assertEqual(self.alm.item("cb-06").id, self.cabo.id)
        self.assertEqual(self.alm.item("818ez002").id, self.leitor.id)
        self.assertEqual(len(self.alm.buscar("818EZ")), 1)

    def test_mesmo_item_mesmo_local_e_bloqueado(self):
        with self.assertRaises(ErroEstoque):
            self.alm.cadastrar_item("Cabo de rede cat6", sku="CB-06", estante="3", pt="PT2", caixa="12")


class TestMovimentacao(Base):
    def test_saida_e_entrada(self):
        self.alm.saida("CB-06", 4, solicitante="luan", area="Montagem")
        self.alm.entrada("CB-06", 1, obs="sobra")
        self.assertEqual(self.alm.item("CB-06").saldo, 7)
        self.assertEqual(self.alm.db.execute("SELECT area FROM pessoas WHERE nome='LUAN'").fetchone()[0],
                         "Montagem")

    def test_saida_sem_saldo_bloqueada_ou_forcada(self):
        with self.assertRaises(ErroEstoque):
            self.alm.saida("CB-06", 11)
        self.alm.saida("CB-06", 11, forcar=True)
        self.assertEqual(self.alm.item("CB-06").saldo, -1)

    def test_saida_com_serial(self):
        self.alm.saida("LT-01", seriais=["818EZ002"])
        it = self.alm.item("LT-01")
        self.assertEqual((it.saldo, it.seriais), (2, ["818EZ001", "818EZ003"]))
        with self.assertRaises(ErroEstoque):
            self.alm.saida("LT-01", seriais=["818EZ002"])

    def test_saida_pelo_serial_bipado(self):
        self.alm.saida("818EZ003")
        self.assertNotIn("818EZ003", self.alm.item("LT-01").seriais)

    def test_item_com_serial_exige_serial_na_saida(self):
        with self.assertRaises(ErroEstoque):
            self.alm.saida("LT-01", 1)

    def test_entrada_serial_repetido(self):
        with self.assertRaises(ErroEstoque):
            self.alm.entrada("LT-01", seriais=["818EZ001"])

    def test_minimo(self):
        self.assertEqual(self.alm.abaixo_do_minimo(), [])
        self.alm.saida("CB-06", 5)
        self.assertEqual([i.id for i in self.alm.abaixo_do_minimo()], [self.cabo.id])

    def test_contagem(self):
        l = self.alm.ajustar_contagem("CB-06", 8)
        self.assertEqual((l["movim"], l["qtd"]), ("Saldo Inicial", -2))
        self.assertEqual(self.alm.item("CB-06").saldo, 8)
        self.assertIsNone(self.alm.ajustar_contagem("CB-06", 8))

    def test_estorno(self):
        l = self.alm.saida("LT-01", seriais=["818EZ001"])
        e = self.alm.estornar(l["id"], "lançado errado")
        self.assertEqual(e["movim"], "Entrada")
        self.assertIn("818EZ001", self.alm.item("LT-01").seriais)
        with self.assertRaises(ErroEstoque):
            self.alm.estornar(l["id"], "de novo")


class TestEmprestimos(Base):
    def test_emprestimo_e_devolucao(self):
        l = self.alm.saida("CB-06", 2, emprestimo=True, devolver_ate="2000-01-01", solicitante="ana")
        self.assertEqual(len(self.alm.emprestimos_atrasados()), 1)
        self.alm.devolver(l["id"])
        self.assertEqual(self.alm.emprestimos_abertos(), [])
        self.assertEqual(self.alm.item("CB-06").saldo, 10)

    def test_emprestimo_exige_data(self):
        with self.assertRaises(ErroEstoque):
            self.alm.saida("CB-06", 1, emprestimo=True)


class TestPedidos(Base):
    def test_fluxo_do_pedido(self):
        p = self.alm.criar_pedido("luan", [("CB-06", 3), (self.leitor.id, 5)], area="Montagem")
        self.assertEqual(p["num"], "P-001")
        self.assertEqual(self.alm.separar_pedido("P-001")["status"], "separado")
        r = self.alm.entregar_pedido("P-001")
        self.assertEqual(len(r["lancamentos"]), 1)      # cabo saiu
        self.assertEqual(len(r["nao_entregues"]), 1)    # leitor: só 3 em estoque
        self.assertEqual(r["pedido"]["status"], "entregue")
        self.assertEqual(self.alm.criar_pedido("ana", [("CB-06", 1)])["num"], "P-002")

    def test_nao_entrega_cancelado(self):
        self.alm.criar_pedido("luan", [("CB-06", 1)])
        self.alm.cancelar_pedido("P-001")
        with self.assertRaises(ErroEstoque):
            self.alm.entregar_pedido("P-001")


class TestDescarte(Base):
    def test_descarte_do_estoque_gera_saida(self):
        d = self.alm.descartar("queimado", "joão", ref="LT-01", seriais=["818EZ003"])
        self.assertEqual((d["num"], d["modo"]), ("D-0001", "estoque"))
        l = self.alm.lancamento(d["lancamento_id"])
        self.assertEqual((l["movim"], l["area"]), ("Saída", "Descarte"))
        self.assertEqual(self.alm.item("LT-01").saldo, 2)

    def test_descarte_de_fora(self):
        d = self.alm.descartar("sucata", "joão", qtd=2, material="monitor antigo")
        self.assertEqual((d["num"], d["modo"], d["lancamento_id"]), ("D-0001", "fora", None))


class TestPlanilha(Base):
    def test_exportar_e_importar_no_formato_do_app(self):
        self.alm.saida("CB-06", 4, solicitante="luan", area="Montagem", os="0001/26")
        self.alm.saida("LT-01", seriais=["818EZ001"], solicitante="luan")
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / f"Movimento do dia {hoje()}.csv"
            self.assertEqual(exportar_dia(self.alm, hoje(), arq), 4)
            self.assertTrue(arq.read_bytes().startswith(b"\xef\xbb\xbf"))

            outro = Almoxarifado(conectar(":memory:"))
            self.addCleanup(outro.db.close)
            r = importar_dia(outro, arq)
            self.assertEqual((r["importados"], r["itens_novos"]), (4, 2))
            self.assertEqual(outro.item("CB-06").saldo, 6)
            self.assertEqual(outro.item("LT-01").seriais, ["818EZ002", "818EZ003"])
            self.assertEqual(importar_dia(outro, arq)["repetidos"], 4)   # não duplica

    def test_importa_arquivo_do_app(self):
        csv = ("﻿Data;Hora;Tipo;Estante;PT;Caixa;SKU;Descrição;Seriais;Quantidade;Solicitante / origem;"
               "Área;OS;NF;Observação;Situação\r\n"
               "10/11/2026;08:15;Entrada;5;PT3;-;FN-9;FONTE 12V;;20;Fornecedor X;Fornecedor;;NF 123;;Na planilha\r\n"
               "10/11/2026;09:40;Saída;5;PT3;-;FN-9;FONTE 12V;;-3;LUAN;Montagem;0042/26;;\"obs; com ponto e vírgula\";Pendente\r\n")
        with tempfile.TemporaryDirectory() as d:
            arq = Path(d) / "Movimento do dia 2026-11-10.csv"
            arq.write_text(csv, encoding="utf-8")
            importar_dia(self.alm, arq)
        fonte = self.alm.item("FN-9")
        self.assertEqual(fonte.saldo, 17)
        h = self.alm.historico("FN-9")
        self.assertEqual(h[0]["obs"], "obs; com ponto e vírgula")
        self.assertEqual([x["status"] for x in h], ["pendente", "lancado"])


if __name__ == "__main__":
    unittest.main()
