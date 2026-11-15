"""Testes do explicador: recuperação do relatório, montagem do pedido, cache e chamada.
Rodar com: python tests/test_explicador.py"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from explicador import (INTENCOES, LIMITE_MATERIAL, MODELO_PADRAO, Armazem, Relatorio,  # noqa: E402
                        chaves_da_selecao, fluxo_api, preparar)
from leitor import Corpus, validar  # noqa: E402

c = Corpus.carregar(RAIZ / "corpus.json")
r = Relatorio.carregar(RAIZ / "relatorio.json")


def disp(id_):
    return validar(c, {"modo": "dispositivo", "inicio": id_})


def ped(id_, intencao="simples"):
    return preparar(c, r, disp(id_), intencao, MODELO_PADRAO)


# dispositivo do projeto: recebe o comentário ao seu artigo, e só ele
p = ped("art-5-par-1")
assert p.numeros == list(range(58, 65)), p.numeros
assert "§ 60. O § 1º separa custódia e ilicitude" in p.usuario
assert "<dispositivos>Art. 5º, § 1º</dispositivos>" in p.usuario

# alínea dentro do texto do Código Penal: comentário ao art. 154-A mais a parte geral do art. 41
assert chaves_da_selecao(c, ["art-41-cp-154-A-par-1-inc-2-ali-a"]) == ["art-41-cp-154-A", "art-41"]
p = ped("art-41-cp-154-A-par-1-inc-2-ali-a")
assert p.numeros[:3] == [174, 175, 176] and 191 in p.numeros and 192 not in p.numeros, p.numeros

# rubrica do tipo penal leva ao artigo que ela nomeia
rub = next(u["id"] for u in c.unidades if u["tipo"] == "rubrica" and u["texto"].endswith("Falsidade informática"))
assert "art-41-cp-306-A" in chaves_da_selecao(c, [rub])

# artigo da Lei 9.296 alterado pelo art. 42: comentário ao art. 42
assert ped("art-42-l9296-10-par-2").numeros == list(range(229, 234))

# cada intenção recebe as partes que lhe cabem
assert set(ped("art-5", "simples").material) == {"comentario"}
assert set(ped("art-5", "racional").material) == {"comentario", "escolhas"}
assert 245 in ped("art-5", "budapeste").numeros
caso = ped("art-41-cp-154-C", "caso")
assert {"comentario", "fronteira", "fenomenos"} <= set(caso.material) and 303 in caso.numeros and 291 in caso.numeros

# capítulo e preâmbulo não têm comentário próprio, e o pedido diz isso ao modelo
p = ped("cap-1")
assert not p.material and "não traz comentário específico" in p.usuario

# o teto de material vale para qualquer dispositivo e intenção
for u in c.unidades:
    if u["tipo"] == "omissao":
        continue
    for k in INTENCOES:
        q = ped(u["id"], k)
        assert sum(len(x["texto"]) for ps in q.material.values() for x in ps) <= LIMITE_MATERIAL

# o prefixo de sistema é idêntico entre pedidos (condição do cache de prompt) e leva o texto e as noções
a, b = ped("art-5-par-1"), ped("art-34", "caso")
assert a.sistema == b.sistema
assert "Art. 45. Esta Lei entra em vigor" in a.sistema and "Resumo criptográfico (hash)" in a.sistema
assert "O § 1º separa custódia" not in a.sistema, "o comentário aos artigos não deve ir para o prefixo"
print(f"prefixo de sistema: {len(a.sistema)} caracteres; pedido típico: {len(a.usuario)} caracteres")

# chave do cache: muda com a intenção e com o trecho, não muda entre chamadas iguais
assert ped("art-5-par-1").chave == a.chave
assert ped("art-5-par-1", "caso").chave != a.chave and ped("art-5-par-2").chave != a.chave

# armazenamento: respostas e contador diário
with tempfile.TemporaryDirectory() as d:
    arm = Armazem(Path(d) / "x" / "t.sqlite")
    assert arm.obter(a.chave) is None and arm.chamadas_hoje() == 0
    arm.guardar(a.chave, "resposta")
    arm.contar_chamada(); arm.contar_chamada()
    assert arm.obter(a.chave) == "resposta" and arm.chamadas_hoje() == 2
    assert Armazem(Path(d) / "x" / "t.sqlite").obter(a.chave) == "resposta"   # persiste entre reinícios


# chamada à API com cliente falso: confere o formato do pedido sem gastar nem depender de chave
class _Fluxo:
    text_stream = ["Olá", ", ", "mundo"]
    def __enter__(self): return self
    def __exit__(self, *a): return False

class _Mensagens:
    def stream(self, **kw):
        self.kw = kw
        return _Fluxo()

class _Cliente:
    messages = _Mensagens()

cli = _Cliente()
assert "".join(fluxo_api(cli, MODELO_PADRAO, a)) == "Olá, mundo"
kw = cli.messages.kw
assert kw["model"] == "claude-sonnet-5-5" and "temperature" not in kw and "top_p" not in kw
assert kw["system"] == [{"type": "text", "text": a.sistema, "cache_control": {"type": "ephemeral"}}]
assert kw["messages"] == [{"role": "user", "content": a.usuario}]

print("explicador: todos os testes passaram")
