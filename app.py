"""Sítio do PL 4939: texto integral, seleção de trecho e explicação por IA.

    streamlit run app.py

Configuração, por variável de ambiente ou em .streamlit/secrets.toml:
    ANTHROPIC_API_KEY    chave da API; sem ela o sítio mostra só o relatório explicativo
    PL4939_MODELO        modelo (padrão: claude-sonnet-5-5)
    PL4939_COTA_SESSAO   explicações novas por sessão (padrão: 20)
    PL4939_COTA_DIA      explicações novas por dia, somadas todas as sessões (padrão: 400)
"""
import logging
import os
from pathlib import Path

import streamlit as st

from explicador import (INTENCOES, MODELO_PADRAO, Armazem, Relatorio, criar_cliente, fluxo_api,
                        fluxo_simulado, preparar, simulando)
from leitor import Corpus, indice, registrar, validar

RAIZ = Path(__file__).parent
ROTULOS_PARTE = {
    "comentario": "Comentário ao artigo",
    "escolhas": "As escolhas da redação",
    "fronteira": "Casos de fronteira",
    "fenomenos": "Os fenômenos e a lei",
}

st.set_page_config(page_title="PL 4939/2020", layout="wide")


def cfg(nome: str, padrao: str | None = None) -> str | None:
    """Lê a configuração do ambiente e, na falta, dos segredos do Streamlit."""
    if os.environ.get(nome):
        return os.environ[nome]
    try:
        return st.secrets[nome]
    except Exception:  # sem arquivo de segredos o acesso levanta erro, e isso não é falha do app
        return padrao


@st.cache_resource
def carregar():
    corpus = Corpus.carregar(RAIZ / "corpus.json")
    relatorio = Relatorio.carregar(RAIZ / "relatorio.json")
    armazem = Armazem(RAIZ / "dados" / "respostas.sqlite")
    return corpus, relatorio, armazem, criar_cliente(cfg("ANTHROPIC_API_KEY"))


corpus, relatorio, armazem, cliente = carregar()
meta = corpus.meta
MODELO = cfg("PL4939_MODELO", MODELO_PADRAO)
COTA_SESSAO = int(cfg("PL4939_COTA_SESSAO", "20"))
COTA_DIA = int(cfg("PL4939_COTA_DIA", "400"))
ia_ativa = cliente is not None or simulando()

st.title("PL 4939/2020")
st.caption(
    f"Redação consolidada, versão {meta['versao']}. Documento de trabalho"
    + (" (amostra parcial do texto)" if meta.get("amostra") else "")
    + f" · texto {meta['sha256'][:12]} · relatório explicativo {relatorio.meta['sha256'][:12]}"
)

col_texto, col_painel = st.columns([3, 2], gap="large")

with col_texto:
    entradas = indice(corpus)

    def _navegar():
        # contador de pedidos: escolher duas vezes o mesmo destino também precisa rolar o leitor
        st.session_state["nav_pedido"] = st.session_state.get("nav_pedido", 0) + 1

    destino = st.selectbox(
        "Ir para", options=list(entradas), format_func=entradas.get, index=None,
        placeholder="Capítulo, seção ou artigo", key="nav_destino", on_change=_navegar,
    )
    leitor = registrar(corpus)
    # O valor de gatilho só existe na execução disparada pelo clique. Por isso a seleção
    # validada vai para o session_state: a escolha da intenção reexecuta o script e,
    # sem isso, o painel perderia o trecho.
    resultado = leitor(
        key="leitor", on_selecao_change=lambda: None,
        data={"ir_para": destino, "pedido": st.session_state.get("nav_pedido", 0)},
    )
    if resultado.selecao:
        st.session_state["selecao"] = validar(corpus, resultado.selecao)

with col_painel:
    st.subheader("Explicação")
    sel = st.session_state.get("selecao")
    if sel is None:
        st.info(
            "Selecione um trecho do texto e use o botão **Explicar seleção**, "
            "ou use o botão **?** ao lado de um dispositivo para explicá-lo por inteiro."
        )
    elif not sel.ok:
        st.error(sel.motivo)
    else:
        st.markdown("**" + "; ".join(sel.refs) + "**")
        st.markdown(f"> {sel.trecho}")
        intencao = st.radio(
            "O que você quer saber?", options=list(INTENCOES), format_func=lambda k: INTENCOES[k][0], key="intencao",
        )
        pedido = preparar(corpus, relatorio, sel, intencao, MODELO)

        # Resposta já dada para o mesmo trecho, intenção e versão sai do cache, sem custo e sem cota.
        resposta = armazem.obter(pedido.chave)
        if resposta:
            st.markdown(resposta)
        elif ia_ativa and st.button("Explicar", type="primary"):
            if st.session_state.get("usos", 0) >= COTA_SESSAO:
                st.warning("Esta sessão atingiu o limite de explicações novas. As já dadas continuam disponíveis.")
            elif armazem.chamadas_hoje() >= COTA_DIA:
                st.warning("O limite diário de explicações novas foi atingido. Volte amanhã ou consulte o relatório abaixo.")
            else:
                st.session_state["usos"] = st.session_state.get("usos", 0) + 1
                armazem.contar_chamada()
                try:
                    fluxo = fluxo_simulado(pedido) if simulando() else fluxo_api(cliente, MODELO, pedido)
                    resposta = st.write_stream(fluxo)
                    if isinstance(resposta, str) and resposta.strip():
                        armazem.guardar(pedido.chave, resposta)
                except Exception:
                    # o detalhe do erro vai para o log do servidor, não para a tela do visitante
                    logging.exception("falha na chamada ao explicador")
                    resposta = None
                    st.error("Não foi possível obter a explicação agora. Tente de novo em instantes.")
        if resposta:
            st.caption(
                "Explicação gerada por IA a partir do relatório explicativo. "
                "Não é interpretação autêntica do projeto nem orientação jurídica."
            )
        if not ia_ativa:
            st.info("A explicação por IA não está ativada neste ambiente. Abaixo, o que o relatório explicativo diz sobre o trecho.")

        # O material que fundamenta a resposta fica sempre à vista do leitor, para conferência.
        if pedido.material:
            with st.expander(f"Relatório explicativo sobre este trecho ({len(pedido.numeros)} parágrafos)", expanded=not ia_ativa):
                for parte, ps in pedido.material.items():
                    st.markdown(f"**{ROTULOS_PARTE[parte]}**")
                    for p in ps:
                        st.markdown(f"§ {p['n']}. {p['texto']}")
        else:
            st.caption("O relatório explicativo não traz comentário específico para este trecho.")
