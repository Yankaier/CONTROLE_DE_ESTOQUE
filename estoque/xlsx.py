"""Leitura e gravação da planilha CONTROLE DE ESTOQUES 2.0 (.xlsx).

Faz as mesmas alterações que o app "Movimentação do Almoxarifado" faz, editando o
XML de dentro do arquivo (sem abrir e salvar com uma biblioteca de planilhas), para
não perder fórmulas, tabelas, filtros e formatação:

- aba **Movimentação** (tabela "movimentação", cabeçalho na linha 4, dados a partir da 5):
  A Data · B Movimentação · C Estante · D PT · E Caixa · F SKU · G Descrição ·
  H Lote/serial · I Unid. (com sinal) · J Solicitante · K Área · L OS · M NF · N Observação
- aba **Contagem** (itens a partir da linha 5): B Estante · C PT · D Caixa · E SKU ·
  F Descrição · BQ/BR/BS fórmulas de entradas, saídas e saldo
- aba **DESCARTES** (cabeçalho na linha 1), reescrita inteira a cada envio
"""

import io
import re
import zipfile
from datetime import date, timedelta
from xml.sax.saxutils import escape as _esc

ESTILOS_MOV = [24, 25, 26, 27, 26, 26, 26, 28, 29, 26, 26, 26, 26, 26]
COLS_MOV = "ABCDEFGHIJKLMN"
DESC_CAB = ["Nº", "Data", "SKU", "Material", "Serial / Lote", "Qtd", "Local de origem", "Motivo",
            "Destino", "Responsável", "Autorizado por", "Documento / Laudo", "Baixa no estoque", "Observação"]
DESC_LARG = [9, 11, 9, 38, 30, 6, 22, 16, 22, 18, 18, 20, 26, 40]
DESC_ESTILO = [26, 24, 26, 26, 28, 26, 26, 26, 26, 26, 26, 26, 26, 26]
_RE_LINHA = re.compile(r'<row r="(\d+)"((?:[^>/]|/(?!>))*)(?:/>|>([\s\S]*?)</row>)')


class ErroPlanilha(Exception):
    pass


def esc(v) -> str:
    return _esc(str(v), {'"': "&quot;"})


def unesc(s: str) -> str:
    return (s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
            .replace("&apos;", "'").replace("&amp;", "&"))


def serial_excel(iso: str) -> int:
    return (date.fromisoformat(iso) - date(1899, 12, 30)).days


def data_de_celula(valor: str) -> str:
    v = str(valor).strip()
    if re.fullmatch(r"\d+(\.\d+)?", v):
        return (date(1899, 12, 30) + timedelta(days=int(float(v)))).isoformat()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v)
    if m:
        d, mth, y = map(int, m.groups())
        return date(y + 2000 if y < 100 else y, mth, d).isoformat()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    return m.group(0) if m else ""


def numero_ou_texto(v):
    """'3' vira número 3 (como na planilha); '03', 'PT2' e '-' ficam texto."""
    s = str(v if v is not None else "").strip()
    return int(s) if re.fullmatch(r"0|[1-9]\d{0,14}", s) else s


def normal(v) -> str:
    s = str(v if v is not None else "").strip()
    if re.fullmatch(r"-?\d+\.0+", s):
        s = s.split(".")[0]
    return s


def chave(estante, pt, caixa, sku, desc) -> str:
    import unicodedata
    return "|".join(unicodedata.normalize("NFC", normal(x)).upper() for x in (estante, pt, caixa, sku, desc))


def _col_num(c: str) -> int:
    n = 0
    for ch in c:
        n = n * 26 + ord(ch) - 64
    return n


def _col_nome(n: int) -> str:
    s = ""
    while n > 0:
        n, m = divmod(n - 1, 26)
        s = chr(65 + m) + s
    return s


ENT = [_col_nome(n) for n in range(_col_num("H"), _col_num("BN") + 1, 2)]
SAI = [_col_nome(n + 1) for n in range(_col_num("H"), _col_num("BN") + 1, 2)]


def _celula(col: str, r: int, valor, estilo) -> str:
    ref, s = f"{col}{r}", f' s="{estilo}"' if estilo is not None else ""
    if valor is None or valor == "":
        return f'<c r="{ref}"{s}/>'
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return f'<c r="{ref}"{s}><v>{valor}</v></c>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{esc(valor)}</t></is></c>'


def _trocar_celula(corpo: str, col: str, r: int, valor) -> str:
    """Troca o valor de uma célula mantendo o estilo; cria a célula se não existir."""
    padrao = re.compile(rf'<c r="{col}{r}"([^>]*?)(?:/>|>[\s\S]*?</c>)')
    m = padrao.search(corpo)
    estilo = None
    if m:
        se = re.search(r's="(\d+)"', m.group(1))
        estilo = se.group(1) if se else None
        return corpo[:m.start()] + _celula(col, r, valor, estilo) + corpo[m.end():]
    # insere na ordem das colunas
    alvo = _col_num(col)
    for c in re.finditer(r'<c r="([A-Z]+)\d+"', corpo):
        if _col_num(c.group(1)) > alvo:
            return corpo[:c.start()] + _celula(col, r, valor, None) + corpo[c.start():]
    return corpo + _celula(col, r, valor, None)


class Planilha:
    """O arquivo .xlsx aberto em memória."""

    def __init__(self, dados: bytes):
        try:
            zf = zipfile.ZipFile(io.BytesIO(dados))
        except zipfile.BadZipFile:
            raise ErroPlanilha("O arquivo não é uma planilha .xlsx válida.") from None
        self._infos = zf.infolist()
        self._dados = {i.filename: zf.read(i.filename) for i in self._infos}
        self._sst = None

    # ---------- acesso ----------
    def texto(self, nome: str) -> str:
        return self._dados[nome].decode("utf-8")

    def gravar(self, nome: str, texto: str) -> None:
        self._dados[nome] = texto.encode("utf-8")

    def existe(self, nome: str) -> bool:
        return nome in self._dados

    def bytes(self) -> bytes:
        saida = io.BytesIO()
        with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as zf:
            for info in self._infos:
                novo = zipfile.ZipInfo(info.filename, info.date_time)
                novo.compress_type = zipfile.ZIP_DEFLATED
                novo.external_attr = info.external_attr
                zf.writestr(novo, self._dados[info.filename])
        return saida.getvalue()

    def caminho_aba(self, nome: str, padrao: str | None = None) -> tuple[str, int] | None:
        wb = self.texto("xl/workbook.xml")
        rels = self.texto("xl/_rels/workbook.xml.rels")
        abas = re.findall(r'<sheet [^>]*?name="([^"]+)"[^>]*?r:id="([^"]+)"', wb)
        import unicodedata
        alvo = unicodedata.normalize("NFC", nome).lower()
        for idx, (n, rid) in enumerate(abas):
            if unicodedata.normalize("NFC", unesc(n)).lower() == alvo:
                m = re.search(rf'<Relationship [^>]*?Id="{rid}"[^>]*?Target="([^"]+)"', rels) or \
                    re.search(rf'<Relationship [^>]*?Target="([^"]+)"[^>]*?Id="{rid}"', rels)
                if m:
                    return "xl/" + re.sub(r"^/?xl/", "", m.group(1)), idx
        if padrao and self.existe(padrao):
            return padrao, 0
        return None

    def strings(self) -> list[str]:
        if self._sst is None:
            if not self.existe("xl/sharedStrings.xml"):
                self._sst = []
            else:
                t = self.texto("xl/sharedStrings.xml")
                self._sst = [unesc("".join(re.findall(r"<t[^>]*>([\s\S]*?)</t>", si)))
                             for si in re.findall(r"<si>([\s\S]*?)</si>", t)]
        return self._sst

    def valor(self, corpo: str, ref: str) -> str:
        m = re.search(rf'<c r="{ref}"([^>]*?)(?:/>|>([\s\S]*?)</c>)', corpo)
        if not m or not m.group(2):
            return ""
        attrs, dentro = m.group(1), m.group(2)
        if 't="s"' in attrs:
            v = re.search(r"<v>([^<]*)</v>", dentro)
            sst = self.strings()
            return sst[int(v.group(1))] if v and int(v.group(1)) < len(sst) else ""
        if 't="inlineStr"' in attrs:
            return unesc("".join(re.findall(r"<t[^>]*>([\s\S]*?)</t>", dentro)))
        v = re.search(r"<v>([^<]*)</v>", dentro)
        return normal(unesc(v.group(1))) if v else ""

    def _aba(self, nome, padrao):
        achado = self.caminho_aba(nome, padrao)
        if not achado:
            raise ErroPlanilha(f"A planilha não tem a aba {nome}.")
        return achado

    # ---------- leitura ----------
    def ler(self) -> dict:
        itens, movs, descartes = [], [], []
        cont, _ = self._aba("Contagem", "xl/worksheets/sheet1.xml")
        for m in _RE_LINHA.finditer(self.texto(cont)):
            r, corpo = int(m.group(1)), m.group(3) or ""
            if r < 5 or not corpo:
                continue
            v = lambda c: self.valor(corpo, f"{c}{r}")
            if not v("F"):
                continue
            itens.append({"linha": r, "estante": v("B"), "pt": v("C"), "caixa": v("D"), "sku": v("E"),
                          "descricao": v("F"), "saldo_planilha": v("BS")})
        mov, _ = self._aba("Movimentação", "xl/worksheets/sheet2.xml")
        for m in _RE_LINHA.finditer(self.texto(mov)):
            r, corpo = int(m.group(1)), m.group(3) or ""
            if r < 5 or not corpo:
                continue
            v = lambda c: self.valor(corpo, f"{c}{r}")
            if not v("A") or not v("G"):
                continue
            movs.append({"linha": r, "data": data_de_celula(v("A")), "movim": v("B"), "estante": v("C"),
                         "pt": v("D"), "caixa": v("E"), "sku": v("F"), "descricao": v("G"), "lote": v("H"),
                         "unid": v("I"), "solicitante": v("J"), "area": v("K"), "os": v("L"), "nf": v("M"),
                         "obs": v("N")})
        achado = self.caminho_aba("DESCARTES")
        if achado:
            for m in _RE_LINHA.finditer(self.texto(achado[0])):
                r, corpo = int(m.group(1)), m.group(3) or ""
                if r < 2 or not corpo:
                    continue
                vals = [self.valor(corpo, f"{_col_nome(i + 1)}{r}") for i in range(14)]
                if not vals[0] or not vals[3]:
                    continue
                descartes.append(dict(zip(
                    ["num", "data", "sku", "material", "serial", "qtd", "origem", "motivo", "destino",
                     "responsavel", "autorizado", "documento", "baixa", "obs"], vals)))
                descartes[-1]["data"] = data_de_celula(descartes[-1]["data"])
        return {"itens": itens, "movimentos": movs, "descartes": descartes}

    # ---------- gravação ----------
    def acrescentar_movimentos(self, linhas: list[list]) -> list[int]:
        """linhas: [dataISO, movim, estante, pt, caixa, sku, desc, lote, unid, solic, area, os, nf, obs]."""
        if not linhas:
            return []
        aba, _ = self._aba("Movimentação", "xl/worksheets/sheet2.xml")
        tabela = None
        for nome in self._dados:
            if nome.startswith("xl/tables/") and nome.endswith(".xml"):
                t = self.texto(nome)
                if re.search(r'name="movimenta[çc][ãa]o"', t, re.I) or re.search(r'ref="A4:N\d+"', t):
                    tabela = nome
                    break
        sx = self.texto(aba)
        ultima = 4
        for m in _RE_LINHA.finditer(sx):
            r = int(m.group(1))
            if r >= 5 and re.search(rf'<c r="A{r}"[^>]*?>[\s\S]*?(<v>|<is>)', m.group(3) or ""):
                ultima = r
        usadas, r = [], ultima + 1
        for vals in linhas:
            vals = list(vals)
            vals[0] = serial_excel(vals[0])
            for i in (2, 3, 4, 5):
                vals[i] = numero_ou_texto(vals[i])
            xml = (f'<row r="{r}" spans="1:14">' +
                   "".join(_celula(COLS_MOV[i], r, v, ESTILOS_MOV[i]) for i, v in enumerate(vals)) + "</row>")
            existente = re.compile(rf'<row r="{r}"(?:(?:[^>/]|/(?!>))*)(?:/>|>[\s\S]*?</row>)')
            if existente.search(sx):
                sx = existente.sub(lambda _: xml, sx, count=1)
            else:
                sx = sx.replace("</sheetData>", xml + "</sheetData>")
            usadas.append(r)
            r += 1
        fim = usadas[-1]
        if tabela:
            tx = self.texto(tabela)
            m = re.search(r'ref="A4:N(\d+)"', tx)
            if m and fim > int(m.group(1)):
                self.gravar(tabela, re.sub(r'ref="A4:N\d+"', f'ref="A4:N{fim}"', tx))
                sx = re.sub(r'<dimension ref="([A-Z]+\d+):N\d+"/>', rf'<dimension ref="\g<1>:N{fim}"/>', sx)
                sx = re.sub(r'sqref="B5:B\d+"', f'sqref="B5:B{fim}"', sx, count=1)
        self.gravar(aba, sx)
        self._recalcular_ao_abrir()
        return usadas

    def acrescentar_itens(self, itens: list[dict]) -> list[int]:
        """Copia a última linha de item da Contagem (com fórmulas) para cada item novo."""
        if not itens:
            return []
        aba, idx = self._aba("Contagem", "xl/worksheets/sheet1.xml")
        sx = self.texto(aba)
        modelo_r = 4
        for m in _RE_LINHA.finditer(sx):
            r = int(m.group(1))
            if r >= 5 and m.group(3) and re.search(rf'<c r="F{r}"[^>]*?>[\s\S]*?(<v>|<is>)', m.group(3)):
                modelo_r = r
        mm = re.search(rf'<row r="{modelo_r}"[^>]*>[\s\S]*?</row>', sx)
        if not mm:
            raise ErroPlanilha("Não encontrei a última linha de itens da aba Contagem.")
        modelo = mm.group(0)
        usadas, novo_xml, r = [], "", modelo_r + 1
        for it in itens:
            x = re.sub(rf'<row r="{modelo_r}"', f'<row r="{r}"', modelo, count=1)
            x = re.sub(rf'r="([A-Z]+){modelo_r}"', rf'r="\g<1>{r}"', x)
            x = re.sub(rf"Contagem!([A-Z]+){modelo_r}(?![0-9])", rf"Contagem!\g<1>{r}", x)
            x = re.sub(r"(</f>)<v>[^<]*</v>", r"\1", x)
            for col, campo in zip("BCDEF", ("estante", "pt", "caixa", "sku", "descricao")):
                valor = it[campo] if campo == "descricao" else numero_ou_texto(it[campo])
                x = _trocar_celula(x, col, r, valor)
            for col, formula in (("BQ", "+".join([f"G{r}"] + [f"{c}{r}" for c in ENT])),
                                 ("BR", "+".join(f"{c}{r}" for c in SAI)), ("BS", f"BQ{r}+BR{r}")):
                pm = re.search(rf'<c r="{col}{r}"([^>]*?)(?:/>|>[\s\S]*?</c>)', x)
                if pm:
                    st = re.search(r's="(\d+)"', pm.group(1))
                    cel = f'<c r="{col}{r}"{f" s={chr(34)}{st.group(1)}{chr(34)}" if st else ""}><f>{formula}</f></c>'
                    x = x[:pm.start()] + cel + x[pm.end():]
            novo_xml += x
            usadas.append(r)
            r += 1
        fim = r - 1
        sx = sx.replace(modelo, modelo + novo_xml, 1)

        def subir(texto, padrao, col):
            def f(m):
                return m.group(0).replace(f"{col}{m.group(2)}", f"{col}{fim}") if int(m.group(2)) < fim else m.group(0)
            return re.sub(padrao, f, texto, count=1)
        sx = subir(sx, r'<dimension ref="([A-Z]+\d+):BS(\d+)"', "BS")
        sx = subir(sx, r'<autoFilter ref="(B4):BW(\d+)"', "BW")
        sx = subir(sx, r'sqref="(H5):BO(\d+)"', "BO")
        self.gravar(aba, sx)
        wx = self.texto("xl/workbook.xml")
        wx2 = re.sub(rf'(<definedName name="_xlnm\._FilterDatabase" localSheetId="{idx}"[^>]*>Contagem!\$B\$4:\$BW\$)(\d+)',
                     lambda m: m.group(1) + str(fim) if int(m.group(2)) < fim else m.group(0), wx)
        if wx2 != wx:
            self.gravar("xl/workbook.xml", wx2)
        self._recalcular_ao_abrir()
        return usadas

    def corrigir_cadastros(self, correcoes: list[tuple[dict, dict]]) -> tuple[int, int]:
        """correcoes: [(como está na planilha, como deve ficar)] com estante/pt/caixa/sku/descricao."""
        if not correcoes:
            return 0, 0
        mapa = {chave(*(de[k] for k in ("estante", "pt", "caixa", "sku", "descricao"))): para for de, para in correcoes}
        cont = [0, 0]

        def aplicar(aba, cols, i):
            sx = self.texto(aba)

            def f(m):
                r, corpo = int(m.group(1)), m.group(3)
                if r < 5 or not corpo:
                    return m.group(0)
                para = mapa.get(chave(*(self.valor(corpo, f"{c}{r}") for c in cols)))
                if not para:
                    return m.group(0)
                cont[i] += 1
                for c, campo in zip(cols, ("estante", "pt", "caixa", "sku", "descricao")):
                    corpo = _trocar_celula(corpo, c, r, para[campo] if campo == "descricao" else numero_ou_texto(para[campo]))
                return f'<row r="{m.group(1)}"{m.group(2)}>{corpo}</row>'
            self.gravar(aba, _RE_LINHA.sub(f, sx))
        aplicar(self._aba("Contagem", "xl/worksheets/sheet1.xml")[0], "BCDEF", 0)
        aplicar(self._aba("Movimentação", "xl/worksheets/sheet2.xml")[0], "CDEFG", 1)
        self._recalcular_ao_abrir()
        return cont[0], cont[1]

    def escrever_descartes(self, registros: list[dict]) -> None:
        achado = self.caminho_aba("DESCARTES")
        if not achado:
            raise ErroPlanilha("A planilha não tem a aba DESCARTES.")
        aba, idx = achado
        antigo = self.texto(aba)
        cabeca = re.match(r"^[\s\S]*?<worksheet[^>]*>", antigo).group(0)
        n = len(registros) + 1
        linhas = ['<row r="1" spans="1:14">' + "".join(_celula(_col_nome(i + 1), 1, h, 23) for i, h in enumerate(DESC_CAB)) + "</row>"]
        for k, d in enumerate(registros):
            r = k + 2
            vals = [d["num"], serial_excel(d["data"]) if d.get("data") else "-", numero_ou_texto(d.get("sku") or "-"),
                    d["material"], d.get("serial") or "-", int(d.get("qtd") or 0), d.get("origem") or "-",
                    d.get("motivo") or "-", d.get("destino") or "-", d.get("responsavel") or "-",
                    d.get("autorizado") or "-", d.get("documento") or "-", d.get("baixa") or "-", d.get("obs") or ""]
            linhas.append(f'<row r="{r}" spans="1:14">' + "".join(
                _celula(_col_nome(i + 1), r, v, DESC_ESTILO[i]) for i, v in enumerate(vals)) + "</row>")
        cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(DESC_LARG))
        xml = (f'{cabeca}<dimension ref="A1:N{n}"/><sheetViews><sheetView showGridLines="0" workbookViewId="0">'
               '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
               '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>'
               '<sheetFormatPr defaultRowHeight="14.4"/>'
               f'<cols>{cols}</cols><sheetData>{"".join(linhas)}</sheetData><autoFilter ref="A1:N{n}"/>'
               '<pageMargins left="0.511811024" right="0.511811024" top="0.787401575" bottom="0.787401575" '
               'header="0.31496062" footer="0.31496062"/></worksheet>')
        self.gravar(aba, xml)
        wx = self.texto("xl/workbook.xml")
        dn = f'<definedName name="_xlnm._FilterDatabase" localSheetId="{idx}" hidden="1">DESCARTES!$A$1:$N${n}</definedName>'
        padrao = re.compile(rf'<definedName name="_xlnm\._FilterDatabase" localSheetId="{idx}"[^>]*>[^<]*</definedName>')
        if padrao.search(wx):
            wx = padrao.sub(lambda _: dn, wx)
        elif "<definedNames>" in wx:
            wx = wx.replace("<definedNames>", "<definedNames>" + dn)
        else:
            wx = wx.replace("</sheets>", "</sheets><definedNames>" + dn + "</definedNames>")
        self.gravar("xl/workbook.xml", wx)

    def _recalcular_ao_abrir(self) -> None:
        wx = self.texto("xl/workbook.xml")
        if "fullCalcOnLoad=" not in wx:
            novo = re.sub(r"<calcPr([^>]*?)/>", r'<calcPr\1 fullCalcOnLoad="1"/>', wx)
            if novo == wx:
                marca = next((m for m in ("<oleSize", "<customWorkbookViews", "<pivotCaches", "<smartTagPr",
                                          "<smartTagTypes", "<webPublishing", "<fileRecoveryPr",
                                          "<webPublishObjects", "<extLst", "</workbook>") if m in wx))
                novo = wx.replace(marca, '<calcPr fullCalcOnLoad="1"/>' + marca, 1)
            self.gravar("xl/workbook.xml", novo)
