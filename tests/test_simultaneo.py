import re
import tempfile
import threading
import unittest
from pathlib import Path

try:
    from estoque.web import criar_app
except ImportError:
    criar_app = None

from estoque.banco import conectar
from estoque.servico import Almoxarifado


@unittest.skipIf(criar_app is None, "Flask não instalado")
class TestUsoSimultaneo(unittest.TestCase):
    def test_dois_aparelhos_ao_mesmo_tempo_nao_tiram_mais_que_o_saldo(self):
        with tempfile.TemporaryDirectory() as d:
            banco = str(Path(d) / "estoque.db")
            app = criar_app(banco)
            prep = app.test_client()
            html = prep.get("/primeiro-acesso").get_data(as_text=True)
            csrf = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
            prep.post("/primeiro-acesso", data={"_csrf": csrf, "senha": "senha-forte-1", "senha2": "senha-forte-1"})
            c = conectar(banco)
            Almoxarifado(c).cadastrar_item("Fonte", sku="FN-1", saldo_inicial=4)
            c.close()

            ok, erros = [], []

            def aparelho():
                cli = app.test_client()
                h = cli.get("/login").get_data(as_text=True)
                t = re.search(r'name="_csrf" value="([^"]+)"', h).group(1)
                cli.post("/login", data={"_csrf": t, "senha": "senha-forte-1"})
                for _ in range(10):
                    h = cli.get("/mov?item=1").get_data(as_text=True)
                    campos = dict(re.findall(r'name="(_csrf|_uso)" value="([^"]+)"', h)[:2])
                    r = cli.post("/mov/registrar", data=dict(campos, tipo="saida", item="1", qtd="1"),
                                 follow_redirects=True).get_data(as_text=True)
                    (ok if "Saída registrada" in r else erros).append(r)

            ts = [threading.Thread(target=aparelho) for _ in range(2)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
            c = conectar(banco)
            saldo = Almoxarifado(c).item("FN-1").saldo
            c.close()
            self.assertEqual(len(ok), 4)
            self.assertEqual(saldo, 0)
            self.assertTrue(all("Saldo insuficiente" in e for e in erros))
