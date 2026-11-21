"use strict";
/* Cliente web do acervo ENADE. Fala com a API REST (nginx encaminha /api/ para o container da API). */
const API = "/api";
const $ = (s, el = document) => el.querySelector(s);
const state = {
  token: sessionStorage.getItem("token"), user: null,
  filtros: { area: [], curso: [], ano: [], tipo_questao: [], componente: [], competencia: [], objeto: [] },
  anuladas: true, pagina: 1, tamanho: 10, lista: new Map(), facetas: null,
};
const FACETAS = [
  { chave: "area", param: "area", titulo: "Área" },
  { chave: "curso", param: "curso", titulo: "Curso" },
  { chave: "ano", param: "ano", titulo: "Ano" },
  { chave: "tipo", param: "tipo_questao", titulo: "Tipo de questão" },
  { chave: "componente", param: "componente", titulo: "Componente" },
  { chave: "competencia", param: "competencia", titulo: "Competência" },
  { chave: "objeto", param: "objeto", titulo: "Objeto de conhecimento" },
];
const ROTULOS = { FG: "Formação Geral", CE: "Componente Específico", objetiva: "Objetiva", discursiva: "Discursiva" };

/* utilidades */
function h(tag, attrs = {}, ...filhos) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f != null && f !== false) el.append(f.nodeType ? f : document.createTextNode(f));
  return el;
}
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
let temporizador;
function avisar(texto, tipo = "ok") {
  const a = $("#aviso");
  a.textContent = texto; a.className = "aviso " + tipo; a.hidden = false;
  clearTimeout(temporizador); temporizador = setTimeout(() => (a.hidden = true), 7000);
}

async function api(caminho, { metodo = "GET", form = null, blob = false } = {}) {
  const hdr = state.token ? { Authorization: "Bearer " + state.token } : {};
  const r = await fetch(API + caminho, { method: metodo, headers: hdr, body: form ? new URLSearchParams(form) : undefined });
  if (r.status === 401 && state.token && caminho !== "/auth/token") { sair("Sessão expirada. Entre novamente."); throw Object.assign(new Error("401"), { status: 401 }); }
  if (!r.ok) {
    let d = r.statusText;
    try { const j = await r.json(); d = Array.isArray(j.detail) ? "Parâmetros inválidos" : (j.detail || d); } catch { /* sem corpo */ }
    throw Object.assign(new Error(d), { status: r.status });
  }
  if (r.status === 204) return null;
  return blob ? r.blob() : r.json();
}

/* bibliotecas de formula e diagrama, carregadas so quando ha conteudo para elas */
const carregados = {};
function carregar(tipo, url) {
  carregados[url] ??= new Promise((ok, falha) => {
    const el = tipo === "css" ? h("link", { rel: "stylesheet", href: url }) : h("script", { src: url });
    el.onload = ok; el.onerror = () => falha(new Error("Falha ao carregar " + url));
    document.head.append(el);
  });
  return carregados[url];
}
async function matematica(el) {
  if (!/\$[^$]+\$|\\\(|\\\[/.test(el.textContent)) return;
  const base = "https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/";
  try {
    await carregar("css", base + "katex.min.css");
    await carregar("js", base + "katex.min.js");
    await carregar("js", base + "contrib/auto-render.min.js");
    window.renderMathInElement(el, { delimiters: [
      { left: "$$", right: "$$", display: true }, { left: "\\[", right: "\\]", display: true },
      { left: "$", right: "$", display: false }, { left: "\\(", right: "\\)", display: false }] });
  } catch { /* sem rede: o texto continua legivel */ }
}
let seqMermaid = 0;
async function diagrama(el, codigo) {
  try {
    await carregar("js", "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js");
    window.mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
    const { svg } = await window.mermaid.render("mmd" + ++seqMermaid, codigo);
    el.innerHTML = svg;
  } catch { el.textContent = codigo; }
}

/* destaque do termo pesquisado no proprio texto (os termos vem dos trechos marcados pelo Elasticsearch) */
function termosDestacados(destaques) {
  const t = new Set();
  for (const frags of Object.values(destaques || {}))
    for (const f of frags) for (const m of f.matchAll(/<mark>(.*?)<\/mark>/gis)) if (m[1].trim().length > 2) t.add(m[1].trim());
  return [...t].sort((a, b) => b.length - a.length);
}
function realcar(texto, termos) {
  let html = esc(texto || "");
  if (termos.length) {
    const rx = new RegExp("(" + termos.map(t => reEsc(esc(t))).join("|") + ")", "gi");
    html = html.replace(rx, "<mark>$1</mark>");
  }
  return html;
}
function paragrafos(texto, termos, classe) {
  const caixa = h("div", { class: "texto-prova " + (classe || "") });
  for (const p of (texto || "").split(/\n{2,}/).filter(x => x.trim())) {
    const el = h("p"); el.innerHTML = realcar(p, termos); caixa.append(el);
  }
  matematica(caixa);
  return caixa;
}

/* autenticacao */
async function entrar(usuario, senha) {
  const t = await api("/auth/token", { metodo: "POST", form: { username: usuario, password: senha } });
  state.token = t.access_token; sessionStorage.setItem("token", state.token);
  await iniciar();
}
function sair(mensagem) {
  state.token = null; state.user = null; state.lista = new Map();
  sessionStorage.removeItem("token");
  $("#app").hidden = true; $("#tela-login").hidden = false; $("#gaveta").hidden = true;
  if (mensagem) { const e = $("#login-erro"); e.textContent = mensagem; e.hidden = false; }
}
async function iniciar() {
  try {
    state.user = await api("/auth/me");
  } catch { return sair(); }
  $("#tela-login").hidden = true; $("#app").hidden = false;
  const professor = state.user.perfil === "professor";
  $("#usuario-info").textContent = `${state.user.usuario} (${professor ? "professor" : "estudante"})`;
  $("#aba-painel").hidden = !professor;
  mostrarAba("busca");
  await carregarLista();
  await buscar(1);
}

/* busca */
function parametros(pagina) {
  const p = new URLSearchParams();
  const q = $("#q").value.trim(); if (q) p.set("q", q);
  for (const [k, vals] of Object.entries(state.filtros)) for (const v of vals) p.append(k, v);
  if (!state.anuladas) p.set("incluir_anuladas", "false");
  p.set("pagina", pagina); p.set("tamanho", state.tamanho);
  return p;
}
async function buscar(pagina = 1) {
  state.pagina = pagina;
  $("#resumo").textContent = "Buscando...";
  try {
    const r = await api("/questoes?" + parametros(pagina));
    state.facetas = r.facetas;
    desenharFacetas();
    desenharResultados(r);
  } catch (e) {
    $("#resumo").textContent = "";
    $("#lista-questoes").replaceChildren(h("p", { class: "vazio" }, e.status === 503 ? "O serviço de busca está indisponível. Tente novamente em instantes." : "Erro na busca: " + e.message));
  }
}
function desenharFacetas() {
  const caixa = $("#facetas"); caixa.replaceChildren();
  for (const f of FACETAS) {
    const itens = new Map((state.facetas?.[f.chave] || []).map(x => [String(x.valor), x.total]));
    for (const sel of state.filtros[f.param]) if (!itens.has(sel)) itens.set(sel, 0);
    if (!itens.size) continue;
    const grupo = h("fieldset", {}, h("legend", {}, f.titulo));
    for (const [valor, total] of itens) {
      grupo.append(h("label", { class: "check" },
        h("input", { type: "checkbox", checked: state.filtros[f.param].includes(valor),
          onchange: ev => { const a = state.filtros[f.param]; ev.target.checked ? a.push(valor) : a.splice(a.indexOf(valor), 1); buscar(1); } }),
        h("span", {}, ROTULOS[valor] || valor), h("span", { class: "n" }, String(total))));
    }
    caixa.append(grupo);
  }
}
function desenharResultados(r) {
  const cursos = (r.facetas.curso || []).length;
  $("#resumo").textContent = r.total
    ? `${r.total} ${r.total === 1 ? "questão" : "questões"} em ${cursos} ${cursos === 1 ? "curso" : "cursos"} · ${r.tempo_es_ms} ms no Elasticsearch${r.cache ? " · resposta do cache" : ""}`
    : "";
  const lista = $("#lista-questoes"); lista.replaceChildren();
  if (!r.itens.length) lista.append(h("p", { class: "vazio" }, "Nenhuma questão encontrada. Tente outro termo ou remova filtros."));
  for (const it of r.itens) lista.append(cartao(it));
  const nav = $("#paginacao"); nav.replaceChildren();
  if (r.paginas > 1) nav.append(
    h("button", { class: "secundario", disabled: r.pagina <= 1, onclick: () => { buscar(r.pagina - 1); scrollTo(0, 0); } }, "Anterior"),
    h("span", {}, `Página ${r.pagina} de ${r.paginas}`),
    h("button", { class: "secundario", disabled: r.pagina >= r.paginas, onclick: () => { buscar(r.pagina + 1); scrollTo(0, 0); } }, "Próxima"));
}

/* cartao de questao */
function cartao(it) {
  const q = it.questao, professor = state.user.perfil === "professor";
  const termos = termosDestacados(it.destaques);
  const numero = q.tipo_questao === "discursiva" ? `Discursiva ${q.numero}` : `Questão ${q.numero}`;
  const base = q.texto_base ? paragrafos(q.texto_base, termos, "texto-base") : null;
  const cab = h("div", { class: "questao-cab" },
    h("h3", {}, `${q.curso}, ${q.ano}`),
    h("span", { class: "meta" }, `${numero} · ${ROTULOS[q.componente]}${q.grau && q.grau !== "Bacharelado" ? " · " + q.grau : ""}`),
    q.anulada && h("span", { class: "etiqueta alerta" }, "Anulada"),
    h("span", { class: "etiqueta" }, q.area));
  const corpo = [cab];
  if (base) corpo.push(h("details", { class: "base", open: termos.some(t => (q.texto_base || "").toLowerCase().includes(t.toLowerCase())) },
    h("summary", {}, "Texto-base"), base));
  corpo.push(paragrafos(q.enunciado, termos));
  for (const m of q.midia || []) corpo.push(midia(m));
  const classif = [...(q.competencias || []), ...(q.habilidades || []), ...(q.objetos_conhecimento || [])];
  if (classif.length) corpo.push(h("div", { class: "classificacao" },
    h("span", { class: q.fonte_metadados === "inferido" ? "etiqueta alerta" : "etiqueta" },
      q.fonte_metadados === "inferido" ? "Competência inferida (sugestão automática)" : "Matriz oficial do INEP"),
    classif.map(c => h("span", { class: "chip" }, c))));
  const letras = Object.keys(q.alternativas || {});
  if (letras.length) {
    const ul = h("ul", { class: "alternativas" });
    for (const l of letras) {
      const li = h("li", { class: professor && q.gabarito === l ? "certa" : "" }, h("span", { class: "letra" }, l + "."), h("span", { class: "texto-prova" }));
      li.lastChild.innerHTML = realcar(q.alternativas[l], termos);
      ul.append(li);
    }
    corpo.push(ul);
  }
  if (professor && q.gabarito) corpo.push(h("p", { class: "meta" }, `Gabarito: ${q.gabarito}`));
  if (professor && q.padrao_resposta) corpo.push(h("div", { class: "padrao" }, h("h4", {}, "Padrão de resposta"), paragrafos(q.padrao_resposta, termos)));
  const na = state.lista.has(q.id);
  const btn = h("button", { class: na ? "secundario" : "primario", onclick: () => alternarLista(q.id, btn) }, na ? "Remover da lista" : "Adicionar à lista");
  corpo.push(h("div", { class: "rodape-questao" },
    h("span", { class: "fonte" }, `Fonte: ${q.origem.pdf.split("/").pop()}, página${q.origem.pagina_inicio === q.origem.pagina_fim ? " " + q.origem.pagina_inicio : "s " + q.origem.pagina_inicio + " a " + q.origem.pagina_fim}`),
    btn));
  return h("article", { class: "questao" }, corpo);
}
function tabelaMarkdown(md) {
  const linhas = md.split("\n").filter(l => !/^\|[-| ]+\|$/.test(l)).map(l => l.replace(/^\||\|$/g, "").split(" | ").map(c => c.trim()));
  const [cab, ...resto] = linhas;
  return h("div", { class: "midia-conteudo" }, h("table", { class: "tabela-prova" },
    h("thead", {}, h("tr", {}, cab.map(c => h("th", {}, c)))),
    h("tbody", {}, resto.map(r => h("tr", {}, r.map(c => h("td", {}, c)))))));
}
function midia(m) {
  if (m.conteudo && m.conversao === "markdown" && m.tipo === "tabela") return tabelaMarkdown(m.conteudo);
  if (m.conteudo && m.conversao === "mermaid") { const el = h("div", { class: "midia-conteudo" }); diagrama(el, m.conteudo); return el; }
  if (m.conteudo && m.conversao === "latex") { const el = h("div", { class: "midia-conteudo" }, "$$" + m.conteudo + "$$"); matematica(el); return el; }
  if (m.conteudo) return h("pre", { class: "midia-conteudo" }, m.conteudo);
  return h("p", { class: "midia-nota" }, `${m.tipo === "imagem" ? "Figura" : "Diagrama ou tabela"} na página ${m.pagina} do PDF original (conversão para LaTeX, Mermaid ou Markdown pendente).`);
}

/* lista de questoes (carrinho, guardada no Redis pela API) */
async function carregarLista() {
  const r = await api("/carrinho");
  state.lista = new Map(r.questoes.map(q => [q.id, q]));
  desenharLista();
}
async function alternarLista(id, btn) {
  try {
    if (state.lista.has(id)) { await api(`/carrinho/${encodeURIComponent(id)}`, { metodo: "DELETE" }); }
    else { await api(`/carrinho/${encodeURIComponent(id)}`, { metodo: "PUT" }); }
    await carregarLista();
    const na = state.lista.has(id);
    btn.textContent = na ? "Remover da lista" : "Adicionar à lista"; btn.className = na ? "secundario" : "primario";
  } catch (e) { avisar(e.status === 409 ? "Essa questão já está na lista." : "Não foi possível atualizar a lista: " + e.message, "erro"); }
}
function desenharLista() {
  $("#contagem-lista").textContent = state.lista.size;
  const caixa = $("#itens-lista"); caixa.replaceChildren();
  if (!state.lista.size) caixa.append(h("p", { class: "vazio" }, "A lista está vazia. Use \"Adicionar à lista\" nas questões."));
  for (const q of state.lista.values()) {
    caixa.append(h("div", { class: "item-lista" },
      h("strong", {}, `${q.curso}, ${q.ano}, ${q.tipo_questao === "discursiva" ? "discursiva " : "questão "}${q.numero}`),
      h("p", {}, q.enunciado.length > 140 ? q.enunciado.slice(0, 140) + "..." : q.enunciado),
      h("button", { class: "texto", onclick: async () => { await api(`/carrinho/${encodeURIComponent(q.id)}`, { metodo: "DELETE" }); await carregarLista(); buscar(state.pagina); } }, "Remover")));
  }
  $("#exp-pdf").disabled = $("#exp-json").disabled = !state.lista.size;
}
async function exportar(formato) {
  try {
    const arq = await api(`/carrinho/exportar?formato=${formato}`, { blob: true });
    const a = h("a", { href: URL.createObjectURL(arq), download: `simulado.${formato}` });
    document.body.append(a); a.click(); a.remove();
    avisar(`Simulado exportado em ${formato.toUpperCase()}.`);
  } catch (e) {
    avisar(e.status === 403 ? `Acesso negado (403): ${e.message}. A exportação é exclusiva do perfil professor.` : "Falha ao exportar: " + e.message, "erro");
  }
}

/* painel analitico (professor) */
function barras(itens) {
  const max = Math.max(1, ...itens.map(i => i.valor));
  return h("div", { class: "barras" }, itens.map(i => h("div", { class: "barra" },
    h("span", {}, i.rotulo), h("div", { class: "trilho" }, h("div", { class: "preenchimento", style: `width:${(100 * i.valor) / max}%` })), h("span", { class: "valor" }, String(i.valor)))));
}
async function desenharPainel() {
  try {
    const [cursos, comp, cache] = await Promise.all([api("/analise/distribuicao-por-curso"), api("/analise/competencias-por-ano"), api("/metricas/cache")]);
    const total = cursos.reduce((s, c) => s + c.total, 0);
    $("#painel-metricas").replaceChildren(
      ...[[total, "questões indexadas"], [cursos.length, "cursos"], [cursos.reduce((s, c) => s + c.anuladas, 0), "anuladas"],
        [cache.hit_rate == null ? "n/d" : Math.round(cache.hit_rate * 100) + "%", "acerto do cache de busca"]]
        .map(([v, r]) => h("div", { class: "metrica" }, h("strong", {}, String(v)), h("span", {}, r))));
    $("#painel-cursos").replaceChildren(barras(cursos.map(c => ({ rotulo: c.curso, valor: c.total }))));
    const comCompetencia = comp.filter(a => a.competencias.length);
    $("#painel-competencias").replaceChildren(comCompetencia.length
      ? h("div", {}, comCompetencia.map(a => h("p", {}, h("strong", {}, a.ano + ": "), a.competencias.map(c => `${c.competencia} (${c.total})`).join(", "))))
      : h("p", { class: "meta" }, "As competências ainda não foram extraídas dos PDFs, então este histograma está vazio. Ele será preenchido quando o campo for populado."));
  } catch (e) { avisar("Não foi possível carregar o painel: " + e.message, "erro"); }
}

/* abas e eventos */
function mostrarAba(nome) {
  $("#vista-busca").hidden = nome !== "busca"; $("#vista-painel").hidden = nome !== "painel";
  document.querySelectorAll("#abas button").forEach(b => b.classList.toggle("ativa", b.dataset.aba === nome));
  if (nome === "painel") desenharPainel();
}
$("#abas").addEventListener("click", e => e.target.dataset.aba && mostrarAba(e.target.dataset.aba));
$("#form-login").addEventListener("submit", async e => {
  e.preventDefault();
  const f = new FormData(e.target), erro = $("#login-erro"); erro.hidden = true;
  try { await entrar(f.get("usuario"), f.get("senha")); e.target.reset(); }
  catch (x) { erro.textContent = x.status === 401 ? "Usuário ou senha inválidos." : x.status === 403 ? "Seu usuário não pertence a nenhum grupo de acesso." : "Não foi possível entrar: " + x.message; erro.hidden = false; }
});
$("#btn-sair").addEventListener("click", () => sair());
$("#form-busca").addEventListener("submit", e => { e.preventDefault(); buscar(1); });
let atraso; $("#q").addEventListener("input", () => { clearTimeout(atraso); atraso = setTimeout(() => buscar(1), 400); });
$("#f-anuladas").addEventListener("change", e => { state.anuladas = e.target.checked; buscar(1); });
$("#limpar-filtros").addEventListener("click", () => { for (const k of Object.keys(state.filtros)) state.filtros[k] = []; $("#f-anuladas").checked = state.anuladas = true; buscar(1); });
$("#btn-lista").addEventListener("click", () => { const g = $("#gaveta"); g.hidden = !g.hidden; });
$("#fechar-gaveta").addEventListener("click", () => ($("#gaveta").hidden = true));
$("#limpar-lista").addEventListener("click", async () => { await api("/carrinho", { metodo: "DELETE" }); await carregarLista(); buscar(state.pagina); });
$("#exp-pdf").addEventListener("click", () => exportar("pdf"));
$("#exp-json").addEventListener("click", () => exportar("json"));
document.addEventListener("keydown", e => { if (e.key === "Escape") $("#gaveta").hidden = true; });

if (state.token) iniciar(); else $("#tela-login").hidden = false;
