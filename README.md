# PL 4939/2020: texto integral com explicação por IA

Sítio em Streamlit que exibe o texto integral da redação consolidada (v3.4), permite
selecionar um trecho e pede à IA, via API, que o explique com base no relatório explicativo.

## Rodar

    pip install -r requirements.txt
    streamlit run app.py

Sem chave de API o sítio funciona como leitor: ao selecionar um trecho, mostra o que o
relatório explicativo diz sobre o dispositivo. Com `ANTHROPIC_API_KEY` configurada (variável
de ambiente ou `.streamlit/secrets.toml`, ver o arquivo de exemplo), aparece o botão Explicar.

## Arquivos

- `fonte/pl4939_v3-4_articulado.md`: articulado da v3.4, na marcação do documento do projeto.
- `fonte/relatorio_explicativo_v3-4.md`: relatório explicativo, cópia do documento do projeto.
- `build_corpus.py`: gera `corpus.json` (um registro por dispositivo, com identificador
  estável e sha256 do texto) e confere a estrutura: sequência de artigos, parágrafos, incisos
  e alíneas, aspas, sinais suspeitos e pontuação final.
- `build_relatorio.py`: gera `relatorio.json` (um registro por parágrafo numerado do relatório,
  com as chaves dos dispositivos a que se refere) e confere que todo artigo tem comentário.
- `leitor.py`: componente v2 do leitor (HTML, CSS, JS), índice de navegação e validação da seleção.
- `explicador.py`: recuperação do material do relatório, montagem do pedido, cache de respostas,
  contador diário e chamada à API com cache de prompt.
- `app.py`: página, painel e cotas.
- `tests/`: validação, explicador e teste de ponta a ponta.

## Atualizar o texto ou o relatório

    python build_corpus.py fonte/pl4939_v3-4_articulado.md corpus.json --versao "3.4" \
        --txt fonte/pl4939_v3-4_texto_plano.txt
    python build_relatorio.py fonte/relatorio_explicativo_v3-4.md corpus.json relatorio.json

O build do corpus aceita o texto limpo inteiro do projeto: descarta o histórico de versões
(antes de `---`) e a justificação (depois de `\*\*\*`). Os dois builds param diante de problema
estrutural, em vez de publicar texto mal dividido. Mudou o texto, muda o sha256, e as respostas
guardadas da versão anterior deixam de ser usadas.

## Como a explicação é montada

- Prefixo de sistema, igual em todos os pedidos e marcado para cache de prompt: instruções,
  texto integral do projeto e a parte V do relatório (noções técnicas em linguagem comum).
- Mensagem: dispositivos alcançados, trecho selecionado e os parágrafos do relatório sobre o
  artigo. As intenções "racional" e "Budapeste" recebem também a parte IV (escolhas da redação);
  a intenção "caso", as partes VI e VII (fenômenos e casos de fronteira).
- A recuperação é determinística, pelo artigo do dispositivo. Não há busca vetorial.
- O painel sempre mostra os parágrafos do relatório enviados, para conferência do leitor.

## Instrução de uso e espera

O quadro "Como pedir a explicação de um trecho" fica acima do texto, dentro do próprio
componente, e reproduz os dois controles (o botão Explicar seleção e o ?) com a aparência
que têm no texto. Os botões ? ficam sempre à vista. Em tela larga a caixa do texto é
ajustada para terminar no pé da janela.

Enquanto o modelo raciocina, antes do primeiro trecho da resposta, o painel mostra uma barra
com os segundos decorridos. A API não informa quanto falta: a barra mede tempo, numa curva
que se aproxima do fim sem alcançá-lo, e some quando a resposta começa a chegar.

## Tela estreita

Abaixo de 640 px de largura o texto corre na própria página, sem caixa de rolagem interna,
alinhado à esquerda, e a explicação abre em diálogo sobre o texto. Nessa largura o Streamlit
empilha as colunas, e a coluna da explicação ficaria abaixo do texto inteiro, fora da vista.
O componente informa a largura a cada pedido, e o Python escolhe entre a coluna e o diálogo.

## Controles

- O servidor só aceita trecho que seja subcadeia do texto canônico.
- Não há pergunta livre: as intenções são fechadas.
- Resposta repetida (mesmo trecho, intenção, versão do texto, do relatório e do prompt) sai do
  cache em `dados/respostas.sqlite`, sem custo e sem consumir cota.
- Cota por sessão e por dia (`PL4939_COTA_SESSAO`, `PL4939_COTA_DIA`). O teto de gasto em dinheiro
  se define no console da API.
- O armazenamento guarda só a chave do pedido e a resposta. Nenhum dado de quem pergunta.

## Testes

    python tests/test_validacao.py
    python tests/test_explicador.py
    pip install -r requirements-dev.txt && python -m playwright install firefox webkit
    streamlit run app.py --server.headless true --server.port 8765 &
    python tests/e2e_selecao.py http://localhost:8765 "" chrome        # ou firefox, webkit
    python tests/e2e_celular.py http://localhost:8765 iphone           # ou pixel
    # com resposta simulada, para percorrer o botão Explicar e o cache:
    PL4939_SIMULAR=1 streamlit run app.py --server.headless true --server.port 8765 &
    python tests/e2e_selecao.py http://localhost:8765 "" chrome sim

## Pendências

- A chamada real à API não foi exercitada: faltava chave no ambiente de desenvolvimento.
  O formato do pedido foi conferido com cliente falso.
- O articulado em `fonte/` foi transcrito do documento do projeto e precisa ser confrontado
  com o original (use `fonte/pl4939_v3-4_texto_plano.txt` na comparação de documentos).
- A justificação ainda não é exibida.
- A intenção "o que muda em relação ao texto de 2020" depende de indexar por dispositivo o
  guia do relator e o texto original.
- Teste em aparelho de verdade (Safari no iOS e Chrome no Android) do gesto de seleção por
  pressão longa. A emulação cobre a largura da tela e o toque, não esse gesto.
