"""Versão web do controle de estoque, com as mesmas abas do app "Movimentação do Almoxarifado".

Privado: roda no seu computador, só aceita conexões da própria máquina (a não ser
que você ligue o modo rede) e todas as páginas pedem login com a sua senha.
"""

import csv
import functools
import hmac
import io
import os
import secrets
import time
from datetime import date, timedelta
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from ..banco import conectar
from ..planilha import exportar_dia
from ..servico import CHECKLIST_TERMINAL, Almoxarifado, ErroEstoque, hoje
from ..sincronizar import enviar_para_planilha, gravar_arquivo, trazer_da_planilha
from ..xlsx import ErroPlanilha, Planilha

ABAS = [("inicio", "Início"), ("mov", "Movimentação"), ("pedidos", "Pedidos"), ("inventario", "Inventário")]
MAIS = [("descarte", "Descarte"), ("dia", "Movimento do dia"), ("terminais", "Terminais"),
        ("relatorios", "Relatórios"), ("pessoas", "Pessoas")]
LOCAIS = {"127.0.0.1", "::1", "localhost"}


def criar_app(caminho_banco: str = "estoque.db", rede: bool = False) -> Flask:
    app = Flask(__name__)
    app.config["BANCO"] = str(Path(caminho_banco).resolve())
    app.config["REDE"] = rede
    c = conectar(app.config["BANCO"])
    try:
        a0 = Almoxarifado(c)
        if not a0.config("segredo"):
            a0.definir_config("segredo", secrets.token_hex(32))
        app.secret_key = a0.config("segredo")
    finally:
        c.close()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict",
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=12), MAX_CONTENT_LENGTH=60 * 1024 * 1024)
    tentativas: dict[str, list[float]] = {}

    # ---------------- infraestrutura ----------------
    def alm() -> Almoxarifado:
        if "alm" not in g:
            g.alm = Almoxarifado(conectar(app.config["BANCO"]))
        return g.alm

    @app.teardown_appcontext
    def fechar(_):
        a = g.pop("alm", None)
        if a:
            a.db.close()

    @app.before_request
    def proteger():
        if not app.config["REDE"] and request.remote_addr not in LOCAIS:
            abort(403)
        livre = request.endpoint in ("login", "primeiro_acesso", "static")
        if not alm().config("senha_hash"):
            if request.endpoint not in ("primeiro_acesso", "static"):
                return redirect(url_for("primeiro_acesso"))
            return None
        if not livre and not session.get("ok"):
            return redirect(url_for("login", proximo=request.full_path if request.method == "GET" else None))
        if request.method == "POST":
            token = request.form.get("_csrf", "")
            if not hmac.compare_digest(token, session.get("csrf", "")):
                abort(400, "Formulário expirado. Volte, recarregue a página e tente de novo.")

    @app.after_request
    def cabecalhos(resp):
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data:; "
                                                   "style-src 'self' 'unsafe-inline'; script-src 'self'; form-action 'self'")
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def contexto():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        dados = {"csrf": session["csrf"], "ABAS": ABAS, "MAIS": MAIS, "aba": getattr(g, "aba", ""), "hoje": hoje()}
        if session.get("ok"):
            a = alm()
            p = a.pendentes()
            dados.update(pend=p, pend_total=p["lancamentos"] + p["itens_novos"] + p["correcoes"],
                         planilha=a.config("planilha"), n_pedidos=len(a.pedidos(abertos=True)),
                         usuario=a.config("usuario", ""))
        return dados

    def aba(nome):
        def deco(f):
            @functools.wraps(f)
            def w(*a, **k):
                g.aba = nome
                return f(*a, **k)
            return w
        return deco

    def item_ref(texto: str):
        t = (texto or "").strip()
        if t.startswith("#"):
            t = t[1:].split()[0] if t[1:].split() else ""
        if not t:
            raise ErroEstoque("Escolha o item.")
        return t

    def depois_de_gravar(msg: str):
        """Mostra a mensagem e, se o envio automático estiver ligado, grava na planilha."""
        flash(msg, "ok")
        a = alm()
        if a.config("auto_enviar") == "1" and a.config("planilha"):
            try:
                r = enviar_para_planilha(a, a.config("planilha"))
                if r["linhas"] or r["itens_novos"]:
                    flash(f"Lançado na planilha ({faixa(r)})." if r["linhas"] else "Planilha atualizada.", "ok")
            except (ErroPlanilha, ErroEstoque, OSError) as e:
                flash(f"Ficou pendente: {e}", "warn")

    def faixa(r):
        a, b = r["primeira_linha"], r["ultima_linha"]
        return f"linha {a} da Movimentação" if a == b else f"linhas {a} a {b} da Movimentação"

    def voltar(padrao="inicio", **kw):
        destino = request.form.get("voltar") or request.args.get("voltar")
        if destino and destino.startswith("/") and not destino.startswith("//"):
            return redirect(destino)
        return redirect(url_for(padrao, **kw))

    @app.errorhandler(ErroEstoque)
    @app.errorhandler(ErroPlanilha)
    @app.errorhandler(ValueError)
    def erro_regra(e):
        msg = str(e) if isinstance(e, (ErroEstoque, ErroPlanilha)) else "Confira os números digitados."
        if request.method == "POST":
            flash(msg, "bad")
            ref = request.referrer or ""
            if ref.startswith(request.host_url):
                return redirect(ref)
            return redirect(url_for("inicio"))
        return render_template("erro.html", erro=msg)

    # ---------------- acesso ----------------
    @app.route("/primeiro-acesso", methods=["GET", "POST"])
    def primeiro_acesso():
        if alm().config("senha_hash"):
            return redirect(url_for("login"))
        if request.remote_addr not in LOCAIS:
            abort(403, "Crie a senha no próprio computador onde o app está rodando.")
        erro = None
        if request.method == "POST":
            if not hmac.compare_digest(request.form.get("_csrf", ""), session.get("csrf", "")):
                abort(400)
            s1, s2 = request.form.get("senha", ""), request.form.get("senha2", "")
            if len(s1) < 8:
                erro = "Use uma senha com pelo menos 8 caracteres."
            elif s1 != s2:
                erro = "As duas senhas não são iguais."
            else:
                alm().definir_config("senha_hash", generate_password_hash(s1))
                alm().definir_config("usuario", request.form.get("nome", "").strip() or "Almoxarifado")
                session.clear()
                session["ok"], session.permanent = True, True
                flash("Senha criada. Agora configure a planilha.", "ok")
                return redirect(url_for("planilha"))
        return render_template("primeiro_acesso.html", erro=erro)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        erro = None
        if request.method == "POST":
            ip = request.remote_addr or "?"
            recentes = [t for t in tentativas.get(ip, []) if t > time.time() - 900]
            if len(recentes) >= 8:
                erro = "Muitas tentativas. Espere 15 minutos."
            elif check_password_hash(alm().config("senha_hash"), request.form.get("senha", "")):
                tentativas.pop(ip, None)
                proximo = request.form.get("proximo") or ""
                session.clear()
                session["ok"], session.permanent = True, True
                return redirect(proximo if proximo.startswith("/") and not proximo.startswith("//") else url_for("inicio"))
            else:
                recentes.append(time.time())
                tentativas[ip] = recentes
                time.sleep(1)
                erro = "Senha incorreta."
        return render_template("login.html", erro=erro, proximo=request.args.get("proximo", ""))

    @app.route("/sair", methods=["POST"])
    def sair():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/senha", methods=["GET", "POST"])
    def trocar_senha():
        if request.method == "POST":
            if not check_password_hash(alm().config("senha_hash"), request.form.get("atual", "")):
                flash("A senha atual está errada.", "bad")
            elif len(request.form.get("nova", "")) < 8 or request.form.get("nova") != request.form.get("nova2"):
                flash("A senha nova precisa ter 8 caracteres ou mais e ser igual nos dois campos.", "bad")
            else:
                alm().definir_config("senha_hash", generate_password_hash(request.form["nova"]))
                flash("Senha trocada.", "ok")
                return redirect(url_for("inicio"))
        return render_template("senha.html")

    # ---------------- Início ----------------
    @app.route("/")
    @aba("inicio")
    def inicio():
        a = alm()
        q = request.args.get("q", "").strip()
        if q:
            return redirect(url_for("mov", q=q))
        return render_template("inicio.html", minimo=a.abaixo_do_minimo(), atrasados=a.emprestimos_atrasados(),
                               resumo=a.resumo(), usuario=a.config("usuario", ""))

    # ---------------- Movimentação ----------------
    @app.route("/mov")
    @aba("mov")
    def mov():
        a = alm()
        tipo = request.args.get("tipo", "saida")
        q, filtro = request.args.get("q", "").strip(), request.args.get("f", "tudo")
        item, serial_bipado, resultados = None, None, []
        if request.args.get("item"):
            item = a.item(request.args["item"])
            serial_bipado = request.args.get("serial")
        elif q or filtro != "tudo":
            # leitor de código de barras: serial ou SKU únicos já selecionam o item
            exato = a.db.execute("SELECT item_id FROM seriais WHERE serial = ?", (q.upper(),)).fetchone() if q else None
            if exato:
                return redirect(url_for("mov", tipo=tipo, item=exato[0], serial=q.upper()))
            por_sku = a.db.execute("SELECT id FROM itens WHERE upper(sku) = upper(?) AND sku != '-'", (q,)).fetchall() if q else []
            if len(por_sku) == 1:
                return redirect(url_for("mov", tipo=tipo, item=por_sku[0][0]))
            resultados = a.buscar(q)
            if filtro == "zerados":
                resultados = [i for i in resultados if i.saldo <= 0]
            elif filtro == "minimo":
                resultados = [i for i in resultados if i.abaixo_do_minimo]
            elif filtro == "semsku":
                resultados = [i for i in resultados if i.sku in ("", "-")]
            resultados = resultados[:80]
        return render_template("mov.html", tipo=tipo, q=q, filtro=filtro, item=item, resultados=resultados,
                               serial_bipado=serial_bipado, ultimos=a.historico(limite=25),
                               pessoas=a.pessoas(), areas=a.areas(),
                               historico_item=a.historico(item.id, limite=10) if item else [])

    @app.route("/mov/registrar", methods=["POST"])
    def registrar():
        a, f = alm(), request.form
        tipo = f.get("tipo", "saida")
        seriais = f.getlist("serial") + f.get("seriais_extra", "").replace(",", "\n").split("\n")
        seriais = [s for s in (x.strip() for x in seriais) if s]
        sem_serial = int(f.get("sem_serial") or 0)
        qtd = int(f.get("qtd") or 0)
        if seriais:
            qtd = len(set(s.upper() for s in seriais)) + sem_serial
        dados = dict(solicitante=f.get("solic", ""), area=f.get("area", ""), os=f.get("os", ""),
                     nf=f.get("nf", ""), obs=f.get("obs", ""), data=f.get("data") or None)
        if tipo == "entrada":
            l = a.entrada(f["item"], qtd, seriais, **dados)
        else:
            emp = f.get("emprestimo") == "1"
            l = a.saida(f["item"], qtd, seriais, forcar=f.get("forcar") == "1", emprestimo=emp,
                        devolver_ate=f.get("devolver_ate") if emp else None, **dados)
        it = a.item(l["item_id"])
        depois_de_gravar(f"{l['movim']} registrada: {l['qtd']} un de {it.descricao}. Saldo agora: {it.saldo}."
                         + (f" ⚠ No mínimo ({it.minimo})." if it.abaixo_do_minimo else ""))
        return redirect(url_for("mov", tipo=tipo))

    @app.route("/lanc/<int:lid>/<acao>", methods=["POST"])
    def lanc_acao(lid, acao):
        a = alm()
        if acao == "estornar":
            l = a.estornar(lid, request.form.get("motivo", ""))
            depois_de_gravar(f"Estorno registrado: {l['movim']} de {abs(l['qtd'])} un de {l['descricao']}.")
        elif acao == "excluir":
            a.excluir_lancamento(lid)
            flash("Lançamento pendente excluído.", "ok")
        elif acao == "devolver":
            l = a.devolver(lid)
            depois_de_gravar(f"Devolução registrada: {l['qtd']} un de {l['descricao']}.")
        else:
            abort(404)
        return voltar("mov")

    @app.route("/mov/nf", methods=["GET", "POST"])
    @aba("mov")
    def receber_nf():
        a = alm()
        if request.method == "POST":
            f = request.form
            forn, nf = f.get("fornecedor", "").strip(), f.get("nf", "").strip()
            if not forn or not nf:
                raise ErroEstoque("Informe o fornecedor e o número da nota.")
            linhas = [(r, q, s) for r, q, s in zip(f.getlist("item"), f.getlist("qtd"), f.getlist("seriais")) if r.strip()]
            if not linhas:
                raise ErroEstoque("Coloque pelo menos um item da nota.")
            feitos = 0
            for r, q, s in linhas:
                seriais = [x for x in (y.strip() for y in s.replace(",", "\n").split("\n")) if x]
                a.entrada(item_ref(r), int(q or 0) or None, seriais, solicitante=forn, area="Fornecedor", nf=nf,
                          obs=f.get("obs", ""), data=f.get("data") or None)
                feitos += 1
            depois_de_gravar(f"Nota {nf} de {forn}: {feitos} item(ns) recebidos.")
            return redirect(url_for("mov", tipo="entrada"))
        return render_template("nf.html", itens=a.buscar(), fornecedores=[p["nome"] for p in a.pessoas()
                                                                          if p["area"] == "Fornecedor"])

    @app.route("/itens/novo", methods=["GET", "POST"])
    @aba("mov")
    def item_novo():
        a = alm()
        if request.method == "POST":
            f = request.form
            criados = []
            for desc, sku, est, pt, cx, qtd, ser, mn in zip(f.getlist("descricao"), f.getlist("sku"), f.getlist("estante"),
                                                            f.getlist("pt"), f.getlist("caixa"), f.getlist("qtd"),
                                                            f.getlist("seriais"), f.getlist("minimo")):
                if not desc.strip():
                    continue
                seriais = [x for x in (y.strip() for y in ser.replace(",", "\n").split("\n")) if x]
                criados.append(a.cadastrar_item(desc, sku, est, pt, cx, int(mn or 0), int(qtd or 0), seriais))
            if not criados:
                raise ErroEstoque("Preencha a descrição de pelo menos um item.")
            depois_de_gravar(f"{len(criados)} item(ns) cadastrado(s): " + ", ".join(i.descricao for i in criados) + ".")
            return redirect(url_for("mov", item=criados[-1].id))
        base = a.item(request.args["base"]) if request.args.get("base") else None
        return render_template("item_novo.html", base=base, estantes=a.estantes(), itens=a.buscar())

    @app.route("/itens/<int:iid>/corrigir", methods=["GET", "POST"])
    @aba("mov")
    def item_corrigir(iid):
        a = alm()
        it = a.item(iid)
        if request.method == "POST":
            f = request.form
            it = a.corrigir_item(iid, descricao=f.get("descricao"), sku=f.get("sku"), estante=f.get("estante"),
                                 pt=f.get("pt"), caixa=f.get("caixa"), minimo=int(f.get("minimo") or 0))
            if f.get("contado", "").strip() != "":
                a.ajustar_contagem(iid, int(f["contado"]), solicitante="Correção de saldo")
            depois_de_gravar(f"{it.descricao} corrigido.")
            return redirect(url_for("mov", item=iid))
        return render_template("item_corrigir.html", item=it, estantes=a.estantes())

    # ---------------- Pedidos e empréstimos ----------------
    @app.route("/pedidos")
    @aba("pedidos")
    def pedidos():
        a = alm()
        filtro = request.args.get("f", "abertos")
        lista = a.pedidos(abertos=filtro == "abertos")
        if filtro not in ("abertos", "todos"):
            lista = [p for p in lista if p["status"] == filtro]
        hoje_ = hoje()
        return render_template("pedidos.html", lista=lista, filtro=filtro, itens=a.buscar(), pessoas=a.pessoas(),
                               areas=a.areas(), emprestimos=a.emprestimos_abertos(), hoje_=hoje_)

    @app.route("/pedidos/novo", methods=["POST"])
    def pedido_novo():
        a, f = alm(), request.form
        itens = [(item_ref(r), int(q or 1)) for r, q in zip(f.getlist("item"), f.getlist("qtd")) if r.strip()]
        p = a.criar_pedido(f.get("solicitante", ""), itens, f.get("area", ""), f.get("os", ""), f.get("obs", ""))
        flash(f"Pedido {p['num']} de {p['solicitante']} criado.", "ok")
        return redirect(url_for("pedidos"))

    @app.route("/pedidos/<num>/<acao>", methods=["POST"])
    def pedido_acao(num, acao):
        a = alm()
        if acao == "separar":
            a.separar_pedido(num)
            flash(f"Pedido {num} separado.", "ok")
        elif acao == "cancelar":
            a.cancelar_pedido(num)
            flash(f"Pedido {num} cancelado.", "ok")
        elif acao == "entregar":
            r = a.entregar_pedido(num)
            for n in r["nao_entregues"]:
                flash(f"Não entregue: {n['descricao']} — {n['motivo']}", "warn")
            depois_de_gravar(f"Pedido {num} entregue: {len(r['lancamentos'])} saída(s).")
        else:
            abort(404)
        return redirect(url_for("pedidos"))

    # ---------------- Inventário ----------------
    @app.route("/inventario", methods=["GET", "POST"])
    @aba("inventario")
    def inventario():
        a = alm()
        estante = request.values.get("estante", "")
        if request.method == "POST":
            contagens = {}
            for k, v in request.form.items():
                if k.startswith("c_") and v.strip() != "":
                    contagens[int(k[2:])] = int(v)
            if not contagens:
                raise ErroEstoque("Nenhuma quantidade contada foi preenchida.")
            ajustes = a.aplicar_inventario(estante, contagens, request.form.get("resp", ""))
            depois_de_gravar(f"Estante {estante}: {len(contagens)} item(ns) contados, {len(ajustes)} ajuste(s) de saldo.")
            return redirect(url_for("inventario", estante=estante))
        return render_template("inventario.html", estantes=a.estantes(), estante=estante,
                               itens=a.itens_da_estante(estante) if estante else [], historico=a.inventarios())

    # ---------------- Descarte ----------------
    @app.route("/descarte", methods=["GET", "POST"])
    @aba("descarte")
    def descarte():
        a = alm()
        if request.method == "POST":
            f = request.form
            seriais = [x for x in (y.strip() for y in f.get("seriais", "").replace(",", "\n").split("\n")) if x]
            ref = item_ref(f["item"]) if f.get("modo") == "estoque" else None
            d = a.descartar(f.get("motivo", ""), f.get("resp", ""), int(f.get("qtd") or 0) or None, ref,
                            f.get("material", ""), f.get("sku", "-"), seriais, f.get("destino", ""),
                            f.get("origem", ""), f.get("autorizado", ""), f.get("documento", ""), f.get("obs", ""),
                            f.get("data") or None)
            depois_de_gravar(f"Descarte {d['num']} registrado: {d['qtd']} un de {d['material']}.")
            return redirect(url_for("descarte"))
        lista = [dict(r) for r in a.db.execute("SELECT * FROM descartes ORDER BY id DESC LIMIT 100")]
        return render_template("descarte.html", itens=a.buscar(), lista=lista, pessoas=a.pessoas())

    # ---------------- Movimento do dia ----------------
    @app.route("/dia")
    @aba("dia")
    def dia():
        a = alm()
        d = request.args.get("data") or hoje()
        lista = a.movimento_do_dia(d)
        ent = sum(abs(l["qtd"]) for l in lista if l["movim"] == "Entrada")
        sai = sum(abs(l["qtd"]) for l in lista if l["movim"] == "Saída")
        return render_template("dia.html", data=d, lista=lista, ent=ent, sai=sai,
                               anterior=(date.fromisoformat(d) - timedelta(days=1)).isoformat(),
                               seguinte=(date.fromisoformat(d) + timedelta(days=1)).isoformat())

    @app.route("/dia.csv")
    def dia_csv():
        d = request.args.get("data") or hoje()
        tmp = Path(app.config["BANCO"]).parent / f".dia-{secrets.token_hex(4)}.csv"
        try:
            exportar_dia(alm(), d, tmp)
            dados = tmp.read_bytes()
        finally:
            tmp.unlink(missing_ok=True)
        return send_file(io.BytesIO(dados), mimetype="text/csv", as_attachment=True,
                         download_name=f"Movimento do dia {d}.csv")

    # ---------------- Terminais ----------------
    @app.route("/terminais", methods=["GET", "POST"])
    @aba("terminais")
    def terminais():
        a = alm()
        if request.method == "POST":
            f = request.form
            checklist = {c: f.get(f"ck_{i}", "OK") for i, c in enumerate(CHECKLIST_TERMINAL)}
            t = a.registrar_terminal(f.get("tipo", "Entrada"), f.get("serial", ""), checklist, f.get("modelo", ""),
                                     f.get("local", ""), f.get("resp", ""), f.get("obs", ""))
            flash(f"Checklist de {t['tipo'].lower()} do terminal {t['serial']} salvo"
                  + (f" com {t['defeitos']} defeito(s)." if t["defeitos"] else "."), "warn" if t["defeitos"] else "ok")
            return redirect(url_for("terminais"))
        return render_template("terminais.html", checklist=CHECKLIST_TERMINAL,
                               lista=a.terminais(request.args.get("q", "")), q=request.args.get("q", ""))

    # ---------------- Relatórios ----------------
    @app.route("/relatorios")
    @aba("relatorios")
    def relatorios():
        dias = max(1, int(request.args.get("dias") or 30))
        prazo = max(1, int(request.args.get("prazo") or 14))
        return render_template("relatorios.html", r=alm().relatorio(dias, prazo))

    @app.route("/relatorios/minimo", methods=["POST"])
    def aplicar_minimo():
        a = alm()
        pares = [(k[2:], v) for k, v in request.form.items() if k.startswith("m_")]
        for iid, v in pares:
            a.corrigir_item(int(iid), minimo=int(v))
        flash(f"Estoque mínimo atualizado em {len(pares)} item(ns).", "ok")
        return voltar("relatorios")

    @app.route("/relatorios/compras.csv")
    def compras_csv():
        r = alm().relatorio(int(request.args.get("dias") or 30), int(request.args.get("prazo") or 14))
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["Item", "SKU", "Local", "Saldo", "Mínimo", "Saída/dia", "Comprar"])
        for x in r["compras"]:
            i = x["item"]
            w.writerow([i.descricao, i.sku, i.local, i.saldo, i.minimo, f"{x['diario']:.2f}".replace(".", ","), x["comprar"]])
        return send_file(io.BytesIO(("﻿" + buf.getvalue()).encode("utf-8")), mimetype="text/csv",
                         as_attachment=True, download_name=f"Lista de compras {hoje()}.csv")

    # ---------------- Pessoas ----------------
    @app.route("/pessoas", methods=["GET", "POST"])
    @aba("pessoas")
    def pessoas():
        a = alm()
        if request.method == "POST":
            if request.form.get("remover"):
                a.remover_pessoa(request.form["remover"])
                flash("Pessoa removida.", "ok")
            else:
                a.salvar_pessoa(request.form.get("nome", ""), request.form.get("area", ""))
                flash("Pessoa salva.", "ok")
            return redirect(url_for("pessoas"))
        return render_template("pessoas.html", lista=a.pessoas(), areas=a.areas())

    # ---------------- Planilha ----------------
    @app.route("/planilha", methods=["GET", "POST"])
    @aba("planilha")
    def planilha():
        a = alm()
        info = None
        if request.method == "POST":
            acao = request.form.get("acao")
            if acao == "config":
                caminho = request.form.get("caminho", "").strip().strip('"')
                if caminho:
                    p = Path(os.path.expandvars(os.path.expanduser(caminho)))
                    if not p.is_file():
                        raise ErroPlanilha(f"Não achei o arquivo {p}. Confira o caminho (inclua o nome .xlsx).")
                    Planilha(p.read_bytes()).ler()
                    a.definir_config("planilha", str(p.resolve()))
                a.definir_config("auto_enviar", "1" if request.form.get("auto") == "1" else "0")
                flash("Configuração salva.", "ok")
            elif acao == "upload":
                arq = request.files.get("arquivo")
                if not arq or not arq.filename.lower().endswith(".xlsx"):
                    raise ErroPlanilha("Escolha o arquivo .xlsx da planilha.")
                dados = arq.read()
                Planilha(dados).ler()
                destino = Path(a.config("planilha") or Path(app.config["BANCO"]).parent / "planilha" / arq.filename)
                destino.parent.mkdir(parents=True, exist_ok=True)
                if destino.exists():
                    bk = destino.parent / "backups-estoque"
                    bk.mkdir(exist_ok=True)
                    (bk / f"{destino.stem} antes-do-upload {time.strftime('%Y-%m-%d_%H%M%S')}{destino.suffix}").write_bytes(destino.read_bytes())
                gravar_arquivo(destino, dados)
                a.definir_config("planilha", str(destino.resolve()))
                r = trazer_da_planilha(a, dados)
                flash(f"Planilha carregada: {r['itens_novos']} item(ns) novo(s), {r['movimentos']} linha(s) de movimentação, "
                      f"{r['descartes']} descarte(s).", "ok")
            elif acao == "trazer":
                caminho = a.config("planilha")
                if not caminho:
                    raise ErroPlanilha("Configure o caminho da planilha primeiro.")
                r = trazer_da_planilha(a, Path(caminho).read_bytes())
                flash(f"Trazido da planilha: {r['itens_novos']} item(ns) novo(s), {r['movimentos']} linha(s) nova(s) de "
                      f"movimentação, {r['descartes']} descarte(s)." + (f" {r['linhas_ignoradas']} linha(s) ignorada(s) "
                      "por falta de data, tipo ou quantidade." if r["linhas_ignoradas"] else ""), "ok")
            elif acao == "enviar":
                caminho = a.config("planilha")
                if not caminho:
                    raise ErroPlanilha("Configure o caminho da planilha primeiro.")
                r = enviar_para_planilha(a, caminho)
                if not (r["linhas"] or r["itens_novos"] or r["correcoes"] or r["descartes"]):
                    flash("Nada pendente: a planilha já está em dia.", "ok")
                else:
                    partes = []
                    if r["linhas"]:
                        partes.append(f"{r['lancamentos']} lançamento(s) na {faixa(r)}")
                    if r["itens_novos"]:
                        partes.append(f"{r['itens_novos']} item(ns) novo(s) na Contagem")
                    if r["correcoes"]:
                        partes.append(f"{r['correcoes']} correção(ões) de cadastro")
                    if r["descartes"]:
                        partes.append(f"aba DESCARTES com {r['descartes']} registro(s)")
                    flash("Planilha atualizada: " + "; ".join(partes) + ". Cópia de segurança salva.", "ok")
            return redirect(url_for("planilha"))
        caminho = a.config("planilha")
        if caminho and Path(caminho).is_file():
            st = Path(caminho).stat()
            info = {"tamanho": f"{st.st_size / 1024:.0f} KB", "alterado": time.strftime("%d/%m/%Y %H:%M", time.localtime(st.st_mtime))}
        pend_l = a.db.execute(
            "SELECT l.*, i.descricao FROM lancamentos l JOIN itens i ON i.id = l.item_id WHERE l.status = 'pendente'"
            " ORDER BY l.criado_em LIMIT 200").fetchall()
        return render_template("planilha.html", caminho=caminho, info=info, auto=a.config("auto_enviar") == "1",
                               pendentes=[dict(x) for x in pend_l])

    @app.route("/planilha/baixar")
    def planilha_baixar():
        caminho = alm().config("planilha")
        if not caminho or not Path(caminho).is_file():
            raise ErroPlanilha("Nenhuma planilha configurada.")
        return send_file(io.BytesIO(Path(caminho).read_bytes()), as_attachment=True, download_name=Path(caminho).name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return app
