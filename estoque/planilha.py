"""Troca de dados com o app "Movimentação do Almoxarifado".

O app exporta, na aba "Movimento do dia", o botão "Baixar" que gera o arquivo
`Movimento do dia AAAA-MM-DD.csv` (separado por ponto e vírgula, com BOM, abre no
Excel). Este módulo lê esse arquivo para dentro do banco local e também gera um
arquivo no mesmo formato a partir do banco.
"""

import csv
import io
from datetime import datetime
from pathlib import Path

from .servico import Almoxarifado, ErroEstoque, _lista_seriais, _txt

CABECALHO = ["Data", "Hora", "Tipo", "Estante", "PT", "Caixa", "SKU", "Descrição", "Seriais",
             "Quantidade", "Solicitante / origem", "Área", "OS", "NF", "Observação", "Situação"]


def _data_iso(texto: str) -> str:
    texto = texto.strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    raise ErroEstoque(f"Data inválida: {texto!r}.")


def _tipo(lanc: dict) -> str:
    """Mesma classificação do app: Entrada, Saída, Cadastro ou Ajuste."""
    if lanc["movim"] == "Saldo Inicial":
        return "Cadastro (saldo inicial)" if lanc["area"] == "Estoque Inicial" else "Ajuste de contagem"
    if lanc["area"] == "Ajuste de inventário":
        return "Ajuste de contagem"
    return lanc["movim"]


def exportar_dia(alm: Almoxarifado, dia: str, destino: str | Path) -> int:
    linhas = alm.movimento_do_dia(dia)
    with open(destino, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";", lineterminator="\r\n")
        w.writerow(CABECALHO)
        for l in linhas:
            sinal = -1 if l["movim"] == "Saída" or l["qtd"] < 0 else 1
            data_br = datetime.fromisoformat(l["data"]).strftime("%d/%m/%Y")
            w.writerow([data_br, l["criado_em"][11:16], _tipo(l), l["estante"], l["pt"], l["caixa"],
                        l["sku"], l["descricao"], l["seriais"], sinal * abs(l["qtd"]), l["solicitante"],
                        l["area"], l["os"], l["nf"], l["obs"],
                        "Na planilha" if l["status"] == "lancado" else "Pendente"])
    return len(linhas)


def _achar_ou_criar_item(alm: Almoxarifado, r: dict) -> int:
    chave = tuple(_txt(r.get(k)) for k in ("Estante", "PT", "Caixa", "SKU")) + (
        _txt(r.get("Descrição"), "").upper(),)
    linha = alm.db.execute(
        "SELECT id FROM itens WHERE estante = ? AND pt = ? AND caixa = ? AND sku = ? AND descricao = ?",
        chave).fetchone()
    if linha:
        return linha[0]
    with alm.db:
        cur = alm.db.execute(
            "INSERT INTO itens (estante, pt, caixa, sku, descricao) VALUES (?, ?, ?, ?, ?)", chave)
    return cur.lastrowid


def importar_dia(alm: Almoxarifado, origem: str | Path) -> dict:
    """Importa o CSV do app. Linhas já importadas (mesma data, hora, item e quantidade) são puladas."""
    texto = Path(origem).read_text(encoding="utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto), delimiter=";")
    faltando = [c for c in ("Data", "Tipo", "Descrição", "Quantidade") if c not in (leitor.fieldnames or [])]
    if faltando:
        raise ErroEstoque(f"Arquivo não parece o 'Movimento do dia' do app (faltam: {', '.join(faltando)}).")
    resultado = {"importados": 0, "repetidos": 0, "itens_novos": 0}
    itens_antes = alm.db.execute("SELECT COUNT(*) FROM itens").fetchone()[0]
    for n, r in enumerate(leitor, start=2):
        if not _txt(r.get("Descrição"), ""):
            continue
        try:
            qtd = int(str(r["Quantidade"]).strip())
        except ValueError:
            raise ErroEstoque(f"Linha {n}: quantidade inválida {r['Quantidade']!r}.") from None
        data = _data_iso(r["Data"])
        hora = (r.get("Hora") or "00:00").strip() or "00:00"
        criado_em = f"{data} {hora}:00"[:19]
        tipo = r["Tipo"].strip()
        if tipo == "Entrada":
            movim, q = "Entrada", abs(qtd)
        elif tipo == "Saída":
            movim, q = "Saída", abs(qtd)
        else:  # Cadastro (saldo inicial) ou Ajuste de contagem
            movim, q = ("Saída", abs(qtd)) if (qtd < 0 and _lista_seriais(r.get("Seriais"))) else ("Saldo Inicial", qtd)
        item_id = _achar_ou_criar_item(alm, r)
        ja = alm.db.execute(
            "SELECT 1 FROM lancamentos WHERE criado_em = ? AND item_id = ? AND movim = ? AND qtd = ? AND obs = ?",
            (criado_em, item_id, movim, q, (r.get("Observação") or "").strip())).fetchone()
        if ja:
            resultado["repetidos"] += 1
            continue
        area = (r.get("Área") or "").strip()
        if tipo == "Cadastro (saldo inicial)" and not area:
            area = "Estoque Inicial"
        alm._lancar(item_id, movim, q, _lista_seriais(r.get("Seriais")),
                    solicitante=r.get("Solicitante / origem") or "", area=area, os=r.get("OS") or "",
                    nf=r.get("NF") or "", obs=r.get("Observação") or "", data=data, criado_em=criado_em,
                    status="lancado" if (r.get("Situação") or "").strip() == "Na planilha" else "pendente")
        resultado["importados"] += 1
    resultado["itens_novos"] = alm.db.execute("SELECT COUNT(*) FROM itens").fetchone()[0] - itens_antes
    return resultado
