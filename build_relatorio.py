"""Build do índice do relatório explicativo: um registro por parágrafo numerado, com as
chaves dos dispositivos a que ele se refere.

Uso:
    python build_relatorio.py fonte/relatorio_explicativo_v3-4.md corpus.json relatorio.json

A recuperação no app é determinística: dado o dispositivo selecionado, o explicador recebe
os parágrafos cujas chaves o alcançam. Não há busca vetorial, porque o corpus é fechado e
o próprio relatório já está organizado por artigo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PARTES = {"I": "introducao", "II": "gerais", "III": "comentario", "IV": "escolhas",
          "V": "nocoes", "VI": "fenomenos", "VII": "fronteira"}
RE_PARTE = re.compile(r"^## ([IVX]+)\. (.+)$")
RE_GRUPO = re.compile(r"^### (.+)$")
RE_ARTS = re.compile(r"^#### Artigos? (.+?) \(.+\)$")
RE_PAR = re.compile(r"^(\d+)\. (.+)$")
RE_TITULO = re.compile(r"^\*\*(.+?)\*\*")
RE_PARENTESES = re.compile(r"\(([^()]*)\)\.?$")


def numeros(seg: str) -> list[str]:
    """Lê uma lista de artigos como "5º e 23 a 26" ou "154-C e 154-D" e devolve os números."""
    saida: list[str] = []
    for a, b in re.findall(r"(?<![\d-])(\d+)º?\s+a\s+(\d+)º?(?![\d-])", seg):
        saida += [str(k) for k in range(int(a), int(b) + 1)]
    saida += [n for n in re.findall(r"\d+(?:-[A-Z])?", seg) if n not in saida]
    return saida


def chaves_da_citacao(cit: str, ids: set[str], alterador: str | None = None) -> list[str]:
    """Converte a citação de um título ("arts. 5º e 23 a 26", "Código Penal, art. 154-A, caput")
    em identificadores do corpus. Só devolve chaves que existem no corpus.

    A leitura de cada lista para no primeiro "§": em "art. 15, §§ 3º a 6º" o intervalo
    é de parágrafos, e sem a parada viraria os arts. 3º a 6º.
    """
    if "Convenção" in cit:
        return []
    saida: list[str] = []
    for m in re.finditer(r"arts?\.\s+([^§()]*)", cit):
        for n in numeros(m[1]):
            if "9.296" in cit:
                chave = f"art-42-l9296-{n}"
            elif "-" in n or int(n) > 45:
                chave = f"art-41-cp-{n}"       # numeração do Código Penal
            else:
                chave = f"art-{n}"
            if chave in ids and chave not in saida:
                saida.append(chave)
    if alterador:  # dentro do comentário a um artigo alterador, só interessam os artigos da lei alterada
        saida = [c for c in saida if c.startswith(alterador + "-")]
    return saida


def indexar(md: str, ids: set[str]) -> list[dict]:
    paragrafos: list[dict] = []
    parte = grupo = ""
    arts: list[str] = []      # artigos do projeto comentados na seção corrente
    sub: list[str] = []       # artigo da lei alterada em comentário (dentro dos arts. 41 a 43)
    for linha in md.splitlines():
        linha = linha.strip()
        if m := RE_PARTE.match(linha):
            parte, grupo, arts, sub = PARTES[m[1]], "", [], []
        elif m := RE_ARTS.match(linha):
            arts, sub = [f"art-{n}" for n in numeros(m[1])], []
            faltam = [a for a in arts if a not in ids]
            if faltam:
                raise ValueError(f"o relatório comenta artigo que não existe no corpus: {faltam}")
        elif m := RE_GRUPO.match(linha):
            grupo = m[1]
        elif m := RE_PAR.match(linha):
            n, texto = int(m[1]), m[2]
            t = RE_TITULO.match(texto)
            titulo = t[1].rstrip(".") if t else ""
            cit = RE_PARENTESES.search(titulo)
            chaves: list[str] = []
            if parte == "comentario":
                if cit and len(arts) == 1:
                    novo = chaves_da_citacao(cit[1], ids, alterador=arts[0])
                    if novo:
                        sub = novo
                chaves = sub or arts
            elif parte in ("escolhas", "fronteira") and cit:
                chaves = chaves_da_citacao(cit[1], ids)
            elif parte == "fenomenos":
                # os fenômenos não trazem artigo no título; valem os tipos penais citados no corpo
                for num in re.findall(r"art\. (\d+-[A-Z]|171)(?![\d-])", texto):
                    chave = f"art-41-cp-{num}"
                    if chave in ids and chave not in chaves:
                        chaves.append(chave)
                if re.search(r"art\. 10, § 2º, da Lei nº 9\.296", texto) and "art-42-l9296-10" in ids:
                    chaves.append("art-42-l9296-10")
            paragrafos.append({"n": n, "parte": parte, "grupo": grupo, "titulo": titulo,
                               "chaves": chaves, "texto": texto})
    return paragrafos


def verificar(paragrafos: list[dict], unidades: list[dict]) -> list[str]:
    problemas: list[str] = []
    ns = [p["n"] for p in paragrafos]
    if ns != list(range(1, len(ns) + 1)):
        problemas.append("parágrafos do relatório fora de sequência")
    cobertos = {c for p in paragrafos if p["parte"] == "comentario" for c in p["chaves"]}
    for u in unidades:
        if u["tipo"] != "artigo":
            continue
        # o artigo da lei alterada pode estar coberto pelo comentário ao artigo alterador (arts. 42 e 43)
        if u["id"] not in cobertos and not (u["citado"] and u["pai"] in cobertos):
            problemas.append(f"artigo sem comentário no relatório: {u['id']}")
    return problemas


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fonte", type=Path)
    ap.add_argument("corpus", type=Path)
    ap.add_argument("saida", type=Path)
    args = ap.parse_args()

    bruto = args.fonte.read_bytes()
    unidades = json.loads(args.corpus.read_text(encoding="utf-8"))["unidades"]
    paragrafos = indexar(bruto.decode("utf-8"), {u["id"] for u in unidades})
    problemas = verificar(paragrafos, unidades)
    for pb in problemas:
        print("PROBLEMA:", pb, file=sys.stderr)
    if problemas:
        sys.exit(f"{len(problemas)} problema(s); índice não gerado")

    saida = {
        "meta": {
            "titulo": "Relatório explicativo da redação consolidada do PL 4939/2020",
            "fonte": args.fonte.name,
            # hash do arquivo de origem: é o mesmo número de versão que o projeto atribui ao documento
            "sha256": hashlib.sha256(bruto).hexdigest(),
            "paragrafos": len(paragrafos),
        },
        "paragrafos": paragrafos,
    }
    args.saida.write_text(json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    por_parte: dict[str, int] = {}
    for p in paragrafos:
        por_parte[p["parte"]] = por_parte.get(p["parte"], 0) + 1
    print(f"{len(paragrafos)} parágrafos, sha256 {saida['meta']['sha256'][:12]}", file=sys.stderr)
    print(", ".join(f"{k}: {v}" for k, v in por_parte.items()), file=sys.stderr)


if __name__ == "__main__":
    main()
