// Pequenos comportamentos das telas (o app funciona sem JavaScript; isto só agiliza).
document.addEventListener('click', (e) => {
  const c = e.target.closest('[data-confirm]');
  if (c && !confirm(c.dataset.confirm)) { e.preventDefault(); e.stopPropagation(); }
  // fecha o menu "Mais" ao clicar fora
  document.querySelectorAll('nav.tabs details[open]').forEach((d) => { if (!d.contains(e.target)) d.removeAttribute('open'); });
  // + Adicionar linha (NF, pedidos, itens novos): clona o modelo
  const add = e.target.closest('[data-add-linha]');
  if (add) {
    const alvo = document.getElementById(add.dataset.addLinha);
    const modelo = alvo.querySelector('.linha-item, tr.linha');
    const nova = modelo.cloneNode(true);
    nova.querySelectorAll('input, textarea, select').forEach((i) => { if (i.type !== 'hidden') i.value = i.dataset.padrao || ''; });
    (modelo.parentNode).appendChild(nova);
    const f = nova.querySelector('input'); if (f) f.focus();
  }
  if (e.target.closest('[data-imprimir]')) window.print();
  const rem = e.target.closest('[data-remover-linha]');
  if (rem) {
    const linha = rem.closest('.linha-item, tr.linha');
    if (linha.parentNode.querySelectorAll('.linha-item, tr.linha').length > 1) linha.remove();
  }
});
// Empréstimo: liga/desliga a data de devolução
document.addEventListener('change', (e) => {
  if (e.target.id === 'emprestimo') { const d = document.getElementById('devolver_ate'); d.disabled = !e.target.checked; d.required = e.target.checked; if (e.target.checked) d.focus(); }
  if (e.target.name === 'modo') document.querySelectorAll('[data-modo]').forEach((b) => { b.hidden = b.dataset.modo !== e.target.value; });
  if (e.target.matches('.serials input, #sem_serial')) {
    const n = document.querySelectorAll('.serials input:checked').length + (Number((document.getElementById('sem_serial') || {}).value) || 0)
      + (document.getElementById('seriais_extra') ? document.getElementById('seriais_extra').value.split(/[\n,]/).filter((s) => s.trim()).length : 0);
    const q = document.getElementById('qtd'); if (q && n) q.value = n;
  }
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'seriais_extra') e.target.dispatchEvent(new Event('change', { bubbles: true }));
});
