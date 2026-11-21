"""Cadastro de cursos: registro dos cursos conhecidos + cadastro automatico para os demais (RF01, RF05).

- Cursos do registro mantem slug, nome e area estaveis (os ids dos documentos nao mudam).
- Os demais sao identificados pelo nome impresso no cabecalho das paginas do proprio PDF; o slug vem do nome.
- A area e inferida por palavras do nome do curso (grandes areas parecidas com as da CAPES).
- Gabarito e padrao de resposta sao pareados com a prova pela semelhanca dos nomes de arquivo.
"""
import re
import unicodedata
from collections import Counter

import pymupdf

AREA_TI = "Computação e Tecnologia da Informação"
STOP = {"de", "da", "do", "das", "dos", "e", "em", "a", "o", "para"}

# (regex sobre o nome normalizado, slug, curso, grau padrao, area). A ordem importa: o mais especifico primeiro.
REGISTRO = [
    (r"medicina veterinaria|veterinaria", "medicina-veterinaria", "Medicina Veterinária", "Bacharelado", "Saúde"),
    (r"biomedicina", "biomedicina", "Biomedicina", "Bacharelado", "Saúde"),
    (r"\bmedicina\b", "medicina", "Medicina", "Bacharelado", "Saúde"),
    (r"enfermagem", "enfermagem", "Enfermagem", "Bacharelado", "Saúde"),
    (r"engenharia (da |de )?comput", "engenharia-de-computacao", "Engenharia de Computação", "Bacharelado", AREA_TI),
    (r"engenharia civil", "engenharia-civil", "Engenharia Civil", "Bacharelado", "Engenharias"),
    (r"ciencia (da )?comput", "ciencia-da-computacao", "Ciência da Computação", "Bacharelado", AREA_TI),
    (r"sistema.*informa|sis informa", "sistemas-de-informacao", "Sistemas de Informação", "Bacharelado", AREA_TI),
    (r"analise.*desenv", "analise-e-desenvolvimento-de-sistemas", "Análise e Desenvolvimento de Sistemas",
     "Tecnólogo", AREA_TI),
    (r"gestao.*tecnologia.*informa", "gestao-da-tecnologia-da-informacao", "Gestão da Tecnologia da Informação",
     "Tecnólogo", AREA_TI),
    (r"redes", "redes-de-computadores", "Redes de Computadores", "Tecnólogo", AREA_TI),
    (r"direito", "direito", "Direito", "Bacharelado", "Ciências Sociais Aplicadas"),
    (r"administracao publica", "administracao-publica", "Administração Pública", "Bacharelado",
     "Ciências Sociais Aplicadas"),
    (r"administracao", "administracao", "Administração", "Bacharelado", "Ciências Sociais Aplicadas"),
    (r"contabeis", "ciencias-contabeis", "Ciências Contábeis", "Bacharelado", "Ciências Sociais Aplicadas"),
    (r"psicologia", "psicologia", "Psicologia", "Bacharelado", "Ciências Humanas"),
    (r"pedagogia", "pedagogia", "Pedagogia", "Licenciatura", "Ciências Humanas"),
    (r"filosofia", "filosofia", "Filosofia", "Bacharelado", "Ciências Humanas"),
]
REGISTRO = [(re.compile(rx), *resto) for rx, *resto in REGISTRO]

# area por palavras do nome (primeira que casar). Nomes normalizados: minusculas e sem acento.
AREAS = [
    ("Saúde", r"medicina|enfermagem|biomedicina|farmacia|fisioterapia|fonoaudiologia|nutricao|odontologia|"
              r"terapia ocupacional|educacao fisica|\bsaude\b|radiologia|estetica|gerontologia|podologia|optica|hospitalar"),
    (AREA_TI, r"comput|informacao|software|redes de|analise e desenvolvimento|jogos digitais|"
              r"seguranca da informacao|banco de dados|sistemas para internet"),
    ("Engenharias", r"engenharia|arquitetura|urbanismo|mecatronica|automacao|construcao|saneamento|mecanica|"
                    r"eletrica|eletronica|producao industrial|seguranca (no |do )?trabalho"),
    ("Ciências Agrárias", r"agronomia|zootecnia|agronegocio|florestal|agricultura|pecuaria|aquicultura|silvicultura|"
                          r"cafeicultura|cooperativismo"),
    ("Ciências Biológicas", r"biologia|biologicas|biotecnologia"),
    ("Ciências Exatas e da Terra", r"matematica|fisica|quimica|estatistica|geologia|oceanografia|meteorologia"),
    ("Ciências Humanas", r"pedagogia|psicologia|filosofia|historia|geografia|sociologia|ciencias sociais|teologia|"
                         r"religiao|\beducacao\b|licenciatura"),
    ("Linguística, Letras e Artes", r"letras|\bartes\b|musica|teatro|danca|cinema|design|fotografia|moda"),
    ("Ciências Sociais Aplicadas", r"direito|administracao|contab|econom|jornalismo|publicidade|comunicacao|"
                                   r"relacoes internacionais|turismo|secretariado|gestao|logistica|marketing|"
                                   r"servico social|negocios|comercio|financ|recursos humanos|hotelaria|gastronomia|"
                                   r"eventos|processos gerenciais|seguranca publica|defesa"),
]
AREAS = [(a, re.compile(rx)) for a, rx in AREAS]
RUIDO_CABECALHO = re.compile(r"quest|rascunho|area livre|valid|^\*r|texto|enade|inep|instituto|prova|"
                             r"formacao|componente|discursiv|pagina|assinale|considere|^\d+$", re.I)


def norm(nome):
    t = unicodedata.normalize("NFKD", nome.lower()).encode("ascii", "ignore").decode()
    t = re.sub(r"\.pdf$", "", t)
    return re.sub(r"[_\-.\s]+", " ", t).strip()


def slug_de(nome):
    return "-".join(t for t in norm(nome).split() if t not in STOP)


def area_do_curso(nome):
    n = norm(nome)
    for area, rx in AREAS:
        if rx.search(n):
            return area
    return "Outras áreas"


def _titulo(nome):
    """'ENGENHARIA ELETRICA' -> 'Engenharia Elétrica' (mantem acentos; artigos e preposicoes em minuscula)."""
    nome = " ".join(nome.split())
    if not nome.isupper():
        return nome
    return " ".join(w if (i and w in STOP) else w.capitalize() for i, w in enumerate(nome.lower().split()))


def nome_no_cabecalho(pdf):
    """O nome do curso aparece em todas as paginas, junto do numero da pagina, no rodape ou no topo."""
    try:
        doc = pymupdf.open(pdf)
    except Exception:
        return None
    cont = Counter()
    for pg in list(doc)[2:16]:
        blocos = pg.get_text("blocks", sort=True)
        for b in blocos[:3] + blocos[-3:]:
            ls = [l.strip() for l in b[4].splitlines() if l.strip()]
            if len(ls) == 2 and ls[0].isdigit() and not ls[1].isdigit() and 3 <= len(ls[1]) <= 70 \
                    and not RUIDO_CABECALHO.search(norm(ls[1])):
                cont[ls[1]] += 1
    if not cont:
        return None
    nome, n = cont.most_common(1)[0]
    return _titulo(nome) if n >= 4 else None


def grau_de(arquivo, nome_curso):
    n = norm(arquivo) + " " + norm(nome_curso or "")
    if "licenciatura" in n:
        return "Licenciatura"
    if "tecnolog" in n or "tecnico" in n:
        return "Tecnólogo"
    return "Bacharelado"


def do_registro(nome_arquivo):
    n = norm(nome_arquivo)
    for rx, slug, curso, grau_padrao, area in REGISTRO:
        if rx.search(n):
            grau = "Licenciatura" if "licenciatura" in n else ("Bacharelado" if "bacharelado" in n else grau_padrao)
            suf = "" if grau == grau_padrao else "-" + grau.lower()  # ids antigos nao mudam
            return {"slug": slug + suf, "curso": curso, "grau": grau, "area": area, "origem": "registro"}
    return None


def info_curso(pdf):
    """Curso, grau e area de uma prova: registro conhecido ou cadastro automatico pelo cabecalho do PDF."""
    c = do_registro(pdf.name)
    if c:
        return c
    nome = nome_no_cabecalho(pdf)
    base = nome or " ".join(t.capitalize() for t in norm(re.sub(r"^\d{4}_|_pv(_\d+)?$", "", pdf.stem, flags=re.I)).split())
    grau = grau_de(pdf.name, base)
    nome_limpo = re.sub(r"\(.*?\)|bacharelado|licenciatura", "", base, flags=re.I).strip(" -")
    if grau == "Tecnólogo":
        nome_limpo = re.sub(r"^tecnologia\s+(em|de|da|do)?\s*", "", nome_limpo, flags=re.I).strip() or nome_limpo
        nome_limpo = nome_limpo[:1].upper() + nome_limpo[1:]
    slug = slug_de(nome_limpo) + ("-licenciatura" if grau == "Licenciatura" else "")
    return {"slug": slug, "curso": nome_limpo, "grau": grau, "area": area_do_curso(nome_limpo),
            "origem": "cabecalho" if nome else "arquivo"}


# ---------- pareamento de gabarito e padrao com a prova
_PREFIXOS = {"pv", "gb", "gab", "gabarito", "prova", "padrao", "resposta", "pr", "prd", "pad", "resp", "ledor",
             "ampliada", "libras", "mp", "cst"}
# abreviacoes que o INEP usa em alguns nomes de arquivo
ABREV = {"gesta": "gestao", "rh": "recursos", "tec": "tecnologia", "rel": "relacoes", "com": "comunicacao", "adm": "administracao", "eng": "engenharia", "ger": "gestao"}


def chave_pareamento(nome):
    toks = set()
    for t in norm(nome).split():
        if re.fullmatch(r"20\d{2}", t) or t in _PREFIXOS or t in STOP:
            continue
        t = ABREV.get(t, t)
        toks.add(t.rstrip("s") if len(t) > 4 else t)
    return toks


def jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def melhor_par(prova, candidatos, slug=None, minimo=0.4):
    """Arquivo de `candidatos` que corresponde a prova: mesmo curso do registro ou nome mais parecido."""
    if slug:
        achados = [c for c in candidatos if (r := do_registro(c.name)) and r["slug"] == slug]
        if achados:
            return achados[0]
    kp = chave_pareamento(prova.name)
    pontos = sorted(((jaccard(kp, chave_pareamento(c.name)), c) for c in candidatos), key=lambda x: -x[0])
    if not pontos or pontos[0][0] < minimo:
        return None
    if len(pontos) > 1 and pontos[1][0] >= minimo and pontos[0][0] - pontos[1][0] < 0.05:
        return None  # ambiguo: melhor nao parear do que parear com o gabarito de outro curso
    return pontos[0][1]
