import json
import re
import ssl
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

try:
    from estoque.web import criar_app
except ImportError:
    criar_app = None

from tests.planilha_exemplo import gerar

FORA = {"REMOTE_ADDR": "192.168.0.77"}
HTTPS = "https://192.168.0.10:5443"


@unittest.skipIf(criar_app is None, "Flask não instalado")
class TestAparelhos(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = Path(self.dir.name)
        self.xlsx = d / "planilha.xlsx"
        self.xlsx.write_bytes(gerar())
        self.app = criar_app(str(d / "estoque.db"))
        self.rede = self.app.extensions["rede"]
        self.rede._srv = object()          # finge que o servidor da rede está ligado (sem abrir porta)
        self.rede.ip = "192.168.0.10"
        self.addCleanup(setattr, self.rede, "_srv", None)
        self.nb = self.app.test_client()   # o notebook
        self.cel = self.app.test_client()  # o celular
        self._post_nb("/primeiro-acesso", senha="senha-forte-1", senha2="senha-forte-1", nome="Luis")
        self._post_nb("/planilha", acao="config", caminho=str(self.xlsx))

    # ----- ajudantes -----
    def _csrf(self, cliente, url, **kw):
        html = cliente.get(url, **kw).get_data(as_text=True)
        return {k: v for k, v in re.findall(r'name="(_csrf|_uso)" value="([^"]+)"', html)[:2]}

    def _post_nb(self, url, origem=None, **dados):
        dados.update(self._csrf(self.nb, origem or url))
        return self.nb.post(url, data=dados, follow_redirects=True)

    def _get_cel(self, url):
        return self.cel.get(url, base_url=HTTPS, environ_base=FORA)

    def _post_cel(self, url, origem, **dados):
        dados.update(self._csrf(self.cel, origem, base_url=HTTPS, environ_base=FORA))
        return self.cel.post(url, data=dados, base_url=HTTPS, environ_base=FORA, follow_redirects=True)

    def _gerar_link(self):
        self._post_nb("/aparelhos", acao="conectar")
        html = self.nb.get("/aparelhos?qr=1").get_data(as_text=True)
        self.assertIn("<svg", html)
        return re.search(r"https://192\.168\.0\.10:\d+(/parear/[\w-]+)", html).group(1)

    def _parear_e_entrar(self, nome="Celular do Luis"):
        caminho = self._gerar_link()
        self.assertEqual(self._get_cel(caminho).status_code, 200)
        self._post_cel(caminho, caminho, nome=nome)
        return self._post_cel("/login", "/login", senha="senha-forte-1")

    # ----- testes -----
    def test_celular_sem_https_ou_com_rede_desligada_e_bloqueado(self):
        self.assertEqual(self.cel.get("/login", environ_base=FORA).status_code, 403)       # http
        self.rede._srv = None
        self.assertEqual(self._get_cel("/login").status_code, 403)                         # rede desligada

    def test_aparelho_desconhecido_nao_entra_nem_com_senha(self):
        r = self._get_cel("/login")
        self.assertEqual(r.status_code, 403)
        self.assertIn("não está autorizado", r.get_data(as_text=True))
        r = self.cel.post("/login", data={"senha": "senha-forte-1"}, base_url=HTTPS, environ_base=FORA)
        self.assertEqual(r.status_code, 403)

    def test_parear_entrar_registrar_e_ver_origem(self):
        r = self._parear_e_entrar()
        self.assertIn("O que você vai fazer agora?", r.get_data(as_text=True))
        cookie = self.cel.get_cookie("estoque_aparelho", domain="192.168.0.10")
        self.assertTrue(cookie.secure and cookie.http_only)
        r = self._post_cel("/mov/registrar", "/mov?item=1", tipo="saida", item="1", qtd="2", solic="ana")
        self.assertIn("Saída registrada", r.get_data(as_text=True))
        html = self.nb.get("/mov").get_data(as_text=True)
        self.assertIn("Celular do Luis", html)                     # notebook vê quem registrou
        self.assertIn("Celular do Luis", self.nb.get("/aparelhos").get_data(as_text=True))

    def test_qr_code_serve_uma_vez(self):
        caminho = self._gerar_link()
        self._post_cel(caminho, caminho, nome="A")
        outro = self.app.test_client()
        r = outro.get(caminho, base_url=HTTPS, environ_base={"REMOTE_ADDR": "192.168.0.99"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("já foi usado", r.get_data(as_text=True))

    def test_desconectar_aparelho_tira_o_acesso(self):
        self._parear_e_entrar()
        html = self.nb.get("/aparelhos").get_data(as_text=True)
        aid = re.search(r'name="acao" value="revogar"><input type="hidden" name="id" value="(\d+)"', html).group(1)
        self._post_nb("/aparelhos", acao="revogar", id=aid)
        self.assertEqual(self._get_cel("/mov").status_code, 403)

    def test_celular_nao_apaga_nem_troca_planilha(self):
        self._parear_e_entrar()
        self.assertEqual(self._get_cel("/dados").status_code, 403)
        self.assertEqual(self._get_cel("/aparelhos").status_code, 403)
        self.assertNotIn('href="/dados"', self._get_cel("/").get_data(as_text=True))
        r = self._post_cel("/planilha", "/planilha", acao="config", caminho="/etc/passwd")
        self.assertIn("só pode ser trocada ou configurada no próprio notebook", r.get_data(as_text=True))

    def test_envio_repetido_nao_registra_duas_vezes(self):
        dados = self._csrf(self.nb, "/mov?item=1")
        dados.update(tipo="saida", item="1", qtd="1")
        self.nb.post("/mov/registrar", data=dados)
        r = self.nb.post("/mov/registrar", data=dados, follow_redirects=True)
        self.assertIn("já tinha sido enviado", r.get_data(as_text=True))
        html = self.nb.get("/dia").get_data(as_text=True)
        self.assertEqual(html.count('class="n qty-out">−1'), 1)     # uma linha só na tabela do dia


@unittest.skipIf(criar_app is None, "Flask não instalado")
class TestServidorHttps(unittest.TestCase):
    def test_servidor_https_de_verdade(self):
        with tempfile.TemporaryDirectory() as d:
            app = criar_app(str(Path(d) / "estoque.db"))
            rede = app.extensions["rede"]
            rede.porta, rede.host = 0, "127.0.0.1"
            rede.iniciar()
            try:
                self.assertTrue((Path(d) / "rede-cert.pem").is_file())
                ctx = ssl.create_default_context()
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                with urllib.request.urlopen(f"https://127.0.0.1:{rede.porta}/primeiro-acesso", context=ctx) as r:
                    self.assertEqual(r.status, 200)
                    self.assertIn("Secure", r.headers.get("Set-Cookie", ""))
                with self.assertRaises(OSError):                        # sem HTTPS a conexão é derrubada
                    urllib.request.urlopen(f"http://127.0.0.1:{rede.porta}/", timeout=3)
            finally:
                rede.parar()
