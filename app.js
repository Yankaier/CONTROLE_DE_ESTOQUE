/* Almoxarifado · página ligada direto à planilha do SharePoint (Microsoft Graph).
   Cada registro ACRESCENTA linhas na tabela "movimentação" — nada é sobrescrito,
   então várias pessoas (nesta página e no Excel) podem trabalhar ao mesmo tempo. */
(() => {
  'use strict';
  const C = window.ALMOX_CONFIG;
  const $ = (id) => document.getElementById(id);
  const REDIRECT = location.origin + location.pathname.replace(/index\.html$/, '');
  const SCOPES = 'openid profile offline_access User.Read Files.ReadWrite.All Sites.ReadWrite.All';
  const AUTH = `https://login.microsoftonline.com/${C.tenantId}/oauth2/v2.0`;
  const GRAPH = 'https://graph.microsoft.com/v1.0';
  const WB = `${GRAPH}/drives/${C.driveId}/items/${C.itemId}/workbook`;
  const TAB = encodeURIComponent(C.tabela);
  const REPETE = [409, 423, 429, 500, 502, 503, 504];
  const esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const up = (s) => String(s == null ? '' : s).trim().toUpperCase();
  const norm = (v) => up(v).replace(/\s+/g, ' ');
  const ss = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (_) {} },
    del: (k) => { try { sessionStorage.removeItem(k); } catch (_) {} }
  };
  const S = { rows: [], itens: [], porChave: new Map(), me: '', tipo: 'Entrada', item: null, gravando: false, carregadoEm: null, inicioTabela: 5, contagemFim: 0, minhas: new Set(), vistas: 0 };
  window._almox = S; // para conferência no console

  /* ---------------- login (OAuth 2.0 com PKCE, sem segredo) ---------------- */
  const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  const rand = (n) => b64url(crypto.getRandomValues(new Uint8Array(n)));
  async function entrar() {
    const verifier = rand(48), state = rand(16);
    const challenge = b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier)));
    ss.set('pkce', JSON.stringify({ verifier, state }));
    const p = new URLSearchParams({ client_id: C.clientId, response_type: 'code', redirect_uri: REDIRECT, response_mode: 'query', scope: SCOPES, code_challenge: challenge, code_challenge_method: 'S256', state });
    location.assign(`${AUTH}/authorize?${p}`);
  }
  async function pedirToken(body) {
    let r, j = {};
    try { r = await fetch(`${AUTH}/token`, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' }, body: new URLSearchParams({ client_id: C.clientId, scope: SCOPES, ...body }) }); j = await r.json(); }
    catch (_) { throw { code: 'rede' }; }
    if (!r.ok) throw { code: 'auth', message: j.error_description || j.error || 'falha no login' };
    ss.set('tok', JSON.stringify({ at: j.access_token, rt: j.refresh_token, exp: Date.now() + (Number(j.expires_in || 3600) - 120) * 1000 }));
    return j.access_token;
  }
  async function voltaDoLogin() {
    const q = new URLSearchParams(location.search);
    if (!q.get('code') && !q.get('error')) return;
    const pk = JSON.parse(ss.get('pkce') || 'null'); ss.del('pkce');
    history.replaceState(null, '', REDIRECT);
    if (q.get('error')) throw { code: 'auth', message: q.get('error_description') || q.get('error') };
    if (!pk || pk.state !== q.get('state')) throw { code: 'auth', message: 'O login expirou. Entre de novo.' };
    await pedirToken({ grant_type: 'authorization_code', code: q.get('code'), redirect_uri: REDIRECT, code_verifier: pk.verifier });
  }
  async function token() {
    const t = JSON.parse(ss.get('tok') || 'null');
    if (!t) throw { code: 'login' };
    if (Date.now() < t.exp) return t.at;
    if (!t.rt) throw { code: 'login' };
    try { return await pedirToken({ grant_type: 'refresh_token', refresh_token: t.rt }); }
    catch (e) { if (e.code === 'rede') throw e; ss.del('tok'); throw { code: 'login' }; }
  }

  /* ---------------- Microsoft Graph ---------------- */
  async function graph(path, opts = {}, tentativa = 0) {
    let r;
    try {
      r = await fetch(path.startsWith('http') ? path : WB + path, {
        method: opts.method || 'GET',
        headers: { Authorization: 'Bearer ' + await token(), ...(opts.body ? { 'Content-Type': 'application/json' } : {}) },
        body: opts.body ? JSON.stringify(opts.body) : undefined
      });
    } catch (e) { if (e && e.code) throw e; throw { code: 'rede' }; }
    if (r.status === 401 && tentativa === 0) { const t = JSON.parse(ss.get('tok') || 'null'); if (t) { t.exp = 0; ss.set('tok', JSON.stringify(t)); } return graph(path, opts, 1); }
    if (REPETE.includes(r.status) && !opts.semRepetir && tentativa < 4) {
      await esperar((Number(r.headers.get('Retry-After')) || 1.5 * 2 ** tentativa) * 1000);
      return graph(path, opts, tentativa + 1);
    }
    if (!r.ok) { let j = {}; try { j = await r.json(); } catch (_) {} throw { code: 'graph', status: r.status, message: (j.error && j.error.message) || r.statusText }; }
    return r.status === 204 ? null : r.json();
  }
  function textoErro(e) {
    if (!e) return 'Erro desconhecido.';
    if (e.code === 'rede') return 'Sem conexão com a Microsoft. Verifique a internet e tente de novo; nada foi gravado.';
    if (e.code === 'auth') return 'Não foi possível entrar: ' + (e.message || '') + '.';
    if (e.status === 403) return 'Sua conta não tem permissão para gravar nesta planilha. Peça ao TI acesso de edição ao arquivo.';
    if (e.status === 404) return 'Planilha ou tabela não encontrada. Ela pode ter sido movida, renomeada ou a tabela "movimentação" foi removida.';
    if (e.status === 423 || e.status === 409) return 'A planilha está bloqueada agora (alguém pode estar com ela aberta no Excel do computador). Tente de novo em instantes.';
    if (e.status === 429 || e.status >= 500) return 'A Microsoft está ocupada agora. Tente de novo em instantes.';
    return 'Erro ' + (e.status || '') + ': ' + (e.message || e.code || '');
  }

  /* ---------------- leitura da planilha ---------------- */
  const dataDe = (v) => (typeof v === 'number' ? new Date(Math.round((v - 25569) * 864e5)) : v ? new Date(v) : null);
  const serialDe = (iso) => { const [y, m, d] = iso.split('-').map(Number); return Date.UTC(y, m - 1, d) / 864e5 + 25569; };
  const fmtData = (v) => { const d = dataDe(v); return d && !isNaN(d) ? d.toISOString().slice(0, 10).split('-').reverse().join('/') : String(v || ''); };
  const temSerial = (v) => { const s = String(v == null ? '' : v).trim(); return s !== '' && s !== '-'; };
  const chave = (est, pt, cx, sku, desc) => [est, pt, cx, sku, desc].map(norm).join('|');

  async function carregar() {
    const [tab, cont] = await Promise.all([
      graph(`/tables/${TAB}/range?$select=address,values`),
      graph(`/worksheets('${encodeURIComponent(C.abaContagem)}')/range(address='B5:F3000')?$select=values`)
    ]);
    const ini = Number((String(tab.address).match(/![A-Z]+(\d+)/) || [])[1] || 4);
    S.inicioTabela = ini + 1;
    S.rows = tab.values.slice(1).map((v, i) => ({
      linha: ini + 1 + i, data: v[0], movim: String(v[1] || '').trim(), est: v[2], pt: v[3], cx: v[4], sku: v[5], desc: v[6], lote: v[7],
      unid: Number(v[8]) || 0, solic: v[9], area: v[10], os: v[11], nf: v[12], obs: String(v[13] || ''), k: chave(v[2], v[3], v[4], v[5], v[6])
    })).filter((r) => r.movim || r.desc);
    const itens = new Map();
    cont.values.forEach((v, i) => {
      if (!String(v[4] || '').trim()) return;
      const k = chave(...v);
      if (!itens.has(k)) itens.set(k, { k, orig: v.slice(0, 5), est: v[0], pt: v[1], cx: v[2], sku: v[3], desc: v[4], saldo: 0, ser: new Map(), linhaContagem: 5 + i });
      S.contagemFim = 5 + i;
    });
    for (const r of S.rows) {
      if (!itens.has(r.k)) itens.set(r.k, { k: r.k, orig: [r.est, r.pt, r.cx, r.sku, r.desc], est: r.est, pt: r.pt, cx: r.cx, sku: r.sku, desc: r.desc, saldo: 0, ser: new Map(), semContagem: true });
      const it = itens.get(r.k);
      const u = r.movim === 'Saída' ? -Math.abs(r.unid) : r.unid;
      it.saldo += u;
      if (temSerial(r.lote)) { const s = String(r.lote).trim(); it.ser.set(s, (it.ser.get(s) || 0) + Math.sign(u)); }
    }
    S.itens = [...itens.values()].sort((a, b) => String(a.desc).localeCompare(String(b.desc), 'pt-BR'));
    S.porChave = itens;
    S.carregadoEm = new Date();
    if (S.item) S.item = itens.get(S.item.k) || null;
    listas();
  }
  const disponiveis = (it) => [...it.ser].filter(([, n]) => n > 0).map(([s]) => s);
  function ondeEsta(serial) { for (const it of S.itens) if ((it.ser.get(serial) || 0) > 0) return it; return null; }

  /* ---------------- gravação (só acrescenta linhas) ---------------- */
  async function acrescentar(valores) {
    const marca = valores[0][13];
    const entrou = () => S.rows.filter((r) => r.obs === marca).length >= valores.length;
    let ultimoErro;
    for (let t = 0; t < 4; t++) {
      try { await graph(`/tables/${TAB}/rows/add`, { method: 'POST', body: { index: null, values: valores }, semRepetir: true }); return; }
      catch (e) {
        ultimoErro = e;
        if (!(e.code === 'rede' || REPETE.includes(e.status))) throw e;
        // a resposta pode ter se perdido com a gravação feita: confere antes de repetir
        await esperar(2000 * (t + 1));
        try { await carregar(); if (entrou()) return; } catch (_) {}
      }
    }
    throw ultimoErro;
  }
  function marcaDoRegistro(obs) {
    const agora = new Date();
    const m = `por ${S.me || 'página'} ${agora.toLocaleDateString('pt-BR')} ${agora.toLocaleTimeString('pt-BR')}`;
    S.minhas.add(m);
    return [obs, m].filter(Boolean).join(' · ');
  }
  const linhaPlanilha = (dataISO, movim, it, lote, unid, solic, area, os, nf, obs) =>
    [serialDe(dataISO), movim, it.orig[0], it.orig[1], it.orig[2], it.orig[3], it.orig[4], lote || '-', unid, up(solic) || '-', up(area) || '-', os || '0000/00', nf || '-', obs];

  /* ---------------- tela ---------------- */
  function chip(t, k) { const c = $('chip'); c.textContent = t; c.className = 'chip' + (k ? ' ' + k : ''); }
  function aviso(t, k) { const m = $('msg'); m.hidden = !t; m.textContent = t || ''; m.className = 'msg ' + (k || 'ok'); if (t) m.scrollIntoView({ block: 'nearest' }); }
  function estado() {
    if (navigator.onLine === false) return chip('Sem conexão', 'bad');
    if (S.gravando) return chip('Salvando na planilha…', 'warn');
    if (S.carregadoEm) chip('Planilha em dia · ' + S.carregadoEm.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }), 'ok');
  }
  function listas() {
    const pes = new Map(), areas = new Set();
    for (const r of S.rows) { const p = up(r.solic); if (p && p !== '-' && p !== 'CARGA INICIAL') pes.set(p, up(r.area)); if (r.movim === 'Saída' && up(r.area) && up(r.area) !== '-') areas.add(up(r.area)); }
    S.areaDe = pes;
    $('pessoas').innerHTML = [...pes.keys()].sort().map((p) => `<option value="${esc(p)}">`).join('');
    $('areas').innerHTML = [...areas].sort().map((a) => `<option value="${esc(a)}">`).join('');
  }
  const local = (it) => `Estante ${it.est} · ${it.pt}${String(it.cx).trim() && String(it.cx).trim() !== '-' ? ' · cx ' + it.cx : ''} · SKU ${it.sku}`;
  function buscar(q, lim) {
    q = norm(q); if (!q) return [];
    const t = q.split(' ');
    const ser = S.itens.filter((it) => [...it.ser.keys()].some((s) => norm(s) === q));
    if (ser.length) return ser;
    return S.itens.filter((it) => { const h = norm([it.desc, 'SKU ' + it.sku, it.sku, 'E' + it.est, 'ESTANTE ' + it.est, it.pt].join(' ')); return t.every((x) => h.includes(x)); }).slice(0, lim || 60);
  }
  function renderResultados() {
    const l = buscar($('busca').value, 40);
    $('resultados').innerHTML = l.map((it) => `<button class="it${S.item && S.item.k === it.k ? ' sel' : ''}" data-k="${esc(it.k)}"><span class="d">${esc(it.desc)}<br><span class="hint">${esc(local(it))}</span></span><span class="s">${it.saldo}</span></button>`).join('')
      || ($('busca').value.trim() ? '<p class="hint">Nada encontrado.</p>' : '');
  }
  function escolher(k) {
    S.item = S.porChave.get(k) || null;
    const box = $('escolhido'); box.hidden = !S.item;
    if (!S.item) return;
    $('eDesc').textContent = S.item.desc;
    $('eLocal').textContent = local(S.item) + ` · saldo ${S.item.saldo}`;
    $('novosSer').value = '';
    renderTipo(); renderResultados();
    box.scrollIntoView({ block: 'nearest' });
  }
  function renderTipo(manter) {
    const sai = S.tipo === 'Saída';
    const antes = manter ? new Set([...$('sers').querySelectorAll('input:checked')].map((x) => x.value)) : new Set();
    $('tEnt').setAttribute('aria-selected', !sai); $('tSai').setAttribute('aria-selected', sai);
    $('lSolic').textContent = sai ? 'Quem está retirando' : 'Quem trouxe / fornecedor';
    $('boxArea').hidden = !sai;
    $('boxNovosSer').hidden = sai;
    const it = S.item;
    const disp = it ? disponiveis(it) : [];
    $('boxSeriais').hidden = !(sai && disp.length);
    $('sers').innerHTML = disp.map((s) => `<label><input type="checkbox" value="${esc(s)}"${antes.has(s) ? ' checked' : ''}> ${esc(s)}</label>`).join('');
    if (manter && sai && disp.length) { $('qtd').value = $('sers').querySelectorAll('input:checked').length; return; }
    $('qtd').disabled = sai && disp.length > 0;
    if (sai && disp.length) $('qtd').value = 0;
    else if (Number($('qtd').value) < 1) $('qtd').value = 1;
  }
  function contarSeriais() {
    if (S.tipo === 'Saída' && !$('boxSeriais').hidden) $('qtd').value = $('sers').querySelectorAll('input:checked').length;
    else if (S.tipo === 'Entrada') { const n = $('novosSer').value.split(/\n|,|;/).map((s) => s.trim()).filter(Boolean).length; if (n) $('qtd').value = n; }
  }
  function renderEstoque() {
    const q = $('buscaEst').value.trim();
    const l = q ? buscar(q, 300) : S.itens.slice(0, 300);
    $('tEst').innerHTML = l.map((it) => `<tr><td>${esc(it.est)}</td><td>${esc(it.pt)}</td><td>${esc(it.cx)}</td><td>${esc(it.sku)}</td><td>${esc(it.desc)}${disponiveis(it).length ? `<div class="hint">${disponiveis(it).length} serial(is)</div>` : ''}</td><td class="n">${it.saldo}</td></tr>`).join('');
  }
  const estornada = (r) => S.rows.some((x) => x.obs.includes(`Estorno da linha ${r.linha} `) || x.obs.endsWith(`Estorno da linha ${r.linha}`));
  function renderUltimos() {
    const novas = new Set(S.rows.slice(S.vistas || S.rows.length).map((r) => r.linha));
    const l = S.rows.slice(-60).reverse();
    $('tUlt').innerHTML = l.map((r) => {
      const pode = !/^Estorno da linha/.test(r.obs) && !estornada(r);
      return `<tr class="${novas.has(r.linha) && ![...S.minhas].some((m) => r.obs.includes(m)) ? 'novo' : ''}"><td>${r.linha}</td><td>${esc(fmtData(r.data))}</td><td class="${r.movim === 'Saída' ? 'sai' : 'ent'}">${esc(r.movim)}</td><td>${esc(r.desc)}<div class="hint">E${esc(r.est)} ${esc(r.pt)}</div></td><td>${temSerial(r.lote) ? esc(r.lote) : ''}</td><td class="n">${r.unid}</td><td>${esc(r.solic)}<div class="hint">${esc(r.area)}</div>${r.obs ? `<div class="hint">${esc(r.obs)}</div>` : ''}</td><td>${pode ? `<button data-estorno="${r.linha}">Estornar</button>` : (estornada(r) ? '<span class="hint">estornada</span>' : '')}</td></tr>`;
    }).join('');
  }
  function renderTudo() { renderResultados(); renderEstoque(); renderUltimos(); estado(); if (S.item) { $('eLocal').textContent = local(S.item) + ` · saldo ${S.item.saldo}`; } }

  /* ---------------- ações ---------------- */
  async function registrar() {
    if (S.gravando || !S.item) return;
    const sai = S.tipo === 'Saída';
    const dataISO = $('data').value; if (!dataISO) return aviso('Informe a data.', 'bad');
    const solic = $('solic').value.trim(); if (!solic) return aviso(sai ? 'Informe quem está retirando.' : 'Informe quem trouxe ou o fornecedor.', 'bad');
    const area = sai ? ($('area').value.trim() || (S.areaDe && S.areaDe.get(up(solic))) || '') : 'ESTOQUE';
    if (sai && !area) return aviso('Informe para onde o material vai (setor de destino).', 'bad');
    const marcados = [...$('sers').querySelectorAll('input:checked')].map((x) => x.value);
    const novos = $('novosSer').value.split(/\n|,|;/).map((s) => s.trim()).filter(Boolean);
    const qtd = Number($('qtd').value);
    if (sai && !$('boxSeriais').hidden && !marcados.length) return aviso('Marque os seriais que estão saindo.', 'bad');
    if (!(sai && marcados.length) && !(qtd > 0)) return aviso('Informe a quantidade.', 'bad');
    S.gravando = true; $('registrar').disabled = true; estado(); aviso('');
    try {
      await carregar(); // confere com o que está na planilha AGORA (outras pessoas podem ter mexido)
      const it = S.porChave.get(S.item.k);
      if (!it) throw { code: 'msg', message: 'Este item não está mais na planilha.' };
      if (sai) {
        const disp = new Set(disponiveis(it));
        const saiu = marcados.filter((s) => !disp.has(s));
        if (saiu.length) throw { code: 'msg', message: `Já saíram (outra pessoa acabou de lançar): ${saiu.join(', ')}. Nada foi gravado.` };
        if (!marcados.length && qtd > it.saldo) throw { code: 'msg', message: `Saldo insuficiente: a planilha tem ${it.saldo} un deste item agora.` };
      } else {
        const rep = novos.filter((s) => ondeEsta(s));
        if (rep.length) throw { code: 'msg', message: `Já estão no estoque: ${rep.map((s) => `${s} (${ondeEsta(s).desc})`).join('; ')}. Nada foi gravado.` };
        if (new Set(novos.map(norm)).size !== novos.length) throw { code: 'msg', message: 'Há serial repetido na lista.' };
      }
      const obs = marcaDoRegistro($('obs').value.trim());
      const os = $('os').value.trim(), nf = $('nf').value.trim();
      const vals = sai
        ? (marcados.length ? marcados.map((s) => linhaPlanilha(dataISO, 'Saída', it, s, -1, solic, area, os, nf, obs)) : [linhaPlanilha(dataISO, 'Saída', it, '', -qtd, solic, area, os, nf, obs)])
        : (novos.length ? novos.map((s) => linhaPlanilha(dataISO, 'Entrada', it, s, 1, solic, area, os, nf, obs)) : [linhaPlanilha(dataISO, 'Entrada', it, '', qtd, solic, area, os, nf, obs)]);
      await acrescentar(vals);
      await carregar();
      const dup = sai ? marcados.filter((s) => (S.porChave.get(it.k).ser.get(s) || 0) < 0) : [];
      const n = vals.reduce((a, v) => a + Math.abs(v[8]), 0);
      aviso(`${sai ? 'Saída' : 'Entrada'} de ${n} un de ${it.desc} gravada na planilha.` + (dup.length ? ` Atenção: ${dup.join(', ')} saiu duas vezes (outra pessoa lançou no mesmo instante). Estorne uma das linhas em Últimos lançamentos.` : ''), dup.length ? 'warn' : 'ok');
      ['obs', 'nf', 'os', 'novosSer'].forEach((k) => ($(k).value = ''));
      $('qtd').value = 1; renderTipo();
    } catch (e) {
      aviso(e.code === 'msg' ? e.message : textoErro(e), 'bad');
    } finally {
      S.gravando = false; $('registrar').disabled = false; renderTudo(); if (S.item) renderTipo(true);
    }
  }

  async function estornar(linha, btn) {
    if (S.gravando) return;
    if (btn.dataset.conf !== '1') { btn.dataset.conf = '1'; btn.textContent = 'Confirmar estorno'; btn.classList.add('primary'); setTimeout(() => { if (btn.isConnected) { btn.dataset.conf = ''; btn.textContent = 'Estornar'; btn.classList.remove('primary'); } }, 6000); return; }
    S.gravando = true; estado(); aviso('');
    try {
      await carregar();
      const r = S.rows.find((x) => x.linha === linha);
      if (!r) throw { code: 'msg', message: `A linha ${linha} não existe mais.` };
      if (estornada(r)) throw { code: 'msg', message: `A linha ${linha} já foi estornada por outra pessoa. Nada foi feito.` };
      const it = S.porChave.get(r.k);
      let movim, unid, area;
      if (r.movim === 'Saída') { movim = 'Entrada'; unid = Math.abs(r.unid); area = 'ESTOQUE'; }
      else if (r.movim === 'Entrada') { movim = 'Saída'; unid = -Math.abs(r.unid); area = 'AJUSTE DE INVENTÁRIO'; }
      else { movim = 'Saldo Inicial'; unid = -r.unid; area = 'AJUSTE DE INVENTÁRIO'; }
      if (temSerial(r.lote) && movim !== 'Entrada' && !((it.ser.get(String(r.lote).trim()) || 0) > 0)) throw { code: 'msg', message: `O serial ${r.lote} não está mais no estoque; não dá para estornar a entrada dele.` };
      const hoje = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
      const obs = marcaDoRegistro(`Estorno da linha ${linha}`);
      await acrescentar([linhaPlanilha(hoje, movim, it, temSerial(r.lote) ? r.lote : '', unid, r.solic, area, '', '', obs)]);
      await carregar();
      aviso(`Linha ${linha} estornada: entrou uma ${movim.toLowerCase()} de ${Math.abs(unid)} un de ${it.desc}.`, 'ok');
    } catch (e) { aviso(e.code === 'msg' ? e.message : textoErro(e), 'bad'); }
    finally { S.gravando = false; renderTudo(); }
  }

  async function novoItem() {
    if (S.gravando) return;
    const v = { est: $('nEst').value.trim(), pt: up($('nPt').value), cx: $('nCx').value.trim() || '-', sku: $('nSku').value.trim(), desc: up($('nDesc').value) };
    const ser = $('nSer').value.split(/\n|,|;/).map((s) => s.trim()).filter(Boolean);
    const qtd = ser.length || Number($('nQtd').value) || 0;
    if (!v.est || !v.pt || !v.sku || !v.desc) return aviso('Preencha estante, prateleira, SKU e descrição.', 'bad');
    const cel = (x) => (/^\d+$/.test(x) ? Number(x) : x);
    const orig = [cel(v.est), v.pt, cel(v.cx), cel(v.sku), v.desc];
    S.gravando = true; estado(); aviso('');
    try {
      await carregar();
      const k = chave(...orig);
      if (S.porChave.has(k)) throw { code: 'msg', message: 'Esse item já existe nesse local.' };
      const rep = ser.filter((s) => ondeEsta(s)); if (rep.length) throw { code: 'msg', message: `Já estão no estoque: ${rep.join(', ')}.` };
      // linha nova na Contagem com as mesmas fórmulas da última linha
      const ultima = S.contagemFim, nova = ultima + 1;
      const aba = encodeURIComponent(C.abaContagem);
      const [modelo, alvo] = await Promise.all([
        graph(`/worksheets('${aba}')/range(address='B${ultima}:BS${ultima}')?$select=formulas`),
        graph(`/worksheets('${aba}')/range(address='B${nova}:BS${nova}')?$select=values`)
      ]);
      if (alvo.values[0].some((x) => x !== '' && x !== null)) throw { code: 'msg', message: 'Alguém acabou de cadastrar um item. Tente de novo.' };
      const f = modelo.formulas[0].map((x, i) => (i < 5 ? orig[i] : typeof x === 'string' && x.startsWith('=') ? x.replace(/(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(])/g, (m, a, col, b, n) => (b === '' && Number(n) === ultima ? `${a}${col}${nova}` : m)) : x));
      await graph(`/worksheets('${aba}')/range(address='B${nova}:BS${nova}')`, { method: 'PATCH', body: { formulas: [f] } });
      const it = { orig };
      const hoje = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
      const obs = marcaDoRegistro('Item novo');
      if (qtd > 0) await acrescentar(ser.length ? ser.map((s) => linhaPlanilha(hoje, 'Saldo Inicial', it, s, 1, 'CARGA INICIAL', 'ESTOQUE INICIAL', '', '', obs)) : [linhaPlanilha(hoje, 'Saldo Inicial', it, '', qtd, 'CARGA INICIAL', 'ESTOQUE INICIAL', '', '', obs)]);
      await carregar();
      ['nEst', 'nPt', 'nCx', 'nSku', 'nDesc', 'nSer'].forEach((x) => ($(x).value = '')); $('nQtd').value = 0;
      aviso(`Item ${v.desc} cadastrado (linha ${nova} da Contagem)${qtd ? ` com saldo inicial de ${qtd} un` : ''}.`, 'ok');
    } catch (e) { aviso(e.code === 'msg' ? e.message : textoErro(e), 'bad'); }
    finally { S.gravando = false; renderTudo(); }
  }

  /* ---------------- eventos ---------------- */
  function aba(a) {
    document.querySelectorAll('[data-aba]').forEach((b) => b.setAttribute('aria-selected', b.dataset.aba === a));
    document.querySelectorAll('[data-painel]').forEach((p) => (p.hidden = p.dataset.painel !== a));
    if (a === 'ult') { renderUltimos(); S.vistas = S.rows.length; }
    try { localStorage.setItem('almox-aba', a); } catch (_) {}
  }
  document.querySelectorAll('[data-aba]').forEach((b) => b.addEventListener('click', () => aba(b.dataset.aba)));
  $('entrar').addEventListener('click', entrar);
  $('sair').addEventListener('click', () => { ss.del('tok'); location.assign(`${AUTH}/logout?post_logout_redirect_uri=${encodeURIComponent(REDIRECT)}`); });
  $('tEnt').addEventListener('click', () => { S.tipo = 'Entrada'; renderTipo(); });
  $('tSai').addEventListener('click', () => { S.tipo = 'Saída'; renderTipo(); });
  $('busca').addEventListener('input', renderResultados);
  $('busca').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); const l = buscar($('busca').value, 2); if (l.length === 1) { escolher(l[0].k); const s = norm($('busca').value); const cb = [...$('sers').querySelectorAll('input')].find((x) => norm(x.value) === s); if (cb) { cb.checked = true; contarSeriais(); } } } });
  $('resultados').addEventListener('click', (e) => { const b = e.target.closest('[data-k]'); if (b) escolher(b.dataset.k); });
  $('sers').addEventListener('change', contarSeriais);
  $('novosSer').addEventListener('input', contarSeriais);
  $('solic').addEventListener('change', () => { const a = S.areaDe && S.areaDe.get(up($('solic').value)); if (a && !$('area').value && a !== 'ESTOQUE') $('area').value = a; });
  $('registrar').addEventListener('click', registrar);
  $('buscaEst').addEventListener('input', renderEstoque);
  $('tUlt').addEventListener('click', (e) => { const b = e.target.closest('[data-estorno]'); if (b) estornar(Number(b.dataset.estorno), b); });
  $('nSalvar').addEventListener('click', novoItem);
  window.addEventListener('online', estado); window.addEventListener('offline', estado);

  // atualização automática: traz o que outras pessoas lançaram (página ou Excel)
  async function atualizar() {
    if (S.gravando || document.visibilityState === 'hidden' || !S.carregadoEm) return;
    const antes = S.rows.length;
    try { await carregar(); } catch (e) { if (e.code === 'login') return mostrarLogin(); chip('Sem conexão com a planilha', 'bad'); return; }
    const novas = S.rows.slice(antes).filter((r) => ![...S.minhas].some((m) => r.obs.includes(m)));
    renderTudo();
    if (novas.length) chip(`${novas.length} lançamento(s) novo(s) de outras pessoas · ${S.carregadoEm.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })}`, 'ok');
  }
  setInterval(atualizar, 45000);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') atualizar(); });

  function mostrarLogin() { $('telaLogin').hidden = false; $('app').hidden = true; $('sair').hidden = true; chip('Desconectado'); }

  /* ---------------- início ---------------- */
  (async () => {
    const hoje = new Date(Date.now() - new Date().getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
    $('data').value = hoje;
    if (/PREENCHER/.test(C.clientId + C.tenantId)) { mostrarLogin(); $('entrar').disabled = true; aviso('Falta configurar o ID do aplicativo e do diretório em config.js.', 'bad'); $('msg').hidden = false; $('app').hidden = true; document.querySelector('.wrap').append($('msg')); return; }
    try { await voltaDoLogin(); } catch (e) { mostrarLogin(); document.querySelector('#telaLogin .hint').textContent = textoErro(e); return; }
    if (!ss.get('tok')) return mostrarLogin();
    $('telaLogin').hidden = true; $('app').hidden = false; $('sair').hidden = false;
    chip('Lendo a planilha…', 'warn');
    try {
      const me = await graph(`${GRAPH}/me?$select=displayName,givenName`);
      S.me = (me.givenName || me.displayName || '').trim();
      $('quem').textContent = me.displayName || '';
      await carregar();
      S.vistas = S.rows.length;
      let a = 'mov'; try { a = localStorage.getItem('almox-aba') || 'mov'; } catch (_) {}
      aba(a); renderTipo(); renderTudo();
    } catch (e) {
      if (e.code === 'login') return mostrarLogin();
      chip('Erro ao ler a planilha', 'bad'); aviso(textoErro(e), 'bad');
    }
  })();
})();
