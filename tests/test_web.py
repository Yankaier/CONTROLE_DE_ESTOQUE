import io
import re
import tempfile
import unittest
from pathlib import Path

try:
    from estoque.web import criar_app
except ImportError:          # Flask não instalado: pula os testes da versão web
    criar_app = None

from estoque.xlsx import Planilha
from tests.planilha_exemplo import gerar


@unittest.skipIf(criar_app is None, "Flask não instalado")
class TestWeb(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = Path(self.dir.name)
        self.xlsx = d / "CONTROLE DE ESTOQUES 2.0.xlsx"
        self.xlsx.write_bytes(gerar())
        self.app = criar_app(str(d / "estoque.db"))
        self.c = self.app.test_client()

    def csrf(self, url="/"):
        html = self.c.get(url).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def post(self, url, origem=None, **dados):
        dados["_csrf"] = self.csrf(origem or url)
        return self.c.post(url, data=dados, follow_redirects=True)

    def entrar(self):
        self.post("/primeiro-acesso", senha="senha-forte-1", senha2="senha-forte-1", nome="Luis")

    def test_tudo_pede_senha(self):
        self.assertIn("/primeiro-acesso", self.c.get("/").headers["Location"])
        self.entrar()
        self.c.post("/sair", data={"_csrf": self.csrf()})
        for url in ("/", "/mov", "/pedidos", "/inventario", "/descarte", "/dia", "/terminais",
                    "/relatorios", "/pessoas", "/planilha", "/planilha/baixar"):
            r = self.c.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])
        r = self.post("/login", senha="errada")
        self.assertIn("Senha incorreta", r.get_data(as_text=True))
        r = self.post("/login", senha="senha-forte-1")
        self.assertIn("O que você vai fazer agora?", r.get_data(as_text=True))

    def test_post_sem_csrf_recusado(self):
        self.entrar()
        self.assertEqual(self.c.post("/pessoas", data={"nome": "X"}).status_code, 400)

    def test_acesso_de_fora_bloqueado(self):
        r = self.c.get("/login", environ_base={"REMOTE_ADDR": "192.168.0.50"})
        self.assertEqual(r.status_code, 403)

    def test_fluxo_completo_com_planilha(self):
        self.entrar()
        r = self.post("/planilha", acao="config", caminho=str(self.xlsx), auto="1")
        txt = r.get_data(as_text=True)
        self.assertIn("Configuração salva", txt)
        self.assertIn("Atualizado da planilha: 4 linha(s) nova(s)", txt)      # leu a planilha sozinho
        r = self.post("/planilha", acao="trazer")
        self.assertIn("0 linha(s) nova(s)", r.get_data(as_text=True))           # nada em dobro
        for url in ("/", "/mov", "/mov?q=cabo", "/mov?item=1", "/mov?tipo=entrada&item=2", "/mov/nf", "/itens/novo",
                    "/itens/1/corrigir", "/pedidos", "/inventario?estante=3", "/descarte", "/dia", "/terminais",
                    "/relatorios", "/pessoas", "/planilha", "/senha", "/mov?f=minimo"):
            self.assertEqual(self.c.get(url).status_code, 200, url)
        # bipar serial seleciona o item com o serial marcado
        r = self.c.get("/mov?q=818ez001")
        self.assertIn("item=2", r.headers["Location"])
        # saída com serial: envio automático grava na planilha
        r = self.post("/mov/registrar", origem="/mov?item=2", tipo="saida", item="2", serial="818EZ001", qtd="1",
                      solic="luan", area="Montagem", data="2026-11-10")
        txt = r.get_data(as_text=True)
        self.assertIn("Saída registrada", txt)
        self.assertIn("Lançado na planilha", txt)
        mov = Planilha(self.xlsx.read_bytes()).ler()["movimentos"]
        self.assertEqual((mov[-1]["lote"], mov[-1]["unid"], mov[-1]["solicitante"]), ("818EZ001", "-1", "LUAN"))
        # NF com dois itens
        self.c.post("/mov/nf", data={"_csrf": self.csrf("/mov/nf"), "fornecedor": "Forn X", "nf": "123",
                                     "data": "2026-11-10", "item": ["#1 · CABO", "#2 · LEITOR"], "qtd": ["5", ""],
                                     "seriais": ["", "NOVO1\nNOVO2"]})
        self.assertEqual(len(Planilha(self.xlsx.read_bytes()).ler()["movimentos"]), 8)
        # pedido e entrega
        self.c.post("/pedidos/novo", data={"_csrf": self.csrf("/pedidos"), "solicitante": "ana", "area": "Montagem",
                                           "item": ["#1 · CABO"], "qtd": ["2"]})
        r = self.post("/pedidos/P-001/entregar", origem="/pedidos")
        self.assertIn("Pedido P-001 entregue", r.get_data(as_text=True))
        # inventário, descarte, terminal, pessoa, item novo
        self.post("/inventario", origem="/inventario?estante=3", estante="3", c_1="5")
        self.post("/descarte", modo="estoque", item="#2 · LEITOR", qtd="1", seriais="NOVO1", motivo="queimado", resp="joao")
        r = self.post("/terminais", tipo="Entrada", serial="T-100", ck_3="Defeito")
        self.assertIn("1 defeito", r.get_data(as_text=True))
        self.post("/pessoas", nome="maria", area="Manutenção")
        r = self.post("/itens/novo", descricao="Fonte 12V", estante="5", pt="PT3", caixa="", sku="FN-9", qtd="4",
                      minimo="2", seriais="")
        self.assertIn("cadastrado", r.get_data(as_text=True))
        lido = Planilha(self.xlsx.read_bytes()).ler()
        self.assertEqual(lido["itens"][-1]["descricao"], "FONTE 12V")
        self.assertEqual(lido["descartes"][0]["num"], "D-0001")
        self.assertIn("Planilha em dia", self.c.get("/").get_data(as_text=True))
        self.assertEqual(self.c.get("/dia.csv?data=2026-11-10").status_code, 200)
        self.assertEqual(self.c.get("/planilha/baixar").status_code, 200)
        self.assertEqual(self.c.get("/relatorios/compras.csv").status_code, 200)

    def test_dados_apagar_exige_confirmacao_e_senha(self):
        self.entrar()
        self.post("/planilha", acao="config", caminho=str(self.xlsx))
        self.post("/planilha", acao="trazer")
        self.assertEqual(self.c.get("/dados").status_code, 200)
        r = self.post("/dados", acao="apagar", confirmacao="apagar", senha="errada")
        self.assertIn("Senha incorreta", r.get_data(as_text=True))
        r = self.post("/dados", acao="apagar", confirmacao="nao", senha="senha-forte-1")
        self.assertIn("digite APAGAR", r.get_data(as_text=True))
        self.assertIn("CABO DE REDE CAT6", self.c.get("/mov?q=cabo").get_data(as_text=True))
        r = self.post("/dados", acao="apagar", confirmacao="APAGAR", senha="senha-forte-1")
        txt = r.get_data(as_text=True)
        self.assertIn("Dados apagados (2 item(ns)", txt)
        self.assertIn("antes de apagar", txt)                       # cópia aparece na lista
        self.assertNotIn("CABO DE REDE CAT6", self.c.get("/mov?q=cabo").get_data(as_text=True))
        nome = re.search(r'name="nome" value="([^"]+)"', txt).group(1)
        self.assertEqual(self.c.get(f"/dados/copia/{nome}").status_code, 200)
        self.post("/dados", acao="restaurar", nome=nome, senha="senha-forte-1")
        self.assertIn("CABO DE REDE CAT6", self.c.get("/mov?q=cabo").get_data(as_text=True))

    def test_modo_teste_pela_tela(self):
        self.entrar()
        self.post("/planilha", acao="config", caminho=str(self.xlsx), auto="1")
        original = self.xlsx.read_bytes()
        r = self.c.post("/dados", data={"_csrf": self.csrf("/dados"), "acao": "iniciar_teste", "apagar": "1",
                                        "arquivo": (io.BytesIO(gerar()), "copia da nuvem.xlsx")},
                        content_type="multipart/form-data", follow_redirects=True)
        txt = r.get_data(as_text=True)
        self.assertIn("Modo teste ligado", txt)
        self.assertIn("Modo teste.", txt)                                # faixa em todas as telas
        r = self.post("/mov/registrar", origem="/mov?item=2", tipo="saida", item="2", serial="818EZ001", qtd="1")
        self.assertIn("Lançado na planilha", r.get_data(as_text=True))  # envio automático foi para o teste
        self.assertEqual(self.xlsx.read_bytes(), original)              # a real não mudou
        r = self.post("/dados", acao="encerrar_teste", apagar="1", trazer="1", senha="senha-forte-1")
        txt = r.get_data(as_text=True)
        self.assertIn("Teste encerrado. Planilha real conectada", txt)
        self.assertNotIn("Modo teste.", txt)
        self.assertEqual(self.xlsx.read_bytes(), original)

    def test_erro_de_regra_volta_com_mensagem(self):
        self.entrar()
        self.post("/planilha", acao="config", caminho=str(self.xlsx))
        self.post("/planilha", acao="trazer")
        r = self.post("/mov/registrar", origem="/mov?item=1", tipo="saida", item="1", qtd="999")
        self.assertIn("Saldo insuficiente", r.get_data(as_text=True))
