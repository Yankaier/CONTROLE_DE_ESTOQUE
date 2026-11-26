"""Converte os dados do app Movimentação do Almoxarifado (formulário) para o banco da Gestão do Almoxarifado.

Uso: python copiar_do_formulario.py <pasta com itens/ pessoas/ lancamentos/ em JSON> <pasta de saída>
Gera um JSON por documento e _lotes.json com lotes de 50 gravações (itens, operadores, movs, config/geral)."""
import json, glob, sys, os, re, unicodedata, collections, datetime
ORIG, OUT = sys.argv[1], sys.argv[2]
load = lambda c: {f.split('/')[-1][:-5]: json.load(open(f)) for f in glob.glob(f"{ORIG}/{c}/*.json")}
itens, lancs, pessoas = load('itens'), load('lancamentos'), load('pessoas')
norm = lambda s: unicodedata.normalize('NFD', str(s or '')).encode('ascii', 'ignore').decode().upper().strip()
FAMILIAS = {'CABO':'Cabos','CABOS':'Cabos','CHAVE':'Chaves','FECHADURA':'Fechaduras','PLACA':'Placas','CHICOTE':'Chicotes','FONTE':'Fontes',
  'PEN':'Pen drives','GAME':'Games','MONITOR':'Monitores','NOTEIRO':'Noteiros','EXTENSAO':'Extensões','KIT':'Kits','INTERFACE':'Interfaces',
  'ADAPTADOR':'Adaptadores','MEMORIA':'Memórias','SSD':'Armazenamento','PLUG':'Plugs','COMPUTADOR':'Computadores','IMPRESSORA':'Impressoras',
  'LEITOR':'Leitores','BOTAO':'Botões','TECLADO':'Teclados','MOUSE':'Periféricos','HD':'Armazenamento','PE':'Peças','AUXILIADORAS':'Auxiliadoras','TINKERS':'Auxiliadoras'}
def categoria(desc):
    w = norm(desc).split()
    return FAMILIAS.get(w[0], 'Outros') if w else 'Outros'
txt = lambda v: '' if v is None else str(v).strip()
def local(j):
    e, p, c = txt(j.get('estante')), txt(j.get('pt')), txt(j.get('caixa'))
    partes = [f"Estante {e}" if e and e != '-' else '', p if p and p != '-' else '', f"Caixa {c}" if c and c != '-' else '']
    return ' · '.join(x for x in partes if x)
SETOR = {'MONTAGEM':'Montagem','MANUTENCAO':'Manutenção','OPERADOR':'OPERADOR','ESTOQUE':'Estoque','LOGISTICA':'Logística','COMERCIAL':'Comercial'}
docs = []   # (colecao, id, dados)
# operadores (pessoas do formulário)
ops = {}
for n, (pid, p) in enumerate(sorted(pessoas.items(), key=lambda kv: norm(kv[1].get('nome'))), start=1):
    nome = re.sub(r'\s+', ' ', txt(p.get('nome')).upper())
    o = {'matricula': f'OP-{n:03d}', 'nome': nome, 'setor': SETOR.get(norm(p.get('area')), txt(p.get('area')).title()), 'cargo': '',
         'status': 'Ativo', 'nivel': 'Gestor' if norm(nome) == 'LUIS ESTOQUE' else 'Solicitante', 'origem': 'Formulário'}
    ops[norm(nome)] = (pid, o); docs.append(('operadores', pid, o))
SISTEMA = {'CARGA INICIAL', 'CONTAGEM FISICA', 'TRANSFERENCIA INTERNA', 'INVENTARIO', '-', ''}
# itens
for iid, j in itens.items():
    docs.append(('itens', iid, {'sku': txt(j.get('sku')) or '-', 'nome': re.sub(r'\s+', ' ', txt(j.get('desc')).upper()), 'categoria': categoria(j.get('desc')),
        'unidade': 'un', 'qtd': float(j.get('saldo') or 0), 'minimo': float(j.get('minimo') or 0), 'valor': 0, 'local': local(j),
        'seriais': [txt(s) for s in (j.get('seriais') or []) if txt(s)], 'criadoEm': j.get('criadoEm') or j.get('alteradoEm') or '2026-11-08T00:00:00.000Z', 'origem': 'Formulário'}))
# movimentações, em ordem de tempo
ordem = sorted(lancs.items(), key=lambda kv: (kv[1].get('criadoEm') or '', kv[0]))
movs = []
for n, (lid, j) in enumerate(ordem, start=1):
    q = float(j.get('qtd') or 0); m = j.get('movim'); area = txt(j.get('area'))
    if m == 'Saída': tipo, qq = 'Saída', abs(q)
    elif m == 'Entrada': tipo, qq = 'Entrada', abs(q)
    elif norm(area) == 'ESTOQUE INICIAL' and q > 0: tipo, qq = 'Entrada', q
    else: tipo, qq = 'Ajuste', q
    sol = re.sub(r'\s+', ' ', txt(j.get('solicitante')).upper())
    op = ops.get(norm(sol)) if norm(sol) not in SISTEMA else None
    seriais = [txt(s) for s in (j.get('seriais') or []) if txt(s)]
    obs = [txt(j.get('obs'))]
    if seriais: obs.append('Seriais: ' + ', '.join(seriais))
    if txt(j.get('recebedor')): obs.append('Recebido por ' + txt(j.get('recebedor')))
    if j.get('estornadoPor'): obs.append('estornado no formulário')
    if j.get('status') == 'pendente': obs.append('pendente na planilha')
    origem = 'Formulário' + (' · Saldo inicial' if tipo == 'Entrada' and m == 'Saldo Inicial' else ' · Ajuste de contagem' if tipo == 'Ajuste' else '')
    it = itens.get(j.get('itemId'), {})
    movs.append([lid, {'n': n, 'tipo': tipo, 'itemId': txt(j.get('itemId')), 'sku': txt(j.get('sku')) or '-', 'nome': re.sub(r'\s+', ' ', txt(j.get('desc')).upper()),
        'unidade': 'un', 'qtd': qq, 'valorUnit': 0, 'valorTotal': 0,
        'destino': (txt(j.get('destino')) or SETOR.get(norm(area), area)) if tipo == 'Saída' else '',
        'operadorId': op[0] if op else '', 'operadorNome': sol if norm(sol) not in SISTEMA else '', 'operadorMatricula': op[1]['matricula'] if op else '',
        'nf': txt(j.get('nf')).strip('-'), 'os': txt(j.get('os')) if txt(j.get('os')) not in ('0000/00', '-') else '',
        'obs': ' · '.join(x for x in obs if x), 'origem': origem, 'dataHora': j.get('criadoEm'), 'saldoApos': 0}])
# saldo após cada movimentação: de trás para frente, partindo do saldo atual do item
delta = lambda d: -d['qtd'] if d['tipo'] == 'Saída' else d['qtd']
por_item = collections.defaultdict(list)
for x in movs: por_item[x[1]['itemId']].append(x[1])
for iid, lst in por_item.items():
    if iid in itens:
        corrente = float(itens[iid].get('saldo') or 0)
        for d in reversed(lst): d['saldoApos'] = corrente; corrente -= delta(d)
    else:
        corrente = 0
        for d in lst: corrente += delta(d); d['saldoApos'] = corrente
docs += [('movs', lid, d) for lid, d in movs]
docs.append(('config', 'geral', {'seq': {'mov': len(movs), 'req': 0}, 'integracao': {'planilha': '', 'aba': 'Respostas ao formulário 1', 'auto': False},
    'importacao': {'origem': 'Movimentação do Almoxarifado', 'em': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                   'itens': len(itens), 'operadores': len(pessoas), 'movs': len(movs)}}))
lotes = []
for k in range(0, len(docs), 50):
    lote = []
    for col, did, dados in docs[k:k + 50]:
        f = f"{OUT}/{col}__{did}.json"; json.dump(dados, open(f, 'w'), ensure_ascii=False); lote.append({'op': 'set', 'collection': col, 'doc_id': did, 'file_path': f})
    lotes.append(lote)
json.dump(lotes, open(f"{OUT}/_lotes.json", 'w'), ensure_ascii=False)
c = collections.Counter(col for col, _, _ in docs); print('documentos:', dict(c), '| lotes:', len(lotes))
print('categorias:', collections.Counter(d['categoria'] for col, _, d in docs if col == 'itens').most_common())
print('tipos mov:', collections.Counter(d['tipo'] for _, d in movs), '| saidas sem destino:', sum(1 for _, d in movs if d['tipo'] == 'Saída' and not d['destino']))
print('saidas com operador cadastrado:', sum(1 for _, d in movs if d['tipo'] == 'Saída' and d['operadorId']), 'de', sum(1 for _, d in movs if d['tipo'] == 'Saída'))
print('ids válidos:', all(re.fullmatch(r'[A-Za-z0-9_\-.~:@+]{1,200}', did) for _, did, _ in docs))
print('exemplo item:', next(d for col, _, d in docs if col == 'itens'))
print('exemplo mov saida:', next(d for _, d in movs if d['tipo'] == 'Saída'))
