import tempfile
import unittest
from pathlib import Path

from estoque import dados
from estoque.banco import conectar
from estoque.servico import Almoxarifado, ErroEstoque
from tests.planilha_exemplo import gerar


class TestDados(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.d = Path(self.dir.name)
        self.banco = self.d / "estoque.db"
        self.alm = Almoxarifado(conectar(self.banco))
        self.addCleanup(self.alm.db.close)
        self.alm.definir_config("senha_hash", "x")
        self.alm.definir_config("usuario", "Luis")
        self.alm.cadastrar_item("Cabo", sku="CB-1", saldo_inicial=5)
        self.alm.saida("CB-1", 2, solicitante="ana")
        self.alm.criar_pedido("ana", [("CB-1", 1)])
        self.real = self.d / "REAL.xlsx"
        self.real.write_bytes(gerar())
        self.alm.definir_config("planilha", str(self.real))
        self.alm.definir_config("auto_enviar", "1")

    def test_apagar_mantem_senha_e_faz_numeracao_recomecar(self):
        antes = dados.apagar_dados(self.alm)
        self.assertEqual((antes["itens"], antes["lancamentos"], antes["pedidos"]), (1, 2, 1))
        self.assertEqual(set(dados.contar(self.alm).values()), {0})
        self.assertEqual(self.alm.config("senha_hash"), "x")
        self.assertEqual(self.alm.cadastrar_item("Novo").id, 1)
        self.assertEqual(self.alm.criar_pedido("x", [("1", 1)])["num"], "P-001")

    def test_copia_e_restaurar(self):
        copia = dados.salvar_copia(self.alm, self.banco, "antes de mexer")
        self.assertTrue(copia.is_file())
        dados.apagar_dados(self.alm)
        self.alm.definir_config("senha_hash", "nova")
        dados.restaurar_copia(self.alm, self.banco, copia.name)
        self.assertEqual(self.alm.item("CB-1").saldo, 3)
        self.assertEqual(self.alm.config("senha_hash"), "nova")       # senha atual continua
        self.assertEqual(len(dados.listar_copias(self.banco)), 2)      # + cópia "antes de restaurar"
        with self.assertRaises(ErroEstoque):
            dados.restaurar_copia(self.alm, self.banco, "../estoque.db")

    def test_modo_teste_nao_toca_na_planilha_real(self):
        original = self.real.read_bytes()
        r = dados.iniciar_teste(self.alm, self.banco, "minha planilha.xlsx", gerar(), apagar=True)
        self.assertTrue(dados.em_teste(self.alm))
        self.assertEqual(r["movimentos"], 4)
        teste = Path(self.alm.config("planilha"))
        self.assertEqual(teste.parent, dados.pasta_teste(self.banco).resolve())
        self.assertEqual(self.alm.config("planilha_real"), str(self.real))
        # trabalhar no teste e enviar: grava só na cópia de teste
        from estoque.sincronizar import enviar_para_planilha
        self.alm.saida("818EZ001", solicitante="luan")
        enviar_para_planilha(self.alm, self.alm.config("planilha"))
        self.assertNotEqual(teste.read_bytes(), gerar())
        self.assertEqual(self.real.read_bytes(), original)
        # encerrar: apaga o teste, volta para a real e traz os dados dela
        fim = dados.encerrar_teste(self.alm, self.banco)
        self.assertFalse(dados.em_teste(self.alm))
        self.assertEqual(self.alm.config("planilha"), str(self.real))
        self.assertEqual(self.alm.config("auto_enviar"), "1")
        self.assertEqual(fim["trazido"]["movimentos"], 4)
        self.assertEqual(self.alm.item("LT-01").seriais, ["818EZ001", "818EZ002"])   # saída do teste sumiu
        self.assertEqual(self.real.read_bytes(), original)

    def test_iniciar_teste_recusa_arquivo_que_nao_e_planilha(self):
        with self.assertRaises(Exception):
            dados.iniciar_teste(self.alm, self.banco, "x.xlsx", b"nada")
        self.assertFalse(dados.em_teste(self.alm))
        self.assertEqual(self.alm.item("CB-1").saldo, 3)     # nada foi apagado
