"""Leitor do PL: componente v2 que exibe o texto e devolve ao Python a seleção do usuário.

Duas responsabilidades ficam aqui, de propósito no mesmo módulo:
  1. renderizar o corpus em HTML e capturar a seleção no navegador;
  2. validar, no servidor, que o trecho recebido existe de fato no texto canônico.
A segunda não confia em nada do que o navegador informa além do próprio trecho.
"""
from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import streamlit as st

# Unidades sem botão próprio: não há comentário do relatório a mostrar para elas.
SEM_BOTAO = {"omissao", "preambulo", "capitulo", "secao", "titulo"}
LIMITE_MIN = 2      # caracteres; abaixo disso a seleção é ruído (um clique duplo num artigo "a")
LIMITE_MAX = 4000   # caracteres; teto de custo por pedido ao explicador


# --------------------------------------------------------------------------- corpus

def texto_plano(u: dict) -> str:
    return f"{u['rotulo']} {u['texto']}" if u["rotulo"] else u["texto"]


def normalizar(s: str) -> str:
    """Forma de comparação: NFC, espaço não separável como espaço, brancos colapsados.

    O navegador devolve a seleção com quebras de linha entre blocos; o corpus guarda
    cada dispositivo numa linha. Colapsar os brancos torna as duas formas comparáveis
    sem tocar em nenhum caractere do texto legal.
    """
    s = unicodedata.normalize("NFC", s).replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Corpus:
    meta: dict
    unidades: list[dict]
    canonico: str = ""                                  # texto inteiro, normalizado
    faixas: list[tuple[int, int, int]] = field(default_factory=list)  # (início, fim, índice da unidade)
    por_id: dict[str, int] = field(default_factory=dict)

    @classmethod
    def carregar(cls, caminho: Path) -> "Corpus":
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
        c = cls(meta=bruto["meta"], unidades=bruto["unidades"])
        partes, pos = [], 0
        for i, u in enumerate(c.unidades):
            t = normalizar(texto_plano(u))
            c.faixas.append((pos, pos + len(t), i))
            c.por_id[u["id"]] = i
            partes.append(t)
            pos += len(t) + 1                           # +1 pelo espaço que une as unidades
        c.canonico = " ".join(partes)
        return c


# --------------------------------------------------------------------------- validação

@dataclass
class Selecao:
    ok: bool
    motivo: str = ""
    modo: str = ""
    trecho: str = ""                 # como está no texto canônico, não como veio do navegador
    ids: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)


def validar(corpus: Corpus, payload: dict | None) -> Selecao:
    if not isinstance(payload, dict):
        return Selecao(False, "Pedido sem conteúdo.")
    modo = payload.get("modo")

    # Toque no dispositivo inteiro: o navegador manda só o identificador,
    # e o texto vem do corpus. Não há trecho do cliente a conferir.
    if modo == "dispositivo":
        i = corpus.por_id.get(str(payload.get("inicio")))
        if i is None or corpus.unidades[i]["tipo"] == "omissao":
            return Selecao(False, "Dispositivo desconhecido.")
        u = corpus.unidades[i]
        return Selecao(True, modo=modo, trecho=texto_plano(u), ids=[u["id"]], refs=[u["ref"]])

    if modo != "selecao" or not isinstance(payload.get("texto"), str):
        return Selecao(False, "Pedido em formato inesperado.")
    alvo = normalizar(payload["texto"])
    if len(alvo) < LIMITE_MIN:
        return Selecao(False, "Seleção curta demais.")
    if len(alvo) > LIMITE_MAX:
        return Selecao(False, f"Seleção acima de {LIMITE_MAX} caracteres. Selecione um trecho menor.")

    # O trecho precisa ser subcadeia do texto canônico. É esta checagem que impede
    # que texto estranho ao projeto chegue ao prompt disfarçado de seleção.
    ocorrencias = [m.start() for m in re.finditer(re.escape(alvo), corpus.canonico)]
    if not ocorrencias:
        return Selecao(False, "O trecho recebido não corresponde ao texto do projeto.")

    # Trechos curtos se repetem ("dados informáticos"). O identificador informado pelo
    # navegador serve só para escolher entre ocorrências verdadeiras, nunca para validar.
    pos = ocorrencias[0]
    dica = corpus.por_id.get(str(payload.get("inicio")))
    if dica is not None and len(ocorrencias) > 1:
        ini_u, fim_u, _ = corpus.faixas[dica]
        pos = next((p for p in ocorrencias if ini_u <= p < fim_u), pos)

    fim = pos + len(alvo)
    tocadas = [i for (a, b, i) in corpus.faixas if a < fim and b > pos]
    return Selecao(
        True, modo=modo, trecho=corpus.canonico[pos:fim],
        ids=[corpus.unidades[i]["id"] for i in tocadas],
        refs=[corpus.unidades[i]["ref"] for i in tocadas],
    )


# --------------------------------------------------------------------------- HTML do leitor

def _html_unidade(u: dict) -> str:
    classes = f"pl-u pl-{u['tipo']} pl-n{u['nivel']}" + (" pl-citado" if u["citado"] else "")
    rot = f'<span class="pl-rot">{html.escape(u["rotulo"])}</span> ' if u["rotulo"] else ""
    # O botão não tem texto: o ícone vem do CSS. Assim ele nunca entra em selection.toString()
    # e o trecho selecionado continua idêntico ao texto canônico.
    botao = "" if u["tipo"] in SEM_BOTAO else (
        f'<button type="button" class="pl-u-btn" aria-label="Explicar {html.escape(u["ref"], quote=True)}"></button>'
    )
    return (
        f'<p class="{classes}" data-id="{html.escape(u["id"], quote=True)}">'
        f"{rot}{html.escape(u['texto'])}{botao}</p>"
    )


def montar_html(corpus: Corpus) -> str:
    corpo = "\n".join(_html_unidade(u) for u in corpus.unidades)
    return (
        '<div class="pl-wrap">'
        f'<div class="pl-leitor" lang="pt-BR" tabindex="0" role="document" aria-label="Texto do projeto de lei">{corpo}</div>'
        '<button type="button" class="pl-sel-btn" hidden>Explicar seleção</button>'
        "</div>"
    )


CSS = """
.pl-wrap { position: relative; }
.pl-leitor {
  position: relative; max-height: 78vh; overflow-y: auto; padding: 1.25rem 2.75rem 2rem 1.5rem;
  border: 1px solid var(--st-border-color, rgba(128,128,128,.3)); border-radius: 8px;
  font-family: Georgia, "Times New Roman", serif; font-size: 1.02rem; line-height: 1.65;
  color: var(--st-text-color, inherit); background: var(--st-background-color, transparent);
}
.pl-u { position: relative; margin: 0 0 .7rem 0; text-align: justify; hyphens: auto; }
.pl-rot { font-weight: 700; }
.pl-inciso .pl-rot, .pl-alinea .pl-rot, .pl-pena .pl-rot { font-weight: 400; }
.pl-n1 { margin-left: 1.5rem; }
.pl-n2 { margin-left: 3rem; }
.pl-preambulo, .pl-capitulo, .pl-secao, .pl-titulo { text-align: center; hyphens: none; }
.pl-capitulo { margin-top: 2rem; font-weight: 700; letter-spacing: .04em; }
.pl-secao { margin-top: 1.4rem; font-weight: 700; }
.pl-titulo { font-weight: 700; margin-bottom: 1.2rem; }
.pl-artigo:not(.pl-citado) { margin-top: 1.1rem; }
.pl-citado { padding-left: 1rem; border-left: 3px solid var(--st-border-color, rgba(128,128,128,.35)); margin-left: 1rem; }
.pl-citado.pl-n1 { margin-left: 2.5rem; }
.pl-citado.pl-n2 { margin-left: 4rem; }
.pl-rubrica { font-weight: 700; }
.pl-omissao { overflow: hidden; white-space: nowrap; opacity: .55; }
/* Botão do dispositivo inteiro: alternativa à seleção, necessária em telas de toque e ao teclado. */
.pl-u-btn {
  position: absolute; right: -2.1rem; top: .15rem; width: 1.6rem; height: 1.6rem; padding: 0;
  border: 1px solid transparent; border-radius: 50%; background: transparent; cursor: pointer;
  color: var(--st-primary-color, #c0392b); opacity: 0; user-select: none; -webkit-user-select: none;
}
.pl-u-btn::before { content: "?"; font: 700 .85rem/1 system-ui, sans-serif; }
.pl-u:hover > .pl-u-btn, .pl-u-btn:focus-visible { opacity: 1; border-color: currentColor; }
@media (hover: none) { .pl-u-btn { opacity: .55; border-color: currentColor; } }
.pl-sel-btn {
  position: absolute; z-index: 5; padding: .35rem .8rem; border: 0; border-radius: 6px; cursor: pointer;
  font: 600 .9rem/1.2 system-ui, sans-serif; color: #fff; background: var(--st-primary-color, #c0392b);
  box-shadow: 0 2px 8px rgba(0,0,0,.25); user-select: none; -webkit-user-select: none;
}
.pl-sel-btn[hidden] { display: none; }
/* Tela estreita. Como o componente não usa shadow root, estas regras alcançam também a página:
   o cabeçalho do Streamlit ocupa metade de uma tela de celular e é encolhido aqui. */
@media (max-width: 640px) {
  /* No celular o texto corre na própria página, sem caixa de rolagem interna: rolar uma
     janela de meia tela dentro de outra rolagem é o que mais atrapalha a leitura por toque. */
  .pl-leitor { max-height: none; overflow: visible; border: 0; padding: .25rem 2.3rem 1rem 0; font-size: 1rem; line-height: 1.6; }
  .pl-u { scroll-margin-top: 4.5rem; }   /* o "Ir para" não pode parar o artigo atrás do cabeçalho fixo */
  /* texto justificado em coluna estreita abre buracos entre as palavras */
  .pl-artigo, .pl-paragrafo, .pl-inciso, .pl-alinea, .pl-pena, .pl-rubrica { text-align: left; hyphens: manual; }
  .pl-n1 { margin-left: .9rem; }
  .pl-n2 { margin-left: 1.8rem; }
  .pl-citado { margin-left: .3rem; padding-left: .7rem; }
  .pl-citado.pl-n1 { margin-left: 1.2rem; }
  .pl-citado.pl-n2 { margin-left: 2.1rem; }
  .pl-u-btn { right: -2rem; }
  [data-testid="stMainBlockContainer"] { padding-top: 3.5rem; padding-bottom: 2rem; }
  [data-testid="stHeading"] h1 { font-size: 1.45rem; padding: .25rem 0; }
}
"""

JS = """
export default function (component) {
  const { parentElement, setTriggerValue, data } = component;
  const wrap = parentElement.querySelector('.pl-wrap');
  if (!wrap) return;
  const leitor = wrap.querySelector('.pl-leitor');
  const btn = wrap.querySelector('.pl-sel-btn');

  // Navegação pedida pelo Python ("Ir para"). O número do pedido fica gravado no próprio
  // elemento: esta função roda de novo a cada reexecução do script, e sem a marca o leitor
  // voltaria ao mesmo artigo toda vez que o usuário pedisse uma explicação.
  if (data && data.ir_para && String(data.pedido) !== wrap.dataset.pedido) {
    wrap.dataset.pedido = String(data.pedido);
    const alvo = leitor.querySelector(`[data-id="${CSS.escape(data.ir_para)}"]`);
    // com caixa de rolagem própria (tela larga) rola-se o leitor; sem ela (celular), a página
    if (alvo && leitor.scrollHeight > leitor.clientHeight + 1) leitor.scrollTop = alvo.offsetTop - 12;
    else if (alvo) alvo.scrollIntoView({ block: 'start' });
  }
  let pendente = null, timer = null;

  const unidade = (no) => {
    const el = no && (no.nodeType === 1 ? no : no.parentElement);
    return el ? el.closest('[data-id]') : null;
  };
  const esconder = () => { btn.hidden = true; pendente = null; };

  const avaliar = () => {
    const sel = document.getSelection();
    if (!sel || sel.isCollapsed || sel.rangeCount === 0) return esconder();
    const r = sel.getRangeAt(0);
    // Seleção que começa ou termina fora do leitor não é pedido de explicação do texto.
    if (!leitor.contains(r.startContainer) || !leitor.contains(r.endContainer)) return esconder();
    // selection.toString(), e não range.toString(): só a primeira separa os blocos com
    // quebra de linha, e sem isso o fim de um dispositivo cola no começo do seguinte.
    const texto = sel.toString();
    if (texto.trim().length < 2) return esconder();
    const ini = unidade(r.startContainer), fim = unidade(r.endContainer);
    // O pedido fica guardado já aqui. No iOS o toque no botão pode desfazer a seleção
    // antes do clique, e ler a seleção só no clique devolveria vazio.
    pendente = { modo: 'selecao', texto, inicio: ini ? ini.dataset.id : null, fim: fim ? fim.dataset.id : null };

    const rects = r.getClientRects();
    const ult = rects.length ? rects[rects.length - 1] : r.getBoundingClientRect();
    const base = wrap.getBoundingClientRect();
    btn.hidden = false;
    const esq = ult.right - base.left - btn.offsetWidth / 2;
    const topo = ult.bottom - base.top + 8;
    btn.style.left = Math.max(4, Math.min(esq, base.width - btn.offsetWidth - 4)) + 'px';
    btn.style.top = Math.max(4, Math.min(topo, base.height - btn.offsetHeight - 4)) + 'px';
  };
  const agendar = () => { clearTimeout(timer); timer = setTimeout(avaliar, 120); };

  // selectionchange cobre mouse, teclado e as alças de seleção das telas de toque.
  document.addEventListener('selectionchange', agendar);
  leitor.addEventListener('scroll', agendar, { passive: true });

  // O Python decide onde mostrar a explicação: ao lado do texto ou, em tela estreita, sobre ele.
  // 640 px é a largura em que o Streamlit empilha as colunas e o painel desce para baixo do leitor.
  const estreita = () => window.matchMedia('(max-width: 640px)').matches;
  let ultimoEnvio = 0;
  const enviar = () => {
    const agora = Date.now();
    if (!pendente || agora - ultimoEnvio < 600) return;
    ultimoEnvio = agora;
    setTriggerValue('selecao', { ...pendente, estreita: estreita(), seq: agora });
  };
  // O pedido sai já no pointerdown. No celular, o toque fora da seleção a desfaz, o botão
  // se esconde e o clique que viria em seguida nunca chega. O clique fica para o teclado,
  // e o intervalo de 600 ms impede o envio em dobro quando os dois eventos ocorrem.
  const segurar = (e) => { e.preventDefault(); enviar(); };
  btn.addEventListener('pointerdown', segurar);
  btn.addEventListener('click', enviar);

  const porDispositivo = (e) => {
    const b = e.target.closest('.pl-u-btn');
    if (!b) return;
    const u = b.closest('[data-id]');
    // seq muda a cada pedido para que dois toques seguidos no mesmo dispositivo gerem dois eventos,
    // e vem do relógio porque um contador voltaria a zero se o componente fosse remontado.
    setTriggerValue('selecao', { modo: 'dispositivo', inicio: u.dataset.id, fim: u.dataset.id, texto: '', estreita: estreita(), seq: Date.now() });
  };
  leitor.addEventListener('click', porDispositivo);

  return () => {
    clearTimeout(timer);
    document.removeEventListener('selectionchange', agendar);
    leitor.removeEventListener('scroll', agendar);
    leitor.removeEventListener('click', porDispositivo);
    btn.removeEventListener('pointerdown', segurar);
    btn.removeEventListener('click', enviar);
  };
}
"""


def indice(corpus: Corpus) -> dict[str, str]:
    """Entradas do "Ir para": capítulos, seções e artigos do projeto, com a rubrica quando houver."""
    saida: dict[str, str] = {}
    us = corpus.unidades
    for i, u in enumerate(us):
        if u["citado"]:
            continue
        if u["tipo"] in ("capitulo", "secao"):
            rubrica = us[i + 1]["texto"] if i + 1 < len(us) and us[i + 1]["tipo"] == "titulo" else ""
            recuo = "" if u["tipo"] == "capitulo" else "\u2003"
            saida[u["id"]] = f"{recuo}{u['texto']}" + (f" · {rubrica}" if rubrica else "")
        elif u["tipo"] == "artigo":
            saida[u["id"]] = f"\u2003\u2003{u['ref']}"
    return saida


def registrar(corpus: Corpus):
    # isolate_styles=False monta o HTML no DOM da página, fora de shadow root.
    # Dentro de shadow root, document.getSelection() não enxerga a seleção de modo
    # uniforme entre navegadores (o Safari é o caso pior), e o leitor ficaria cego.
    # O preço é a falta de isolamento de CSS, contornada pelo prefixo "pl-" em tudo.
    return st.components.v2.component(
        "pl4939_leitor", html=montar_html(corpus), css=CSS, js=JS, isolate_styles=False
    )
