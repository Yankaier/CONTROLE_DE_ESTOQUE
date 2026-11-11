"""Acesso pelo celular: um segundo servidor, só com HTTPS, ligado na rede Wi-Fi.

- O notebook continua abrindo pelo endereço local (http://127.0.0.1:5000), que só ele enxerga.
- O celular abre por https://IP-DO-NOTEBOOK:5443. A conexão é criptografada com um
  certificado gerado no próprio notebook (o celular avisa "não é particular" na primeira
  vez porque o certificado não vem de uma empresa certificadora; dá para conferir a
  "impressão digital" mostrada na tela Aparelhos).
- Pode ser ligado e desligado na tela Aparelhos sem fechar o app.
"""

import datetime as dt
import ipaddress
import socket
import threading
from pathlib import Path

PORTA_REDE = 5443


def ip_local() -> str:
    """IP deste computador na rede Wi-Fi (não envia nada pela rede)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def garantir_certificado(pasta: Path, ip: str) -> tuple[Path, Path, str]:
    """Cria (uma vez) o certificado HTTPS deste notebook. Refaz se o IP mudou."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    pasta.mkdir(parents=True, exist_ok=True)
    cert_p, chave_p = pasta / "rede-cert.pem", pasta / "rede-chave.pem"
    if cert_p.is_file() and chave_p.is_file():
        cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
        try:
            ips = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
        except x509.ExtensionNotFound:
            ips = []
        validade = cert.not_valid_after_utc
        if ipaddress.ip_address(ip) in ips and validade > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30):
            return cert_p, chave_p, impressao(cert)
    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Controle de Estoque - Almoxarifado")])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(minutes=5)).not_valid_after(agora + dt.timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                                                        x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(chave, hashes.SHA256()))
    chave_p.write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    try:
        chave_p.chmod(0o600)
    except OSError:
        pass
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_p, chave_p, impressao(cert)


def impressao(cert) -> str:
    from cryptography.hazmat.primitives import hashes
    h = cert.fingerprint(hashes.SHA256()).hex().upper()
    return " ".join(h[i:i + 4] for i in range(0, 24, 4))   # começo da impressão digital, fácil de conferir


class ServidorRede:
    """Liga/desliga o servidor HTTPS da rede dentro do mesmo app."""

    def __init__(self, app, pasta: Path, porta: int = PORTA_REDE, host: str = "0.0.0.0"):
        self.app, self.pasta, self.porta, self.host = app, Path(pasta), porta, host
        self._srv = None
        self._lock = threading.Lock()
        self.ip = ""
        self.impressao = ""
        self.erro = ""

    @property
    def ativo(self) -> bool:
        return self._srv is not None

    @property
    def endereco(self) -> str:
        return f"https://{self.ip}:{self.porta}" if self.ip else ""

    def iniciar(self) -> None:
        import ssl
        from werkzeug.serving import make_server
        with self._lock:
            if self._srv:
                return
            self.ip = ip_local()
            cert, chave, self.impressao = garantir_certificado(self.pasta, self.ip)
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.load_cert_chain(cert, chave)
            try:
                self._srv = make_server(self.host, self.porta, self.app, threaded=True, ssl_context=ctx)
            except OSError as e:
                self.erro = f"Não consegui abrir a porta {self.porta}: {e}"
                raise
            self.porta = self._srv.server_port
            self.erro = ""
            threading.Thread(target=self._srv.serve_forever, daemon=True, name="estoque-rede").start()

    def parar(self) -> None:
        with self._lock:
            if self._srv:
                srv, self._srv = self._srv, None
                srv.shutdown()
                srv.server_close()
