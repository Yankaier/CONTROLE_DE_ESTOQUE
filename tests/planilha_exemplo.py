"""Gera uma planilha .xlsx pequena com a mesma estrutura da CONTROLE DE ESTOQUES 2.0."""

import io
import zipfile

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" ' \
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _s(ref, idx, st=26):
    return f'<c r="{ref}" s="{st}" t="s"><v>{idx}</v></c>'


def _n(ref, v, st=26):
    return f'<c r="{ref}" s="{st}"><v>{v}</v></c>'


def gerar() -> bytes:
    strings = ["CABO DE REDE CAT6", "PT2", "CB-06", "Saldo Inicial", "CARGA INICIAL", "Estoque Inicial",
               "-", "LEITOR DE CARTÃO", "PT1", "LT-01", "818EZ001", "818EZ002", "Saída", "LUAN", "Montagem",
               "Descrição", "Estante"]
    sst = "".join(f"<si><t>{s}</t></si>" for s in strings)
    ent = "+".join(["G5"] + [f"{c}5" for c in ("H", "J", "L")])
    contagem = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {NS}>'
                '<dimension ref="B4:BS6"/><sheetData>'
                f'<row r="4">{_s("B4", 16)}{_s("F4", 15)}</row>'
                f'<row r="5">{_n("B5", 3)}{_s("C5", 1)}{_n("D5", 12)}{_s("E5", 2)}{_s("F5", 0)}<c r="G5" s="30"/>'
                f'<c r="H5" s="31"><f>SUMIFS(Movimentação!I:I,Movimentação!G:G,Contagem!F5)</f><v>10</v></c>'
                f'<c r="BQ5" s="32"><f>{ent}</f><v>10</v></c><c r="BR5" s="32"><f>I5</f><v>-6</v></c>'
                f'<c r="BS5" s="33"><f>BQ5+BR5</f><v>4</v></c></row>'
                f'<row r="6">{_n("B6", 1)}{_s("C6", 8)}{_s("D6", 6)}{_s("E6", 9)}{_s("F6", 7)}<c r="G6" s="30"/>'
                f'<c r="H6" s="31"><f>SUMIFS(Movimentação!I:I,Movimentação!G:G,Contagem!F6)</f><v>2</v></c>'
                f'<c r="BQ6" s="32"><f>G6+H6</f><v>2</v></c><c r="BR6" s="32"><f>I6</f><v>0</v></c>'
                f'<c r="BS6" s="33"><f>BQ6+BR6</f><v>2</v></c></row>'
                '</sheetData><autoFilter ref="B4:BW6"/></worksheet>')

    def mov(r, data, movim, est, pt, cx, sku, desc, lote, unid, sol, area):
        return (f'<row r="{r}">{_n(f"A{r}", data, 24)}{_s(f"B{r}", movim)}{_n(f"C{r}", est)}{_s(f"D{r}", pt)}'
                f'{(_n(f"E{r}", cx) if isinstance(cx, int) and cx > 6 else _s(f"E{r}", cx))}{_s(f"F{r}", sku)}'
                f'{_s(f"G{r}", desc)}{_s(f"H{r}", lote)}{_n(f"I{r}", unid)}{_s(f"J{r}", sol)}{_s(f"K{r}", area)}'
                f'<c r="L{r}" s="26" t="inlineStr"><is><t>0000/00</t></is></c>{_s(f"M{r}", 6)}<c r="N{r}" s="26"/></row>')
    movimentacao = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {NS}>'
                    '<dimension ref="A4:N9"/><sheetData><row r="4"><c r="A4" t="inlineStr"><is><t>Data</t></is></c></row>'
                    + mov(5, 46000, 3, 3, 1, 12, 2, 0, 6, 10, 4, 5)
                    + mov(6, 46000, 3, 1, 8, 6, 9, 7, 10, 1, 4, 5)
                    + mov(7, 46000, 3, 1, 8, 6, 9, 7, 11, 1, 4, 5)
                    + mov(8, 46001, 12, 3, 1, 12, 2, 0, 6, -6, 13, 14)
                    + '<row r="9"><c r="A9" s="24"/><c r="B9" s="25"/></row>'
                    '</sheetData><dataValidations count="1"><dataValidation type="list" sqref="B5:B9">'
                    '<formula1>"Entrada,Saída,Saldo Inicial"</formula1></dataValidation></dataValidations>'
                    '<tableParts count="1"><tablePart r:id="rId1"/></tableParts></worksheet>')
    tabela = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<table xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" id="1" name="movimentação" '
              'displayName="movimentação" ref="A4:N9"><autoFilter ref="A4:N9"/><tableColumns count="14">'
              + "".join(f'<tableColumn id="{i + 1}" name="C{i + 1}"/>' for i in range(14))
              + '</tableColumns></table>')
    descartes = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {NS}><sheetData>'
                 '<row r="1"><c r="A1" t="inlineStr"><is><t>Nº</t></is></c></row></sheetData></worksheet>')
    workbook = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {NS}><sheets>'
                '<sheet name="Contagem" sheetId="1" r:id="rId1"/><sheet name="Movimentação" sheetId="2" r:id="rId2"/>'
                '<sheet name="DESCARTES" sheetId="3" r:id="rId3"/></sheets><definedNames>'
                '<definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">Contagem!$B$4:$BW$6</definedName>'
                '</definedNames><calcPr calcId="191029"/></workbook>')
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
               f'<Relationship Id="rId2" Type="{rel}/worksheet" Target="worksheets/sheet2.xml"/>'
               f'<Relationship Id="rId3" Type="{rel}/worksheet" Target="worksheets/sheet3.xml"/>'
               f'<Relationship Id="rId4" Type="{rel}/sharedStrings" Target="sharedStrings.xml"/>'
               f'<Relationship Id="rId5" Type="{rel}/styles" Target="styles.xml"/>'
               '</Relationships>')
    s2_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               f'<Relationship Id="rId1" Type="{rel}/table" Target="../tables/table1.xml"/></Relationships>')
    ct = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          + "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in (1, 2, 3))
          + '<Override PartName="/xl/tables/table1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
          '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
          '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 '</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        z.writestr("xl/worksheets/sheet1.xml", contagem)
        z.writestr("xl/worksheets/sheet2.xml", movimentacao)
        z.writestr("xl/worksheets/_rels/sheet2.xml.rels", s2_rels)
        z.writestr("xl/worksheets/sheet3.xml", descartes)
        z.writestr("xl/tables/table1.xml", tabela)
        xfs = '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' * 40
        z.writestr("xl/styles.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   f'<cellXfs count="40">{xfs}</cellXfs></styleSheet>')
        z.writestr("xl/sharedStrings.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{sst}</sst>')
    return buf.getvalue()
