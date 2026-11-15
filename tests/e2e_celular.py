"""Teste de ponta a ponta em tela de celular (emulação de iPhone no WebKit e de Pixel no Chrome).

    streamlit run app.py --server.headless true --server.port 8765 &
    python tests/e2e_celular.py http://localhost:8765 [iphone|pixel] [pasta_das_capturas] [sim]

A emulação reproduz a largura da tela e o toque, não o gesto de seleção por pressão
longa nem o menu nativo de seleção. Esses dois só se conferem em aparelho de verdade.
"""
import sys

from playwright.sync_api import expect, sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8765"
APARELHO = sys.argv[2] if len(sys.argv) > 2 else "iphone"
PASTA = (sys.argv[3] if len(sys.argv) > 3 else "") or None
SIMULADO = len(sys.argv) > 4 and sys.argv[4] == "sim"

with sync_playwright() as p:
    if APARELHO == "iphone":
        nav = p.webkit.launch(headless=True)
        ctx = nav.new_context(**p.devices["iPhone 14"])
    else:
        nav = p.chromium.launch(channel="chrome", headless=True, args=["--no-sandbox"])
        ctx = nav.new_context(**p.devices["Pixel 7"])
    page = ctx.new_page()
    erros = []
    page.on("pageerror", lambda e: erros.append(str(e)))
    page.goto(URL, timeout=120000)
    page.wait_for_selector(".pl-leitor [data-id='art-1']", timeout=120000)
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(1500)
    alt = page.viewport_size["height"]
    dialogo = page.get_by_role("dialog")

    # 1. o leitor começa dentro da primeira tela e ocupa boa parte dela
    # o quadro de uso cabe inteiro na primeira tela, e o texto começa logo depois dele
    uso = page.locator(".pl-uso")
    expect(uso).to_contain_text("Como pedir a explicação de um trecho")
    expect(uso).to_contain_text("A explicação abre sobre o texto.")
    cu = uso.bounding_box()
    assert cu["y"] + cu["height"] <= alt, f"o quadro de uso não cabe na primeira tela: {cu}"
    cx = page.locator(".pl-leitor").bounding_box()
    assert cx["y"] < alt, f"o texto começa fora da primeira tela: {cx['y']:.0f} de {alt}"
    assert page.evaluate("getComputedStyle(document.querySelector(\"[data-id='art-1']\")).textAlign") == "justify"
    assert page.locator("[data-id='cap-1'] .pl-u-btn").count() == 0, "título de capítulo não deve ter botão"
    if PASTA:
        page.screenshot(path=f"{PASTA}/cel_{APARELHO}_1_leitor.png")
    print(f"1. quadro de uso inteiro na primeira tela (termina em {cu['y'] + cu['height']:.0f} de {alt} px), texto justificado")

    # 2. toque no botão do dispositivo abre a explicação sobre o texto, visível sem rolar
    page.locator("[data-id='art-5-par-1']").scroll_into_view_if_needed()
    page.locator("[data-id='art-5-par-1'] .pl-u-btn").tap()
    expect(dialogo).to_be_visible(timeout=15000)
    expect(dialogo).to_contain_text("Art. 5º, § 1º")
    expect(dialogo).to_contain_text("não torna a prova ilícita nem inadmissível")
    cd = dialogo.bounding_box()
    assert cd["y"] >= 0 and cd["y"] < alt * 0.5, f"o diálogo não está na tela: {cd}"
    if PASTA:
        page.wait_for_timeout(600)
        page.screenshot(path=f"{PASTA}/cel_{APARELHO}_2_dialogo.png")
    print("2. toque no dispositivo abre a explicação sobre o texto")

    # 3. a troca de intenção acontece dentro do diálogo, que continua aberto
    dialogo.locator("label").filter(has_text="Racional do dispositivo").tap()
    expect(dialogo).to_contain_text("8 parágrafos", timeout=15000)   # 7 do comentário mais 1 das escolhas da redação
    expect(dialogo).to_be_visible()
    print("3. troca de intenção dentro do diálogo")

    if SIMULADO:
        dialogo.get_by_role("button", name="Explicar").tap()
        expect(dialogo.get_by_role("progressbar")).to_be_visible(timeout=5000)
        expect(dialogo).to_contain_text("[simulação] Explicação de teste apoiada em: §", timeout=15000)
        expect(dialogo).to_contain_text("Explicação gerada por IA")
        expect(dialogo.get_by_role("progressbar")).to_be_hidden(timeout=5000)
        print("3b. explicação em fluxo dentro do diálogo")
    else:
        expect(dialogo).to_contain_text("O § 1º separa custódia e ilicitude")

    # 4. fechar o diálogo devolve a leitura ao mesmo ponto do texto
    dialogo.get_by_role("button", name="Close").tap()
    expect(dialogo).to_be_hidden(timeout=10000)
    page.wait_for_timeout(500)
    topo = page.locator("[data-id='art-5-par-1']").bounding_box()["y"]
    assert 0 <= topo < alt, f"o dispositivo consultado saiu da tela ao fechar o diálogo: y={topo:.0f}"
    print("4. fechar o diálogo preserva o ponto de leitura")

    # 5. seleção de trecho e botão flutuante, acionado por toque
    page.evaluate(
        """() => {
          const no = (id) => [...document.querySelector(`[data-id='${id}']`).childNodes]
              .filter(n => n.nodeType === 3 && n.textContent.trim()).pop();
          const r = document.createRange();
          r.setStart(no('art-5-par-2'), 3); r.setEnd(no('art-5-par-2'), 60);
          const s = document.getSelection(); s.removeAllRanges(); s.addRange(r);
        }"""
    )
    page.wait_for_timeout(500)
    botao = page.locator(".pl-sel-btn")
    expect(botao).to_be_visible()
    cb = botao.bounding_box()
    assert cb["x"] >= 0 and cb["x"] + cb["width"] <= page.viewport_size["width"], f"botão fora da tela: {cb}"
    botao.tap()
    expect(dialogo).to_be_visible(timeout=15000)
    expect(dialogo).to_contain_text("Art. 5º, § 2º")
    print("5. seleção de trecho e botão flutuante por toque")

    # 6. "Ir para" leva a página ao artigo, abaixo do cabeçalho fixo
    dialogo.get_by_role("button", name="Close").tap()
    expect(dialogo).to_be_hidden(timeout=10000)
    page.evaluate("document.getSelection().removeAllRanges()")
    caixa = page.get_by_role("combobox", name="Ir para")
    caixa.scroll_into_view_if_needed()
    caixa.click()
    caixa.fill("Art. 34")
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    y = page.locator("[data-id='art-34']").bounding_box()["y"]
    assert 40 <= y < alt * 0.6, f"o art. 34 deveria estar no alto da tela: y={y:.0f}"
    if PASTA:
        page.screenshot(path=f"{PASTA}/cel_{APARELHO}_3_navegacao.png")
    print("6. navegação pelo índice")

    assert not erros, erros
    nav.close()
print(f"celular ({APARELHO}): todos os testes passaram")
