"""Sincroniza o banco local com a planilha CONTROLE DE ESTOQUES 2.0.

- `trazer_da_planilha`: lê a planilha e traz itens da Contagem, linhas novas da
  Movimentação e descartes. Pode rodar quantas vezes quiser: linhas já conhecidas
  (pelo número da linha) não entram de novo e os lançamentos feitos aqui são mantidos.
- `enviar_para_planilha`: grava na planilha tudo o que está pendente (lançamentos,
  itens novos, correções de cadastro e a aba DESCARTES), faz uma cópia de segurança
  do arquivo antes e só marca como lançado depois que o arquivo foi salvo.
"""

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .servico import CHAVE, Almoxarifado, _lista_seriais
from .xlsx import ErroPlanilha, Planilha, chave, normal


def _movim(texto: str) -> str | None:
    t = texto.strip().upper()
    if t.startswith("SALDO"):
        return "Saldo Inicial"
    if t.startswith("ENT"):
        return "Entrada"
    if t.startswith("SA"):
        return "Saída"
    return None


def _inteiro(v) -> int:
    try:
        return int(round(float(str(v).replace(",", "."))))
    except ValueError:
        return 0


def _indice_itens(alm: Almoxarifado) -> dict:
    return {chave(*(r[k] for k in CHAVE)): r["id"]
            for r in alm.db.execute("SELECT id, estante, pt, caixa, sku, descricao FROM itens")}


def trazer_da_planilha(alm: Almoxarifado, dados: bytes) -> dict:
    lido = Planilha(dados).ler()
    idx = _indice_itens(alm)
    res = {"itens_novos": 0, "movimentos": 0, "descartes": 0, "linhas_ignoradas": 0}

    def item_id(reg: dict, linha_contagem=None) -> int:
        k = chave(reg["estante"], reg["pt"], reg["caixa"], reg["sku"], reg["descricao"])
        if k in idx:
            if linha_contagem:
                alm.db.execute("UPDATE itens SET na_planilha = 1, linha_contagem = ? WHERE id = ?",
                               (linha_contagem, idx[k]))
            return idx[k]
        vals = [normal(reg[c]) or "-" for c in ("estante", "pt", "caixa", "sku")]
        cur = alm.db.execute(
            "INSERT INTO itens (estante, pt, caixa, sku, descricao, na_planilha, linha_contagem)"
            " VALUES (?, ?, ?, ?, ?, 1, ?)", (*vals, reg["descricao"].strip(), linha_contagem))
        idx[k] = cur.lastrowid
        res["itens_novos"] += 1
        return cur.lastrowid

    with alm.db:
        for it in lido["itens"]:
            item_id(it, it["linha"])
        conhecidas = set()
        for (linhas,) in alm.db.execute("SELECT linhas FROM lancamentos WHERE linhas != ''"):
            conhecidas.update(int(x) for x in linhas.split(",") if x.strip().isdigit())
        for m in lido["movimentos"]:
            if m["linha"] in conhecidas:
                continue
            movim, unid = _movim(m["movim"]), _inteiro(m["unid"])
            if not movim or not m["data"] or unid == 0:
                res["linhas_ignoradas"] += 1
                continue
            qtd = unid if movim == "Saldo Inicial" else abs(unid)
            limpa = lambda v: "" if normal(v) == "-" else normal(v)
            alm.db.execute(
                "INSERT INTO lancamentos (criado_em, data, movim, item_id, qtd, seriais, solicitante, area, os, nf,"
                " obs, status, linhas) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'lancado', ?)",
                (f"{m['data']} 00:00:{m['linha'] % 60:02d}", m["data"], movim, item_id(m), qtd,
                 ", ".join(_lista_seriais(m["lote"])), limpa(m["solicitante"]).upper(), limpa(m["area"]),
                 "" if m["os"] in ("0000/00", "-") else m["os"], limpa(m["nf"]), m["obs"], str(m["linha"])))
            pessoa = limpa(m["solicitante"]).upper()
            if pessoa and pessoa not in ("CARGA INICIAL",):
                alm.db.execute("INSERT OR IGNORE INTO pessoas (nome, area) VALUES (?, ?)", (pessoa, limpa(m["area"])))
            res["movimentos"] += 1
        existentes = {r[0] for r in alm.db.execute("SELECT num FROM descartes")}
        for d in lido["descartes"]:
            if d["num"] in existentes:
                continue
            limpa = lambda v: "" if normal(v) == "-" else normal(v)
            alm.db.execute(
                "INSERT INTO descartes (num, data, modo, sku, material, seriais, qtd, origem, motivo, destino,"
                " responsavel, autorizado, documento, baixa, obs) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (d["num"], d["data"] or datetime.now().date().isoformat(),
                 "estoque" if d["baixa"].startswith("Sim") else "fora", normal(d["sku"]) or "-", d["material"],
                 limpa(d["serial"]), max(1, _inteiro(d["qtd"])), limpa(d["origem"]), limpa(d["motivo"]),
                 limpa(d["destino"]), limpa(d["responsavel"]), limpa(d["autorizado"]), limpa(d["documento"]),
                 d["baixa"], d["obs"]))
            res["descartes"] += 1
    alm.recalcular_saldos()
    return res


def _linhas_do_lancamento(l: dict) -> list[list]:
    """Mesma regra do app: uma linha por serial e uma linha a mais para as unidades sem serial."""
    def base(lote, unid):
        return [l["data"], l["movim"], l["estante"], l["pt"], l["caixa"], l["sku"], l["descricao"], lote, unid,
                l["solicitante"] or "-", l["area"] or "-", l["os"] or "0000/00", l["nf"] or "-", l["obs"] or ""]
    sinal = -1 if l["movim"] == "Saída" else 1
    seriais = _lista_seriais(l["seriais"])
    if seriais:
        linhas = [base(s, sinal) for s in seriais]
        resto = abs(l["qtd"]) - len(seriais)
        if resto > 0:
            linhas.append(base("-", sinal * resto))
        return linhas
    return [base("-", sinal * l["qtd"])]


def _intervalo(rs: list[int]) -> str:
    return "" if not rs else (f"{rs[0]} a {rs[-1]}" if len(rs) > 1 else str(rs[0]))


def preparar_envio(alm: Almoxarifado, dados: bytes) -> tuple[bytes, callable, dict]:
    """Monta a planilha nova. Devolve (bytes, confirmar, resumo); `confirmar()` grava no banco."""
    pl = Planilha(dados)
    db = alm.db
    correcoes = []
    for item_id, de in db.execute("SELECT item_id, de FROM correcoes").fetchall():
        atual = dict(db.execute("SELECT estante, pt, caixa, sku, descricao FROM itens WHERE id = ?", (item_id,)).fetchone())
        correcoes.append((json.loads(de), atual))
    n_cont, n_mov = pl.corrigir_cadastros(correcoes)

    novos = [dict(r) for r in db.execute("SELECT * FROM itens WHERE na_planilha = 0 ORDER BY id")]
    linhas_itens = pl.acrescentar_itens(novos)

    pend = [dict(r) for r in db.execute(
        "SELECT l.*, i.estante, i.pt, i.caixa, i.sku, i.descricao FROM lancamentos l JOIN itens i ON i.id = l.item_id"
        " WHERE l.status = 'pendente' ORDER BY l.criado_em, l.id")]
    todas, partes = [], []
    for l in pend:
        ls = _linhas_do_lancamento(l)
        partes.append((l["id"], len(ls)))
        todas.extend(ls)
    usadas = pl.acrescentar_movimentos(todas)
    linhas_por_lanc, k = {}, 0
    for lid, n in partes:
        linhas_por_lanc[lid] = usadas[k:k + n]
        k += n

    descartes = [dict(r) for r in db.execute("SELECT * FROM descartes")]
    escreveu_desc = False
    if descartes and pl.caminho_aba("DESCARTES"):
        descartes.sort(key=lambda d: int("".join(c for c in d["num"] if c.isdigit()) or 0))
        regs = []
        for d in descartes:
            baixa = d["baixa"] or "Não (fora do estoque)"
            if d["lancamento_id"]:
                rs = linhas_por_lanc.get(d["lancamento_id"])
                if rs is None:
                    r = db.execute("SELECT linhas FROM lancamentos WHERE id = ?", (d["lancamento_id"],)).fetchone()
                    rs = [int(x) for x in (r[0] if r else "").split(",") if x.strip().isdigit()]
                baixa = f"Sim, Movimentação linha {_intervalo(rs)}" if rs else "Sim"
            regs.append(dict(d, serial=d["seriais"], baixa=baixa))
        pl.escrever_descartes(regs)
        escreveu_desc = True

    def confirmar():
        with db:
            for it, r in zip(novos, linhas_itens):
                db.execute("UPDATE itens SET na_planilha = 1, linha_contagem = ? WHERE id = ?", (r, it["id"]))
            for lid, rs in linhas_por_lanc.items():
                db.execute("UPDATE lancamentos SET status = 'lancado', linhas = ? WHERE id = ?",
                           (",".join(map(str, rs)), lid))
            db.execute("DELETE FROM correcoes")
    resumo = {"lancamentos": len(pend), "linhas": len(usadas), "itens_novos": len(novos),
              "correcoes": len(correcoes), "linhas_corrigidas": n_cont + n_mov,
              "descartes": len(descartes) if escreveu_desc else 0,
              "primeira_linha": usadas[0] if usadas else None, "ultima_linha": usadas[-1] if usadas else None}
    return pl.bytes(), confirmar, resumo


def enviar_para_planilha(alm: Almoxarifado, caminho: str | Path, pasta_backup: str | Path | None = None) -> dict:
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroPlanilha(f"Planilha não encontrada em {caminho}.")
    dados = caminho.read_bytes()
    novo, confirmar, resumo = preparar_envio(alm, dados)
    if not (resumo["linhas"] or resumo["itens_novos"] or resumo["correcoes"] or resumo["descartes"]):
        return resumo
    pasta_backup = Path(pasta_backup or caminho.parent / "backups-estoque")
    pasta_backup.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    shutil.copy2(caminho, pasta_backup / f"{caminho.stem} {carimbo}{caminho.suffix}")
    for velho in sorted(pasta_backup.glob(f"{caminho.stem} *{caminho.suffix}"))[:-30]:
        velho.unlink(missing_ok=True)   # guarda as 30 cópias mais recentes
    gravar_arquivo(caminho, novo)
    confirmar()
    return resumo


def gravar_arquivo(caminho: Path, dados: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=".~estoque-", suffix=caminho.suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        os.replace(tmp, caminho)
    except PermissionError:
        Path(tmp).unlink(missing_ok=True)
        raise ErroPlanilha("Não consegui salvar a planilha: feche o arquivo no Excel e tente de novo.") from None
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
