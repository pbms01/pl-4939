"""Teste de ponta a ponta da captura de seleção, em Chrome headless.

    streamlit run app.py --server.headless true --server.port 8765 &
    python tests/e2e_selecao.py http://localhost:8765 [captura.png] [chrome|firefox|webkit] [sim]

Sem chave de API o app mostra só o relatório, e é assim que os passos 1 a 7 rodam.
Com o quarto argumento "sim", o app deve ter sido iniciado com PL4939_SIMULAR=1, e o
teste percorre também o botão Explicar, a resposta em fluxo e o cache de respostas.
"""
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
SHOT = (sys.argv[2] if len(sys.argv) > 2 else None) or None
MOTOR = sys.argv[3] if len(sys.argv) > 3 else "chrome"
SIMULADO = len(sys.argv) > 4 and sys.argv[4] == "sim"

# número de parágrafos do relatório que a intenção "caso" deve trazer para a seleção do passo 3,
# calculado pelo próprio explicador para que o teste não envelheça quando o relatório mudar
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from explicador import MODELO_PADRAO, Relatorio, preparar  # noqa: E402
from leitor import Corpus, validar  # noqa: E402

_c, _r = Corpus.carregar(RAIZ / "corpus.json"), Relatorio.carregar(RAIZ / "relatorio.json")
_sel = validar(_c, {"modo": "selecao", "texto": "sitivo ou programa de computador; b) senha, código"})
assert _sel.ok
ESPERADO_CASO = len(preparar(_c, _r, _sel, "caso", MODELO_PADRAO).numeros)
ESPERADO_SIMPLES = len(preparar(_c, _r, _sel, "simples", MODELO_PADRAO).numeros)
assert ESPERADO_CASO > ESPERADO_SIMPLES


def painel(page):
    return page.locator('[data-testid="stColumn"]').nth(1)


with sync_playwright() as p:
    if MOTOR == "chrome":
        nav = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
    else:
        nav = getattr(p, MOTOR).launch(headless=True)
    page = nav.new_page(viewport={"width": 1440, "height": 900})
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    page.goto(URL)
    page.wait_for_selector(".pl-leitor [data-id='art-1']", timeout=30000)
    # na primeira carga o layout ainda se acomoda (fontes, colunas); medir antes disso desloca o arrasto
    page.evaluate("document.fonts.ready")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(800)

    # 1. o leitor está no DOM da página, e não em shadow root
    assert page.evaluate("!!document.querySelector('.pl-leitor')")
    assert page.evaluate("document.querySelector('.pl-leitor').getRootNode() === document")
    # o quadro de uso está à vista, diz onde a explicação aparece e não gera pedido se for selecionado
    uso = page.locator(".pl-uso")
    expect(uso).to_be_visible()
    expect(uso).to_contain_text("A explicação aparece ao lado do texto.")
    assert float(page.locator("[data-id='art-1'] .pl-u-btn").evaluate("el => getComputedStyle(el).opacity")) >= 0.4
    page.evaluate(
        """() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('.pl-uso'));
                   const s = document.getSelection(); s.removeAllRanges(); s.addRange(r); }"""
    )
    page.wait_for_timeout(400)
    expect(page.locator(".pl-sel-btn")).to_be_hidden()
    page.evaluate("document.getSelection().removeAllRanges()")
    # a caixa do texto termina dentro da janela: não há segunda rolagem, a da página
    page.wait_for_timeout(1200)
    cx = page.locator(".pl-leitor").bounding_box()
    assert cx["y"] + cx["height"] <= page.viewport_size["height"], f"a caixa do texto passa do pé da janela: {cx}"
    assert cx["height"] >= 320
    print(f"1. leitor montado fora de shadow root, quadro de uso e botões ? à vista, caixa do texto com {cx['height']:.0f} px")

    # 2. seleção por arrasto do mouse, atravessando dispositivos
    # os dois dispositivos precisam estar na parte visível da caixa do texto antes do arrasto
    page.evaluate("""() => { const l = document.querySelector('.pl-leitor');
        l.scrollTop = document.querySelector("[data-id='art-1-par-unico']").offsetTop - 12; }""")
    page.wait_for_timeout(300)
    a = page.locator("[data-id='art-1-par-unico']").bounding_box()
    b = page.locator("[data-id='art-2-inc-1']").bounding_box()
    page.mouse.move(a["x"] + 150, a["y"] + 12)
    page.mouse.down()
    page.mouse.move(b["x"] + 260, b["y"] + 12, steps=12)
    page.mouse.up()
    expect(page.locator(".pl-sel-btn")).to_be_visible()
    bruto = page.evaluate("document.getSelection().toString()")
    page.locator(".pl-sel-btn").click()
    expect(painel(page)).to_contain_text("Art. 2º, I", timeout=15000)
    txt = painel(page).inner_text()
    assert "Art. 1º, parágrafo único" in txt and "Art. 2º, I" in txt, txt
    assert "\n" in bruto, "a seleção bruta deveria trazer quebras entre blocos"
    print("2. arrasto entre dispositivos:", repr(bruto[:70]), "...")

    # 3. seleção que corta palavras, dentro do texto citado do Código Penal
    page.evaluate(
        """() => {
          const no = (id) => [...document.querySelector(`[data-id='${id}']`).childNodes]
              .filter(n => n.nodeType === 3 && n.textContent.trim()).pop();
          const r = document.createRange();
          r.setStart(no('art-41-cp-154-A-par-1-inc-2-ali-a'), 6);
          r.setEnd(no('art-41-cp-154-A-par-1-inc-2-ali-b'), 14);
          const s = document.getSelection(); s.removeAllRanges(); s.addRange(r);
          document.querySelector(`[data-id='art-41-cp-154-A-par-1-inc-2-ali-a']`).scrollIntoView({block: 'center'});
        }"""
    )
    page.wait_for_timeout(500)  # o leitor reavalia a seleção com atraso de 120 ms
    expect(page.locator(".pl-sel-btn")).to_be_visible()
    page.locator(".pl-sel-btn").click()
    expect(painel(page)).to_contain_text("§ 1º, II, b", timeout=15000)
    txt = painel(page).inner_text()
    assert "Art. 41 · CP, art. 154-A, § 1º, II, a" in txt, txt
    print("3. seleção no texto citado, cortando palavras")

    # 4. escolha de intenção reexecuta o script e a seleção permanece no painel
    painel(page).locator("label").filter(has_text="Caso concreto").click()
    # a intenção "caso" acrescenta os casos de fronteira do art. 154-A ao material do relatório
    expect(painel(page)).to_contain_text(f"{ESPERADO_CASO} parágrafos", timeout=15000)
    assert "§ 1º, II, b" in painel(page).inner_text()
    print("4. seleção preservada depois da troca de intenção, com o material da nova intenção")

    # 5. botão do dispositivo inteiro
    alvo = page.locator("[data-id='art-5-par-1']")
    alvo.scroll_into_view_if_needed()
    alvo.hover()
    alvo.locator(".pl-u-btn").click()
    expect(painel(page)).to_contain_text("Art. 5º, § 1º", timeout=15000)
    assert "não torna a prova ilícita nem inadmissível" in painel(page).inner_text()
    if not SIMULADO:
        # sem IA, o painel abre o comentário do relatório ao art. 5º
        expect(painel(page)).to_contain_text("O § 1º separa custódia e ilicitude", timeout=15000)
    print("5. botão do dispositivo inteiro")

    # 6. seleção fora do leitor não aciona o botão
    page.evaluate(
        """() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('h1'));
                   const s = document.getSelection(); s.removeAllRanges(); s.addRange(r); }"""
    )
    page.wait_for_timeout(400)
    expect(page.locator(".pl-sel-btn")).to_be_hidden()
    print("6. seleção fora do leitor ignorada")

    # 7. "Ir para" rola o leitor até o artigo, sem rolar a página
    page.evaluate("document.getSelection().removeAllRanges()")
    # a lista do seletor é virtualizada: digitar filtra as opções e traz o artigo para a tela
    caixa = page.get_by_role("combobox", name="Ir para")
    caixa.click()
    caixa.fill("Art. 34")
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1200)
    visivel = page.evaluate(
        """() => { const l = document.querySelector('.pl-leitor').getBoundingClientRect();
                   const a = document.querySelector("[data-id='art-34']").getBoundingClientRect();
                   return a.top >= l.top - 2 && a.top < l.bottom; }"""
    )
    assert visivel, "o art. 34 deveria estar visível no leitor"
    # um pedido de explicação depois da navegação não pode devolver o leitor ao destino anterior
    page.locator(".pl-leitor").evaluate("el => el.scrollTop = 0")
    alvo = page.locator("[data-id='art-1']")
    alvo.hover()
    alvo.locator(".pl-u-btn").click()
    expect(painel(page)).to_contain_text("Art. 1º", timeout=15000)
    page.wait_for_timeout(600)
    assert page.locator(".pl-leitor").evaluate("el => el.scrollTop") < 50, "o leitor voltou ao destino antigo"
    print("7. navegação pelo índice")

    if SIMULADO:
        # 8. botão Explicar, resposta em fluxo, aviso e cache de respostas
        painel(page).locator("label").filter(has_text="Racional do dispositivo").click()
        painel(page).get_by_role("button", name="Explicar").click()
        # enquanto o modelo não responde, a barra de espera fica à vista; some quando o texto começa
        barra = painel(page).get_by_role("progressbar")
        expect(barra).to_be_visible(timeout=5000)
        assert "analisando" not in painel(page).inner_text(), "a barra de espera não deve trazer texto"
        expect(painel(page)).to_contain_text("[simulação] Explicação de teste apoiada em: §", timeout=15000)
        expect(painel(page)).to_contain_text("Explicação gerada por IA", timeout=15000)
        expect(barra).to_be_hidden(timeout=5000)
        # mesma seleção e mesma intenção de novo: a resposta vem do cache e o botão não reaparece
        alvo.hover()
        alvo.locator(".pl-u-btn").click()
        page.wait_for_timeout(1500)
        expect(painel(page)).to_contain_text("[simulação]", timeout=15000)
        assert painel(page).get_by_role("button", name="Explicar").count() == 0
        print("8. explicação em fluxo e cache de respostas")

    assert not erros, erros
    if SHOT:
        page.evaluate("document.getSelection().removeAllRanges()")
        page.locator("[data-id='art-5']").scroll_into_view_if_needed()
        b = page.locator("[data-id='art-5-par-1']").bounding_box()
        page.mouse.move(b["x"] + 60, b["y"] + 12)
        page.mouse.down()
        page.mouse.move(b["x"] + 420, b["y"] + 40, steps=8)
        page.mouse.up()
        page.wait_for_timeout(500)
        page.screenshot(path=SHOT)
    nav.close()
print(f"ponta a ponta ({MOTOR}): todos os testes passaram")
