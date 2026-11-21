"""Testes unitarios do extrator (funcoes puras, sem PDF, sem rede, sem docker).

Rodar da raiz do projeto:  python -m pytest ingestion/testes -q
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import classificacao as cl  # noqa: E402
import cursos  # noqa: E402
import extrair as ex  # noqa: E402
import matriz2025 as mz  # noqa: E402


def L(*textos, pag=1):
    """Monta a lista [(pagina, linha)] que o extrator usa."""
    return [(pag, t) for t in textos]


# ----------------------------------------------------------------------------- limpeza de texto
def test_ligaturas_quebradas_sao_coladas():
    assert ex.corrigir_ligaturas("questi onario") == "questionario"


def test_texto_normal_nao_e_ilegivel():
    assert not ex.ilegivel("Assinale a opção correta sobre o texto apresentado na questão anterior, " * 3)


def test_fonte_sem_mapeamento_e_ilegivel():
    assert ex.ilegivel("ƚƌĞĐŚŽĚĂŵƷƐŝĐĂŶŽƐĂŝůĞƐĚĂsŝĚĂĚĞDŝůƚŽŶEĂƐĐŝŵĞŶƚŽƚŽĚŽĂƌƟƐƚĂƚĞŵĚĞŝƌĂŽŶĚĞŽƉŽǀŽ")


def test_texto_curto_nao_e_julgado():
    assert not ex.ilegivel("ƚƌĞ")


# ----------------------------------------------------------------------------- numero de questao lido por OCR
@pytest.mark.parametrize("lido,esperado", [("05", 5), ("OS", 5), ("O8", 8), ("l2", 12), ("155", 15), ("35", 35)])
def test_numero_ocr_corrige_confusoes(lido, esperado):
    assert ex._numero_ocr(lido) == esperado


# ----------------------------------------------------------------------------- blocos (1 bloco por questao)
def test_blocos_divide_por_titulo():
    linhas = L(" QUESTÃO 01", "enunciado um", " QUESTÃO 02", "enunciado dois", " QUESTÃO DISCURSIVA 3", "disc")
    bs = ex.blocos(linhas)
    assert [(b["num"], b["disc"]) for b in bs] == [(1, False), (2, False), (3, True)]
    assert [x for _, x in bs[0]["linhas"]] == ["enunciado um"]


def test_blocos_ignora_questionario_de_percepcao():
    linhas = L(" QUESTÃO 01", "a", " QUESTÃO 02", "b", " QUESTIONÁRIO DE PERCEPÇÃO", " QUESTÃO 01", "c")
    assert [b["num"] for b in ex.blocos(linhas)] == [1, 2]


def test_blocos_numeracao_que_reinicia_encerra_a_prova():
    linhas = L(" QUESTÃO 01", "a", " QUESTÃO 02", "b", " QUESTÃO 01", "intruso")
    assert [b["num"] for b in ex.blocos(linhas)] == [1, 2]


def test_blocos_titulo_de_ocr_com_ruido_so_vale_em_modo_ocr():
    linhas = L(" QUESTÃO 03", "a", " QUESTÃO OS", "b")
    assert [b["num"] for b in ex.blocos(linhas)] == [3]
    assert [b["num"] for b in ex.blocos(linhas, ocr=True)] == [3, 5]


def test_blocos_titulo_ocr_fora_de_sequencia_e_ignorado():
    linhas = L(" QUESTÃO 03", "a", " QUESTÃO O9", "b")  # lido com ruido e salto grande (3 -> 9): descartado
    assert [b["num"] for b in ex.blocos(linhas, ocr=True)] == [3]
    linhas = L(" QUESTÃO 03", "a", " QUESTÃO O5", "b")  # ruido, mas e a sequencia (3 -> 5): aceito
    assert [b["num"] for b in ex.blocos(linhas, ocr=True)] == [3, 5]


def test_blocos_titulo_lido_duas_vezes_fica_um():
    linhas = L(" QUESTÃO 09", " QUESTÃO 09", "texto")
    assert [b["num"] for b in ex.blocos(linhas, ocr=True)] == [9]


# ----------------------------------------------------------------------------- alternativas
def test_alternativas_com_letras():
    corpo = L("Pergunta?", "A primeira", "B segunda", "C terceira", "D quarta", "E quinta")
    ini, alts = ex.alternativas(corpo)
    assert ini == 1 and list(alts) == list("ABCDE") and alts["C"] == "terceira"


def test_alternativas_quatro_opcoes_sao_aceitas():
    ini, alts = ex.alternativas(L("?", "A um", "B dois", "C tres", "D quatro"))
    assert list(alts) == list("ABCD")


def test_alternativas_continuacao_de_linha():
    _, alts = ex.alternativas(L("A começa", "e continua", "B b", "C c", "D d", "E e"))
    assert alts["A"] == "começa e continua"


def test_sem_alternativas_devolve_vazio():
    assert ex.alternativas(L("so enunciado", "outra linha")) == (None, {})


def test_alternativas_por_bolinha_em_ocr():
    corpo = L("Assinale a opção correta.", "O um", "O dois", "O tres", "O quatro", "O cinco")
    ini, alts = ex.alternativas(corpo, permitir_bolinha=True)
    assert ini == 1 and alts["A"] == "um" and alts["E"] == "cinco"


def test_bolinha_so_vale_se_for_prova_escaneada():
    corpo = L("Assinale a opção correta.", "O um", "O dois", "O tres", "O quatro", "O cinco")
    assert ex.alternativas(corpo, permitir_bolinha=False) == (None, {})


def test_alternativas_com_bolinha_ruidosa_e_rodape():
    corpo = L("É correto apenas o que se afirma em", "O", "I, apenas.", "OQ II, apenas.", "Olelll, apenas.",
              "(D) II e III, apenas.", "O I, II e III.", "SISTEMAS DE INFORMAÇÃO", "EXAME NACIONAL DE DESEMPENHO")
    ini, alts = ex.alternativas(corpo, permitir_bolinha=True)
    assert len(alts) == 5
    assert "SISTEMAS" not in alts["E"] and "EXAME" not in alts["E"]


# ----------------------------------------------------------------------------- texto-base x enunciado
def test_separar_texto_usa_ultima_referencia():
    linhas = L(" Texto do jornal sobre o clima.", " Disponível em: <http://x.org>. Acesso em: 4 ago. 2014.",
               " A partir do texto, avalie.")
    base, enun = ex.separar_texto(linhas)
    assert "Disponível em" in base and enun == "A partir do texto, avalie."


def test_separar_texto_sem_referencia_nao_tem_base():
    base, enun = ex.separar_texto(L(" Apenas um enunciado."))
    assert base == "" and enun == "Apenas um enunciado."


# ----------------------------------------------------------------------------- gabarito em grade (2025)
def test_gabarito_em_grade():
    toks = "1 2 3 4 5 C A D B ANULADA".split()
    assert ex._gabarito_em_grade(toks) == {1: "C", 2: "A", 3: "D", 4: "B", 5: "ANULADA"}


def test_gabarito_em_grade_ignora_bloco_inconsistente():
    assert ex._gabarito_em_grade("1 2 3 C A".split()) == {}


# ----------------------------------------------------------------------------- cursos
def test_norm_e_slug():
    assert cursos.norm("Ciências_Contábeis.pdf") == "ciencias contabeis"
    assert cursos.slug_de("Engenharia de Computação") == "engenharia-computacao"


@pytest.mark.parametrize("nome,area", [("Enfermagem", "Saúde"), ("Sistemas de Informação", "Computação e Tecnologia da Informação"),
                                       ("Curso Inventado", "Outras áreas")])
def test_area_do_curso(nome, area):
    assert cursos.area_do_curso(nome) == area


def test_grau():
    assert cursos.grau_de("2021_PV_licenciatura_filosofia.pdf", "") == "Licenciatura"
    assert cursos.grau_de("x.pdf", "Tecnologia em Redes") == "Tecnólogo"
    assert cursos.grau_de("x.pdf", "Direito") == "Bacharelado"


def test_titulo_mantem_artigos_em_minuscula():
    assert cursos._titulo("ENGENHARIA DE COMPUTACAO") == "Engenharia de Computacao"


def test_pareamento_ignora_ano_e_prefixos():
    assert cursos.chave_pareamento("2023_PV_biomedicina.pdf") == cursos.chave_pareamento("2023_GB_biomedicina.pdf")


def test_pareamento_expande_abreviacao():
    assert cursos.chave_pareamento("gesta_rh.pdf") == cursos.chave_pareamento("gestao_recursos.pdf")


def test_melhor_par_escolhe_o_mesmo_curso():
    prova = Path("2022_PV_direito.pdf")
    cands = [Path("2022_GB_direito.pdf"), Path("2022_GB_psicologia.pdf")]
    assert cursos.melhor_par(prova, cands) == cands[0]


def test_melhor_par_recusa_quando_ambiguo_ou_distante():
    prova = Path("2022_PV_xyz.pdf")
    assert cursos.melhor_par(prova, [Path("2022_GB_abc.pdf")]) is None


def test_registro_conhecido_devolve_campos_completos():
    c = cursos.do_registro("2023_PV_biomedicina.pdf")
    assert c and {"slug", "curso", "grau", "area", "origem"} <= set(c) and c["origem"] == "registro"


# ----------------------------------------------------------------------------- matriz oficial de 2025
V1 = {1: {"gabarito": "A"}, 2: {"gabarito": "B"}, 3: {"gabarito": "C"}}
V2 = {1: {"gabarito": "A"}, 2: {"gabarito": "E"}, 3: {"gabarito": "E"}}


def test_escolhe_versao_que_concorda_com_o_gabarito():
    assert mz.escolher_versao([V2, V1], {1: "A", 2: "B", 3: "C"}) is V1
    assert mz.escolher_versao([], {1: "A"}) is None


def test_concordancia():
    assert mz.concordancia(V1, {1: "A", 2: "B", 3: "C"}) == 1.0
    assert mz.concordancia(V2, {1: "A", 2: "B", 3: "C"}) == pytest.approx(1 / 3)
    assert mz.concordancia({}, {1: "A"}) == 0.0


# ----------------------------------------------------------------------------- classificador de competencias
def test_tokens_removem_acento_paradas_e_palavras_curtas():
    t = cl.tokens("A Educação ambiental, para todos os cidadãos!")
    assert "educaca" in t and "ambient" in t and "para" not in t and "os" not in t


def _q(ano, comp, enun, competencia=None):
    return {"ano": ano, "componente": comp, "enunciado": enun, "texto_base": "", "alternativas": {},
            "competencias": [competencia] if competencia else []}


def test_naive_bayes_aprende_palavras_discriminantes():
    nb = cl.NaiveBayes([(cl.tokens("clima ambiente sustentabilidade floresta"), "C01"),
                        (cl.tokens("clima poluicao ambiente reciclagem"), "C01"),
                        (cl.tokens("contrato empresa mercado lucro"), "C02"),
                        (cl.tokens("mercado empresa gestao orcamento"), "C02")])
    assert nb.prever(cl.tokens("floresta e ambiente")) == "C01"
    assert nb.prever(cl.tokens("orcamento da empresa")) == "C02"


def test_treino_usa_so_fg_de_2025_sem_repeticao():
    qs = [_q(2025, "FG", "mesma questao", "FG_C01. A"), _q(2025, "FG", "mesma questao", "FG_C01. A"),
          _q(2025, "CE", "especifica", "CE_C01. B"), _q(2023, "FG", "antiga")]
    amostras, rotulos = cl.treino_2025(qs)
    assert len(amostras) == 1 and rotulos == {"FG_C01": "FG_C01. A"}


def test_loo_devolve_acuracia_e_linha_de_base():
    amostras = [(cl.tokens("floresta clima ambiente"), "A"), (cl.tokens("floresta ambiente solo"), "A"),
                (cl.tokens("empresa mercado lucro"), "B"), (cl.tokens("empresa lucro gestao"), "B")]
    acc, base = cl.loo(amostras)
    assert 0 <= acc <= 1 and base == 0.5
