"""Build do corpus: converte o texto limpo do PL (markdown do projeto) em JSON por dispositivo.

Uso:
    python build_corpus.py fonte/pl4939_v3-4_amostra.md corpus.json --versao "3.4" [--amostra]

O script roda fora do app. O app só lê o corpus.json, de modo que o texto exibido
e o texto contra o qual a seleção é validada são sempre o mesmo objeto, com hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Marcadores do markdown do projeto. Fora de citação, os rótulos vêm em negrito;
# dentro de citação (linhas iniciadas por ">"), vêm sem negrito e podem trazer aspas de abertura.
RE_CAP = re.compile(r"^## (CAPÍTULO ([IVXLCDM]+))$")
RE_SEC = re.compile(r"^### (Seção ([IVXLCDM]+))$")
RE_ART = re.compile(r"^\*\*(Art\. (\d+)[º.]?)\*\*\s+(.+)$")
RE_PAR = re.compile(r"^\*\*(§ (\d+)[º.]?|Parágrafo único\.)\*\*\s+(.+)$")
RE_NEGRITO = re.compile(r"^\*\*(.+)\*\*$")
RE_INC = re.compile(r"^([IVXLCDM]+) - (.+)$")
RE_ALI = re.compile(r"^([a-z])\) (.+)$")
RE_Q_ART = re.compile(r"^(“?Art\. (\d+(?:-[A-Z])?)[º.]?)\s+(.+)$")
RE_Q_PAR = re.compile(r"^(§ (\d+)[º.]?(?:-([A-Z]))?|Parágrafo único\.)\s+(.+)$")
RE_Q_PENA = re.compile(r"^(Pena -)\s+(.+)$")
RE_OMISSAO = re.compile(r"^\.{5,}")

# A lei alterada entra no identificador do dispositivo citado, para que
# "art. 10" da Lei 9.296 e "art. 10" do Marco Civil nunca colidam.
LEIS_ALTERADAS = [
    ("Decreto-Lei nº 2.848", "cp", "CP"),
    ("Lei nº 9.296", "l9296", "Lei 9.296/1996"),
    ("Lei nº 12.965", "l12965", "Lei 12.965/2014"),
]


def romano(s: str) -> int:
    val = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for a, b in zip(s, s[1:] + " "):
        total += -val[a] if b != " " and val[a] < val[b] else val[a]
    return total


def recortar_articulado(md: str) -> list[str]:
    """Descarta o histórico de versões (antes de '---') e a justificação (depois de '\\*\\*\\*')."""
    linhas = md.splitlines()
    if any(l.strip() == "---" for l in linhas):
        linhas = linhas[next(i for i, l in enumerate(linhas) if l.strip() == "---") + 1 :]
    for i, l in enumerate(linhas):
        if l.strip() in (r"\*\*\*", "***"):
            linhas = linhas[:i]
            break
    return linhas


def parse(md: str) -> list[dict]:
    unidades: list[dict] = []
    ids: set[str] = set()

    def add(id_, tipo, rotulo, texto, ref, nivel=0, citado=False, pai=None):
        if id_ in ids:
            raise ValueError(f"identificador duplicado: {id_}")
        ids.add(id_)
        unidades.append(
            {"id": id_, "tipo": tipo, "rotulo": rotulo, "texto": texto, "ref": ref,
             "nivel": nivel, "citado": citado, "pai": pai}
        )

    cap = sec = 0
    cap_rom = ""
    pre = 0                       # contador do preâmbulo
    aguarda_titulo = None         # id do capítulo ou seção cuja rubrica vem na linha seguinte
    art = par = inc = None        # dispositivo corrente fora de citação: (id, ref)
    q_base = None                 # (id, ref) do prefixo da lei alterada, fixado pelo artigo alterador
    q_art = q_par = q_inc = None  # dispositivo corrente dentro de citação
    q_rub = q_omis = 0

    for bruta in recortar_articulado(md):
        linha = bruta.strip()
        if not linha:
            continue

        # ---------- linhas citadas (texto da lei alterada) ----------
        if linha.startswith(">"):
            linha = linha[1:].strip()
            if not linha:
                continue
            if art is None or q_base is None:
                raise ValueError(f"citação fora de artigo alterador: {linha[:60]}")
            if RE_OMISSAO.match(linha):
                q_omis += 1
                add(f"{q_base[0]}-omis-{q_omis}", "omissao", "", linha, f"{q_base[1]}, linha de omissão",
                    citado=True, pai=(q_art or art)[0])
            elif m := RE_Q_ART.match(linha):
                q_art = (f"{q_base[0]}-{m[2]}", f"{q_base[1]}, art. {m[2]}")
                q_par = q_inc = None
                add(q_art[0], "artigo", m[1], m[3], q_art[1], citado=True, pai=art[0])
            elif (m := RE_Q_PAR.match(linha)) and q_art:
                if m[2]:
                    suf = f"{m[2]}" + (f"-{m[3]}" if m[3] else "")
                    q_par = (f"{q_art[0]}-par-{suf}", f"{q_art[1]}, § {m[2]}º" + (f"-{m[3]}" if m[3] else ""))
                else:
                    q_par = (f"{q_art[0]}-par-unico", f"{q_art[1]}, parágrafo único")
                q_inc = None
                add(q_par[0], "paragrafo", m[1], m[4], q_par[1], citado=True, pai=q_art[0])
            elif (m := RE_Q_PENA.match(linha)) and q_art:
                dono = q_par or q_art  # a pena pertence ao caput ou ao parágrafo, nunca ao inciso
                add(f"{dono[0]}-pena", "pena", m[1], m[2], f"{dono[1]}, pena", nivel=1, citado=True, pai=dono[0])
            elif (m := RE_INC.match(linha)) and q_art:
                dono = q_par or q_art
                q_inc = (f"{dono[0]}-inc-{romano(m[1])}", f"{dono[1]}, {m[1]}")
                add(q_inc[0], "inciso", f"{m[1]} -", m[2], q_inc[1], nivel=1, citado=True, pai=dono[0])
            elif (m := RE_ALI.match(linha)) and q_art:
                dono = q_inc or q_par or q_art
                add(f"{dono[0]}-ali-{m[1]}", "alinea", f"{m[1]})", m[2], f"{dono[1]}, {m[1]}",
                    nivel=2, citado=True, pai=dono[0])
            else:
                # rubrica do tipo penal ou cabeçalho de seção da lei alterada
                q_rub += 1
                add(f"{q_base[0]}-rub-{q_rub}", "rubrica", "", linha, f"{q_base[1]}, rubrica",
                    citado=True, pai=art[0])
            continue

        # ---------- linhas do próprio projeto ----------
        if m := RE_CAP.match(linha):
            cap, sec, cap_rom = romano(m[2]), 0, m[2]
            aguarda_titulo = f"cap-{cap}"
            add(aguarda_titulo, "capitulo", "", m[1], f"Capítulo {cap_rom}")
        elif m := RE_SEC.match(linha):
            sec = romano(m[2])
            aguarda_titulo = f"cap-{cap}-sec-{sec}"
            add(aguarda_titulo, "secao", "", m[1], f"Capítulo {cap_rom}, {m[1]}")
        elif m := RE_ART.match(linha):
            art = (f"art-{m[2]}", f"Art. {m[2]}" + ("º" if int(m[2]) < 10 else ""))
            par = inc = None
            q_art = q_par = q_inc = None
            q_rub = q_omis = 0
            q_base = None
            for chave, sigla, nome in LEIS_ALTERADAS:
                if chave in m[3] and "passa a vigorar" in m[3]:
                    q_base = (f"{art[0]}-{sigla}", f"{art[1]} · {nome}")
            add(art[0], "artigo", m[1], m[3], art[1])
        elif (m := RE_PAR.match(linha)) and art:
            if m[2]:
                par = (f"{art[0]}-par-{m[2]}", f"{art[1]}, § {m[2]}" + ("º" if int(m[2]) < 10 else ""))
            else:
                par = (f"{art[0]}-par-unico", f"{art[1]}, parágrafo único")
            inc = None
            add(par[0], "paragrafo", m[1], m[3], par[1], pai=art[0])
        elif (m := RE_INC.match(linha)) and art:
            dono = par or art
            inc = (f"{dono[0]}-inc-{romano(m[1])}", f"{dono[1]}, {m[1]}")
            add(inc[0], "inciso", f"{m[1]} -", m[2], inc[1], nivel=1, pai=dono[0])
        elif (m := RE_ALI.match(linha)) and art:
            dono = inc or par or art
            add(f"{dono[0]}-ali-{m[1]}", "alinea", f"{m[1]})", m[2], f"{dono[1]}, {m[1]}", nivel=2, pai=dono[0])
        elif (m := RE_NEGRITO.match(linha)) and aguarda_titulo:
            ref = unidades[-1]["ref"]
            add(f"{aguarda_titulo}-titulo", "titulo", "", m[1], f"{ref}, rubrica")
            aguarda_titulo = None
        elif art is None:
            pre += 1
            m = RE_NEGRITO.match(linha)
            add(f"pre-{pre}", "preambulo", "", m[1] if m else linha, "Preâmbulo")
        else:
            raise ValueError(f"linha não classificada depois de {art[1]}: {linha[:80]}")
    return unidades


def texto_plano(u: dict) -> str:
    """Texto do dispositivo como aparece na tela: rótulo, espaço, texto."""
    return f"{u['rotulo']} {u['texto']}" if u["rotulo"] else u["texto"]


def verificar(unidades: list[dict]) -> list[str]:
    """Conferência estrutural do texto dividido. Devolve a lista de problemas encontrados.

    Não substitui o confronto com o documento de origem, mas pega os erros típicos de
    cópia: dispositivo faltando ou repetido, aspas desencontradas, sinal trocado.
    """
    problemas: list[str] = []
    por_id = {u["id"]: u for u in unidades}
    filhos: dict[tuple, list[str]] = {}
    for u in unidades:
        filhos.setdefault((u["pai"], u["tipo"]), []).append(u["id"])

    # artigos do projeto em sequência contínua
    nums = [int(u["id"].split("-")[1]) for u in unidades if u["tipo"] == "artigo" and not u["citado"]]
    if nums != list(range(1, len(nums) + 1)):
        problemas.append(f"artigos fora de sequência: {nums}")

    for (pai, tipo), ids in filhos.items():
        if pai is None:
            continue
        citado = por_id[ids[0]]["citado"]
        sufixos = [i.rsplit("-", 1)[1] for i in ids]
        if tipo == "inciso" and [int(x) for x in sufixos] != list(range(1, len(ids) + 1)):
            problemas.append(f"incisos fora de sequência em {pai}: {sufixos}")
        if tipo == "alinea" and sufixos != [chr(97 + k) for k in range(len(ids))]:
            problemas.append(f"alíneas fora de sequência em {pai}: {sufixos}")
        # no texto das leis alteradas a sequência de parágrafos é interrompida por linhas de omissão
        if tipo == "paragrafo" and not citado and sufixos != ["unico"]:
            if "unico" in sufixos or [int(x) for x in sufixos] != list(range(1, len(ids) + 1)):
                problemas.append(f"parágrafos fora de sequência em {pai}: {sufixos}")

    inteiro = "\n".join(texto_plano(u) for u in unidades)
    if inteiro.count("“") != inteiro.count("”"):
        problemas.append(f"aspas desencontradas: {inteiro.count('“')} de abertura, {inteiro.count('”')} de fechamento")
    for sinal, nome in (('"', "aspas retas"), ("'", "apóstrofo reto"), ("°", "sinal de grau no lugar de º"),
                        ("  ", "espaço duplo"), (" ,", "espaço antes de vírgula"), (" ;", "espaço antes de ponto e vírgula"),
                        ("\u00a0", "espaço não separável"), ("–", "travessão curto"), ("—", "travessão")):
        for u in unidades:
            # o cabeçalho do gabinete traz travessão no original; fora do preâmbulo, é suspeito
            if sinal in texto_plano(u) and u["tipo"] != "preambulo":
                problemas.append(f"{nome} em {u['id']}")
    fim_ok = (".", ";", ":", "; ou", "” (NR)", "”")
    for u in unidades:
        if u["tipo"] in ("artigo", "paragrafo", "inciso", "alinea", "pena") and not u["texto"].endswith(fim_ok):
            problemas.append(f"pontuação final inesperada em {u['id']}: ...{u['texto'][-25:]!r}")
    return problemas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonte", type=Path)
    ap.add_argument("saida", type=Path)
    ap.add_argument("--versao", required=True)
    ap.add_argument("--amostra", action="store_true", help="marca o corpus como recorte parcial do texto")
    ap.add_argument("--tolerante", action="store_true", help="gera o corpus mesmo com problemas estruturais")
    ap.add_argument("--txt", type=Path, help="grava também o texto plano, para confronto com o documento de origem")
    args = ap.parse_args()

    unidades = parse(args.fonte.read_text(encoding="utf-8"))
    problemas = verificar(unidades)
    for pb in problemas:
        print("PROBLEMA:", pb, file=sys.stderr)
    if problemas and not args.tolerante:
        sys.exit(f"{len(problemas)} problema(s) estrutural(is); corpus não gerado (use --tolerante para gerar assim mesmo)")
    # O hash é calculado sobre o texto plano, não sobre o markdown, para que mudanças
    # de marcação que não alteram a redação não mudem a identidade da versão.
    canonico = "\n".join(texto_plano(u) for u in unidades)
    corpus = {
        "meta": {
            "titulo": "PL 4939/2020, redação consolidada (substitutivo)",
            "versao": args.versao,
            "amostra": args.amostra,
            "sha256": hashlib.sha256(canonico.encode("utf-8")).hexdigest(),
            "fonte": args.fonte.name,
            "unidades": len(unidades),
        },
        "unidades": unidades,
    }
    args.saida.write_text(json.dumps(corpus, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.txt:
        args.txt.write_text(canonico + "\n", encoding="utf-8")
    tipos: dict[str, int] = {}
    for u in unidades:
        tipos[u["tipo"]] = tipos.get(u["tipo"], 0) + 1
    print(f"{len(unidades)} unidades, sha256 {corpus['meta']['sha256'][:12]}", file=sys.stderr)
    print(", ".join(f"{k}: {v}" for k, v in sorted(tipos.items())), file=sys.stderr)


if __name__ == "__main__":
    main()
