import unittest

from estoque.banco import conectar
from estoque.servico import ErroEstoque, Estoque


class TestEstoque(unittest.TestCase):
    def setUp(self):
        self.estoque = Estoque(conectar(":memory:"))
        self.estoque.cadastrar("p001", "Caneta Azul", "Papelaria", 2.5, estoque_minimo=10)

    def test_cadastro_normaliza_codigo(self):
        p = self.estoque.buscar("P001")
        self.assertEqual(p.codigo, "P001")
        self.assertEqual(p.quantidade, 0)

    def test_codigo_duplicado(self):
        with self.assertRaises(ErroEstoque):
            self.estoque.cadastrar("P001", "Outra")

    def test_entrada_e_saida(self):
        self.estoque.entrada("P001", 30)
        p = self.estoque.saida("P001", 12, "Sala 3")
        self.assertEqual(p.quantidade, 18)
        hist = self.estoque.historico("P001")
        self.assertEqual([m["tipo"] for m in hist], ["SAIDA", "ENTRADA"])

    def test_saida_maior_que_estoque(self):
        self.estoque.entrada("P001", 5)
        with self.assertRaises(ErroEstoque):
            self.estoque.saida("P001", 6)
        self.assertEqual(self.estoque.buscar("P001").quantidade, 5)

    def test_quantidade_invalida(self):
        with self.assertRaises(ErroEstoque):
            self.estoque.entrada("P001", 0)

    def test_alerta_estoque_minimo(self):
        self.estoque.entrada("P001", 10)
        self.assertEqual(len(self.estoque.abaixo_do_minimo()), 1)
        self.estoque.entrada("P001", 1)
        self.assertEqual(self.estoque.abaixo_do_minimo(), [])

    def test_resumo(self):
        self.estoque.cadastrar("P002", "Caderno", preco=15.0)
        self.estoque.entrada("P001", 20)
        self.estoque.entrada("P002", 4)
        r = self.estoque.resumo()
        self.assertEqual(r["total_itens"], 24)
        self.assertEqual(r["valor_total"], 110.0)

    def test_atualizar_e_remover(self):
        self.estoque.atualizar("P001", preco=3.0)
        self.assertEqual(self.estoque.buscar("P001").preco, 3.0)
        self.estoque.remover("P001")
        with self.assertRaises(ErroEstoque):
            self.estoque.buscar("P001")


if __name__ == "__main__":
    unittest.main()
