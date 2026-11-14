'use strict';
/* Controle de estoque: valor investido, curva ABC, idade, ficha (kardex) e inventário. */

const diasTxt = (d) => (d == null ? '—' : `${num(d)} dia${d === 1 ? '' : 's'}`);
const tagClasse = (c) => (c ? `<span class="tag tag-abc-${c}">${c}</span>` : '—');

function graficoLinha(dados, { valor = (d) => d.valor, fmt = brl, rotulo = (d) => dia(d.dia).slice(0, 5) } = {}) {
  if (!dados.length) return '<p class="vazio">Sem dados.</p>';
  const L = 760, A = 220, mE = 62, mB = 26, mT = 10;
  const vs = dados.map(valor);
  const max = Math.max(...vs, 1);
  const bruto = max / 4;
  const ordem = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map((f) => f * ordem).find((s) => s >= bruto);
  const topo = passo * 4;
  const x = (i) => mE + ((L - mE - 6) * i) / Math.max(dados.length - 1, 1);
  const y = (v) => mT + (A - mT - mB) * (1 - v / topo);
  const grade = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const v = topo * f;
    const t = v >= 1000 ? `${(v / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}k` : num(Math.round(v));
    return `<line class="grade" x1="${mE}" x2="${L}" y1="${y(v)}" y2="${y(v)}"/><text class="eixo" x="${mE - 8}" y="${y(v) + 4}" text-anchor="end">${t}</text>`;
  }).join('');
  const pts = vs.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const cada = Math.ceil(dados.length / 10);
  const rot = dados.map((d, i) => (i % cada === 0 ? `<text class="eixo" x="${x(i)}" y="${A - 8}" text-anchor="middle">${esc(rotulo(d))}</text>` : '')).join('');
  const pontos = dados.map((d, i) => `<circle class="ponto" cx="${x(i)}" cy="${y(vs[i])}" r="6"><title>${esc(dia(d.dia))}: ${esc(fmt(vs[i]))}</title></circle>`).join('');
  return `<div class="grafico"><svg viewBox="0 0 ${L} ${A}" role="img" aria-label="Gráfico de linha">${grade}
    <polygon class="area" points="${x(0)},${y(0)} ${pts} ${x(dados.length - 1)},${y(0)}"/><polyline class="linha" points="${pts}"/>${pontos}${rot}</svg></div>`;
}

/* =========================================================================
   Painel do valor do estoque
   ========================================================================= */
const est = { filtro: 'com', ordem: 'valor', categoria: '' };

async function paginaEstoque() {
  const d = await api('GET', '/api/estoque/painel');
  const r = d.resumo;
  const f = d.fluxo_mes;
  const totalAbc = d.classes.reduce((a, c) => a + c.valor, 0) || 1;
  $('#conteudo').innerHTML = `
    <div class="ferramentas nao-imprimir"><span class="sutil">Quanto dinheiro você tem parado em produtos, onde ele está e há quanto tempo.</span><span class="espaco"></span>
      <a class="btn" href="#/inventario">Fazer inventário</a><button class="btn" id="e-imp">Imprimir</button></div>
    <div class="so-impressao"><h2>${esc(estado.meta.config.nome_loja)}: posição do estoque em ${dia(isoLocal(new Date()))}</h2></div>
    <div class="kpis">
      <div class="kpi destaque-kpi"><span>Valor investido em estoque (custo)</span><strong>${brl(r.valor_custo)}</strong><small>${num(r.unidades)} unidades em ${num(r.com_estoque)} produtos</small></div>
      <div class="kpi"><span>Valor de venda do estoque</span><strong>${brl(r.valor_venda)}</strong><small>se vender tudo pelo preço de tabela</small></div>
      <div class="kpi bom"><span>Lucro potencial</span><strong>${brl(r.lucro_potencial)}</strong><small>margem de ${pct(r.margem)}</small></div>
      <div class="kpi ${r.parado_90_valor ? 'alerta' : ''}"><span>Parado há mais de 90 dias</span><strong>${brl(r.parado_90_valor)}</strong><small>${r.valor_custo ? pct((100 * r.parado_90_valor) / r.valor_custo) : '0%'} do valor investido</small></div>
    </div>
    <div class="kpis">
      <div class="kpi"><span>Idade média do estoque</span><strong>${diasTxt(r.idade_media)}</strong><small>ponderada pelo valor</small></div>
      <div class="kpi"><span>Cobertura do estoque</span><strong>${r.cobertura_dias != null ? diasTxt(r.cobertura_dias) : '—'}</strong><small>dura isso no ritmo de vendas dos últimos 90 dias</small></div>
      <div class="kpi"><span>Comprado este mês</span><strong>${brl(f.comprado)}</strong><small>saiu em vendas: ${brl(f.vendido_custo)} (custo)</small></div>
      <div class="kpi ${f.baixas_custo ? 'alerta' : ''}"><span>Perdas e baixas no mês</span><strong>${brl(f.baixas_custo)}</strong><small>avarias, garantia, uso interno, ajustes</small></div>
    </div>
    <section class="cartao"><div class="cartao-cab"><h2>Evolução do valor investido <small>últimos 90 dias</small></h2></div>${graficoLinha(d.historico)}</section>
    <div class="duas-iguais">
      <section class="cartao"><div class="cartao-cab"><h2>Onde está o dinheiro: por categoria</h2></div>${barrasH(d.por_categoria, { valor: (l) => l.valor_custo, fmt: (v) => brl(v), rotulo: (l) => `${l.chave} · ${pct(l.pct)} · ${num(l.unidades)} un.` })}</section>
      <section class="cartao"><div class="cartao-cab"><h2>Por marca</h2></div>${barrasH(d.por_marca.slice(0, 10), { valor: (l) => l.valor_custo, rotulo: (l) => `${l.chave} · ${pct(l.pct)}` })}</section>
    </div>
    <div class="duas-iguais">
      <section class="cartao"><div class="cartao-cab"><h2>Idade do estoque <small>tempo desde a entrada de cada unidade</small></h2></div>${barrasH(d.faixas, { valor: (l) => l.valor, rotulo: (l) => `${l.faixa} · ${num(l.unidades)} un.` })}</section>
      <section class="cartao"><div class="cartao-cab"><h2>Curva ABC do estoque</h2></div>
        <div class="abc">${d.classes.map((c) => `<div class="abc-${c.classe}"><b>${c.classe}</b><strong>${brl(c.valor)}</strong><small>${num(c.produtos)} produto(s) · ${pct((100 * c.valor) / totalAbc)}</small></div>`).join('')}</div>
        <p class="sutil" style="margin:12px 0 0;font-size:13px"><b>A</b>: os poucos produtos que concentram 80% do dinheiro; confira e negocie estes primeiro. <b>B</b>: os próximos 15%. <b>C</b>: muitos itens baratos que somam só 5%.</p>
        ${barrasH(d.por_condicao, { valor: (l) => l.valor_custo, rotulo: (l) => `${l.chave} · ${num(l.unidades)} un.` }).replace('class="hbarras"', 'class="hbarras" style="margin-top:14px"')}</section>
    </div>
    <section class="cartao sem-pad" id="e-tab"></section>`;
  $('#e-imp').addEventListener('click', () => window.print());

  const filtros = {
    com: ['Com estoque', (p) => p.estoque_atual > 0],
    parado: ['Parados +90 dias', (p) => p.parado],
    A: ['Classe A', (p) => p.classe === 'A'],
    baixo: ['Abaixo do mínimo', (p) => p.estoque_minimo > 0 && p.estoque_atual <= p.estoque_minimo],
    zerados: ['Zerados', (p) => p.estoque_atual === 0],
    todos: ['Todos', () => true],
  };
  const ordens = {
    valor: ['Maior valor investido', (a, b) => b.valor_custo - a.valor_custo],
    idade: ['Mais antigos', (a, b) => (b.idade_media ?? -1) - (a.idade_media ?? -1)],
    semvenda: ['Mais tempo sem vender', (a, b) => (b.dias_sem_venda ?? 1e9) - (a.dias_sem_venda ?? 1e9)],
    lucro: ['Maior lucro potencial', (a, b) => b.lucro_potencial - a.lucro_potencial],
    margem: ['Menor margem', (a, b) => (a.margem ?? 999) - (b.margem ?? 999)],
    cobertura: ['Maior cobertura', (a, b) => (b.cobertura_dias ?? 1e9) - (a.cobertura_dias ?? 1e9)],
    nome: ['Nome', (a, b) => a.nome.localeCompare(b.nome)],
  };
  const cols = [
    { r: 'Produto', v: (p) => p.nome, h: (p) => `<div class="celula-produto"><strong>${esc(p.nome)}</strong><small>${esc([p.codigo, p.categoria, p.condicao, p.localizacao].filter(Boolean).join(' · '))}</small></div>` },
    { r: 'ABC', v: (p) => p.classe || '', h: (p) => tagClasse(p.classe) },
    { r: 'Qtd', v: (p) => p.estoque_atual, h: (p) => `<span class="estoque ${p.estoque_atual === 0 ? 'zero' : p.estoque_atual <= p.estoque_minimo ? 'baixo' : ''}">${num(p.estoque_atual)}</span>`, cls: 'num' },
    { r: 'Custo médio', v: (p) => p.preco_custo, h: (p) => brl(p.preco_custo), cls: 'num' },
    { r: 'Valor investido', v: (p) => p.valor_custo, h: (p) => `<strong>${brl(p.valor_custo)}</strong>`, cls: 'num' },
    { r: '% do estoque', v: (p) => p.pct, h: (p) => (p.pct ? pct(p.pct) : '—'), cls: 'num' },
    { r: 'Valor de venda', v: (p) => p.valor_venda, h: (p) => brl(p.valor_venda), cls: 'num' },
    { r: 'Lucro potencial', v: (p) => p.lucro_potencial, h: (p) => brl(p.lucro_potencial), cls: 'num' },
    { r: 'Margem', v: (p) => p.margem ?? '', h: (p) => (p.margem != null ? `<span class="${p.margem < 10 ? 'estoque baixo' : ''}">${pct(p.margem)}</span>` : '—'), cls: 'num' },
    { r: 'Idade média', v: (p) => p.idade_media ?? '', h: (p) => (p.idade_media != null ? `<span class="${p.idade_media > 90 ? 'estoque baixo' : ''}">${diasTxt(p.idade_media)}</span>` : '—'), cls: 'num' },
    { r: 'Sem vender há', v: (p) => p.dias_sem_venda ?? 'nunca vendeu', h: (p) => (p.dias_sem_venda != null ? diasTxt(p.dias_sem_venda) : '<small class="sutil">nunca vendeu</small>'), cls: 'num' },
    { r: 'Vendidos 90d', v: (p) => p.vendidos_90d, cls: 'num' },
    { r: 'Cobertura', v: (p) => p.cobertura_dias ?? '', h: (p) => (p.cobertura_dias != null ? diasTxt(p.cobertura_dias) : '—'), cls: 'num' },
  ];
  const cats = [...new Set(d.produtos.map((p) => p.categoria))].sort();
  const desenhar = () => {
    const linhas = d.produtos.filter(filtros[est.filtro][1]).filter((p) => !est.categoria || p.categoria === est.categoria).sort(ordens[est.ordem][1]);
    const soma = (k) => linhas.reduce((a, p) => a + (p[k] || 0), 0);
    $('#e-tab').innerHTML = `<div class="cartao-cab"><h2>Estoque detalhado por produto <small>${num(linhas.length)} produto(s)</small></h2>
        <div class="ferramentas nao-imprimir" style="margin:0">
          <select id="e-cat"><option value="">Todas as categorias</option>${cats.map((c) => `<option ${c === est.categoria ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
          <select id="e-ord">${Object.entries(ordens).map(([k, [t]]) => `<option value="${k}" ${k === est.ordem ? 'selected' : ''}>Ordenar: ${t}</option>`).join('')}</select>
          <button class="btn btn-p" id="e-csv">Exportar CSV</button></div></div>
      <div class="chips nao-imprimir" style="padding:0 18px 8px">${Object.entries(filtros).map(([k, [t]]) => `<button class="chip ${k === est.filtro ? 'ativo' : ''}" data-f="${k}">${t}</button>`).join('')}</div>
      ${tabela(cols, linhas, { clique: true, vazio: 'Nenhum produto neste filtro.', rodape: ['Total', '', num(soma('estoque_atual')), '', brl(soma('valor_custo')), '', brl(soma('valor_venda')), brl(soma('lucro_potencial')), '', '', '', num(soma('vendidos_90d')), ''] })}`;
    ligarCliques($('#e-tab'), linhas, (p) => { location.hash = `#/produtos/${p.id}`; });
    $$('[data-f]', $('#e-tab')).forEach((b) => b.addEventListener('click', () => { est.filtro = b.dataset.f; desenhar(); }));
    $('#e-cat').addEventListener('change', (e) => { est.categoria = e.target.value; desenhar(); });
    $('#e-ord').addEventListener('change', (e) => { est.ordem = e.target.value; desenhar(); });
    $('#e-csv').addEventListener('click', () => baixarCSV(`estoque-detalhado-${isoLocal(new Date())}`, cols, linhas));
  };
  desenhar();
}

/* =========================================================================
   Ficha do produto: unidades em estoque e kardex
   ========================================================================= */
async function fichaProduto(p, el) {
  const f = await api('GET', `/api/produtos/${p.id}/ficha`);
  const imei = !!p.controla_imei;
  const colsUn = [
    ...(imei ? [{ r: 'IMEI', v: (u) => u.imei, h: (u) => `<span class="mono">${esc(u.imei)}</span>` }] : [{ r: 'Qtd', v: (u) => u.quantidade, cls: 'num' }]),
    { r: 'Entrada', v: (u) => dia(u.data), h: (u) => (u.entrada_id ? `<a href="#/movimentacoes/${u.entrada_id}">${dia(u.data)}</a>` : '—') },
    { r: 'Fornecedor', v: (u) => u.fornecedor || '' },
    { r: 'Na loja há', v: (u) => u.dias ?? '', h: (u) => `<span class="${u.dias > 90 ? 'estoque baixo' : ''}">${diasTxt(u.dias)}</span>`, cls: 'num' },
    { r: imei ? 'Custo deste aparelho' : 'Custo da compra', v: (u) => u.custo, h: (u) => brl(u.custo), cls: 'num' },
    ...(imei ? [{ r: 'Lucro se vender a ' + brl(p.preco_venda), v: (u) => u.preco_venda - u.custo, h: (u) => `<span class="${u.preco_venda - u.custo < 0 ? 'estoque baixo' : ''}">${brl(u.preco_venda - u.custo)}</span>`, cls: 'num' }] : []),
  ];
  const colsK = [
    { r: 'Data', v: (k) => dataHora(k.data), h: (k) => `<a href="#/movimentacoes/${k.id}">${esc(dataHora(k.data))}</a>` },
    { r: 'Movimento', v: (k) => `${nomeTipo(k.tipo)} — ${k.motivo}`, h: (k) => `${tagTipo(k)} ${esc(k.motivo)}${k.documento ? ` <small class="sutil">${esc(k.documento)}</small>` : ''}` },
    { r: 'Cliente / fornecedor', v: (k) => k.parceiro || '' },
    { r: 'Entrada', v: (k) => (k.tipo === 'entrada' ? k.quantidade : ''), h: (k) => (k.tipo === 'entrada' ? `<span class="txt-entrada">+${num(k.quantidade)}</span>` : ''), cls: 'num' },
    { r: 'Saída', v: (k) => (k.tipo === 'saida' ? k.quantidade : ''), h: (k) => (k.tipo === 'saida' ? `<span class="txt-saida">−${num(k.quantidade)}</span>` : ''), cls: 'num' },
    { r: 'Saldo', v: (k) => k.saldo_qtd, h: (k) => `<strong>${num(k.saldo_qtd)}</strong>`, cls: 'num' },
    { r: 'Custo un.', v: (k) => k.custo_unitario, h: (k) => brl(k.custo_unitario), cls: 'num' },
    { r: 'Valor do movimento', v: (k) => k.valor_mov, h: (k) => brl(k.valor_mov), cls: 'num' },
    { r: 'Saldo em R$', v: (k) => k.saldo_valor, h: (k) => `<strong>${brl(k.saldo_valor)}</strong>`, cls: 'num' },
    { r: 'Custo médio', v: (k) => k.custo_medio, h: (k) => brl(k.custo_medio), cls: 'num' },
  ];
  const kardex = [...f.kardex].reverse();
  el.innerHTML = `
    ${cartaoTabela('f-un', imei ? `Aparelhos em estoque (${f.camadas.length})` : 'Lotes que formam o saldo atual', colsUn, f.camadas, { csv: true, vazio: 'Sem unidades em estoque.', sub: imei ? 'custo real de cada unidade' : 'pelas compras mais recentes (PEPS)' })}
    ${cartaoTabela('f-k', 'Ficha de estoque (kardex)', colsK, kardex, { csv: true, vazio: 'Sem movimentações.', sub: 'do mais recente ao mais antigo, com saldo em quantidade e em valor' })}`;
  ligarCSV(el, {
    'f-un': [`unidades-${p.id}`, colsUn, f.camadas],
    'f-k': [`kardex-${p.codigo || p.id}`, colsK, f.kardex],
  });
}

/* =========================================================================
   Inventário (contagem física)
   ========================================================================= */
async function paginaInventario(param) {
  if (param) return contagemInventario(+param);
  const lista = await api('GET', '/api/inventarios');
  const aberto = lista.find((v) => v.status === 'aberto');
  const st = { aberto: ['Em contagem', 'tag-saida'], finalizado: ['Finalizado', 'tag-entrada'], cancelado: ['Cancelado', 'tag-perigo'] };
  const cols = [
    { r: 'Nº', v: (v) => v.id, h: (v) => `<strong>#${v.id}</strong>` },
    { r: 'Início', v: (v) => dataHora(v.criado_em) },
    { r: 'Abrangência', v: (v) => v.categoria || 'Todo o estoque' },
    { r: 'Situação', v: (v) => st[v.status][0], h: (v) => `<span class="tag ${st[v.status][1]}">${st[v.status][0]}</span>` },
    { r: 'Contados', v: (v) => `${v.resumo.contados}/${v.resumo.produtos}`, cls: 'num' },
    { r: 'Faltas', v: (v) => v.resumo.falta_valor, h: (v) => (v.resumo.falta_unidades ? `<span class="estoque baixo">${num(v.resumo.falta_unidades)} un. · ${brl(v.resumo.falta_valor)}</span>` : '—'), cls: 'num' },
    { r: 'Sobras', v: (v) => v.resumo.sobra_valor, h: (v) => (v.resumo.sobra_unidades ? `${num(v.resumo.sobra_unidades)} un. · ${brl(v.resumo.sobra_valor)}` : '—'), cls: 'num' },
    { r: 'Responsável', v: (v) => v.usuario_nome },
  ];
  $('#conteudo').innerHTML = `
    <div class="faixa faixa-info">Conte o que existe fisicamente na loja e compare com o sistema. Use o leitor de código de barras: cada leitura soma 1 ao produto, e para celulares cada IMEI lido marca o aparelho como encontrado. Ao finalizar, as faltas e sobras viram <b>ajustes de inventário</b> e o estoque fica igual ao contado.</div>
    <div class="ferramentas"><span class="espaco"></span>${aberto ? `<a class="btn btn-primario" href="#/inventario/${aberto.id}">Continuar contagem #${aberto.id}</a>` : '<button class="btn btn-primario" id="inv-novo">+ Iniciar inventário</button>'}</div>
    ${cartaoTabela('inv-lista', 'Inventários', cols, lista, { clique: true, vazio: 'Nenhum inventário feito ainda.' })}`;
  ligarCliques($('#inv-lista'), lista, (v) => { location.hash = `#/inventario/${v.id}`; });
  $('#inv-novo')?.addEventListener('click', () => abrirForm({
    titulo: 'Iniciar inventário',
    campos: [
      { n: 'categoria', r: 'O que contar', t: 'select', vazio: 'Todo o estoque', opts: estado.meta.categorias, col2: true, ajuda: 'Dá para contar por partes, por exemplo só Acessórios hoje e Smartphones amanhã.' },
      { n: 'observacao', r: 'Observação', col2: true },
    ],
    textoBotao: 'Iniciar contagem',
    salvar: async (dd) => { const r = await api('POST', '/api/inventarios', dd); fecharModal(); location.hash = `#/inventario/${r.id}`; },
  }));
}

async function contagemInventario(id) {
  let inv = await api('GET', `/api/inventarios/${id}`);
  const aberto = inv.status === 'aberto';
  $('#titulo-pagina').textContent = `Inventário #${inv.id}`;
  const ui = { filtro: aberto ? 'todos' : 'diferenca', q: '' };
  $('#conteudo').innerHTML = `
    <div class="ferramentas nao-imprimir"><a class="btn" href="#/inventario">← Inventários</a><span class="espaco"></span>
      <button class="btn" id="inv-imp">Imprimir folha</button>
      ${aberto ? '<button class="btn btn-perigo" id="inv-cancelar">Cancelar</button><button class="btn btn-primario" id="inv-final">Finalizar e ajustar estoque</button>' : ''}
      ${inv.saida_id ? `<a class="btn" href="#/movimentacoes/${inv.saida_id}">Ajuste de faltas #${inv.saida_id}</a>` : ''}
      ${inv.entrada_id ? `<a class="btn" href="#/movimentacoes/${inv.entrada_id}">Ajuste de sobras #${inv.entrada_id}</a>` : ''}</div>
    <div class="so-impressao"><h2>${esc(estado.meta.config.nome_loja)}: inventário #${inv.id} (${esc(inv.categoria || 'todo o estoque')}), ${dia(inv.criado_em)}</h2></div>
    <div id="inv-kpis" class="kpis"></div>
    ${aberto ? `<section class="cartao nao-imprimir"><form id="inv-scan" class="linha-input"><input id="inv-leitor" autocomplete="off" placeholder="Leia o código de barras ou IMEI (soma 1 a cada leitura)…" style="font-size:16px;padding:12px 14px"><button class="btn btn-primario">Contar</button></form><p class="sutil" id="inv-ultimo" style="margin:8px 0 0;min-height:1.5em"></p></section>` : ''}
    <section class="cartao sem-pad"><div class="cartao-cab"><h2>Itens</h2>
      <div class="ferramentas nao-imprimir" style="margin:0"><input type="search" id="inv-q" placeholder="Filtrar produto ou local"></div></div>
      <div class="chips nao-imprimir" id="inv-chips" style="padding:0 18px 8px"></div><div id="inv-itens"></div></section>`;

  const porId = () => Object.fromEntries(inv.itens.map((i) => [i.produto_id, i]));
  function kpis() {
    const r = inv.resumo;
    $('#inv-kpis').innerHTML = `
      <div class="kpi"><span>Contados</span><strong>${num(r.contados)} / ${num(r.produtos)}</strong><small>valor esperado ${brl(r.valor_esperado)}</small></div>
      <div class="kpi ${r.falta_unidades ? 'alerta' : ''}"><span>Faltas</span><strong>${brl(r.falta_valor)}</strong><small>${num(r.falta_unidades)} unidade(s)</small></div>
      <div class="kpi"><span>Sobras</span><strong>${brl(r.sobra_valor)}</strong><small>${num(r.sobra_unidades)} unidade(s)</small></div>
      <div class="kpi ${r.sobra_valor - r.falta_valor < 0 ? 'alerta' : 'bom'}"><span>Resultado</span><strong>${brl(r.sobra_valor - r.falta_valor)}</strong><small>${num(r.com_diferenca)} produto(s) com diferença</small></div>`;
  }
  const filtros = {
    todos: ['Todos', () => true], pendentes: ['Não contados', (i) => i.contado == null],
    diferenca: ['Com diferença', (i) => i.diferenca], ok: ['Conferidos', (i) => i.contado != null && !i.diferenca],
  };
  let salvando = Promise.resolve();
  async function salvar(item) {
    salvando = salvando.then(async () => {
      try {
        inv = await api('PUT', `/api/inventarios/${id}/contagem`, { itens: [item] });
        kpis();
        const novo = porId()[item.produto_id];
        const linha = $(`[data-linha="${item.produto_id}"]`);
        if (linha && novo) {
          $('.dif', linha).innerHTML = htmlDif(novo);
          const ci = $('.contado-imei', linha);
          if (ci) ci.textContent = novo.contado ?? '—';
        }
      } catch (e) { avisar(e.message, 'erro'); }
    });
    return salvando;
  }
  const htmlDif = (i) => (i.diferenca == null ? '<small class="sutil">não contado</small>' : i.diferenca === 0 ? '<span class="tag tag-entrada">OK</span>'
    : `<strong class="${i.diferenca < 0 ? 'estoque baixo' : 'txt-entrada'}">${i.diferenca > 0 ? '+' : ''}${num(i.diferenca)}</strong><br><small>${brl(i.valor_diferenca)}</small>`);
  function desenhar() {
    $('#inv-chips').innerHTML = Object.entries(filtros).map(([k, [t, fn]]) => `<button class="chip ${k === ui.filtro ? 'ativo' : ''}" data-f="${k}">${t} (${inv.itens.filter(fn).length})</button>`).join('');
    $$('#inv-chips [data-f]').forEach((b) => b.addEventListener('click', () => { ui.filtro = b.dataset.f; desenhar(); }));
    const q = ui.q.toLowerCase();
    const linhas = inv.itens.filter(filtros[ui.filtro][1]).filter((i) => !q || `${i.nome} ${i.codigo || ''} ${i.localizacao || ''}`.toLowerCase().includes(q));
    $('#inv-itens').innerHTML = `<div class="tabela-wrap"><table><thead><tr><th>Local</th><th>Produto</th><th class="num">No sistema</th><th class="num">Contado</th><th class="num">Diferença</th></tr></thead><tbody>
      ${linhas.length ? linhas.map((i) => {
        const imeisHtml = i.controla_imei ? `<div class="imeis-lista" style="margin-top:6px">${[...i.imeis_esperados, ...i.imeis_contados.filter((x) => !i.imeis_esperados.includes(x))].map((x) => {
          const achou = i.imeis_contados.includes(x);
          const extra = !i.imeis_esperados.includes(x);
          return `<label class="imei-op ${extra ? 'imei-extra' : ''}" title="${extra ? 'Encontrado, mas não constava no sistema' : ''}"><input type="checkbox" data-imei="${i.produto_id}" value="${esc(x)}" ${achou ? 'checked' : ''} ${aberto ? '' : 'disabled'}>${esc(x)}</label>`;
        }).join('')}</div>` : '';
        return `<tr data-linha="${i.produto_id}"><td>${esc(i.localizacao || '—')}</td>
          <td><div class="celula-produto"><strong>${esc(i.nome)}</strong><small>${esc([i.codigo, i.categoria].filter(Boolean).join(' · '))}</small></div>${imeisHtml}</td>
          <td class="num">${num(i.esperado)}</td>
          <td class="num">${i.controla_imei ? `<strong class="contado-imei">${i.contado ?? '—'}</strong>` : aberto ? `<input class="qtd" type="number" min="0" step="1" data-cont="${i.produto_id}" value="${i.contado ?? ''}">` : num(i.contado ?? '—')}<span class="so-impressao">________</span></td>
          <td class="num dif">${htmlDif(i)}</td></tr>`;
      }).join('') : '<tr><td class="vazio" colspan="5">Nada neste filtro.</td></tr>'}</tbody></table></div>`;
    $$('[data-cont]').forEach((inp) => inp.addEventListener('change', () => {
      const i = porId()[+inp.dataset.cont];
      salvar({ produto_id: i.produto_id, contado: inp.value });
    }));
    $$('[data-imei]').forEach((cb) => cb.addEventListener('change', () => {
      const i = porId()[+cb.dataset.imei];
      const set = new Set(i.imeis_contados);
      if (cb.checked) set.add(cb.value); else set.delete(cb.value);
      i.imeis_contados = [...set];
      salvar({ produto_id: i.produto_id, imeis: i.imeis_contados, contado: i.imeis_contados.length });
    }));
  }
  $('#inv-q').addEventListener('input', (e) => { ui.q = e.target.value.trim(); desenhar(); });
  $('#inv-imp').addEventListener('click', () => window.print());
  $('#inv-scan')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const leitor = $('#inv-leitor');
    const termo = leitor.value.trim();
    leitor.value = '';
    leitor.focus();
    if (!termo) return;
    const digitos = termo.replace(/\D/g, '');
    let alvo = inv.itens.find((i) => i.codigo && i.codigo.toLowerCase() === termo.toLowerCase());
    if (alvo && !alvo.controla_imei) {
      await salvar({ produto_id: alvo.produto_id, contado: (alvo.contado || 0) + 1 });
      const n = porId()[alvo.produto_id];
      $('#inv-ultimo').innerHTML = `✓ <b>${esc(n.nome)}</b>: ${num(n.contado)} contado(s) de ${num(n.esperado)}`;
      desenhar();
      return;
    }
    if (digitos.length === 15) {
      alvo = inv.itens.find((i) => i.imeis_esperados.includes(digitos));
      if (!alvo) {
        try {
          const r = await api('GET', `/api/imeis/${digitos}`);
          alvo = r.atual && porId()[r.atual.produto_id];
        } catch { /* não cadastrado */ }
      }
      if (!alvo) { $('#inv-ultimo').innerHTML = `<span class="estoque baixo">IMEI ${esc(digitos)} não pertence a nenhum produto deste inventário. Dê entrada nele antes.</span>`; return; }
      const set = new Set(alvo.imeis_contados);
      const repetido = set.has(digitos);
      set.add(digitos);
      await salvar({ produto_id: alvo.produto_id, imeis: [...set], contado: set.size });
      const n = porId()[alvo.produto_id];
      $('#inv-ultimo').innerHTML = `${repetido ? 'Já contado:' : '✓'} <b>${esc(n.nome)}</b> IMEI ${esc(digitos)}${n.imeis_esperados.includes(digitos) ? '' : ' <span class="estoque baixo">(não constava no sistema)</span>'} · ${num(n.contado)} de ${num(n.esperado)}`;
      desenhar();
      return;
    }
    ui.q = termo;
    $('#inv-q').value = termo;
    $('#inv-ultimo').textContent = alvo ? 'Este produto controla IMEI: leia o IMEI de cada aparelho.' : 'Código não encontrado; filtrando a lista pelo texto digitado.';
    desenhar();
  });
  $('#inv-cancelar')?.addEventListener('click', async () => {
    if (!confirm('Cancelar este inventário? Nada no estoque será alterado.')) return;
    try { await api('POST', `/api/inventarios/${id}/cancelar`); avisar('Inventário cancelado.', 'ok'); rotear(); } catch (e) { avisar(e.message, 'erro'); }
  });
  $('#inv-final')?.addEventListener('click', async () => {
    await salvando;
    const r = inv.resumo;
    const pend = r.produtos - r.contados;
    abrirForm({
      titulo: `Finalizar inventário #${id}`,
      campos: [],
      extra: `<div class="totais">
          <div><span>Produtos contados</span><span>${num(r.contados)} de ${num(r.produtos)}</span></div>
          <div><span>Faltas (saem do estoque)</span><span class="estoque baixo">${num(r.falta_unidades)} un. · ${brl(r.falta_valor)}</span></div>
          <div><span>Sobras (entram no estoque)</span><span>${num(r.sobra_unidades)} un. · ${brl(r.sobra_valor)}</span></div></div>
        ${pend ? `<p class="faixa faixa-alerta" style="margin-top:12px">${num(pend)} produto(s) não foram contados e ficam como estão.</p>` : ''}
        <p class="sutil" style="margin-top:12px">O sistema vai lançar os ajustes de inventário e o estoque passa a ser o que foi contado.</p>`,
      textoBotao: 'Finalizar e ajustar',
      salvar: async () => { await api('POST', `/api/inventarios/${id}/finalizar`); fecharModal(); avisar('Inventário finalizado e estoque ajustado.', 'ok'); rotear(); },
    });
  });
  kpis();
  desenhar();
  $('#inv-leitor')?.focus();
}

Object.assign(ROTAS, {
  estoque: { t: 'Valor do estoque', f: paginaEstoque, admin: true },
  inventario: { t: 'Inventário', f: paginaInventario, admin: true },
});
