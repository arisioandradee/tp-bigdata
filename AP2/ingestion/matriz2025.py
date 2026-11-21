"""Matriz de prova do Enade 2025 (arquivos `2025_MP_<curso>.pdf`): metadados OFICIAIS por questao (RF05).

Cada matriz traz uma tabela com: numero do item na prova, gabarito, competencia, habilidade e ate dois objetos
de conhecimento. Os codigos `FG_...` sao da Formacao Geral; os sem prefixo, do Componente Especifico.

O layout muda de curso para curso (colunas deslocadas, cabecalho quebrado em varias linhas, mais de uma versao do
caderno no mesmo arquivo). Por isso as celulas sao classificadas pelo CONTEUDO (letra de gabarito, C01., H03.,
OC04.) e nao pela posicao, e a versao do caderno e escolhida pela concordancia com o gabarito oficial.
"""
import re

import pymupdf

_COD = r"((?:FG[\s_]*)?(?:{})\d{{2}}\.\s?.*)"
RX = {"comp": re.compile(_COD.format("C")), "hab": re.compile(_COD.format("H")), "oc": re.compile(_COD.format("OC"))}
RX_GAB = re.compile(r"^(?:[A-E]|ANULAD[OA])$", re.I)


def _limpa(c):
    return " ".join((c or "").replace("_", " ").replace("\n", " ").split())


def _extrai(tipo, celula, cortar_em_dois_pontos=False):
    """Pega o texto a partir do codigo (ignora lixo de quebra de pagina antes dele): 'FG_C02. Competencia ...'."""
    m = RX[tipo].search(celula)
    if not m:
        return None
    t = re.sub(r"^(FG|CE)\s*", r"\1_", m.group(1).strip())
    t = re.sub(r"\s+", " ", t)
    if cortar_em_dois_pontos and ":" in t:
        t = t.split(":", 1)[0].strip()
    return t


def ler_versoes(caminho):
    """Lista de versoes do caderno; cada uma e {item: {gabarito, competencia, habilidade, objetos}}."""
    versoes, atual = [], {}
    for pg in pymupdf.open(caminho):
        for tb in pg.find_tables().tables:
            for row in tb.extract():
                cel = [_limpa(c) for c in row]
                n = next((int(c) for c in cel[:3] if re.fullmatch(r"\d{1,2}", c)), None)
                if n is None:
                    continue
                gab = next((c.upper() for c in cel if RX_GAB.match(c)), "")
                comp = next((x for c in cel if (x := _extrai("comp", c, True))), "")
                hab = next((x for c in cel if (x := _extrai("hab", c))), "")
                ocs = [x for c in cel if (x := _extrai("oc", c))]
                if not (gab or comp or hab or ocs):
                    continue
                if n in atual:  # o item reaparece: comecou outra versao do caderno
                    versoes.append(atual)
                    atual = {}
                atual[n] = {"gabarito": "ANULADA" if gab.startswith("ANULAD") else gab, "competencia": comp,
                            "habilidade": hab, "objetos": ocs}
    if atual:
        versoes.append(atual)
    return versoes


def escolher_versao(versoes, gabarito):
    """A versao cujo gabarito mais concorda com o gabarito oficial (`gabarito`: {item: letra}); None se nao houver."""
    if not versoes:
        return None
    def pontos(v):
        return sum(1 for n, m in v.items() if gabarito.get(n) == m["gabarito"])
    return max(versoes, key=lambda v: (pontos(v), len(v)))


def concordancia(versao, gabarito):
    """Fracao dos itens da versao cujo gabarito coincide com o gabarito oficial."""
    if not versao:
        return 0.0
    return sum(1 for n, x in versao.items() if gabarito.get(n) == x["gabarito"]) / len(versao)
