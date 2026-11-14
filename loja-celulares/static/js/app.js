'use strict';

/* =========================================================================
   Utilidades
   ========================================================================= */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const brl = (v) => Number(v || 0).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const num = (v) => Number(v || 0).toLocaleString('pt-BR');
const pct = (v) => `${Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`;
const dataHora = (s) => (s ? new Date(s.replace(' ', 'T')).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : '');
const dia = (s) => (s ? s.slice(0, 10).split('-').reverse().join('/') : '');
const isoLocal = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const paraNumero = (v) => { const n = parseFloat(String(v ?? '').replace(/\./g, (m, i, s) => (s.includes(',') ? '' : m)).replace(',', '.')); return Number.isFinite(n) ? n : 0; };
const nomeTipo = (t) => (t === 'entrada' ? 'Entrada' : 'Saída');
const tagTipo = (m) => `<span class="tag tag-${m.tipo}">${m.tipo === 'entrada' ? '↓ Entrada' : '↑ Saída'}</span>`;

const estado = { usuario: null, meta: null, periodo: null };
const ehAdmin = () => estado.usuario?.perfil === 'admin';

async function api(metodo, url, corpo) {
  const op = { method: metodo, headers: {}, credentials: 'same-origin' };
  if (corpo !== undefined) { op.headers['Content-Type'] = 'application/json'; op.body = JSON.stringify(corpo); }
  let r;
  try { r = await fetch(url, op); } catch { throw new Error('Sem conexão com o servidor.'); }
  const dados = await r.json().catch(() => ({}));
  if (r.status === 401 && url !== '/api/login') { mostrarLogin(); throw new Error(dados.erro || 'Entre novamente.'); }
  if (!r.ok) throw new Error(dados.erro || `Erro ${r.status}`);
  return dados;
}

function avisar(msg, tipo = '') {
  const el = document.createElement('div');
  el.className = `aviso ${tipo}`;
  el.textContent = msg;
  $('#avisos').append(el);
  setTimeout(() => el.remove(), tipo === 'erro' ? 6000 : 3500);
}

function qs(obj) {
  const p = new URLSearchParams();
  Object.entries(obj).forEach(([k, v]) => { if (v !== '' && v != null && v !== false) p.set(k, v === true ? '1' : v); });
  const s = p.toString();
  return s ? `?${s}` : '';
}

function baixarCSV(nome, colunas, linhas) {
  const cel = (v) => {
    if (typeof v === 'number') v = String(Math.round(v * 100) / 100).replace('.', ',');
    v = String(v ?? '');
    return /[;"\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
  };
  const corpo = [colunas.map((c) => cel(c.r)).join(';'), ...linhas.map((l) => colunas.map((c) => cel(c.v(l))).join(';'))].join('\r\n');
  const blob = new Blob(['﻿' + corpo], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${nome}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* Tabela genérica: colunas = [{ r: rótulo, v: linha => valor bruto (CSV), h?: linha => html, cls? }] */
function tabela(colunas, linhas, { vazio = 'Nada encontrado.', clique, rodape, classeLinha } = {}) {
  const cab = colunas.map((c) => `<th class="${c.cls || ''}">${esc(c.r)}</th>`).join('');
  const corpo = linhas.length
    ? linhas.map((l, i) => `<tr data-i="${i}" class="${clique ? 'clicavel' : ''} ${classeLinha ? classeLinha(l) : ''}">${colunas.map((c) => `<td class="${c.cls || ''}">${c.h ? c.h(l) : esc(c.v(l))}</td>`).join('')}</tr>`).join('')
    : `<tr><td class="vazio" colspan="${colunas.length}">${esc(vazio)}</td></tr>`;
  const pe = rodape ? `<tfoot><tr>${rodape.map((t, i) => `<td class="${colunas[i]?.cls || ''}">${t ?? ''}</td>`).join('')}</tr></tfoot>` : '';
  return `<div class="tabela-wrap"><table><thead><tr>${cab}</tr></thead><tbody>${corpo}</tbody>${pe}</table></div>`;
}
function ligarCliques(raiz, linhas, fn) {
  $$('tbody tr.clicavel', raiz).forEach((tr) => tr.addEventListener('click', (e) => { if (!e.target.closest('button,a,input')) fn(linhas[+tr.dataset.i]); }));
}

function cartaoTabela(id, titulo, colunas, linhas, op = {}) {
  return `<section class="cartao sem-pad" id="${id}"><div class="cartao-cab"><h2>${esc(titulo)}${op.sub ? ` <small>${esc(op.sub)}</small>` : ''}</h2>
    ${op.csv ? `<button class="btn btn-p nao-imprimir" data-csv="${id}">Exportar CSV</button>` : ''}</div>${tabela(colunas, linhas, op)}</section>`;
}
function ligarCSV(raiz, mapa) {
  $$('[data-csv]', raiz).forEach((b) => b.addEventListener('click', () => { const [nome, cols, linhas] = mapa[b.dataset.csv]; baixarCSV(nome, cols, linhas); }));
}

/* Gráfico de barras verticais em SVG */
function graficoBarras(dados, { valor = (d) => d.faturamento, rotulo = (d) => dia(d.dia).slice(0, 5), dica = (d) => `${dia(d.dia)}: ${brl(valor(d))}` } = {}) {
  if (!dados.length) return '<p class="vazio">Sem dados no período.</p>';
  const L = 760, A = 230, mE = 54, mB = 26, mT = 8;
  const max = Math.max(...dados.map(valor), 1);
  const bruto = max / 4;
  const ordem = Math.pow(10, Math.floor(Math.log10(bruto)));
  const passo = [1, 2, 2.5, 5, 10].map((f) => f * ordem).find((s) => s >= bruto);
  const topo = passo * 4;
  const larg = (L - mE) / dados.length;
  const linhas = [0, 0.25, 0.5, 0.75, 1].map((f) => {
    const y = mT + (A - mT - mB) * (1 - f);
    const v = topo * f;
    const txt = v >= 1000 ? `${(v / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}k` : num(Math.round(v));
    return `<line class="grade" x1="${mE}" x2="${L}" y1="${y}" y2="${y}"/><text class="eixo" x="${mE - 8}" y="${y + 4}" text-anchor="end">${txt}</text>`;
  }).join('');
  const cada = Math.ceil(dados.length / 12);
  const barras = dados.map((d, i) => {
    const h = ((A - mT - mB) * valor(d)) / topo;
    const x = mE + i * larg + larg * 0.15;
    const w = Math.max(larg * 0.7, 1);
    const y = A - mB - h;
    const r = i % cada === 0 ? `<text class="eixo" x="${x + w / 2}" y="${A - 8}" text-anchor="middle">${esc(rotulo(d))}</text>` : '';
    return `<rect class="barra" x="${x}" y="${y}" width="${w}" height="${Math.max(h, 0)}" rx="2"><title>${esc(dica(d))}</title></rect>${r}`;
  }).join('');
  return `<div class="grafico"><svg viewBox="0 0 ${L} ${A}" role="img" aria-label="Gráfico de barras">${linhas}${barras}</svg></div>`;
}

function barrasH(lista, { valor = (l) => l.faturamento, rotulo = (l) => l.chave, fmt = brl } = {}) {
  if (!lista.length) return '<p class="vazio">Sem dados no período.</p>';
  const max = Math.max(...lista.map(valor), 1);
  return `<div class="hbarras">${lista.map((l) => `<div class="hbarra"><span>${esc(rotulo(l) || '—')}</span><span class="num">${esc(fmt(valor(l)))}</span><div class="trilho"><i style="width:${(100 * valor(l)) / max}%"></i></div></div>`).join('')}</div>`;
}

/* =========================================================================
   Modal e formulários
   ========================================================================= */
function abrirModal(titulo, html, { largo = false } = {}) {
  const m = $('#modal');
  $('#modal-titulo').textContent = titulo;
  $('#modal-corpo').innerHTML = html;
  $('.modal-caixa', m).classList.toggle('largo', largo);
  m.hidden = false;
  setTimeout(() => $('#modal-corpo input:not([type=hidden]), #modal-corpo select, #modal-corpo textarea')?.focus(), 30);
  return $('#modal-corpo');
}
function fecharModal() { $('#modal').hidden = true; $('#modal-corpo').innerHTML = ''; }

function campoHTML(c, v) {
  const val = v ?? c.padrao ?? '';
  const attrs = `name="${c.n}" ${c.req ? 'required' : ''} ${c.attrs || ''}`;
  let ctrl;
  if (c.t === 'select') ctrl = `<select ${attrs}>${(c.vazio ? `<option value="">${esc(c.vazio)}</option>` : '') + c.opts.map((o) => { const [ov, ot] = Array.isArray(o) ? o : [o, o]; return `<option value="${esc(ov)}" ${String(ov) === String(val) ? 'selected' : ''}>${esc(ot)}</option>`; }).join('')}</select>`;
  else if (c.t === 'textarea') ctrl = `<textarea ${attrs}>${esc(val)}</textarea>`;
  else if (c.t === 'check') return `<label class="check ${c.col2 ? 'col-2' : ''}"><input type="checkbox" ${attrs} ${val ? 'checked' : ''}> ${esc(c.r)}</label>`;
  else ctrl = `<input type="${c.t || 'text'}" ${attrs} value="${esc(val)}">`;
  return `<label class="${c.col2 ? 'col-2' : ''}">${esc(c.r)}${c.req ? ' *' : ''}${ctrl}${c.ajuda ? `<small>${esc(c.ajuda)}</small>` : ''}</label>`;
}

function lerForm(form) {
  const d = {};
  $$('[name]', form).forEach((el) => { d[el.name] = el.type === 'checkbox' ? el.checked : el.value; });
  return d;
}

function abrirForm({ titulo, campos, valores = {}, salvar, textoBotao = 'Salvar', extra = '' }) {
  const corpo = abrirModal(titulo, `<form class="form-modal"><div class="grade-form">${campos.map((c) => campoHTML(c, valores[c.n])).join('')}</div>${extra}
    <p class="erro-form"></p><div class="acoes-form"><button type="button" class="btn" data-fechar>Cancelar</button><button class="btn btn-primario" type="submit">${esc(textoBotao)}</button></div></form>`);
  const form = $('form', corpo);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('button[type=submit]', form);
    btn.disabled = true;
    $('.erro-form', form).textContent = '';
    try { await salvar(lerForm(form), form); } catch (err) { $('.erro-form', form).textContent = err.message; } finally { btn.disabled = false; }
  });
  return form;
}

/* =========================================================================
   Sessão, menu e roteamento
   ========================================================================= */
function mostrarLogin() {
  estado.usuario = null;
  $('#app').hidden = true;
  $('#tela-login').hidden = false;
  fecharModal();
  setTimeout(() => $('#form-login [name=login]').focus(), 20);
}

async function iniciarApp() {
  estado.meta = await api('GET', '/api/meta');
  $('#tela-login').hidden = true;
  $('#app').hidden = false;
  $('#usuario-nome').textContent = estado.usuario.nome;
  $('#usuario-perfil').textContent = estado.usuario.perfil === 'admin' ? 'Administrador' : 'Vendedor';
  $$('[data-admin]').forEach((a) => { a.hidden = !ehAdmin(); });
  atualizarNomeLoja();
  rotear();
}
function atualizarNomeLoja() {
  const n = estado.meta?.config?.nome_loja;
  document.title = n ? `${n} · Estoque` : 'Estoque da Loja';
}

$('#form-login').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('#erro-login').textContent = '';
  try {
    estado.usuario = await api('POST', '/api/login', lerForm(e.target));
    e.target.reset();
    await iniciarApp();
  } catch (err) { $('#erro-login').textContent = err.message; }
});
$('#btn-sair').addEventListener('click', async () => { await api('POST', '/api/logout').catch(() => {}); location.hash = ''; mostrarLogin(); });
$('#btn-conta').addEventListener('click', () => abrirForm({
  titulo: 'Minha conta — trocar senha',
  campos: [
    { n: 'atual', r: 'Senha atual', t: 'password', req: true, col2: true, attrs: 'autocomplete="current-password"' },
    { n: 'nova', r: 'Nova senha', t: 'password', req: true, attrs: 'minlength="6" autocomplete="new-password"' },
    { n: 'confirma', r: 'Repita a nova senha', t: 'password', req: true, attrs: 'minlength="6" autocomplete="new-password"' },
  ],
  textoBotao: 'Trocar senha',
  salvar: async (d) => {
    if (d.nova !== d.confirma) throw new Error('As senhas não conferem.');
    await api('POST', '/api/me/senha', d);
    fecharModal(); avisar('Senha alterada.', 'ok');
  },
}));
$('#btn-menu').addEventListener('click', () => $('#app').classList.add('menu-aberto'));
$('#fundo-menu').addEventListener('click', () => $('#app').classList.remove('menu-aberto'));
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal' || e.target.closest('[data-fechar]')) fecharModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#modal').hidden) fecharModal(); });

const ROTAS = {
  painel: { t: 'Painel', f: paginaPainel },
  produtos: { t: 'Produtos e estoque', f: paginaProdutos },
  produto: { t: 'Produto', f: paginaProduto, menu: 'produtos' },
  entrada: { t: 'Nova entrada', f: (p, q) => paginaLancamento('entrada', q) },
  saida: { t: 'Nova venda / saída', f: (p, q) => paginaLancamento('saida', q) },
  movimentacoes: { t: 'Movimentações', f: paginaMovimentacoes },
  movimentacao: { t: 'Comprovante', f: paginaMovimentacao, menu: 'movimentacoes' },
  relatorios: { t: 'Relatórios', f: paginaRelatorios },
  clientes: { t: 'Clientes', f: () => paginaCadastro('clientes') },
  fornecedores: { t: 'Fornecedores', f: () => paginaCadastro('fornecedores') },
  usuarios: { t: 'Usuários', f: paginaUsuarios, admin: true },
  config: { t: 'Configurações', f: paginaConfig, admin: true },
};

let geracao = 0;
async function rotear() {
  if (!estado.usuario) return;
  const [caminho, busca = ''] = location.hash.replace(/^#\/?/, '').split('?');
  let [nome, param] = caminho.split('/');
  if (nome === 'produtos' && param) nome = 'produto';
  if (nome === 'movimentacoes' && param) nome = 'movimentacao';
  let r = ROTAS[nome];
  if (!r || (r.admin && !ehAdmin())) { nome = 'painel'; r = ROTAS.painel; }
  $('#titulo-pagina').textContent = r.t;
  $$('#menu a').forEach((a) => a.classList.toggle('ativo', a.dataset.rota === (r.menu || nome)));
  $('#app').classList.remove('menu-aberto');
  fecharModal();
  const el = $('#conteudo');
  el.innerHTML = '<div class="carregando">Carregando…</div>';
  const minha = ++geracao;
  try {
    await r.f(param, new URLSearchParams(busca), () => minha === geracao);
  } catch (err) {
    if (minha === geracao) el.innerHTML = `<div class="faixa faixa-perigo">${esc(err.message)}</div>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', rotear);

/* =========================================================================
   Período (compartilhado entre relatórios e movimentações)
   ========================================================================= */
function presetsPeriodo() {
  const h = new Date();
  const d = (n) => { const x = new Date(h); x.setDate(x.getDate() - n); return isoLocal(x); };
  const ini = new Date(h.getFullYear(), h.getMonth(), 1);
  const iniAnt = new Date(h.getFullYear(), h.getMonth() - 1, 1);
  const fimAnt = new Date(h.getFullYear(), h.getMonth(), 0);
  return {
    hoje: ['Hoje', isoLocal(h), isoLocal(h)],
    d7: ['7 dias', d(6), isoLocal(h)],
    d30: ['30 dias', d(29), isoLocal(h)],
    mes: ['Este mês', isoLocal(ini), isoLocal(h)],
    mesAnt: ['Mês passado', isoLocal(iniAnt), isoLocal(fimAnt)],
    ano: ['Este ano', `${h.getFullYear()}-01-01`, isoLocal(h)],
  };
}
function periodoAtual() {
  if (!estado.periodo) { const p = presetsPeriodo().mes; estado.periodo = { chave: 'mes', inicio: p[1], fim: p[2] }; }
  return estado.periodo;
}
function htmlPeriodo() {
  const p = periodoAtual();
  const ps = presetsPeriodo();
  return `<div class="periodo"><div class="chips">${Object.entries(ps).map(([k, v]) => `<button type="button" class="chip ${p.chave === k ? 'ativo' : ''}" data-preset="${k}">${v[0]}</button>`).join('')}</div>
    <label>De<input type="date" data-per="inicio" value="${p.inicio}"></label><label>Até<input type="date" data-per="fim" value="${p.fim}"></label></div>`;
}
function ligarPeriodo(raiz, aoMudar) {
  $$('[data-preset]', raiz).forEach((b) => b.addEventListener('click', () => {
    const v = presetsPeriodo()[b.dataset.preset];
    estado.periodo = { chave: b.dataset.preset, inicio: v[1], fim: v[2] };
    aoMudar();
  }));
  $$('[data-per]', raiz).forEach((i) => i.addEventListener('change', () => {
    if (!i.value) return;
    estado.periodo = { ...periodoAtual(), chave: '', [i.dataset.per]: i.value };
    aoMudar();
  }));
}
const textoPeriodo = () => { const p = periodoAtual(); return `${dia(p.inicio)} a ${dia(p.fim)}`; };

/* =========================================================================
   Painel
   ========================================================================= */
async function paginaPainel(_, __, vivo) {
  const d = await api('GET', '/api/painel');
  if (!vivo()) return;
  const e = d.estoque;
  const colsUlt = [
    { r: 'Nº', v: (m) => m.id, h: (m) => `#${m.id}` },
    { r: 'Tipo', v: (m) => nomeTipo(m.tipo), h: tagTipo },
    { r: 'Motivo', v: (m) => m.motivo },
    { r: 'Quem', v: (m) => m.cliente_nome || m.fornecedor_nome || '—' },
    { r: 'Data', v: (m) => dataHora(m.data) },
    { r: 'Total', v: (m) => m.total, h: (m) => brl(m.total), cls: 'num' },
  ];
  $('#conteudo').innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>Vendas hoje</span><strong>${brl(d.hoje.faturamento)}</strong><small>${num(d.hoje.vendas)} venda(s) · ${num(d.hoje.itens)} item(ns)</small></div>
      <div class="kpi"><span>Faturamento do mês</span><strong>${brl(d.mes.faturamento)}</strong><small>${num(d.mes.vendas)} vendas · ticket ${brl(d.mes.ticket_medio)}</small></div>
      ${ehAdmin() ? `<div class="kpi bom"><span>Lucro bruto do mês</span><strong>${brl(d.mes.lucro)}</strong><small>Margem de ${pct(d.mes.margem)}</small></div>` : ''}
      <div class="kpi"><span>Unidades em estoque</span><strong>${num(e.unidades)}</strong><small>${num(e.produtos)} produtos ativos</small></div>
      ${ehAdmin() ? `<div class="kpi"><span>Estoque a preço de custo</span><strong>${brl(e.valor_custo)}</strong><small>A preço de venda: ${brl(e.valor_venda)}</small></div>` : ''}
      <div class="kpi ${e.abaixo_minimo ? 'alerta' : ''}"><span>Abaixo do mínimo</span><strong>${num(e.abaixo_minimo)}</strong><small>${num(e.zerados)} produto(s) zerado(s)</small></div>
    </div>
    <div class="duas-col">
      <section class="cartao"><div class="cartao-cab"><h2>Vendas dos últimos 30 dias</h2><a href="#/relatorios">Ver relatórios →</a></div>${graficoBarras(d.grafico)}</section>
      <section class="cartao"><div class="cartao-cab"><h2>Mais vendidos no mês</h2></div>${barrasH(d.top_produtos, { valor: (l) => l.quantidade, fmt: (v) => `${num(v)} un.` })}</section>
    </div>
    <div class="duas-col">
      <section class="cartao sem-pad" id="ultimas"><div class="cartao-cab"><h2>Últimas movimentações</h2><a href="#/movimentacoes">Ver todas →</a></div>${tabela(colsUlt, d.ultimas, { clique: true, vazio: 'Nenhuma movimentação ainda.' })}</section>
      <section class="cartao sem-pad" id="baixo"><div class="cartao-cab"><h2>Repor estoque</h2><a href="#/produtos?baixo=1">Ver lista →</a></div>
        ${tabela([{ r: 'Produto', v: (p) => p.nome }, { r: 'Atual', v: (p) => p.estoque_atual, h: (p) => `<span class="estoque baixo">${num(p.estoque_atual)}</span>`, cls: 'num' }, { r: 'Mín.', v: (p) => p.estoque_minimo, cls: 'num' }], d.estoque_baixo, { clique: true, vazio: 'Tudo certo: nenhum produto abaixo do mínimo.' })}</section>
    </div>`;
  ligarCliques($('#ultimas'), d.ultimas, (m) => { location.hash = `#/movimentacoes/${m.id}`; });
  ligarCliques($('#baixo'), d.estoque_baixo, (p) => { location.hash = `#/produtos/${p.id}`; });
}

/* =========================================================================
   Produtos
   ========================================================================= */
function camposProduto() {
  const m = estado.meta;
  return [
    { n: 'nome', r: 'Nome do produto', req: true, col2: true, ajuda: 'Ex.: Samsung Galaxy A15 128GB Preto' },
    { n: 'categoria', r: 'Categoria', t: 'select', opts: m.categorias, req: true },
    { n: 'condicao', r: 'Condição', t: 'select', opts: m.condicoes },
    { n: 'marca', r: 'Marca' },
    { n: 'modelo', r: 'Modelo' },
    { n: 'armazenamento', r: 'Armazenamento', attrs: 'placeholder="128GB"' },
    { n: 'cor', r: 'Cor' },
    { n: 'codigo', r: 'Código / código de barras (SKU)', col2: true, ajuda: 'Opcional. Pode ler com o leitor de código de barras.' },
    { n: 'preco_custo', r: 'Preço de custo (R$)', attrs: 'inputmode="decimal"' },
    { n: 'preco_venda', r: 'Preço de venda (R$)', attrs: 'inputmode="decimal"' },
    { n: 'estoque_minimo', r: 'Estoque mínimo', t: 'number', attrs: 'min="0" step="1"', ajuda: 'Avisa quando o estoque chegar nesse número.' },
    { n: 'controla_imei', r: 'Controlar IMEI (um por aparelho)', t: 'check', ajuda: '' },
  ];
}

function formProduto(p, aoSalvar) {
  const valores = p ? { ...p, preco_custo: String(p.preco_custo).replace('.', ','), preco_venda: String(p.preco_venda).replace('.', ',') } : { categoria: 'Smartphone', condicao: 'Novo', controla_imei: true, estoque_minimo: 1 };
  const extra = p ? `<label class="check" style="margin-top:12px"><input type="checkbox" name="ativo" ${p.ativo ? 'checked' : ''}> Produto ativo (desmarque para esconder das vendas)</label>` : '';
  const form = abrirForm({
    titulo: p ? 'Editar produto' : 'Novo produto',
    campos: camposProduto(), valores, extra,
    salvar: async (d) => {
      d.preco_custo = paraNumero(d.preco_custo); d.preco_venda = paraNumero(d.preco_venda);
      const r = p ? await api('PUT', `/api/produtos/${p.id}`, d) : await api('POST', '/api/produtos', d);
      fecharModal(); avisar(p ? 'Produto atualizado.' : 'Produto cadastrado.', 'ok');
      aoSalvar(r);
    },
  });
  // sugere o nome a partir de marca/modelo/armazenamento/cor
  if (!p) {
    const nome = $('[name=nome]', form);
    let editado = false;
    nome.addEventListener('input', () => { editado = true; });
    ['marca', 'modelo', 'armazenamento', 'cor'].forEach((n) => $(`[name=${n}]`, form).addEventListener('input', () => {
      if (editado && nome.value) return;
      editado = false;
      nome.value = ['marca', 'modelo', 'armazenamento', 'cor'].map((k) => $(`[name=${k}]`, form).value.trim()).filter(Boolean).join(' ');
    }));
    $('[name=categoria]', form).addEventListener('change', (e) => { $('[name=controla_imei]', form).checked = ['Smartphone', 'Tablet', 'Smartwatch'].includes(e.target.value); });
  }
}

const COLS_PRODUTO = () => [
  { r: 'Código', v: (p) => p.codigo || '', h: (p) => `<span class="mono">${esc(p.codigo || '—')}</span>` },
  { r: 'Produto', v: (p) => p.nome, h: (p) => `<div class="celula-produto"><strong>${esc(p.nome)}${p.ativo ? '' : ' <span class="tag">inativo</span>'}</strong><small>${esc([p.marca, p.condicao, p.controla_imei ? 'IMEI' : ''].filter(Boolean).join(' · '))}</small></div>` },
  { r: 'Categoria', v: (p) => p.categoria },
  { r: 'Estoque', v: (p) => p.estoque_atual, h: (p) => `<span class="estoque ${p.estoque_atual === 0 ? 'zero' : p.estoque_atual <= p.estoque_minimo ? 'baixo' : ''}">${num(p.estoque_atual)}</span>`, cls: 'num' },
  { r: 'Mínimo', v: (p) => p.estoque_minimo, cls: 'num' },
  ...(ehAdmin() ? [{ r: 'Custo', v: (p) => p.preco_custo, h: (p) => brl(p.preco_custo), cls: 'num' }] : []),
  { r: 'Venda', v: (p) => p.preco_venda, h: (p) => brl(p.preco_venda), cls: 'num' },
  ...(ehAdmin() ? [{ r: 'Margem', v: (p) => (p.preco_venda ? Math.round(((p.preco_venda - p.preco_custo) / p.preco_venda) * 1000) / 10 : 0), h: (p) => (p.preco_venda ? pct(((p.preco_venda - p.preco_custo) / p.preco_venda) * 100) : '—'), cls: 'num' }] : []),
];

async function paginaProdutos(_, q) {
  const f = { q: q.get('q') || '', categoria: q.get('categoria') || '', baixo: q.get('baixo') === '1', todos: false };
  $('#conteudo').innerHTML = `
    <div class="ferramentas">
      <label class="busca">Buscar<input type="search" id="f-q" placeholder="Nome, marca, código ou IMEI" value="${esc(f.q)}"></label>
      <label>Categoria<select id="f-cat"><option value="">Todas</option>${estado.meta.categorias.map((c) => `<option ${c === f.categoria ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></label>
      <label class="check"><input type="checkbox" id="f-baixo" ${f.baixo ? 'checked' : ''}> Só abaixo do mínimo</label>
      <label class="check"><input type="checkbox" id="f-todos"> Mostrar inativos</label>
      <span class="espaco"></span>
      <button class="btn" id="b-csv">Exportar CSV</button>
      ${ehAdmin() ? '<button class="btn btn-primario" id="b-novo">+ Novo produto</button>' : ''}
    </div>
    <section class="cartao sem-pad" id="lista-produtos"><div class="carregando">Carregando…</div></section>`;
  let linhas = [];
  const carregar = async () => {
    linhas = await api('GET', `/api/produtos${qs(f)}`);
    const tot = linhas.reduce((a, p) => a + p.estoque_atual, 0);
    $('#lista-produtos').innerHTML = `<div class="cartao-cab"><h2>${num(linhas.length)} produto(s) <small>${num(tot)} unidades</small></h2></div>${tabela(COLS_PRODUTO(), linhas, { clique: true, vazio: 'Nenhum produto encontrado.' })}`;
    ligarCliques($('#lista-produtos'), linhas, (p) => { location.hash = `#/produtos/${p.id}`; });
  };
  let t;
  $('#f-q').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); carregar(); }, 250); });
  $('#f-cat').addEventListener('change', (e) => { f.categoria = e.target.value; carregar(); });
  $('#f-baixo').addEventListener('change', (e) => { f.baixo = e.target.checked; carregar(); });
  $('#f-todos').addEventListener('change', (e) => { f.todos = e.target.checked; carregar(); });
  $('#b-csv').addEventListener('click', () => baixarCSV('produtos', COLS_PRODUTO(), linhas));
  $('#b-novo')?.addEventListener('click', () => formProduto(null, (p) => { location.hash = `#/produtos/${p.id}`; }));
  await carregar();
}

async function paginaProduto(id, _, vivo) {
  const p = await api('GET', `/api/produtos/${id}`);
  if (!vivo()) return;
  $('#titulo-pagina').textContent = p.nome;
  const info = [
    ['Código', p.codigo || '—'], ['Categoria', p.categoria], ['Marca', p.marca || '—'], ['Modelo', p.modelo || '—'],
    ['Armazenamento', p.armazenamento || '—'], ['Cor', p.cor || '—'], ['Condição', p.condicao], ['Controla IMEI', p.controla_imei ? 'Sim' : 'Não'],
    ...(ehAdmin() ? [['Custo médio', brl(p.preco_custo)]] : []), ['Preço de venda', brl(p.preco_venda)], ['Estoque mínimo', num(p.estoque_minimo)], ['Situação', p.ativo ? 'Ativo' : 'Inativo'],
  ];
  const colsMov = [
    { r: 'Nº', v: (m) => m.id, h: (m) => `#${m.id}` },
    { r: 'Tipo', v: (m) => nomeTipo(m.tipo), h: tagTipo },
    { r: 'Motivo', v: (m) => m.motivo },
    { r: 'Data', v: (m) => dataHora(m.data) },
    { r: 'Qtd', v: (m) => m.quantidade, h: (m) => `${m.tipo === 'entrada' ? '+' : '−'}${num(m.quantidade)}`, cls: 'num' },
    { r: 'Valor un.', v: (m) => m.valor_unitario, h: (m) => brl(m.valor_unitario), cls: 'num' },
  ];
  $('#conteudo').innerHTML = `
    <div class="ferramentas">
      <a class="btn" href="#/produtos">← Produtos</a><span class="espaco"></span>
      ${ehAdmin() ? '<button class="btn" id="b-editar">Editar</button><button class="btn btn-perigo" id="b-excluir">Excluir</button>' : ''}
      <a class="btn" href="#/entrada?produto=${p.id}">+ Dar entrada</a>
      ${p.estoque_atual > 0 && p.ativo ? `<a class="btn btn-primario" href="#/saida?produto=${p.id}">Vender</a>` : ''}
    </div>
    <div class="kpis">
      <div class="kpi ${p.estoque_atual <= p.estoque_minimo ? 'alerta' : ''}"><span>Em estoque</span><strong>${num(p.estoque_atual)}</strong><small>Mínimo: ${num(p.estoque_minimo)}</small></div>
      <div class="kpi"><span>Preço de venda</span><strong>${brl(p.preco_venda)}</strong>${ehAdmin() ? `<small>Margem ${p.preco_venda ? pct(((p.preco_venda - p.preco_custo) / p.preco_venda) * 100) : '—'}</small>` : ''}</div>
      ${ehAdmin() ? `<div class="kpi"><span>Valor em estoque (custo)</span><strong>${brl(p.estoque_atual * p.preco_custo)}</strong></div>` : ''}
    </div>
    <div class="duas-col">
      <section class="cartao"><div class="cartao-cab"><h2>Dados do produto</h2></div>
        <div class="recibo"><dl>${info.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl></div></section>
      ${p.controla_imei ? `<section class="cartao"><div class="cartao-cab"><h2>IMEIs em estoque <small>${p.imeis_disponiveis.length}</small></h2></div>
        ${p.imeis_disponiveis.length ? `<div class="imeis-lista">${p.imeis_disponiveis.map((i) => `<span class="imei-op">${esc(i)}</span>`).join('')}</div>` : '<p class="sutil">Nenhum aparelho em estoque.</p>'}</section>` : '<div></div>'}
    </div>
    ${cartaoTabela('hist-prod', 'Histórico de movimentações', colsMov, p.movimentacoes, { clique: true, vazio: 'Sem movimentações.', classeLinha: (m) => (m.cancelada ? 'cancelada' : '') })}`;
  ligarCliques($('#hist-prod'), p.movimentacoes, (m) => { location.hash = `#/movimentacoes/${m.id}`; });
  $('#b-editar')?.addEventListener('click', () => formProduto(p, () => rotear()));
  $('#b-excluir')?.addEventListener('click', async () => {
    if (!confirm(`Excluir "${p.nome}"? Se já tiver movimentações, o produto será apenas desativado.`)) return;
    try { const r = await api('DELETE', `/api/produtos/${p.id}`); avisar(r.desativado ? 'Produto desativado (tem histórico).' : 'Produto excluído.', 'ok'); location.hash = '#/produtos'; } catch (e) { avisar(e.message, 'erro'); }
  });
}

/* =========================================================================
   Lançamento: entrada / saída / venda
   ========================================================================= */
async function paginaLancamento(tipo, q) {
  const meta = estado.meta;
  const ehEntrada = tipo === 'entrada';
  const motivos = meta.motivos[tipo].filter((m) => ehAdmin() || !meta.motivos_admin.includes(m));
  const L = { motivo: motivos[0], itens: [], parceiro: '', forma: meta.pagamentos[0], desconto: 0, documento: '', observacao: '' };
  const parceiros = await api('GET', ehEntrada ? '/api/fornecedores' : '/api/clientes');
  const ehVenda = () => !ehEntrada && L.motivo === 'Venda';

  $('#conteudo').innerHTML = `
    <div class="ferramentas"><div class="segmentado"><a href="#/saida" class="${ehEntrada ? '' : 'ativo'}">Saída / venda</a><a href="#/entrada" class="${ehEntrada ? 'ativo' : ''}">Entrada</a></div></div>
    <div class="lancamento">
      <div style="display:grid;gap:18px;min-width:0">
        <section class="cartao">
          <div class="cartao-cab"><h2>Produtos</h2><small class="sutil">Digite o nome, leia o código de barras ou o IMEI e tecle Enter</small></div>
          <div class="busca-produto"><input id="busca" type="search" autocomplete="off" placeholder="Buscar produto, código ou IMEI…"><div class="resultados" id="resultados" hidden></div></div>
          <div id="itens" style="margin-top:14px"></div>
        </section>
      </div>
      <aside class="lancamento-lateral">
        <section class="cartao"><div class="grade-form">
          <label class="col-2">Motivo<select id="l-motivo">${motivos.map((m) => `<option>${esc(m)}</option>`).join('')}</select></label>
          <label class="col-2">${ehEntrada ? 'Fornecedor' : 'Cliente'}<div class="linha-input"><select id="l-parceiro"><option value="">${ehEntrada ? '— sem fornecedor —' : '— consumidor não identificado —'}</option>${parceiros.map((p) => `<option value="${p.id}">${esc(p.nome)}${p.documento ? ` · ${esc(p.documento)}` : ''}</option>`).join('')}</select><button class="btn" type="button" id="l-novo-parceiro" title="Cadastrar">+</button></div></label>
          <label class="col-2" id="w-forma">Forma de pagamento<select id="l-forma">${meta.pagamentos.map((m) => `<option>${esc(m)}</option>`).join('')}</select></label>
          <label class="col-2">${ehEntrada ? 'Nota fiscal / documento' : 'Documento (opcional)'}<input id="l-doc" maxlength="60"></label>
          <label class="col-2">Observação<textarea id="l-obs" maxlength="1000" rows="2"></textarea></label>
        </div></section>
        <section class="cartao"><div class="totais">
          <div><span>Itens</span><span id="t-itens">0</span></div>
          <div><span>Subtotal</span><span id="t-sub">R$ 0,00</span></div>
          <div id="w-desc"><label style="width:100%">Desconto (R$)<input id="l-desc" inputmode="decimal" placeholder="0,00"></label></div>
          <div class="total"><span>Total</span><span id="t-total">R$ 0,00</span></div>
          ${ehAdmin() ? '<div id="w-lucro"><small>Lucro estimado</small><small id="t-lucro"></small></div>' : ''}
          <p class="erro-form" id="l-erro"></p>
          <button class="btn btn-g btn-largo ${ehEntrada ? 'btn-sucesso' : 'btn-primario'}" id="l-finalizar">${ehEntrada ? 'Registrar entrada' : 'Finalizar'}</button>
        </div></section>
      </aside>
    </div>`;

  const valorPadrao = (p) => (ehVenda() ? p.preco_venda : p.preco_custo);
  const qtdItem = (it) => (it.p.controla_imei ? it.imeis.length : it.quantidade);

  function atualizarTotais() {
    const sub = L.itens.reduce((a, it) => a + qtdItem(it) * it.valor, 0);
    const desc = ehVenda() ? Math.min(L.desconto, sub) : 0;
    const total = sub - desc;
    $('#t-itens').textContent = num(L.itens.reduce((a, it) => a + qtdItem(it), 0));
    $('#t-sub').textContent = brl(sub);
    $('#t-total').textContent = brl(total);
    if ($('#t-lucro')) {
      const custo = L.itens.reduce((a, it) => a + qtdItem(it) * it.p.preco_custo, 0);
      $('#t-lucro').textContent = `${brl(total - custo)}${total ? ` (${pct(((total - custo) / total) * 100)})` : ''}`;
      $('#w-lucro').hidden = !ehVenda();
    }
    $('#w-forma').hidden = !ehVenda();
    $('#w-desc').hidden = !ehVenda();
    $$('#itens [data-sub]').forEach((el) => { const it = L.itens[+el.dataset.sub]; el.textContent = brl(qtdItem(it) * it.valor); });
    $$('#itens [data-qtdimei]').forEach((el) => { el.textContent = num(L.itens[+el.dataset.qtdimei].imeis.length); });
  }

  function desenharItens() {
    const el = $('#itens');
    if (!L.itens.length) { el.innerHTML = '<p class="vazio">Nenhum produto adicionado.</p>'; atualizarTotais(); return; }
    el.innerHTML = `<div class="tabela-wrap"><table><thead><tr><th>Produto</th><th class="num">Qtd</th><th class="num">Valor un.</th><th class="num">Subtotal</th><th></th></tr></thead><tbody>
      ${L.itens.map((it, i) => {
        const p = it.p;
        let imeis = '';
        if (p.controla_imei) {
          imeis = ehEntrada
            ? `<div class="imeis-caixa"><small>IMEIs (um por linha, 15 dígitos)</small><textarea data-imeis="${i}" placeholder="Leia ou digite os IMEIs">${esc(it.imeis.join('\n'))}</textarea></div>`
            : `<div class="imeis-caixa"><small>Selecione os aparelhos (IMEI) — ${p.imeis_disponiveis.length} em estoque</small>${p.imeis_disponiveis.length > 8 ? `<input type="search" data-filtroimei="${i}" placeholder="Filtrar IMEI…">` : ''}
               <div class="imeis-lista">${p.imeis_disponiveis.map((im) => `<label class="imei-op"><input type="checkbox" data-imei="${i}" value="${esc(im)}" ${it.imeis.includes(im) ? 'checked' : ''}>${esc(im)}</label>`).join('')}</div></div>`;
        }
        return `<tr class="item-linha"><td><div class="celula-produto"><strong>${esc(p.nome)}</strong><small>${esc(p.codigo || '')} · estoque ${num(p.estoque_atual)}</small></div>${imeis}</td>
          <td class="num">${p.controla_imei ? `<strong data-qtdimei="${i}">${num(it.imeis.length)}</strong>` : `<input class="qtd" type="number" min="1" step="1" ${ehEntrada ? '' : `max="${p.estoque_atual}"`} data-qtd="${i}" value="${it.quantidade}">`}</td>
          <td class="num"><input class="valor" inputmode="decimal" data-valor="${i}" value="${String(it.valor.toFixed(2)).replace('.', ',')}"></td>
          <td class="num" data-sub="${i}"></td>
          <td><button class="btn btn-fantasma btn-p" data-remover="${i}" title="Remover" aria-label="Remover">✕</button></td></tr>`;
      }).join('')}</tbody></table></div>`;
    $$('[data-qtd]', el).forEach((inp) => inp.addEventListener('input', () => { L.itens[+inp.dataset.qtd].quantidade = Math.max(1, parseInt(inp.value, 10) || 1); atualizarTotais(); }));
    $$('[data-valor]', el).forEach((inp) => inp.addEventListener('input', () => { L.itens[+inp.dataset.valor].valor = paraNumero(inp.value); atualizarTotais(); }));
    $$('[data-remover]', el).forEach((b) => b.addEventListener('click', () => { L.itens.splice(+b.dataset.remover, 1); desenharItens(); }));
    $$('[data-imeis]', el).forEach((ta) => ta.addEventListener('input', () => { L.itens[+ta.dataset.imeis].imeis = ta.value.split(/[\s,;]+/).map((s) => s.replace(/\D/g, '')).filter(Boolean); atualizarTotais(); }));
    $$('[data-imei]', el).forEach((cb) => cb.addEventListener('change', () => {
      const it = L.itens[+cb.dataset.imei];
      it.imeis = cb.checked ? [...new Set([...it.imeis, cb.value])] : it.imeis.filter((x) => x !== cb.value);
      atualizarTotais();
    }));
    $$('[data-filtroimei]', el).forEach((f) => f.addEventListener('input', () => {
      $$(`[data-imei="${f.dataset.filtroimei}"]`, el).forEach((cb) => { cb.parentElement.hidden = !cb.value.includes(f.value.replace(/\D/g, '')); });
    }));
    atualizarTotais();
  }

  async function adicionar(resumo, imeiBuscado) {
    const p = await api('GET', `/api/produtos/${resumo.id}`);
    if (!p.ativo) return avisar('Produto inativo.', 'erro');
    if (!ehEntrada && p.estoque_atual <= 0) return avisar(`${p.nome} está sem estoque.`, 'erro');
    let it = L.itens.find((x) => x.p.id === p.id);
    if (it) {
      if (!p.controla_imei) it.quantidade += 1;
    } else {
      it = { p, quantidade: 1, valor: valorPadrao(p), imeis: [] };
      L.itens.push(it);
    }
    if (p.controla_imei && imeiBuscado && !it.imeis.includes(imeiBuscado)) {
      if (ehEntrada || p.imeis_disponiveis.includes(imeiBuscado)) it.imeis.push(imeiBuscado);
    }
    desenharItens();
    if (p.controla_imei && ehEntrada) setTimeout(() => $(`[data-imeis="${L.itens.indexOf(it)}"]`)?.focus(), 20);
  }

  // ---- busca com autocompletar
  const busca = $('#busca');
  const res = $('#resultados');
  let encontrados = [], foco = -1, tBusca;
  const fecharRes = () => { res.hidden = true; foco = -1; };
  async function buscar() {
    const termo = busca.value.trim();
    if (!termo) { encontrados = []; fecharRes(); return; }
    encontrados = await api('GET', `/api/produtos${qs({ q: termo, com_estoque: !ehEntrada })}`);
    if (busca.value.trim() !== termo) return;
    res.innerHTML = encontrados.length
      ? encontrados.slice(0, 30).map((p, i) => `<button type="button" data-r="${i}"><span><strong>${esc(p.nome)}</strong><br><small>${esc([p.codigo, p.categoria, p.condicao].filter(Boolean).join(' · '))}</small></span><span class="num"><small>estoque</small> ${num(p.estoque_atual)}<br>${brl(ehEntrada ? p.preco_custo : p.preco_venda)}</span></button>`).join('')
      : `<button type="button" disabled><span class="sutil">Nada encontrado${ehEntrada && ehAdmin() ? ' — cadastre o produto em Produtos' : ' com estoque'}.</span></button>`;
    res.hidden = false;
    $$('[data-r]', res).forEach((b) => b.addEventListener('click', () => escolher(+b.dataset.r)));
  }
  function escolher(i) {
    const p = encontrados[i];
    if (!p) return;
    const termo = busca.value.replace(/\D/g, '');
    busca.value = '';
    fecharRes();
    adicionar(p, termo.length === 15 ? termo : null).catch((e) => avisar(e.message, 'erro'));
    busca.focus();
  }
  busca.addEventListener('input', () => { clearTimeout(tBusca); tBusca = setTimeout(() => buscar().catch(() => {}), 200); });
  busca.addEventListener('keydown', async (e) => {
    const botoes = $$('[data-r]', res);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!botoes.length) return;
      foco = (foco + (e.key === 'ArrowDown' ? 1 : -1) + botoes.length) % botoes.length;
      botoes.forEach((b, i) => b.classList.toggle('foco', i === foco));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(tBusca);
      if (foco < 0) { await buscar().catch(() => {}); }
      if (foco >= 0) escolher(foco);
      else if (encontrados.length === 1) escolher(0);
      else {
        const termo = busca.value.trim();
        const exato = encontrados.findIndex((p) => p.codigo && p.codigo.toLowerCase() === termo.toLowerCase());
        if (exato >= 0) escolher(exato);
      }
    } else if (e.key === 'Escape') fecharRes();
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.busca-produto')) fecharRes(); });

  // ---- campos laterais
  $('#l-motivo').addEventListener('change', (e) => {
    const eraVenda = ehVenda();
    L.motivo = e.target.value;
    if (eraVenda !== ehVenda()) { L.itens.forEach((it) => { it.valor = valorPadrao(it.p); }); desenharItens(); } else atualizarTotais();
  });
  $('#l-forma').addEventListener('change', (e) => { L.forma = e.target.value; });
  $('#l-desc').addEventListener('input', (e) => { L.desconto = paraNumero(e.target.value); atualizarTotais(); });
  $('#l-novo-parceiro').addEventListener('click', () => abrirForm({
    titulo: ehEntrada ? 'Novo fornecedor' : 'Novo cliente', campos: CAMPOS_CADASTRO(ehEntrada ? 'fornecedores' : 'clientes'),
    salvar: async (d) => {
      const r = await api('POST', ehEntrada ? '/api/fornecedores' : '/api/clientes', d);
      const op = document.createElement('option');
      op.value = r.id; op.textContent = r.nome; op.selected = true;
      $('#l-parceiro').append(op);
      fecharModal(); avisar('Cadastrado.', 'ok');
    },
  }));

  $('#l-finalizar').addEventListener('click', async () => {
    const btn = $('#l-finalizar');
    $('#l-erro').textContent = '';
    if (!L.itens.length) { $('#l-erro').textContent = 'Adicione pelo menos um produto.'; return; }
    const corpo = {
      tipo, motivo: L.motivo, forma_pagamento: ehVenda() ? $('#l-forma').value : null,
      desconto: ehVenda() ? L.desconto : 0, documento: $('#l-doc').value, observacao: $('#l-obs').value,
      [ehEntrada ? 'fornecedor_id' : 'cliente_id']: $('#l-parceiro').value || null,
      itens: L.itens.map((it) => ({ produto_id: it.p.id, quantidade: qtdItem(it), valor_unitario: it.valor, imeis: it.imeis })),
    };
    const semImei = L.itens.find((it) => it.p.controla_imei && !it.imeis.length);
    if (semImei) { $('#l-erro').textContent = `Informe o(s) IMEI(s) de ${semImei.p.nome}.`; return; }
    btn.disabled = true;
    try {
      const m = await api('POST', '/api/movimentacoes', corpo);
      avisar(ehVenda() ? `Venda #${m.id} registrada: ${brl(m.total)}` : `${nomeTipo(tipo)} #${m.id} registrada.`, 'ok');
      location.hash = `#/movimentacoes/${m.id}`;
    } catch (e) {
      $('#l-erro').textContent = e.message;
    } finally { btn.disabled = false; }
  });

  desenharItens();
  const pre = q.get('produto');
  if (pre) await adicionar({ id: pre }).catch((e) => avisar(e.message, 'erro'));
  busca.focus();
}

/* =========================================================================
   Movimentações
   ========================================================================= */
const COLS_MOV = [
  { r: 'Nº', v: (m) => m.id, h: (m) => `<strong>#${m.id}</strong>` },
  { r: 'Data', v: (m) => dataHora(m.data) },
  { r: 'Tipo', v: (m) => nomeTipo(m.tipo), h: (m) => `${tagTipo(m)}${m.cancelada ? ' <span class="tag tag-perigo">cancelada</span>' : ''}` },
  { r: 'Motivo', v: (m) => m.motivo },
  { r: 'Produtos', v: (m) => m.produtos, h: (m) => `<span title="${esc(m.produtos)}">${esc((m.produtos || '').length > 60 ? `${m.produtos.slice(0, 60)}…` : m.produtos)}</span>` },
  { r: 'Qtd', v: (m) => m.quantidade, cls: 'num' },
  { r: 'Cliente / fornecedor', v: (m) => m.cliente_nome || m.fornecedor_nome || '' },
  { r: 'Pagamento', v: (m) => m.forma_pagamento || '' },
  { r: 'Usuário', v: (m) => m.usuario_nome },
  { r: 'Total', v: (m) => m.total, h: (m) => brl(m.total), cls: 'num' },
];

async function paginaMovimentacoes() {
  const f = { tipo: '', motivo: '', q: '', canceladas: false };
  const todos = [...new Set([...estado.meta.motivos.entrada, ...estado.meta.motivos.saida])];
  const desenhar = () => {
    $('#conteudo').innerHTML = `
      <div class="ferramentas">${htmlPeriodo()}</div>
      <div class="ferramentas">
        <label class="busca">Buscar<input type="search" id="m-q" placeholder="Nº, cliente, produto, IMEI, nota…" value="${esc(f.q)}"></label>
        <label>Tipo<select id="m-tipo"><option value="">Todos</option><option value="entrada" ${f.tipo === 'entrada' ? 'selected' : ''}>Entradas</option><option value="saida" ${f.tipo === 'saida' ? 'selected' : ''}>Saídas</option></select></label>
        <label>Motivo<select id="m-motivo"><option value="">Todos</option>${todos.map((m) => `<option ${m === f.motivo ? 'selected' : ''}>${esc(m)}</option>`).join('')}</select></label>
        <label class="check"><input type="checkbox" id="m-canc" ${f.canceladas ? 'checked' : ''}> Incluir canceladas</label>
        <span class="espaco"></span><button class="btn" id="m-csv">Exportar CSV</button>
      </div>
      <section class="cartao sem-pad" id="lista-mov"><div class="carregando">Carregando…</div></section>`;
    ligarPeriodo($('#conteudo'), desenhar);
    let t;
    $('#m-q').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { f.q = e.target.value.trim(); carregar(); }, 300); });
    $('#m-tipo').addEventListener('change', (e) => { f.tipo = e.target.value; carregar(); });
    $('#m-motivo').addEventListener('change', (e) => { f.motivo = e.target.value; carregar(); });
    $('#m-canc').addEventListener('change', (e) => { f.canceladas = e.target.checked; carregar(); });
    $('#m-csv').addEventListener('click', () => baixarCSV(`movimentacoes-${periodoAtual().inicio}-a-${periodoAtual().fim}`, COLS_MOV, linhas));
    carregar();
  };
  let linhas = [];
  const carregar = async () => {
    const p = periodoAtual();
    linhas = await api('GET', `/api/movimentacoes${qs({ ...f, inicio: p.inicio, fim: p.fim })}`);
    const ent = linhas.filter((m) => m.tipo === 'entrada' && !m.cancelada).reduce((a, m) => a + m.total, 0);
    const sai = linhas.filter((m) => m.tipo === 'saida' && !m.cancelada).reduce((a, m) => a + m.total, 0);
    $('#lista-mov').innerHTML = `<div class="cartao-cab"><h2>${num(linhas.length)} movimentação(ões) <small>${textoPeriodo()}</small></h2><small class="sutil">Entradas ${brl(ent)} · Saídas ${brl(sai)}</small></div>
      ${tabela(COLS_MOV, linhas, { clique: true, vazio: 'Nenhuma movimentação no período.', classeLinha: (m) => (m.cancelada ? 'cancelada' : '') })}`;
    ligarCliques($('#lista-mov'), linhas, (m) => { location.hash = `#/movimentacoes/${m.id}`; });
  };
  desenhar();
}

async function paginaMovimentacao(id, _, vivo) {
  const m = await api('GET', `/api/movimentacoes/${id}`);
  if (!vivo()) return;
  const cfg = estado.meta.config;
  const venda = m.tipo === 'saida' && m.motivo === 'Venda';
  $('#titulo-pagina').textContent = `${venda ? 'Venda' : nomeTipo(m.tipo)} #${m.id}`;
  $('#conteudo').innerHTML = `
    <div class="ferramentas nao-imprimir">
      <a class="btn" href="#/movimentacoes">← Movimentações</a><span class="espaco"></span>
      ${ehAdmin() && !m.cancelada ? '<button class="btn btn-perigo" id="b-cancelar">Cancelar lançamento</button>' : ''}
      <button class="btn" id="b-imprimir">Imprimir</button>
      <a class="btn btn-primario" href="#/${m.tipo}">${m.tipo === 'saida' ? 'Nova venda' : 'Nova entrada'}</a>
    </div>
    ${m.cancelada ? `<div class="faixa faixa-perigo"><strong>Cancelada</strong> em ${esc(dataHora(m.cancelada_em))} por ${esc(m.cancelada_por_nome)} — ${esc(m.motivo_cancelamento)}. O estoque foi estornado.</div>` : ''}
    <section class="cartao recibo">
      <div class="recibo-cab">
        <div><h2>${esc(cfg.nome_loja)}</h2><small>${esc([cfg.documento, cfg.endereco, cfg.telefone].filter(Boolean).join(' · '))}</small></div>
        <div class="num"><h2>${venda ? 'Comprovante de venda' : `${nomeTipo(m.tipo)} de estoque`}</h2><small>Nº ${m.id} · ${esc(dataHora(m.data))}</small></div>
      </div>
      <dl>
        <dt>Motivo</dt><dd>${esc(m.motivo)}</dd>
        ${m.cliente_nome ? `<dt>Cliente</dt><dd>${esc(m.cliente_nome)}${m.cliente_documento ? ` · ${esc(m.cliente_documento)}` : ''}${m.cliente_telefone ? ` · ${esc(m.cliente_telefone)}` : ''}</dd>` : ''}
        ${m.fornecedor_nome ? `<dt>Fornecedor</dt><dd>${esc(m.fornecedor_nome)}</dd>` : ''}
        ${m.documento ? `<dt>Documento</dt><dd>${esc(m.documento)}</dd>` : ''}
        ${m.forma_pagamento ? `<dt>Pagamento</dt><dd>${esc(m.forma_pagamento)}</dd>` : ''}
        <dt>Atendido por</dt><dd>${esc(m.usuario_nome)}</dd>
        ${m.observacao ? `<dt>Observação</dt><dd>${esc(m.observacao)}</dd>` : ''}
      </dl>
      ${tabela([
        { r: 'Produto', v: (i) => i.produto_nome, h: (i) => `<div class="celula-produto"><strong>${esc(i.produto_nome)}</strong>${i.imeis.length ? `<div class="imeis-txt">IMEI: ${i.imeis.map(esc).join(', ')}</div>` : ''}</div>` },
        { r: 'Qtd', v: (i) => i.quantidade, cls: 'num' },
        { r: 'Valor un.', v: (i) => i.valor_unitario, h: (i) => brl(i.valor_unitario), cls: 'num' },
        { r: 'Subtotal', v: (i) => i.quantidade * i.valor_unitario, h: (i) => brl(i.quantidade * i.valor_unitario), cls: 'num' },
      ], m.itens)}
      <div class="totais" style="max-width:300px;margin:14px 0 0 auto">
        ${m.desconto ? `<div><span>Subtotal</span><span>${brl(m.subtotal)}</span></div><div><span>Desconto</span><span>− ${brl(m.desconto)}</span></div>` : ''}
        <div class="total"><span>Total</span><span>${brl(m.total)}</span></div>
      </div>
      ${venda && cfg.rodape_recibo ? `<p class="sutil" style="text-align:center;margin:20px 0 0">${esc(cfg.rodape_recibo)}</p>` : ''}
    </section>`;
  $('#b-imprimir').addEventListener('click', () => window.print());
  $('#b-cancelar')?.addEventListener('click', () => abrirForm({
    titulo: `Cancelar lançamento #${m.id}`,
    campos: [{ n: 'motivo', r: 'Motivo do cancelamento', t: 'textarea', req: true, col2: true }],
    extra: `<p class="faixa faixa-alerta" style="margin-top:12px">O estoque será estornado: ${m.tipo === 'entrada' ? 'os itens saem do estoque' : 'os itens voltam para o estoque'}. Esta ação não pode ser desfeita.</p>`,
    textoBotao: 'Confirmar cancelamento',
    salvar: async (d) => { await api('POST', `/api/movimentacoes/${m.id}/cancelar`, d); fecharModal(); avisar('Lançamento cancelado e estoque estornado.', 'ok'); rotear(); },
  }));
}

/* =========================================================================
   Relatórios
   ========================================================================= */
let abaRelatorio = 'vendas';
async function paginaRelatorios() {
  const abas = { vendas: 'Vendas', estoque: 'Estoque', movimento: 'Entradas e saídas', imei: 'Rastrear IMEI' };
  const desenhar = async () => {
    $('#conteudo').innerHTML = `
      <div class="abas">${Object.entries(abas).map(([k, v]) => `<button data-aba="${k}" class="${k === abaRelatorio ? 'ativo' : ''}">${v}</button>`).join('')}</div>
      ${['vendas', 'movimento'].includes(abaRelatorio) ? `<div class="ferramentas">${htmlPeriodo()}<span class="espaco"></span><button class="btn" id="r-imp">Imprimir</button></div>` : ''}
      ${abaRelatorio === 'estoque' ? '<div class="ferramentas"><span class="espaco"></span><button class="btn" id="r-imp">Imprimir</button></div>' : ''}
      <div class="so-impressao"><h2>${esc(estado.meta.config.nome_loja)} — Relatório de ${esc(abas[abaRelatorio])}${abaRelatorio !== 'estoque' ? ` (${textoPeriodo()})` : ` em ${dia(isoLocal(new Date()))}`}</h2></div>
      <div id="rel" style="display:grid;gap:18px"><div class="carregando">Carregando…</div></div>`;
    $$('[data-aba]').forEach((b) => b.addEventListener('click', () => { abaRelatorio = b.dataset.aba; desenhar(); }));
    ligarPeriodo($('#conteudo'), desenhar);
    $('#r-imp')?.addEventListener('click', () => window.print());
    await ({ vendas: relVendas, estoque: relEstoque, movimento: relMovimento, imei: relImei })[abaRelatorio]();
  };
  await desenhar();
}

const colsGrupo = (rotulo) => [
  { r: rotulo, v: (l) => l.chave || '—' },
  { r: 'Vendas', v: (l) => l.vendas, cls: 'num' },
  { r: 'Itens', v: (l) => l.quantidade, h: (l) => num(l.quantidade), cls: 'num' },
  { r: 'Faturamento', v: (l) => l.faturamento, h: (l) => brl(l.faturamento), cls: 'num' },
  ...(ehAdmin() ? [{ r: 'Lucro bruto', v: (l) => l.lucro, h: (l) => brl(l.lucro), cls: 'num' }, { r: 'Margem', v: (l) => (l.faturamento ? Math.round((1000 * l.lucro) / l.faturamento) / 10 : 0), h: (l) => (l.faturamento ? pct((100 * l.lucro) / l.faturamento) : '—'), cls: 'num' }] : []),
];
const somaRodape = (cols, linhas) => cols.map((c, i) => {
  if (i === 0) return 'Total';
  if (['Faturamento', 'Lucro bruto', 'Valor (custo)', 'Valor (venda)', 'Valor', 'Custo'].includes(c.r)) return brl(linhas.reduce((a, l) => a + (+c.v(l) || 0), 0));
  if (['Itens', 'Unidades', 'Quantidade', 'Produtos', 'Lançamentos', 'Entradas', 'Vendidas', 'Outras saídas'].includes(c.r)) return num(linhas.reduce((a, l) => a + (+c.v(l) || 0), 0));
  return '';
});

async function relVendas() {
  const p = periodoAtual();
  const d = await api('GET', `/api/relatorios/vendas${qs({ inicio: p.inicio, fim: p.fim })}`);
  const r = d.resumo;
  const colsProd = colsGrupo('Produto');
  const colsVend = colsGrupo('Vendedor');
  const colsCat = colsGrupo('Categoria');
  const colsMarca = colsGrupo('Marca');
  const colsDia = [
    { r: 'Dia', v: (l) => dia(l.dia) }, { r: 'Vendas', v: (l) => l.vendas, cls: 'num' },
    { r: 'Faturamento', v: (l) => l.faturamento, h: (l) => brl(l.faturamento), cls: 'num' },
    ...(ehAdmin() ? [{ r: 'Lucro bruto', v: (l) => l.lucro, h: (l) => brl(l.lucro), cls: 'num' }] : []),
  ];
  const diasComVenda = d.por_dia.filter((l) => l.vendas);
  $('#rel').innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>Faturamento</span><strong>${brl(r.faturamento)}</strong><small>${num(r.vendas)} venda(s)</small></div>
      <div class="kpi"><span>Ticket médio</span><strong>${brl(r.ticket_medio)}</strong><small>${num(r.itens)} itens vendidos</small></div>
      ${ehAdmin() ? `<div class="kpi bom"><span>Lucro bruto</span><strong>${brl(r.lucro)}</strong><small>Margem ${pct(r.margem)} · custo ${brl(r.custo)}</small></div>` : ''}
      <div class="kpi"><span>Descontos concedidos</span><strong>${brl(r.descontos)}</strong></div>
    </div>
    <div class="duas-col">
      <section class="cartao"><div class="cartao-cab"><h2>Faturamento por dia</h2></div>${graficoBarras(d.por_dia)}</section>
      <section class="cartao"><div class="cartao-cab"><h2>Por forma de pagamento</h2></div>${barrasH(d.por_pagamento)}</section>
    </div>
    ${cartaoTabela('rv-prod', 'Vendas por produto', colsProd, d.por_produto, { csv: true, rodape: somaRodape(colsProd, d.por_produto), vazio: 'Nenhuma venda no período.' })}
    <div class="duas-iguais">
      ${cartaoTabela('rv-vend', 'Por vendedor', colsVend, d.por_vendedor, { csv: true })}
      ${cartaoTabela('rv-cat', 'Por categoria', colsCat, d.por_categoria, { csv: true })}
    </div>
    <div class="duas-iguais">
      ${cartaoTabela('rv-marca', 'Por marca', colsMarca, d.por_marca, { csv: true })}
      ${cartaoTabela('rv-dia', 'Por dia', colsDia, diasComVenda, { csv: true, sub: 'dias com venda' })}
    </div>`;
  ligarCSV($('#rel'), {
    'rv-prod': [`vendas-por-produto-${p.inicio}-a-${p.fim}`, colsProd, d.por_produto],
    'rv-vend': [`vendas-por-vendedor-${p.inicio}-a-${p.fim}`, colsVend, d.por_vendedor],
    'rv-cat': [`vendas-por-categoria-${p.inicio}-a-${p.fim}`, colsCat, d.por_categoria],
    'rv-marca': [`vendas-por-marca-${p.inicio}-a-${p.fim}`, colsMarca, d.por_marca],
    'rv-dia': [`vendas-por-dia-${p.inicio}-a-${p.fim}`, colsDia, d.por_dia],
  });
}

async function relEstoque() {
  const d = await api('GET', '/api/relatorios/estoque');
  const r = d.resumo;
  const adm = ehAdmin();
  const colsProd = [
    { r: 'Código', v: (l) => l.codigo || '' },
    { r: 'Produto', v: (l) => l.nome },
    { r: 'Categoria', v: (l) => l.categoria },
    { r: 'Unidades', v: (l) => l.estoque_atual, h: (l) => `<span class="estoque ${l.estoque_atual === 0 ? 'zero' : l.estoque_atual <= l.estoque_minimo ? 'baixo' : ''}">${num(l.estoque_atual)}</span>`, cls: 'num' },
    { r: 'Mínimo', v: (l) => l.estoque_minimo, cls: 'num' },
    ...(adm ? [{ r: 'Custo un.', v: (l) => l.preco_custo, h: (l) => brl(l.preco_custo), cls: 'num' }, { r: 'Valor (custo)', v: (l) => l.valor_custo, h: (l) => brl(l.valor_custo), cls: 'num' }] : []),
    { r: 'Valor (venda)', v: (l) => l.valor_venda, h: (l) => brl(l.valor_venda), cls: 'num' },
    { r: 'Última saída', v: (l) => dia(l.ultima_saida) || '—' },
  ];
  const colsCat = [
    { r: 'Categoria', v: (l) => l.chave }, { r: 'Produtos', v: (l) => l.produtos, cls: 'num' }, { r: 'Unidades', v: (l) => l.unidades, h: (l) => num(l.unidades), cls: 'num' },
    ...(adm ? [{ r: 'Valor (custo)', v: (l) => l.valor_custo, h: (l) => brl(l.valor_custo), cls: 'num' }] : []),
    { r: 'Valor (venda)', v: (l) => l.valor_venda, h: (l) => brl(l.valor_venda), cls: 'num' },
  ];
  const baixos = d.produtos.filter((l) => l.estoque_minimo > 0 && l.estoque_atual <= l.estoque_minimo);
  const colsBaixo = [
    { r: 'Produto', v: (l) => l.nome }, { r: 'Unidades', v: (l) => l.estoque_atual, cls: 'num' }, { r: 'Mínimo', v: (l) => l.estoque_minimo, cls: 'num' },
    { r: 'Sugestão de compra', v: (l) => Math.max(l.estoque_minimo * 2 - l.estoque_atual, 1), h: (l) => `<strong>${num(Math.max(l.estoque_minimo * 2 - l.estoque_atual, 1))}</strong>`, cls: 'num' },
  ];
  $('#rel').innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>Unidades em estoque</span><strong>${num(r.unidades)}</strong><small>${num(r.produtos)} produtos ativos</small></div>
      ${adm ? `<div class="kpi"><span>Valor a preço de custo</span><strong>${brl(r.valor_custo)}</strong></div>` : ''}
      <div class="kpi"><span>Valor a preço de venda</span><strong>${brl(r.valor_venda)}</strong>${adm ? `<small>Lucro potencial ${brl(r.valor_venda - r.valor_custo)}</small>` : ''}</div>
      <div class="kpi ${r.abaixo_minimo ? 'alerta' : ''}"><span>Abaixo do mínimo</span><strong>${num(r.abaixo_minimo)}</strong><small>${num(r.zerados)} zerado(s)</small></div>
    </div>
    <div class="duas-iguais">
      ${cartaoTabela('re-cat', 'Por categoria', colsCat, d.por_categoria, { csv: true, rodape: somaRodape(colsCat, d.por_categoria) })}
      ${cartaoTabela('re-baixo', 'Lista de reposição', colsBaixo, baixos, { csv: true, vazio: 'Nenhum produto abaixo do mínimo.', sub: 'sugestão = 2× o mínimo' })}
    </div>
    ${cartaoTabela('re-prod', 'Posição de estoque por produto', colsProd, d.produtos, { csv: true, rodape: somaRodape(colsProd, d.produtos) })}`;
  ligarCSV($('#rel'), {
    're-cat': ['estoque-por-categoria', colsCat, d.por_categoria],
    're-baixo': ['lista-de-reposicao', colsBaixo, baixos],
    're-prod': [`posicao-de-estoque-${isoLocal(new Date())}`, colsProd, d.produtos],
  });
}

async function relMovimento() {
  const p = periodoAtual();
  const d = await api('GET', `/api/relatorios/movimentacoes${qs({ inicio: p.inicio, fim: p.fim })}`);
  const adm = ehAdmin();
  const colsMot = [
    { r: 'Tipo', v: (l) => nomeTipo(l.tipo), h: tagTipo }, { r: 'Motivo', v: (l) => l.motivo },
    { r: 'Lançamentos', v: (l) => l.lancamentos, cls: 'num' }, { r: 'Quantidade', v: (l) => l.quantidade, h: (l) => num(l.quantidade), cls: 'num' },
    { r: 'Valor', v: (l) => l.valor, h: (l) => brl(l.valor), cls: 'num' },
    ...(adm ? [{ r: 'Custo', v: (l) => l.custo, h: (l) => brl(l.custo), cls: 'num' }] : []),
  ];
  const colsProd = [
    { r: 'Produto', v: (l) => l.nome }, { r: 'Entradas', v: (l) => l.entradas, h: (l) => (l.entradas ? `+${num(l.entradas)}` : '—'), cls: 'num' },
    { r: 'Vendidas', v: (l) => l.vendidas, h: (l) => (l.vendidas ? `−${num(l.vendidas)}` : '—'), cls: 'num' },
    { r: 'Outras saídas', v: (l) => l.outras_saidas, h: (l) => (l.outras_saidas ? `−${num(l.outras_saidas)}` : '—'), cls: 'num' },
    ...(adm ? [{ r: 'Custo das perdas', v: (l) => l.custo_perdas, h: (l) => (l.custo_perdas ? brl(l.custo_perdas) : '—'), cls: 'num' }] : []),
    { r: 'Estoque atual', v: (l) => l.estoque_atual, cls: 'num' },
  ];
  const colsParado = [
    { r: 'Produto', v: (l) => l.nome }, { r: 'Unidades', v: (l) => l.estoque_atual, cls: 'num' },
    ...(adm ? [{ r: 'Valor (custo)', v: (l) => l.valor_custo, h: (l) => brl(l.valor_custo), cls: 'num' }] : []),
    { r: 'Última saída', v: (l) => dia(l.ultima_saida) || 'nunca' },
  ];
  const perdas = d.por_motivo.filter((l) => l.tipo === 'saida' && l.motivo === 'Perda/Avaria');
  const totEnt = d.por_motivo.filter((l) => l.tipo === 'entrada').reduce((a, l) => a + l.quantidade, 0);
  const totSai = d.por_motivo.filter((l) => l.tipo === 'saida').reduce((a, l) => a + l.quantidade, 0);
  const comprado = d.por_motivo.filter((l) => l.tipo === 'entrada' && l.motivo === 'Compra').reduce((a, l) => a + l.valor, 0);
  $('#rel').innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>Unidades que entraram</span><strong>${num(totEnt)}</strong>${adm ? `<small>Compras: ${brl(comprado)}</small>` : ''}</div>
      <div class="kpi"><span>Unidades que saíram</span><strong>${num(totSai)}</strong></div>
      <div class="kpi ${perdas.length ? 'alerta' : ''}"><span>Perdas e avarias</span><strong>${num(perdas.reduce((a, l) => a + l.quantidade, 0))} un.</strong>${adm ? `<small>Custo ${brl(perdas.reduce((a, l) => a + l.custo, 0))}</small>` : ''}</div>
      <div class="kpi"><span>Produtos sem saída no período</span><strong>${num(d.parados.length)}</strong></div>
    </div>
    ${cartaoTabela('rm-mot', 'Resumo por motivo', colsMot, d.por_motivo, { csv: true, vazio: 'Nenhuma movimentação no período.' })}
    ${cartaoTabela('rm-prod', 'Entradas e saídas por produto', colsProd, d.por_produto, { csv: true, rodape: somaRodape(colsProd, d.por_produto), vazio: 'Nenhuma movimentação no período.' })}
    ${cartaoTabela('rm-par', 'Estoque parado (sem saída no período)', colsParado, d.parados, { csv: true, vazio: 'Todos os produtos com estoque tiveram saída.' })}`;
  ligarCSV($('#rel'), {
    'rm-mot': [`movimento-por-motivo-${p.inicio}-a-${p.fim}`, colsMot, d.por_motivo],
    'rm-prod': [`movimento-por-produto-${p.inicio}-a-${p.fim}`, colsProd, d.por_produto],
    'rm-par': [`estoque-parado-${p.inicio}-a-${p.fim}`, colsParado, d.parados],
  });
}

async function relImei() {
  $('#rel').innerHTML = `
    <section class="cartao"><form id="f-imei" class="ferramentas"><label class="busca">IMEI do aparelho<input id="imei" inputmode="numeric" maxlength="20" placeholder="15 dígitos" autofocus></label><button class="btn btn-primario">Rastrear</button></form>
    <p class="sutil" style="margin:10px 0 0">Veja de onde o aparelho veio, para quem foi vendido e se está em estoque. Útil para garantia e trocas.</p></section>
    <div id="imei-res"></div>`;
  $('#f-imei').addEventListener('submit', async (e) => {
    e.preventDefault();
    const imei = $('#imei').value.replace(/\D/g, '');
    const alvo = $('#imei-res');
    if (imei.length !== 15) { alvo.innerHTML = '<div class="faixa faixa-alerta">O IMEI tem 15 dígitos.</div>'; return; }
    try {
      const d = await api('GET', `/api/imeis/${imei}`);
      const st = { disponivel: ['Em estoque', 'tag-entrada'], vendido: ['Vendido', 'tag-saida'], baixado: ['Baixado (saída)', 'tag-alerta'], cancelado: ['Entrada cancelada', 'tag-perigo'] }[d.atual?.status] || ['—', ''];
      alvo.innerHTML = `<section class="cartao"><div class="cartao-cab"><h2 class="mono">${esc(d.imei)}</h2><span class="tag ${st[1]}">${st[0]}</span></div>
        ${d.atual ? `<p>Produto: <a href="#/produtos/${d.atual.produto_id}">${esc(d.atual.produto_nome)}</a></p>` : ''}
        <ul class="linha-tempo">${d.historico.map((h) => `<li class="${h.tipo}"><strong><a href="#/movimentacoes/${h.id}">#${h.id}</a> · ${esc(nomeTipo(h.tipo))} — ${esc(h.motivo)}</strong>${h.cancelada ? ' <span class="tag tag-perigo">cancelada</span>' : ''}<br>
          <small>${esc(dataHora(h.data))} · ${esc(h.produto_nome)}${h.cliente_nome ? ` · Cliente: ${esc(h.cliente_nome)}` : ''}${h.fornecedor_nome ? ` · Fornecedor: ${esc(h.fornecedor_nome)}` : ''} · ${brl(h.valor_unitario)}</small></li>`).join('')}</ul></section>`;
    } catch (err) { alvo.innerHTML = `<div class="faixa faixa-alerta">${esc(err.message)}</div>`; }
  });
}

/* =========================================================================
   Clientes e fornecedores
   ========================================================================= */
const CAMPOS_CADASTRO = (tabela) => [
  { n: 'nome', r: tabela === 'clientes' ? 'Nome' : 'Razão social / nome', req: true, col2: true },
  { n: 'documento', r: tabela === 'clientes' ? 'CPF' : 'CNPJ / CPF' },
  { n: 'telefone', r: 'Telefone / WhatsApp', t: 'tel' },
  { n: 'email', r: 'E-mail', t: 'email', col2: true },
  { n: 'observacao', r: 'Observação', t: 'textarea', col2: true },
];

async function paginaCadastro(tab) {
  const rotulo = tab === 'clientes' ? 'cliente' : 'fornecedor';
  const cols = [
    { r: 'Nome', v: (c) => c.nome, h: (c) => `<strong>${esc(c.nome)}</strong>` },
    { r: tab === 'clientes' ? 'CPF' : 'CNPJ / CPF', v: (c) => c.documento || '' },
    { r: 'Telefone', v: (c) => c.telefone || '' },
    { r: 'E-mail', v: (c) => c.email || '' },
    { r: 'Cadastro', v: (c) => dia(c.criado_em) },
  ];
  $('#conteudo').innerHTML = `<div class="ferramentas"><label class="busca">Buscar<input type="search" id="c-q" placeholder="Nome, documento ou telefone"></label><span class="espaco"></span>
    <button class="btn" id="c-csv">Exportar CSV</button><button class="btn btn-primario" id="c-novo">+ Novo ${rotulo}</button></div>
    <section class="cartao sem-pad" id="lista-cad"></section>`;
  let linhas = [];
  const carregar = async () => {
    linhas = await api('GET', `/api/${tab}${qs({ q: $('#c-q').value.trim() })}`);
    $('#lista-cad').innerHTML = `<div class="cartao-cab"><h2>${num(linhas.length)} ${rotulo}(es)</h2></div>${tabela(cols, linhas, { clique: true, vazio: `Nenhum ${rotulo} cadastrado.` })}`;
    ligarCliques($('#lista-cad'), linhas, abrir);
  };
  const form = (c) => abrirForm({
    titulo: c ? `Editar ${rotulo}` : `Novo ${rotulo}`, campos: CAMPOS_CADASTRO(tab), valores: c || {},
    salvar: async (d) => { await (c ? api('PUT', `/api/${tab}/${c.id}`, d) : api('POST', `/api/${tab}`, d)); fecharModal(); avisar('Salvo.', 'ok'); carregar(); },
  });
  async function abrir(c) {
    const d = await api('GET', `/api/${tab}/${c.id}`);
    const ativas = d.movimentacoes.filter((m) => !m.cancelada);
    const corpo = abrirModal(d.nome, `
      <div class="recibo"><dl>
        ${d.documento ? `<dt>Documento</dt><dd>${esc(d.documento)}</dd>` : ''}${d.telefone ? `<dt>Telefone</dt><dd>${esc(d.telefone)}</dd>` : ''}
        ${d.email ? `<dt>E-mail</dt><dd>${esc(d.email)}</dd>` : ''}${d.observacao ? `<dt>Observação</dt><dd>${esc(d.observacao)}</dd>` : ''}
        <dt>${tab === 'clientes' ? 'Total comprado' : 'Total fornecido'}</dt><dd><strong>${brl(ativas.reduce((a, m) => a + m.total, 0))}</strong> em ${num(ativas.length)} lançamento(s)</dd>
      </dl></div>
      ${tabela([{ r: 'Nº', v: (m) => m.id, h: (m) => `<a href="#/movimentacoes/${m.id}">#${m.id}</a>` }, { r: 'Motivo', v: (m) => m.motivo }, { r: 'Data', v: (m) => dataHora(m.data) }, { r: 'Total', v: (m) => m.total, h: (m) => brl(m.total), cls: 'num' }], d.movimentacoes, { vazio: 'Sem movimentações.', classeLinha: (m) => (m.cancelada ? 'cancelada' : '') })}
      <div class="acoes-form">${ehAdmin() ? '<button class="btn btn-perigo" id="c-excluir">Excluir</button>' : ''}<span class="espaco"></span><button class="btn" id="c-editar">Editar</button></div>`, { largo: true });
    $('#c-editar', corpo).addEventListener('click', () => form(d));
    $('#c-excluir', corpo)?.addEventListener('click', async () => {
      if (!confirm(`Excluir ${d.nome}?`)) return;
      try { await api('DELETE', `/api/${tab}/${d.id}`); fecharModal(); avisar('Excluído.', 'ok'); carregar(); } catch (e) { avisar(e.message, 'erro'); }
    });
    $$('a', corpo).forEach((a) => a.addEventListener('click', fecharModal));
  }
  let t;
  $('#c-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(carregar, 250); });
  $('#c-novo').addEventListener('click', () => form(null));
  $('#c-csv').addEventListener('click', () => baixarCSV(tab, cols, linhas));
  await carregar();
}

/* =========================================================================
   Usuários e configurações (admin)
   ========================================================================= */
async function paginaUsuarios() {
  const lista = await api('GET', '/api/usuarios');
  const cols = [
    { r: 'Nome', v: (u) => u.nome, h: (u) => `<strong>${esc(u.nome)}</strong>` },
    { r: 'Usuário', v: (u) => u.login, h: (u) => `<span class="mono">${esc(u.login)}</span>` },
    { r: 'Perfil', v: (u) => u.perfil, h: (u) => `<span class="tag ${u.perfil === 'admin' ? 'tag-saida' : ''}">${u.perfil === 'admin' ? 'Administrador' : 'Vendedor'}</span>` },
    { r: 'Situação', v: (u) => (u.ativo ? 'Ativo' : 'Inativo'), h: (u) => (u.ativo ? 'Ativo' : '<span class="tag tag-perigo">Inativo</span>') },
    { r: 'Desde', v: (u) => dia(u.criado_em) },
  ];
  $('#conteudo').innerHTML = `<div class="faixa faixa-info"><strong>Administrador</strong>: acesso total, vê custos e lucro, cadastra produtos, cancela lançamentos e faz ajustes de inventário. <strong>Vendedor</strong>: registra vendas, entradas e clientes, sem ver custos.</div>
    <div class="ferramentas"><span class="espaco"></span><button class="btn btn-primario" id="u-novo">+ Novo usuário</button></div>
    <section class="cartao sem-pad" id="lista-u">${tabela(cols, lista, { clique: true })}</section>`;
  const form = (u) => abrirForm({
    titulo: u ? `Editar ${u.nome}` : 'Novo usuário',
    campos: [
      { n: 'nome', r: 'Nome', req: true, col2: true },
      ...(u ? [] : [{ n: 'login', r: 'Usuário (login)', req: true, attrs: 'autocomplete="off" pattern="[A-Za-z0-9._\\-]+"' }]),
      { n: 'perfil', r: 'Perfil', t: 'select', opts: [['vendedor', 'Vendedor'], ['admin', 'Administrador']] },
      { n: 'senha', r: u ? 'Nova senha (deixe vazio para manter)' : 'Senha', t: 'password', req: !u, attrs: 'minlength="6" autocomplete="new-password"' },
      ...(u ? [{ n: 'ativo', r: 'Usuário ativo', t: 'check' }] : []),
    ],
    valores: u ? { ...u, ativo: !!u.ativo } : { perfil: 'vendedor' },
    salvar: async (d) => { await (u ? api('PUT', `/api/usuarios/${u.id}`, d) : api('POST', '/api/usuarios', d)); fecharModal(); avisar('Usuário salvo.', 'ok'); rotear(); },
  });
  ligarCliques($('#lista-u'), lista, form);
  $('#u-novo').addEventListener('click', () => form(null));
}

async function paginaConfig() {
  const cfg = estado.meta.config;
  $('#conteudo').innerHTML = `
    <div class="duas-iguais">
      <section class="cartao"><div class="cartao-cab"><h2>Dados da loja</h2><small class="sutil">Aparecem nos comprovantes e relatórios</small></div>
        <form id="f-cfg"><div class="grade-form">
          ${campoHTML({ n: 'nome_loja', r: 'Nome da loja', req: true, col2: true }, cfg.nome_loja)}
          ${campoHTML({ n: 'documento', r: 'CNPJ' }, cfg.documento)}
          ${campoHTML({ n: 'telefone', r: 'Telefone' }, cfg.telefone)}
          ${campoHTML({ n: 'endereco', r: 'Endereço', col2: true }, cfg.endereco)}
          ${campoHTML({ n: 'rodape_recibo', r: 'Mensagem no rodapé do comprovante', t: 'textarea', col2: true }, cfg.rodape_recibo)}
        </div><p class="erro-form"></p><div class="acoes-form"><button class="btn btn-primario">Salvar</button></div></form></section>
      <section class="cartao"><div class="cartao-cab"><h2>Cópia de segurança</h2></div>
        <p>Baixe uma cópia completa do banco de dados (produtos, estoque, vendas, clientes). Faça isso com frequência e guarde fora deste computador (pen drive, Google Drive).</p>
        <p class="sutil">Para restaurar: pare o sistema, substitua o arquivo <span class="mono">dados/estoque.db</span> pela cópia e inicie de novo.</p>
        <a class="btn btn-primario" href="/api/backup" download>Baixar backup agora</a></section>
    </div>`;
  $('#f-cfg').addEventListener('submit', async (e) => {
    e.preventDefault();
    try { estado.meta.config = await api('PUT', '/api/config', lerForm(e.target)); atualizarNomeLoja(); avisar('Configurações salvas.', 'ok'); } catch (err) { $('.erro-form', e.target).textContent = err.message; }
  });
}

/* =========================================================================
   Início
   ========================================================================= */
(async () => {
  try { estado.usuario = await api('GET', '/api/me'); await iniciarApp(); } catch { mostrarLogin(); }
})();
