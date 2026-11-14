'use strict';
/* Módulos de gestão: ordens de serviço, orçamentos, financeiro e caixa.
   Usa as utilidades globais definidas em app.js (api, esc, brl, tabela, abrirForm...). */

/* =========================================================================
   Componentes compartilhados
   ========================================================================= */
function ligarBuscaProduto(input, caixa, { params = {}, filtro = () => true, aoEscolher, precoDe = (p) => p.preco_venda }) {
  let achados = [], foco = -1, t;
  const fechar = () => { caixa.hidden = true; foco = -1; };
  async function buscar() {
    const termo = input.value.trim();
    if (!termo) { achados = []; fechar(); return; }
    achados = (await api('GET', `/api/produtos${qs({ q: termo, ...params })}`)).filter(filtro);
    if (input.value.trim() !== termo) return;
    caixa.innerHTML = achados.length
      ? achados.slice(0, 30).map((p, i) => `<button type="button" data-r="${i}"><span><strong>${esc(p.nome)}</strong><br><small>${esc([p.codigo, p.categoria].filter(Boolean).join(' · '))}</small></span><span class="num"><small>estoque</small> ${num(p.estoque_atual)}<br>${brl(precoDe(p))}</span></button>`).join('')
      : '<button type="button" disabled><span class="sutil">Nada encontrado.</span></button>';
    caixa.hidden = false;
    $$('[data-r]', caixa).forEach((b) => b.addEventListener('click', () => escolher(+b.dataset.r)));
  }
  function escolher(i) {
    const p = achados[i];
    if (!p) return;
    input.value = '';
    fechar();
    aoEscolher(p);
    input.focus();
  }
  input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => buscar().catch(() => {}), 200); });
  input.addEventListener('keydown', async (e) => {
    const bs = $$('[data-r]', caixa);
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!bs.length) return;
      foco = (foco + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length;
      bs.forEach((b, i) => b.classList.toggle('foco', i === foco));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(t);
      if (foco < 0) await buscar().catch(() => {});
      if (foco >= 0) escolher(foco);
      else if (achados.length === 1) escolher(0);
      else {
        const k = achados.findIndex((p) => p.codigo && p.codigo.toLowerCase() === input.value.trim().toLowerCase());
        if (k >= 0) escolher(k);
      }
    } else if (e.key === 'Escape') fechar();
  });
  document.addEventListener('click', (e) => { if (!e.target.closest('.busca-produto')) fechar(); });
}

/* Editor de linhas de produtos (orçamento e peças da OS). itens: [{produto_id, produto_nome, quantidade, valor_unitario, estoque_atual}] */
function editorItens(el, itens, aoMudar) {
  const desenhar = () => {
    if (!itens.length) { el.innerHTML = '<p class="vazio">Nenhum item adicionado.</p>'; aoMudar(); return; }
    el.innerHTML = `<div class="tabela-wrap"><table><thead><tr><th>Produto</th><th class="num">Qtd</th><th class="num">Valor un.</th><th class="num">Subtotal</th><th></th></tr></thead><tbody>
      ${itens.map((it, i) => `<tr class="item-linha"><td><div class="celula-produto"><strong>${esc(it.produto_nome)}</strong><small>estoque ${num(it.estoque_atual)}</small></div></td>
        <td class="num"><input class="qtd" type="number" min="1" step="1" data-q="${i}" value="${it.quantidade}"></td>
        <td class="num"><input class="valor" inputmode="decimal" data-v="${i}" value="${String(Number(it.valor_unitario).toFixed(2)).replace('.', ',')}"></td>
        <td class="num" data-s="${i}">${brl(it.quantidade * it.valor_unitario)}</td>
        <td><button type="button" class="btn btn-fantasma btn-p" data-x="${i}" aria-label="Remover">✕</button></td></tr>`).join('')}</tbody></table></div>`;
    const sub = (i) => { $(`[data-s="${i}"]`, el).textContent = brl(itens[i].quantidade * itens[i].valor_unitario); aoMudar(); };
    $$('[data-q]', el).forEach((x) => x.addEventListener('input', () => { itens[+x.dataset.q].quantidade = Math.max(1, parseInt(x.value, 10) || 1); sub(+x.dataset.q); }));
    $$('[data-v]', el).forEach((x) => x.addEventListener('input', () => { itens[+x.dataset.v].valor_unitario = paraNumero(x.value); sub(+x.dataset.v); }));
    $$('[data-x]', el).forEach((x) => x.addEventListener('click', () => { itens.splice(+x.dataset.x, 1); desenhar(); }));
    aoMudar();
  };
  desenhar();
  return {
    adicionar(p) {
      const ja = itens.find((i) => i.produto_id === p.id);
      if (ja) ja.quantidade += 1;
      else itens.push({ produto_id: p.id, produto_nome: p.nome, quantidade: 1, valor_unitario: p.preco_venda, estoque_atual: p.estoque_atual });
      desenhar();
    },
  };
}

function opcoesClientes(clientes, sel, vazio = '— selecione o cliente —') {
  return `<option value="">${esc(vazio)}</option>${clientes.map((c) => `<option value="${c.id}" ${String(c.id) === String(sel) ? 'selected' : ''}>${esc(c.nome)}${c.telefone ? ` · ${esc(c.telefone)}` : ''}</option>`).join('')}`;
}
function ligarNovoCliente(botao, select) {
  botao.addEventListener('click', () => abrirForm({
    titulo: 'Novo cliente', campos: CAMPOS_CADASTRO('clientes'),
    salvar: async (d) => {
      const r = await api('POST', '/api/clientes', d);
      select.insertAdjacentHTML('beforeend', `<option value="${r.id}" selected>${esc(r.nome)}</option>`);
      select.value = r.id;
      select.dispatchEvent(new Event('change'));
      fecharModal(); avisar('Cliente cadastrado.', 'ok');
    },
  }));
}
function linkWhatsApp(telefone, texto) {
  let n = String(telefone || '').replace(/\D/g, '');
  if (!n) return '';
  if (n.length <= 11) n = `55${n}`;
  return `https://wa.me/${n}?text=${encodeURIComponent(texto)}`;
}
function cabecalhoLoja(titulo, sub) {
  const cfg = estado.meta.config;
  return `<div class="recibo-cab"><div><h2>${esc(cfg.nome_loja)}</h2><small>${esc([cfg.documento, cfg.endereco, cfg.telefone].filter(Boolean).join(' · '))}</small></div>
    <div class="num"><h2>${esc(titulo)}</h2><small>${esc(sub)}</small></div></div>`;
}
function campoCondicao(prefixo) {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return `<label>Parcelas<input type="number" id="${prefixo}-parcelas" min="1" max="48" value="1"></label>
    <label>1º vencimento<input type="date" id="${prefixo}-venc" value="${isoLocal(d)}"></label>`;
}

/* =========================================================================
   Ordens de serviço
   ========================================================================= */
const CLASSE_OS = {
  Aberta: '', 'Em análise': 'tag-alerta', 'Aguardando aprovação': 'tag-alerta', Aprovada: 'tag-saida', 'Aguardando peça': 'tag-alerta',
  'Em reparo': 'tag-saida', 'Pronta para retirada': 'tag-entrada', Entregue: 'tag-ok', Cancelada: 'tag-perigo',
};
const tagOS = (s) => `<span class="tag ${CLASSE_OS[s] ?? ''}">${esc(s)}</span>`;
let filtroOS = 'abertas';

async function paginaOS(param, q) {
  if (param === 'novo') return editorOS(null, q);
  if (param && q.get('editar') === '1') return editorOS(+param, q);
  if (param) return verOS(+param);
  const chips = [['abertas', 'Em andamento'], ...estado.meta.status_os.map((s) => [s, s]), ['', 'Todas']];
  $('#conteudo').innerHTML = `
    <div class="ferramentas"><label class="busca">Buscar<input type="search" id="os-q" placeholder="Nº, cliente, telefone, aparelho ou IMEI"></label><span class="espaco"></span>
      <button class="btn" id="os-csv">Exportar CSV</button><a class="btn btn-primario" href="#/os/novo">+ Nova OS</a></div>
    <div class="chips" id="os-chips">${chips.map(([k, r]) => `<button class="chip ${k === filtroOS ? 'ativo' : ''}" data-k="${esc(k)}">${esc(r)}</button>`).join('')}</div>
    <section class="cartao sem-pad" id="lista-os"><div class="carregando">Carregando…</div></section>`;
  const hoje = isoLocal(new Date());
  const cols = [
    { r: 'Nº', v: (o) => o.id, h: (o) => `<strong>#${o.id}</strong>` },
    { r: 'Entrada', v: (o) => dia(o.entrada_em) },
    { r: 'Cliente', v: (o) => o.cliente_nome, h: (o) => `<div class="celula-produto"><strong>${esc(o.cliente_nome)}</strong><small>${esc(o.cliente_telefone || '')}</small></div>` },
    { r: 'Aparelho', v: (o) => o.aparelho, h: (o) => `<div class="celula-produto"><strong>${esc(o.aparelho)}</strong><small>${esc((o.defeito || '').slice(0, 60))}</small></div>` },
    { r: 'Técnico', v: (o) => o.tecnico || '' },
    { r: 'Previsão', v: (o) => dia(o.previsao), h: (o) => (o.previsao ? `<span class="${o.previsao < hoje && !['Entregue', 'Cancelada', 'Pronta para retirada'].includes(o.status) ? 'estoque baixo' : ''}">${dia(o.previsao)}</span>` : '—') },
    { r: 'Situação', v: (o) => o.status, h: (o) => tagOS(o.status) },
    { r: 'Total', v: (o) => o.total, h: (o) => brl(o.total), cls: 'num' },
  ];
  let linhas = [];
  const carregar = async () => {
    linhas = await api('GET', `/api/os${qs({ status: filtroOS, q: $('#os-q').value.trim() })}`);
    $('#lista-os').innerHTML = `<div class="cartao-cab"><h2>${num(linhas.length)} ordem(ns) de serviço</h2></div>${tabela(cols, linhas, { clique: true, vazio: 'Nenhuma OS encontrada.' })}`;
    ligarCliques($('#lista-os'), linhas, (o) => { location.hash = `#/os/${o.id}`; });
  };
  $$('#os-chips [data-k]').forEach((b) => b.addEventListener('click', () => {
    filtroOS = b.dataset.k;
    $$('#os-chips .chip').forEach((x) => x.classList.toggle('ativo', x === b));
    carregar();
  }));
  let t;
  $('#os-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(carregar, 250); });
  $('#os-csv').addEventListener('click', () => baixarCSV('ordens-de-servico', cols, linhas));
  await carregar();
}

async function editorOS(id) {
  const [clientes, o] = await Promise.all([api('GET', '/api/clientes'), id ? api('GET', `/api/os/${id}`) : null]);
  $('#titulo-pagina').textContent = id ? `Editar OS #${id}` : 'Nova ordem de serviço';
  const d = o || { garantia_dias: estado.meta.config.garantia_os_dias || 90, servicos: [], pecas: [], desconto: 0 };
  const servicos = (d.servicos || []).map((s) => ({ descricao: s.descricao, valor: s.valor }));
  const pecas = (d.pecas || []).map((p) => ({ ...p }));
  $('#conteudo').innerHTML = `
    <div class="ferramentas"><a class="btn" href="#/os${id ? `/${id}` : ''}">← Voltar</a></div>
    <form id="f-os" class="lancamento">
      <div style="display:grid;gap:18px;min-width:0">
        <section class="cartao"><div class="cartao-cab"><h2>Cliente e aparelho</h2></div><div class="grade-form">
          <label class="col-2">Cliente *<div class="linha-input"><select name="cliente_id" required>${opcoesClientes(clientes, d.cliente_id)}</select><button class="btn" type="button" id="os-novo-cli" title="Cadastrar cliente">+</button></div></label>
          ${campoHTML({ n: 'aparelho', r: 'Aparelho (marca e modelo)', req: true, attrs: 'placeholder="Ex.: iPhone 11 128GB"' }, d.aparelho)}
          ${campoHTML({ n: 'cor', r: 'Cor' }, d.cor)}
          ${campoHTML({ n: 'imei', r: 'IMEI', attrs: 'inputmode="numeric" maxlength="20"' }, d.imei)}
          ${campoHTML({ n: 'senha_desbloqueio', r: 'Senha / padrão de desbloqueio' }, d.senha_desbloqueio)}
          ${campoHTML({ n: 'acessorios', r: 'Acessórios deixados', col2: true, attrs: 'placeholder="Ex.: capinha, chip, carregador"' }, d.acessorios)}
          ${campoHTML({ n: 'defeito', r: 'Defeito relatado pelo cliente', t: 'textarea', req: true, col2: true }, d.defeito)}
          ${campoHTML({ n: 'laudo', r: 'Laudo técnico / diagnóstico', t: 'textarea', col2: true }, d.laudo)}
        </div></section>
        <section class="cartao"><div class="cartao-cab"><h2>Serviços</h2><button type="button" class="btn btn-p" id="os-add-serv">+ Serviço</button></div><div id="os-servicos"></div></section>
        <section class="cartao"><div class="cartao-cab"><h2>Peças do estoque</h2><small class="sutil">Saem do estoque quando a OS for entregue</small></div>
          <div class="busca-produto"><input id="os-busca" type="search" autocomplete="off" placeholder="Buscar peça pelo nome ou código…"><div class="resultados" id="os-res" hidden></div></div>
          <div id="os-pecas" style="margin-top:12px"></div></section>
      </div>
      <aside class="lancamento-lateral">
        <section class="cartao"><div class="grade-form">
          ${campoHTML({ n: 'tecnico', r: 'Técnico responsável', col2: true }, d.tecnico)}
          ${campoHTML({ n: 'previsao', r: 'Previsão de entrega', t: 'date' }, d.previsao)}
          ${campoHTML({ n: 'garantia_dias', r: 'Garantia (dias)', t: 'number', attrs: 'min="0"' }, d.garantia_dias)}
          ${campoHTML({ n: 'observacao', r: 'Observação interna', t: 'textarea', col2: true }, d.observacao)}
        </div></section>
        <section class="cartao"><div class="totais">
          <div><span>Serviços</span><span id="os-t-serv"></span></div>
          <div><span>Peças</span><span id="os-t-pecas"></span></div>
          <div><label style="width:100%">Desconto (R$)<input name="desconto" inputmode="decimal" value="${d.desconto ? String(d.desconto).replace('.', ',') : ''}" placeholder="0,00"></label></div>
          <div class="total"><span>Total</span><span id="os-t-total"></span></div>
          <p class="erro-form" id="os-erro"></p>
          <button class="btn btn-g btn-primario btn-largo" type="submit">${id ? 'Salvar alterações' : 'Abrir ordem de serviço'}</button>
        </div></section>
      </aside>
    </form>`;
  const form = $('#f-os');
  const totais = () => {
    const vs = servicos.reduce((a, s) => a + (s.valor || 0), 0);
    const vp = pecas.reduce((a, p) => a + p.quantidade * p.valor_unitario, 0);
    $('#os-t-serv').textContent = brl(vs);
    $('#os-t-pecas').textContent = brl(vp);
    $('#os-t-total').textContent = brl(Math.max(vs + vp - paraNumero($('[name=desconto]', form).value), 0));
  };
  const desenharServ = () => {
    const el = $('#os-servicos');
    el.innerHTML = servicos.length ? servicos.map((s, i) => `<div class="linha-input" style="margin-bottom:8px"><input data-sd="${i}" placeholder="Ex.: Troca de tela" value="${esc(s.descricao)}"><input data-sv="${i}" inputmode="decimal" style="max-width:130px" placeholder="0,00" value="${s.valor ? String(s.valor.toFixed(2)).replace('.', ',') : ''}"><button type="button" class="btn btn-fantasma" data-sx="${i}" aria-label="Remover">✕</button></div>`).join('') : '<p class="vazio">Nenhum serviço. Adicione o que será feito (pode ser depois do diagnóstico).</p>';
    $$('[data-sd]', el).forEach((x) => x.addEventListener('input', () => { servicos[+x.dataset.sd].descricao = x.value; }));
    $$('[data-sv]', el).forEach((x) => x.addEventListener('input', () => { servicos[+x.dataset.sv].valor = paraNumero(x.value); totais(); }));
    $$('[data-sx]', el).forEach((x) => x.addEventListener('click', () => { servicos.splice(+x.dataset.sx, 1); desenharServ(); }));
    totais();
  };
  $('#os-add-serv').addEventListener('click', () => { servicos.push({ descricao: '', valor: 0 }); desenharServ(); $(`[data-sd="${servicos.length - 1}"]`).focus(); });
  desenharServ();
  const ed = editorItens($('#os-pecas'), pecas, totais);
  ligarBuscaProduto($('#os-busca'), $('#os-res'), { filtro: (p) => !p.controla_imei, aoEscolher: (p) => ed.adicionar(p) });
  ligarNovoCliente($('#os-novo-cli'), $('[name=cliente_id]', form));
  $('[name=desconto]', form).addEventListener('input', totais);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('button[type=submit]', form);
    btn.disabled = true;
    $('#os-erro').textContent = '';
    const corpo = { ...lerForm(form), desconto: paraNumero($('[name=desconto]', form).value), servicos: servicos.filter((s) => s.descricao.trim()), pecas: pecas.map((p) => ({ produto_id: p.produto_id, quantidade: p.quantidade, valor_unitario: p.valor_unitario })) };
    try {
      const r = id ? await api('PUT', `/api/os/${id}`, corpo) : await api('POST', '/api/os', corpo);
      avisar(id ? 'OS atualizada.' : `OS #${r.id} aberta.`, 'ok');
      location.hash = `#/os/${r.id}`;
    } catch (err) { $('#os-erro').textContent = err.message; } finally { btn.disabled = false; }
  });
}

async function verOS(id) {
  const o = await api('GET', `/api/os/${id}`);
  const cfg = estado.meta.config;
  const aberta = !['Entregue', 'Cancelada'].includes(o.status);
  $('#titulo-pagina').textContent = `OS #${o.id}`;
  const msgPronta = `Olá, ${o.cliente_nome}! Aqui é da ${cfg.nome_loja}. Seu aparelho ${o.aparelho} (OS #${o.id}) está pronto para retirada. Valor: ${brl(o.total)}.`;
  const zap = linkWhatsApp(o.cliente_telefone, msgPronta);
  $('#conteudo').innerHTML = `
    <div class="ferramentas nao-imprimir">
      <a class="btn" href="#/os">← Ordens de serviço</a><span class="espaco"></span>
      ${zap && aberta ? `<a class="btn" href="${esc(zap)}" target="_blank" rel="noopener">Avisar no WhatsApp</a>` : ''}
      ${aberta || ehAdmin() ? (o.status !== 'Cancelada' ? '<button class="btn btn-perigo" id="os-cancelar">Cancelar OS</button>' : '') : ''}
      ${aberta ? `<a class="btn" href="#/os/${o.id}?editar=1">Editar</a><button class="btn" id="os-status">Mudar situação</button>` : ''}
      <button class="btn" id="os-imprimir">Imprimir</button>
      ${aberta ? '<button class="btn btn-sucesso" id="os-entregar">Entregar e receber</button>' : ''}
    </div>
    <div class="nao-imprimir">${tagOS(o.status)} ${o.previsao && aberta ? `<small class="sutil">Previsão: ${dia(o.previsao)}</small>` : ''}</div>
    <div class="duas-col">
      <section class="cartao recibo" style="max-width:none">
        ${cabecalhoLoja('Ordem de serviço', `Nº ${o.id} · entrada ${dataHora(o.entrada_em)}`)}
        <dl>
          <dt>Cliente</dt><dd>${esc(o.cliente_nome)}${o.cliente_documento ? ` · ${esc(o.cliente_documento)}` : ''}${o.cliente_telefone ? ` · ${esc(o.cliente_telefone)}` : ''}</dd>
          <dt>Aparelho</dt><dd>${esc(o.aparelho)}${o.cor ? ` · ${esc(o.cor)}` : ''}</dd>
          ${o.imei ? `<dt>IMEI</dt><dd class="mono">${esc(o.imei)}</dd>` : ''}
          ${o.acessorios ? `<dt>Acessórios</dt><dd>${esc(o.acessorios)}</dd>` : ''}
          ${o.senha_desbloqueio ? `<dt class="nao-imprimir">Senha</dt><dd class="nao-imprimir mono">${esc(o.senha_desbloqueio)}</dd>` : ''}
          <dt>Defeito relatado</dt><dd>${esc(o.defeito)}</dd>
          ${o.laudo ? `<dt>Laudo técnico</dt><dd>${esc(o.laudo)}</dd>` : ''}
          ${o.tecnico ? `<dt>Técnico</dt><dd>${esc(o.tecnico)}</dd>` : ''}
          <dt>Situação</dt><dd>${esc(o.status)}${o.entregue_em ? ` em ${esc(dataHora(o.entregue_em))}` : ''}</dd>
          ${o.forma_pagamento ? `<dt>Pagamento</dt><dd>${esc(o.forma_pagamento)}</dd>` : ''}
          <dt>Garantia</dt><dd>${num(o.garantia_dias)} dias${o.entregue_em ? ` (até ${(() => { const d = new Date(o.entregue_em.replace(' ', 'T')); d.setDate(d.getDate() + o.garantia_dias); return d.toLocaleDateString('pt-BR'); })()})` : ' a partir da entrega'}</dd>
        </dl>
        ${tabela([
          { r: 'Descrição', v: (i) => i.d, h: (i) => `${esc(i.d)}${i.t ? ' <small class="sutil">(peça)</small>' : ''}` },
          { r: 'Qtd', v: (i) => i.q, cls: 'num' },
          { r: 'Valor', v: (i) => i.v, h: (i) => brl(i.v), cls: 'num' },
          { r: 'Subtotal', v: (i) => i.q * i.v, h: (i) => brl(i.q * i.v), cls: 'num' },
        ], [...o.servicos.map((s) => ({ d: s.descricao, q: 1, v: s.valor })), ...o.pecas.map((p) => ({ d: p.produto_nome, q: p.quantidade, v: p.valor_unitario, t: 1 }))], { vazio: 'Orçamento ainda não definido.' })}
        <div class="totais" style="max-width:300px;margin:14px 0 0 auto">
          ${o.desconto ? `<div><span>Subtotal</span><span>${brl(o.valor_servicos + o.valor_pecas)}</span></div><div><span>Desconto</span><span>− ${brl(o.desconto)}</span></div>` : ''}
          <div class="total"><span>Total</span><span>${brl(o.total)}</span></div>
        </div>
        ${o.financeiro.length > 1 ? `<p class="sutil">Parcelas: ${o.financeiro.map((f) => `${esc(f.parcela)} ${brl(f.valor)} venc. ${dia(f.vencimento)}`).join(' · ')}</p>` : ''}
        ${cfg.termo_os ? `<p class="sutil" style="font-size:12.5px;margin-top:18px">${esc(cfg.termo_os)}</p>` : ''}
        <div class="assinaturas"><span>Assinatura do cliente</span><span>${esc(cfg.nome_loja)}</span></div>
      </section>
      <section class="cartao nao-imprimir"><div class="cartao-cab"><h2>Andamento</h2></div>
        <ul class="linha-tempo">${o.historico.map((h) => `<li class="${h.status === 'Entregue' ? 'entrada' : ''}"><strong>${esc(h.status)}</strong><br><small>${esc(dataHora(h.data))} · ${esc(h.usuario_nome)}</small>${h.nota ? `<br><small>${esc(h.nota)}</small>` : ''}</li>`).join('')}</ul>
        ${o.observacao ? `<p class="faixa faixa-info">${esc(o.observacao)}</p>` : ''}
      </section>
    </div>`;
  $('#os-imprimir').addEventListener('click', () => window.print());
  $('#os-status')?.addEventListener('click', () => abrirForm({
    titulo: `Situação da OS #${o.id}`,
    campos: [
      { n: 'status', r: 'Nova situação', t: 'select', opts: estado.meta.status_os.filter((s) => !['Entregue', 'Cancelada'].includes(s)), col2: true },
      { n: 'nota', r: 'Anotação (opcional)', t: 'textarea', col2: true },
    ],
    valores: { status: o.status },
    salvar: async (d) => { await api('POST', `/api/os/${o.id}/status`, d); fecharModal(); avisar('Situação atualizada.', 'ok'); rotear(); },
  }));
  $('#os-cancelar')?.addEventListener('click', () => abrirForm({
    titulo: `Cancelar OS #${o.id}`,
    campos: [{ n: 'motivo', r: 'Motivo do cancelamento', t: 'textarea', req: true, col2: true }],
    extra: o.status === 'Entregue' ? '<p class="faixa faixa-alerta" style="margin-top:12px">As peças voltam para o estoque e o valor sai do contas a receber.</p>' : '',
    textoBotao: 'Cancelar OS',
    salvar: async (d) => { await api('POST', `/api/os/${o.id}/cancelar`, d); fecharModal(); avisar('OS cancelada.', 'ok'); rotear(); },
  }));
  $('#os-entregar')?.addEventListener('click', () => {
    const form = abrirForm({
      titulo: `Entregar OS #${o.id} — ${brl(o.total)}`,
      campos: [
        ...(o.total > 0 ? [{ n: 'forma_pagamento', r: 'Forma de pagamento', t: 'select', opts: estado.meta.pagamentos, col2: true }] : []),
        { n: 'nota', r: 'Anotação (opcional)', col2: true },
      ],
      extra: `<div class="grade-form" id="ent-cred" hidden style="margin-top:12px">${campoCondicao('ent')}</div>
        ${o.pecas.length ? `<p class="faixa faixa-info" style="margin-top:12px">Peças que saem do estoque: ${o.pecas.map((p) => `${num(p.quantidade)}× ${esc(p.produto_nome)}`).join(', ')}</p>` : ''}`,
      textoBotao: 'Confirmar entrega',
      salvar: async (d) => {
        d.parcelas = $('#ent-parcelas')?.value; d.primeiro_vencimento = $('#ent-venc')?.value;
        await api('POST', `/api/os/${o.id}/entregar`, d); fecharModal(); avisar('OS entregue e valor lançado no financeiro.', 'ok'); rotear();
      },
    });
    const sel = $('[name=forma_pagamento]', form);
    sel?.addEventListener('change', () => { $('#ent-cred').hidden = sel.value !== 'Crediário'; });
  });
}

/* =========================================================================
   Orçamentos
   ========================================================================= */
const ROTULO_ORC = { aberto: ['Em aberto', ''], aprovado: ['Aprovado', 'tag-saida'], recusado: ['Recusado', 'tag-perigo'], convertido: ['Virou venda', 'tag-entrada'] };
const tagOrc = (s) => `<span class="tag ${ROTULO_ORC[s]?.[1] || ''}">${esc(ROTULO_ORC[s]?.[0] || s)}</span>`;
let filtroOrc = '';

async function paginaOrcamentos(param, q) {
  if (param === 'novo' || (param && q.get('editar') === '1')) return editorOrcamento(param === 'novo' ? null : +param);
  if (param) return verOrcamento(+param);
  $('#conteudo').innerHTML = `
    <div class="ferramentas"><label class="busca">Buscar<input type="search" id="orc-q" placeholder="Nº ou cliente"></label><span class="espaco"></span><a class="btn btn-primario" href="#/orcamentos/novo">+ Novo orçamento</a></div>
    <div class="chips" id="orc-chips">${[['', 'Todos'], ...Object.entries(ROTULO_ORC).map(([k, v]) => [k, v[0]])].map(([k, r]) => `<button class="chip ${k === filtroOrc ? 'ativo' : ''}" data-k="${k}">${esc(r)}</button>`).join('')}</div>
    <section class="cartao sem-pad" id="lista-orc"></section>`;
  const hoje = isoLocal(new Date());
  const cols = [
    { r: 'Nº', v: (o) => o.id, h: (o) => `<strong>#${o.id}</strong>` },
    { r: 'Data', v: (o) => dia(o.data) },
    { r: 'Cliente', v: (o) => o.cliente_nome || 'Não identificado' },
    { r: 'Produtos', v: (o) => o.produtos, h: (o) => esc((o.produtos || '').length > 60 ? `${o.produtos.slice(0, 60)}…` : o.produtos) },
    { r: 'Validade', v: (o) => dia(o.validade), h: (o) => `<span class="${o.validade < hoje && ['aberto', 'aprovado'].includes(o.status) ? 'estoque baixo' : ''}">${dia(o.validade)}</span>` },
    { r: 'Situação', v: (o) => ROTULO_ORC[o.status]?.[0], h: (o) => tagOrc(o.status) },
    { r: 'Vendedor', v: (o) => o.usuario_nome },
    { r: 'Total', v: (o) => o.total, h: (o) => brl(o.total), cls: 'num' },
  ];
  const carregar = async () => {
    const linhas = await api('GET', `/api/orcamentos${qs({ status: filtroOrc, q: $('#orc-q').value.trim() })}`);
    $('#lista-orc').innerHTML = `<div class="cartao-cab"><h2>${num(linhas.length)} orçamento(s)</h2></div>${tabela(cols, linhas, { clique: true, vazio: 'Nenhum orçamento.' })}`;
    ligarCliques($('#lista-orc'), linhas, (o) => { location.hash = `#/orcamentos/${o.id}`; });
  };
  $$('#orc-chips [data-k]').forEach((b) => b.addEventListener('click', () => { filtroOrc = b.dataset.k; $$('#orc-chips .chip').forEach((x) => x.classList.toggle('ativo', x === b)); carregar(); }));
  let t;
  $('#orc-q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(carregar, 250); });
  await carregar();
}

async function editorOrcamento(id) {
  const [clientes, o] = await Promise.all([api('GET', '/api/clientes'), id ? api('GET', `/api/orcamentos/${id}`) : null]);
  $('#titulo-pagina').textContent = id ? `Editar orçamento #${id}` : 'Novo orçamento';
  const itens = (o?.itens || []).map((i) => ({ ...i }));
  const dias = +estado.meta.config.validade_orcamento_dias || 7;
  const val = o?.validade || (() => { const d = new Date(); d.setDate(d.getDate() + dias); return isoLocal(d); })();
  $('#conteudo').innerHTML = `
    <div class="ferramentas"><a class="btn" href="#/orcamentos${id ? `/${id}` : ''}">← Voltar</a></div>
    <form id="f-orc" class="lancamento">
      <section class="cartao" style="min-width:0"><div class="cartao-cab"><h2>Produtos</h2></div>
        <div class="busca-produto"><input id="orc-busca" type="search" autocomplete="off" placeholder="Buscar produto, código ou IMEI…"><div class="resultados" id="orc-res" hidden></div></div>
        <div id="orc-itens" style="margin-top:12px"></div></section>
      <aside class="lancamento-lateral">
        <section class="cartao"><div class="grade-form">
          <label class="col-2">Cliente<div class="linha-input"><select name="cliente_id">${opcoesClientes(clientes, o?.cliente_id, '— não identificado —')}</select><button class="btn" type="button" id="orc-novo-cli">+</button></div></label>
          ${campoHTML({ n: 'validade', r: 'Válido até', t: 'date', col2: true }, val)}
          ${campoHTML({ n: 'observacao', r: 'Observações / condições', t: 'textarea', col2: true, attrs: 'placeholder="Ex.: pagamento em até 10x no cartão"' }, o?.observacao)}
        </div></section>
        <section class="cartao"><div class="totais">
          <div><span>Subtotal</span><span id="orc-sub"></span></div>
          <div><label style="width:100%">Desconto (R$)<input name="desconto" inputmode="decimal" value="${o?.desconto ? String(o.desconto).replace('.', ',') : ''}" placeholder="0,00"></label></div>
          <div class="total"><span>Total</span><span id="orc-total"></span></div>
          <p class="erro-form" id="orc-erro"></p>
          <button class="btn btn-g btn-primario btn-largo" type="submit">Salvar orçamento</button>
        </div></section>
      </aside>
    </form>`;
  const form = $('#f-orc');
  const totais = () => {
    const s = itens.reduce((a, i) => a + i.quantidade * i.valor_unitario, 0);
    $('#orc-sub').textContent = brl(s);
    $('#orc-total').textContent = brl(Math.max(s - paraNumero($('[name=desconto]', form).value), 0));
  };
  const ed = editorItens($('#orc-itens'), itens, totais);
  ligarBuscaProduto($('#orc-busca'), $('#orc-res'), { aoEscolher: (p) => ed.adicionar(p) });
  ligarNovoCliente($('#orc-novo-cli'), $('[name=cliente_id]', form));
  $('[name=desconto]', form).addEventListener('input', totais);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const corpo = { ...lerForm(form), desconto: paraNumero($('[name=desconto]', form).value), itens: itens.map((i) => ({ produto_id: i.produto_id, quantidade: i.quantidade, valor_unitario: i.valor_unitario })) };
    try {
      const r = id ? await api('PUT', `/api/orcamentos/${id}`, corpo) : await api('POST', '/api/orcamentos', corpo);
      avisar('Orçamento salvo.', 'ok');
      location.hash = `#/orcamentos/${r.id}`;
    } catch (err) { $('#orc-erro').textContent = err.message; }
  });
  $('#orc-busca').focus();
}

async function verOrcamento(id) {
  const o = await api('GET', `/api/orcamentos/${id}`);
  const cfg = estado.meta.config;
  $('#titulo-pagina').textContent = `Orçamento #${o.id}`;
  const editavel = o.status !== 'convertido';
  const texto = `Olá${o.cliente_nome ? `, ${o.cliente_nome}` : ''}! Segue o orçamento #${o.id} da ${cfg.nome_loja}:\n${o.itens.map((i) => `• ${i.quantidade}× ${i.produto_nome}: ${brl(i.quantidade * i.valor_unitario)}`).join('\n')}${o.desconto ? `\nDesconto: ${brl(o.desconto)}` : ''}\nTotal: ${brl(o.total)}\nVálido até ${dia(o.validade)}.`;
  const zap = linkWhatsApp(o.cliente_telefone, texto);
  $('#conteudo').innerHTML = `
    <div class="ferramentas nao-imprimir">
      <a class="btn" href="#/orcamentos">← Orçamentos</a><span class="espaco"></span>
      ${editavel && o.status !== 'recusado' ? '<button class="btn btn-perigo" data-st="recusado">Recusado</button>' : ''}
      ${editavel && o.status !== 'aprovado' ? '<button class="btn" data-st="aprovado">Aprovado</button>' : ''}
      ${editavel ? `<a class="btn" href="#/orcamentos/${o.id}?editar=1">Editar</a>` : ''}
      ${zap ? `<a class="btn" href="${esc(zap)}" target="_blank" rel="noopener">Enviar no WhatsApp</a>` : '<button class="btn" id="orc-copiar">Copiar texto</button>'}
      <button class="btn" id="orc-imprimir">Imprimir</button>
      ${editavel && o.status !== 'recusado' ? `<a class="btn btn-primario" href="#/saida?orcamento=${o.id}">Converter em venda</a>` : ''}
      ${o.movimentacao_id ? `<a class="btn btn-primario" href="#/movimentacoes/${o.movimentacao_id}">Ver venda #${o.movimentacao_id}</a>` : ''}
    </div>
    <div class="nao-imprimir">${tagOrc(o.status)}</div>
    <section class="cartao recibo">
      ${cabecalhoLoja('Orçamento', `Nº ${o.id} · ${dia(o.data)}`)}
      <dl>
        <dt>Cliente</dt><dd>${esc(o.cliente_nome || 'Não identificado')}${o.cliente_telefone ? ` · ${esc(o.cliente_telefone)}` : ''}</dd>
        <dt>Válido até</dt><dd>${dia(o.validade)}</dd>
        <dt>Vendedor</dt><dd>${esc(o.usuario_nome)}</dd>
        ${o.observacao ? `<dt>Condições</dt><dd>${esc(o.observacao)}</dd>` : ''}
      </dl>
      ${tabela([
        { r: 'Produto', v: (i) => i.produto_nome },
        { r: 'Qtd', v: (i) => i.quantidade, cls: 'num' },
        { r: 'Valor un.', v: (i) => i.valor_unitario, h: (i) => brl(i.valor_unitario), cls: 'num' },
        { r: 'Subtotal', v: (i) => i.quantidade * i.valor_unitario, h: (i) => brl(i.quantidade * i.valor_unitario), cls: 'num' },
      ], o.itens)}
      <div class="totais" style="max-width:300px;margin:14px 0 0 auto">
        ${o.desconto ? `<div><span>Subtotal</span><span>${brl(o.subtotal)}</span></div><div><span>Desconto</span><span>− ${brl(o.desconto)}</span></div>` : ''}
        <div class="total"><span>Total</span><span>${brl(o.total)}</span></div>
      </div>
      <p class="sutil" style="font-size:12.5px;margin-top:18px">Orçamento sujeito à disponibilidade de estoque. Preços válidos até a data indicada.</p>
    </section>`;
  $('#orc-imprimir').addEventListener('click', () => window.print());
  $('#orc-copiar')?.addEventListener('click', async () => { try { await navigator.clipboard.writeText(texto); avisar('Texto copiado.', 'ok'); } catch { avisar('Não foi possível copiar.', 'erro'); } });
  $$('[data-st]').forEach((b) => b.addEventListener('click', async () => {
    try { await api('POST', `/api/orcamentos/${o.id}/status`, { status: b.dataset.st }); avisar('Situação atualizada.', 'ok'); rotear(); } catch (e) { avisar(e.message, 'erro'); }
  }));
}

/* =========================================================================
   Financeiro: contas a receber e a pagar
   ========================================================================= */
const SITUACAO_FIN = { pendente: ['A vencer', ''], vencido: ['Vencido', 'tag-perigo'], pago: ['Pago', 'tag-entrada'] };
const fin = { tipo: 'receber', situacao: 'abertos', inicio: '', fim: '', q: '' };

async function paginaFinanceiro(_, q) {
  if (q.get('tipo')) fin.tipo = q.get('tipo');
  const receber = fin.tipo === 'receber';
  $('#titulo-pagina').textContent = receber ? 'Contas a receber' : 'Contas a pagar';
  $('#conteudo').innerHTML = `
    <div class="abas"><button data-t="receber" class="${receber ? 'ativo' : ''}">A receber</button><button data-t="pagar" class="${receber ? '' : 'ativo'}">A pagar</button></div>
    <div id="fin-kpis" class="kpis"></div>
    <div class="ferramentas">
      <div class="chips">${[['abertos', 'Em aberto'], ['vencidos', 'Vencidos'], ['pagos', receber ? 'Recebidos' : 'Pagos'], ['todos', 'Todos']].map(([k, r]) => `<button class="chip ${fin.situacao === k ? 'ativo' : ''}" data-s="${k}">${r}</button>`).join('')}</div>
      <label>${fin.situacao === 'pagos' ? 'Pago de' : 'Vencimento de'}<input type="date" id="fin-ini" value="${fin.inicio}"></label><label>Até<input type="date" id="fin-fim" value="${fin.fim}"></label>
      <label class="busca">Buscar<input type="search" id="fin-q" value="${esc(fin.q)}" placeholder="Descrição, ${receber ? 'cliente' : 'fornecedor'} ou categoria"></label>
      <button class="btn" id="fin-csv">Exportar CSV</button>
      <button class="btn btn-primario" id="fin-novo">+ ${receber ? 'Nova receita' : 'Nova despesa'}</button>
    </div>
    <section class="cartao sem-pad" id="fin-lista"><div class="carregando">Carregando…</div></section>`;
  $$('[data-t]').forEach((b) => b.addEventListener('click', () => { fin.tipo = b.dataset.t; location.hash = `#/financeiro?tipo=${fin.tipo}`; }));
  $$('[data-s]').forEach((b) => b.addEventListener('click', () => { fin.situacao = b.dataset.s; paginaFinanceiro(_, new URLSearchParams()); }));
  $('#fin-ini').addEventListener('change', (e) => { fin.inicio = e.target.value; if (!fin.fim && fin.inicio) fin.fim = fin.inicio; carregar(); });
  $('#fin-fim').addEventListener('change', (e) => { fin.fim = e.target.value; if (!fin.inicio && fin.fim) fin.inicio = fin.fim; carregar(); });
  let t;
  $('#fin-q').addEventListener('input', (e) => { clearTimeout(t); t = setTimeout(() => { fin.q = e.target.value.trim(); carregar(); }, 250); });
  const cols = [
    { r: 'Vencimento', v: (f) => dia(f.vencimento) },
    { r: 'Descrição', v: (f) => `${f.descricao}${f.parcela ? ` (${f.parcela})` : ''}`, h: (f) => `<div class="celula-produto"><strong>${esc(f.descricao)}${f.parcela ? ` <small>parc. ${esc(f.parcela)}</small>` : ''}</strong><small>${esc(f.categoria)}</small></div>` },
    { r: receber ? 'Cliente' : 'Fornecedor', v: (f) => f.cliente_nome || f.fornecedor_nome || '' },
    { r: 'Forma', v: (f) => f.forma_pagamento || '' },
    { r: 'Situação', v: (f) => SITUACAO_FIN[f.situacao][0], h: (f) => `<span class="tag ${SITUACAO_FIN[f.situacao][1]}">${f.situacao === 'pago' ? (receber ? 'Recebido' : 'Pago') : SITUACAO_FIN[f.situacao][0]}</span>${f.pago_em ? `<br><small class="sutil">${dia(f.pago_em)}</small>` : ''}` },
    { r: 'Valor', v: (f) => f.valor, h: (f) => `<strong>${brl(f.valor)}</strong>`, cls: 'num' },
    { r: '', v: () => '', h: (f) => `<span class="acoes-linha">${f.pago_em ? `<button class="btn btn-p" data-a="estornar" data-id="${f.id}">Estornar</button>` : `<button class="btn btn-p btn-sucesso" data-a="baixar" data-id="${f.id}">${receber ? 'Receber' : 'Pagar'}</button><button class="btn btn-p" data-a="editar" data-id="${f.id}">Editar</button>`}${!f.movimentacao_id && !f.os_id ? `<button class="btn btn-p btn-fantasma" data-a="excluir" data-id="${f.id}" aria-label="Excluir">✕</button>` : ''}${f.movimentacao_id ? `<a class="btn btn-p btn-fantasma" href="#/movimentacoes/${f.movimentacao_id}">ver</a>` : ''}${f.os_id ? `<a class="btn btn-p btn-fantasma" href="#/os/${f.os_id}">OS</a>` : ''}</span>`, cls: 'num' },
  ];
  let linhas = [];
  async function carregar() {
    linhas = await api('GET', `/api/financeiro${qs({ tipo: fin.tipo, situacao: fin.situacao, inicio: fin.inicio, fim: fin.fim, q: fin.q })}`);
    const soma = (fn) => linhas.filter(fn).reduce((a, f) => a + f.valor, 0);
    const em7 = (() => { const d = new Date(); d.setDate(d.getDate() + 7); return isoLocal(d); })();
    $('#fin-kpis').innerHTML = `
      <div class="kpi"><span>Total listado</span><strong>${brl(soma(() => true))}</strong><small>${num(linhas.length)} lançamento(s)</small></div>
      <div class="kpi ${soma((f) => f.situacao === 'vencido') ? 'alerta' : ''}"><span>Vencido</span><strong>${brl(soma((f) => f.situacao === 'vencido'))}</strong></div>
      <div class="kpi"><span>Vence em 7 dias</span><strong>${brl(soma((f) => f.situacao === 'pendente' && f.vencimento <= em7))}</strong></div>
      <div class="kpi bom"><span>${receber ? 'Recebido' : 'Pago'} (na lista)</span><strong>${brl(soma((f) => f.situacao === 'pago'))}</strong></div>`;
    $('#fin-lista').innerHTML = `<div class="cartao-cab"><h2>${receber ? 'Contas a receber' : 'Contas a pagar'}</h2></div>${tabela(cols, linhas, { vazio: 'Nenhum lançamento.', classeLinha: (f) => (f.situacao === 'vencido' ? 'linha-alerta' : '') })}`;
    $$('#fin-lista [data-a]').forEach((b) => b.addEventListener('click', () => acao(b.dataset.a, linhas.find((f) => f.id === +b.dataset.id))));
  }
  async function acao(a, f) {
    if (a === 'baixar') {
      abrirForm({
        titulo: `${receber ? 'Receber' : 'Pagar'} ${brl(f.valor)} — ${f.descricao}`,
        campos: [{ n: 'data', r: 'Data do pagamento', t: 'date', req: true }, { n: 'forma_pagamento', r: 'Forma', t: 'select', opts: estado.meta.pagamentos }],
        valores: { data: isoLocal(new Date()), forma_pagamento: f.forma_pagamento || 'Dinheiro' },
        textoBotao: 'Confirmar',
        salvar: async (d) => { await api('POST', `/api/financeiro/${f.id}/baixar`, d); fecharModal(); avisar('Baixa registrada.', 'ok'); carregar(); },
      });
    } else if (a === 'estornar') {
      if (!confirm('Estornar a baixa? O lançamento volta a ficar em aberto.')) return;
      try { await api('POST', `/api/financeiro/${f.id}/estornar`); avisar('Baixa estornada.', 'ok'); carregar(); } catch (e) { avisar(e.message, 'erro'); }
    } else if (a === 'excluir') {
      if (!confirm(`Excluir "${f.descricao}"?`)) return;
      try { await api('DELETE', `/api/financeiro/${f.id}`); avisar('Lançamento excluído.', 'ok'); carregar(); } catch (e) { avisar(e.message, 'erro'); }
    } else if (a === 'editar') {
      abrirForm({
        titulo: 'Editar lançamento',
        campos: [
          { n: 'descricao', r: 'Descrição', req: true, col2: true },
          { n: 'categoria', r: 'Categoria', t: 'select', opts: estado.meta.categorias_fin[fin.tipo] },
          { n: 'valor', r: 'Valor (R$)', attrs: 'inputmode="decimal"', req: true },
          { n: 'vencimento', r: 'Vencimento', t: 'date', req: true },
          { n: 'observacao', r: 'Observação', t: 'textarea', col2: true },
        ],
        valores: { ...f, valor: String(f.valor).replace('.', ',') },
        salvar: async (d) => { d.valor = paraNumero(d.valor); await api('PUT', `/api/financeiro/${f.id}`, d); fecharModal(); avisar('Lançamento atualizado.', 'ok'); carregar(); },
      });
    }
  }
  $('#fin-csv').addEventListener('click', () => baixarCSV(`contas-a-${fin.tipo}`, cols.slice(0, -1), linhas));
  $('#fin-novo').addEventListener('click', async () => {
    const parceiros = await api('GET', receber ? '/api/clientes' : '/api/fornecedores');
    const form = abrirForm({
      titulo: receber ? 'Nova conta a receber' : 'Nova conta a pagar (despesa)',
      campos: [
        { n: 'descricao', r: 'Descrição', req: true, col2: true, attrs: `placeholder="${receber ? 'Ex.: Conserto avulso' : 'Ex.: Aluguel da loja'}"` },
        { n: 'categoria', r: 'Categoria', t: 'select', opts: estado.meta.categorias_fin[fin.tipo] },
        { n: 'valor', r: 'Valor (R$)', req: true, attrs: 'inputmode="decimal"' },
        { n: 'vencimento', r: 'Vencimento (1ª parcela)', t: 'date', req: true },
        { n: 'parcelas', r: 'Parcelas / meses', t: 'number', attrs: 'min="1" max="120"' },
        { n: 'repetir', r: 'Despesa fixa: repetir o mesmo valor todo mês (em vez de dividir)', t: 'check', col2: true },
        { n: receber ? 'cliente_id' : 'fornecedor_id', r: receber ? 'Cliente' : 'Fornecedor', t: 'select', vazio: '— nenhum —', opts: parceiros.map((p) => [p.id, p.nome]) },
        { n: 'forma_pagamento', r: 'Forma de pagamento', t: 'select', vazio: '—', opts: estado.meta.pagamentos },
        { n: 'pago', r: receber ? 'Já foi recebido' : 'Já foi pago', t: 'check', col2: true },
        { n: 'observacao', r: 'Observação', t: 'textarea', col2: true },
      ],
      valores: { vencimento: isoLocal(new Date()), parcelas: 1, categoria: receber ? 'Outras receitas' : 'Outras despesas' },
      salvar: async (d) => {
        d.valor = paraNumero(d.valor); d.tipo = fin.tipo;
        await api('POST', '/api/financeiro', d); fecharModal(); avisar('Lançamento criado.', 'ok'); carregar();
      },
    });
    const parc = $('[name=parcelas]', form);
    const pago = $('[name=pago]', form);
    parc.addEventListener('input', () => { pago.disabled = +parc.value > 1; if (pago.disabled) pago.checked = false; });
  });
  await carregar();
}

/* =========================================================================
   Caixa
   ========================================================================= */
function htmlResumoCaixa(cx) {
  return `
    <div class="kpis">
      <div class="kpi"><span>Troco inicial</span><strong>${brl(cx.saldo_inicial)}</strong><small>Aberto ${esc(dataHora(cx.aberto_em))}</small></div>
      <div class="kpi bom"><span>Recebido (todas as formas)</span><strong>${brl(cx.total_recebido)}</strong></div>
      <div class="kpi"><span>Sangrias / suprimentos</span><strong>−${brl(cx.sangrias)} / +${brl(cx.suprimentos)}</strong></div>
      <div class="kpi"><span>Dinheiro esperado na gaveta</span><strong>${brl(cx.esperado_dinheiro)}</strong><small>troco + recebido em dinheiro − pago em dinheiro ± movimentos</small></div>
      ${cx.fechado_em ? `<div class="kpi ${Math.abs(cx.saldo_informado - cx.saldo_esperado) > 0.009 ? 'alerta' : 'bom'}"><span>Contado no fechamento</span><strong>${brl(cx.saldo_informado)}</strong><small>Diferença ${brl(cx.saldo_informado - cx.saldo_esperado)}</small></div>` : ''}
    </div>
    <div class="duas-iguais">
      <section class="cartao"><div class="cartao-cab"><h2>Recebimentos por forma</h2></div>${barrasH(cx.formas.filter((f) => f.recebido), { valor: (f) => f.recebido, rotulo: (f) => f.chave || 'Não informado' })}</section>
      <section class="cartao sem-pad"><div class="cartao-cab"><h2>Sangrias e suprimentos</h2></div>${tabela([
        { r: 'Hora', v: (m) => dataHora(m.data).slice(-5) }, { r: 'Tipo', v: (m) => (m.tipo === 'sangria' ? 'Sangria' : 'Suprimento'), h: (m) => `<span class="tag ${m.tipo === 'sangria' ? 'tag-alerta' : 'tag-entrada'}">${m.tipo === 'sangria' ? 'Sangria' : 'Suprimento'}</span>` },
        { r: 'Descrição', v: (m) => m.descricao || '' }, { r: 'Por', v: (m) => m.usuario_nome }, { r: 'Valor', v: (m) => m.valor, h: (m) => brl(m.valor), cls: 'num' },
      ], cx.movimentos, { vazio: 'Nenhuma sangria ou suprimento.' })}</section>
    </div>
    <section class="cartao sem-pad"><div class="cartao-cab"><h2>Lançamentos no caixa</h2></div>${tabela([
      { r: 'Hora', v: (f) => dataHora(f.pago_em) }, { r: 'Descrição', v: (f) => f.descricao }, { r: 'Forma', v: (f) => f.forma_pagamento || '' },
      { r: 'Tipo', v: (f) => (f.tipo === 'receber' ? 'Entrada' : 'Saída'), h: (f) => `<span class="tag ${f.tipo === 'receber' ? 'tag-entrada' : 'tag-alerta'}">${f.tipo === 'receber' ? 'Entrada' : 'Saída'}</span>` },
      { r: 'Valor', v: (f) => f.valor, h: (f) => brl(f.valor), cls: 'num' },
    ], cx.lancamentos, { vazio: 'Nenhum recebimento ou pagamento neste caixa.' })}</section>`;
}

async function paginaCaixa() {
  const d = await api('GET', '/api/caixa');
  estado.meta.caixa = d.atual ? { id: d.atual.id } : null;
  atualizarIndicadorCaixa();
  const cx = d.atual;
  const colsHist = [
    { r: 'Nº', v: (c) => c.id, h: (c) => `#${c.id}` }, { r: 'Abertura', v: (c) => dataHora(c.aberto_em) }, { r: 'Por', v: (c) => c.aberto_por_nome },
    { r: 'Fechamento', v: (c) => dataHora(c.fechado_em) || 'aberto' }, { r: 'Esperado', v: (c) => c.saldo_esperado ?? '', h: (c) => (c.fechado_em ? brl(c.saldo_esperado) : '—'), cls: 'num' },
    { r: 'Contado', v: (c) => c.saldo_informado ?? '', h: (c) => (c.fechado_em ? brl(c.saldo_informado) : '—'), cls: 'num' },
    { r: 'Diferença', v: (c) => (c.fechado_em ? c.saldo_informado - c.saldo_esperado : ''), h: (c) => (c.fechado_em ? `<span class="${Math.abs(c.saldo_informado - c.saldo_esperado) > 0.009 ? 'estoque baixo' : ''}">${brl(c.saldo_informado - c.saldo_esperado)}</span>` : '—'), cls: 'num' },
  ];
  $('#conteudo').innerHTML = `
    ${cx ? `<div class="ferramentas"><div class="faixa faixa-info" style="flex:1">Caixa <strong>#${cx.id}</strong> aberto desde ${esc(dataHora(cx.aberto_em))}.</div>
        <button class="btn" data-mov="suprimento">+ Suprimento</button><button class="btn" data-mov="sangria">− Sangria</button><button class="btn btn-primario" id="cx-fechar">Fechar caixa</button></div>${htmlResumoCaixa(cx)}`
    : `<section class="cartao" style="max-width:520px"><div class="cartao-cab"><h2>Caixa fechado</h2></div>
        <p class="sutil">Abra o caixa no início do expediente informando o troco que está na gaveta. No fim do dia, feche contando o dinheiro: o sistema mostra se sobrou ou faltou.</p>
        <form id="cx-abrir" class="linha-input"><input name="saldo_inicial" inputmode="decimal" placeholder="Troco inicial (R$)"><button class="btn btn-primario">Abrir caixa</button></form></section>`}
    ${cartaoTabela('cx-hist', 'Caixas anteriores', colsHist, d.historico, { clique: true, vazio: 'Nenhum caixa ainda.' })}`;
  $('#cx-abrir')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try { await api('POST', '/api/caixa/abrir', { saldo_inicial: paraNumero(e.target.saldo_inicial.value) }); avisar('Caixa aberto.', 'ok'); rotear(); } catch (err) { avisar(err.message, 'erro'); }
  });
  $$('[data-mov]').forEach((b) => b.addEventListener('click', () => abrirForm({
    titulo: b.dataset.mov === 'sangria' ? 'Sangria (retirada de dinheiro)' : 'Suprimento (reforço de troco)',
    campos: [{ n: 'valor', r: 'Valor (R$)', req: true, attrs: 'inputmode="decimal"' }, { n: 'descricao', r: 'Motivo', attrs: 'placeholder="Ex.: depósito no banco"' }],
    salvar: async (dd) => { await api('POST', '/api/caixa/movimento', { tipo: b.dataset.mov, valor: paraNumero(dd.valor), descricao: dd.descricao }); fecharModal(); avisar('Registrado.', 'ok'); rotear(); },
  })));
  $('#cx-fechar')?.addEventListener('click', () => {
    const form = abrirForm({
      titulo: `Fechar caixa #${cx.id}`,
      campos: [{ n: 'saldo_informado', r: 'Dinheiro contado na gaveta (R$)', req: true, attrs: 'inputmode="decimal"', col2: true }, { n: 'observacao', r: 'Observação', t: 'textarea', col2: true }],
      extra: `<p class="faixa faixa-info" style="margin-top:12px" id="cx-dif">Esperado em dinheiro: <strong>${brl(cx.esperado_dinheiro)}</strong></p>`,
      textoBotao: 'Fechar caixa',
      salvar: async (dd) => { await api('POST', '/api/caixa/fechar', { ...dd, saldo_informado: paraNumero(dd.saldo_informado) }); fecharModal(); avisar('Caixa fechado.', 'ok'); rotear(); },
    });
    $('[name=saldo_informado]', form).addEventListener('input', (e) => {
      const dif = paraNumero(e.target.value) - cx.esperado_dinheiro;
      $('#cx-dif').innerHTML = `Esperado: <strong>${brl(cx.esperado_dinheiro)}</strong> · Diferença: <strong>${brl(dif)}</strong> ${Math.abs(dif) < 0.01 ? '(confere)' : dif > 0 ? '(sobra)' : '(falta)'}`;
    });
  });
  ligarCliques($('#cx-hist'), d.historico, async (c) => {
    const r = await api('GET', `/api/caixa/${c.id}`);
    abrirModal(`Caixa #${r.id}`, htmlResumoCaixa(r), { largo: true });
  });
}

function atualizarIndicadorCaixa() {
  const el = $('#indicador-caixa');
  if (!el) return;
  const aberto = !!estado.meta?.caixa;
  el.textContent = aberto ? 'Caixa aberto' : 'Caixa fechado';
  el.className = `tag ${aberto ? 'tag-entrada' : 'tag-alerta'}`;
}

/* =========================================================================
   Relatórios extras: financeiro e ordens de serviço
   ========================================================================= */
async function relFinanceiro() {
  const p = periodoAtual();
  const d = await api('GET', `/api/relatorios/financeiro${qs({ inicio: p.inicio, fim: p.fim })}`);
  const colsDia = [
    { r: 'Dia', v: (l) => dia(l.dia) },
    { r: 'Entradas', v: (l) => l.entradas, h: (l) => (l.entradas ? brl(l.entradas) : '—'), cls: 'num' },
    { r: 'Saídas', v: (l) => l.saidas, h: (l) => (l.saidas ? brl(l.saidas) : '—'), cls: 'num' },
    { r: 'Saldo acumulado', v: (l) => l.saldo, h: (l) => `<strong class="${l.saldo < 0 ? 'estoque baixo' : ''}">${brl(l.saldo)}</strong>`, cls: 'num' },
    { r: 'A receber (previsto)', v: (l) => l.a_receber, h: (l) => (l.a_receber ? brl(l.a_receber) : '—'), cls: 'num' },
    { r: 'A pagar (previsto)', v: (l) => l.a_pagar, h: (l) => (l.a_pagar ? brl(l.a_pagar) : '—'), cls: 'num' },
  ];
  const colsCat = [
    { r: 'Tipo', v: (l) => (l.tipo === 'receber' ? 'Receita' : 'Despesa'), h: (l) => `<span class="tag ${l.tipo === 'receber' ? 'tag-entrada' : 'tag-alerta'}">${l.tipo === 'receber' ? 'Receita' : 'Despesa'}</span>` },
    { r: 'Categoria', v: (l) => l.chave }, { r: 'Lançamentos', v: (l) => l.lancamentos, cls: 'num' }, { r: 'Valor', v: (l) => l.valor, h: (l) => brl(l.valor), cls: 'num' },
  ];
  const colsDre = [{ r: 'Demonstrativo', v: (l) => l.linha, h: (l) => (l.total ? `<strong>${esc(l.linha)}</strong>` : esc(l.linha)) }, { r: 'Valor', v: (l) => l.valor, h: (l) => (l.total ? `<strong>${brl(l.valor)}</strong>` : brl(l.valor)), cls: 'num' }];
  const movimentados = d.dias.filter((l) => l.entradas || l.saidas || l.a_receber || l.a_pagar);
  $('#rel').innerHTML = `
    <div class="kpis">
      <div class="kpi bom"><span>Recebido no período</span><strong>${brl(d.receitas)}</strong></div>
      <div class="kpi"><span>Pago no período</span><strong>${brl(d.despesas)}</strong></div>
      <div class="kpi ${d.receitas - d.despesas < 0 ? 'alerta' : ''}"><span>Saldo do período</span><strong>${brl(d.receitas - d.despesas)}</strong><small>Saldo acumulado: ${brl(d.saldo_final)}</small></div>
      <div class="kpi"><span>Em aberto a receber</span><strong>${brl(d.abertos.a_receber)}</strong><small>vencido ${brl(d.abertos.receber_vencido)}</small></div>
      <div class="kpi"><span>Em aberto a pagar</span><strong>${brl(d.abertos.a_pagar)}</strong><small>vencido ${brl(d.abertos.pagar_vencido)}</small></div>
    </div>
    <section class="cartao"><div class="cartao-cab"><h2>Fluxo de caixa realizado</h2><span class="legenda"><i class="l1"></i>Entradas <i class="l2"></i>Saídas</span></div>
      ${graficoBarras(d.dias, { series: [(l) => l.entradas, (l) => l.saidas], dica: (l) => `${dia(l.dia)}: entradas ${brl(l.entradas)} · saídas ${brl(l.saidas)}` })}</section>
    <div class="duas-iguais">
      ${cartaoTabela('rf-dre', 'Resultado (DRE simplificado)', colsDre, d.dre, { csv: true, sub: 'vendas e OS do período − custos − despesas pagas' })}
      ${cartaoTabela('rf-cat', 'Por categoria (realizado)', colsCat, d.categorias, { csv: true, vazio: 'Nada pago ou recebido no período.' })}
    </div>
    ${cartaoTabela('rf-dia', 'Fluxo de caixa diário', colsDia, movimentados, { csv: true, sub: `saldo anterior ${brl(d.saldo_anterior)}`, vazio: 'Sem movimento no período.' })}`;
  ligarCSV($('#rel'), {
    'rf-dre': [`dre-${p.inicio}-a-${p.fim}`, colsDre, d.dre],
    'rf-cat': [`financeiro-por-categoria-${p.inicio}-a-${p.fim}`, colsCat, d.categorias],
    'rf-dia': [`fluxo-de-caixa-${p.inicio}-a-${p.fim}`, colsDia, d.dias],
  });
}

async function relOS() {
  const p = periodoAtual();
  const d = await api('GET', `/api/relatorios/os${qs({ inicio: p.inicio, fim: p.fim })}`);
  const f = d.faturamento;
  const colsTec = [{ r: 'Técnico', v: (l) => l.chave }, { r: 'OS entregues', v: (l) => l.quantidade, cls: 'num' }, { r: 'Faturamento', v: (l) => l.faturamento, h: (l) => brl(l.faturamento), cls: 'num' }];
  const colsServ = [{ r: 'Serviço', v: (l) => l.chave }, { r: 'Vezes', v: (l) => l.quantidade, cls: 'num' }, { r: 'Faturamento', v: (l) => l.faturamento, h: (l) => brl(l.faturamento), cls: 'num' }];
  $('#rel').innerHTML = `
    <div class="kpis">
      <div class="kpi"><span>OS abertas no período</span><strong>${num(d.resumo.abertas_periodo)}</strong><small>${num(d.resumo.canceladas || 0)} cancelada(s)</small></div>
      <div class="kpi bom"><span>Faturamento (OS entregues)</span><strong>${brl(f.total)}</strong><small>${num(f.qtd)} entregue(s)</small></div>
      <div class="kpi"><span>Serviços / peças</span><strong>${brl(f.servicos)}</strong><small>Peças: ${brl(f.pecas)}</small></div>
      <div class="kpi"><span>Prazo médio de entrega</span><strong>${f.prazo_medio != null ? `${num(f.prazo_medio)} dia(s)` : '—'}</strong></div>
    </div>
    <div class="duas-iguais">
      <section class="cartao"><div class="cartao-cab"><h2>Em andamento agora</h2><a href="#/os">Ver OS →</a></div>${barrasH(d.por_status, { valor: (l) => l.quantidade, fmt: (v) => num(v) })}</section>
      ${cartaoTabela('ro-tec', 'Por técnico', colsTec, d.por_tecnico, { csv: true, vazio: 'Nenhuma OS entregue no período.' })}
    </div>
    ${cartaoTabela('ro-serv', 'Serviços mais realizados', colsServ, d.servicos, { csv: true, vazio: 'Nenhum serviço no período.' })}`;
  ligarCSV($('#rel'), { 'ro-tec': [`os-por-tecnico-${p.inicio}-a-${p.fim}`, colsTec, d.por_tecnico], 'ro-serv': [`servicos-${p.inicio}-a-${p.fim}`, colsServ, d.servicos] });
}

/* ---- registro das rotas destes módulos */
Object.assign(ROTAS, {
  os: { t: 'Ordens de serviço', f: paginaOS },
  orcamentos: { t: 'Orçamentos', f: paginaOrcamentos },
  financeiro: { t: 'Financeiro', f: paginaFinanceiro, admin: true },
  caixa: { t: 'Caixa', f: paginaCaixa },
});
