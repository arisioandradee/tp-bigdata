"""Extracao e segmentacao das provas ENADE (RF02-RF06).

Entrada : data/raw/<ano>/{prova,gabarito,padrao}/*.pdf
Saida   : data/processed/questoes.jsonl     (documentos validos)
          data/processed/rejeitadas.jsonl   (invalidos -> DLQ no Kafka)
          data/processed/relatorio.json     (contagens por PDF)

Uso: python extrair.py [--raw ../data/raw] [--out ../data/processed]
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

VERSAO = "0.3.0"
COBERTURA_MINIMA_OCR = 0.6  # com OCR por coluna nao ha mistura de questoes; abaixo disso o PDF inteiro e retido

from cursos import info_curso, melhor_par  # noqa: E402
from matriz2025 import concordancia, escolher_versao, ler_versoes  # noqa: E402

CACHE_OCR = Path(__file__).resolve().parent.parent / "data" / "cache" / "ocr"
CACHE_TAB = Path(__file__).resolve().parent.parent / "data" / "cache" / "tabelas"
# O OCR deixa lixo apos o cabecalho (linha horizontal vira "————"): aceita ate ~3 letras soltas
HEAD = re.compile(r"^\s*QUEST[ÃA]O\s+(DISCURSIVA\s+)?(\d{1,2})(?!\d)(?![A-Za-zÀ-ú]{4})", re.I)
BOLINHA = re.compile(r"^\s*(?:[O0QÓ©®●○◯@]{1,2})\s+(?=\S)")
BOLINHA_FROUXA = re.compile(r"^\s*(?:[O0QÓ©®●○◯@]{1,2}\s*$|[O0QÓ©®●○◯@]{1,2}\s*(?=\S)|\(\s*[A-E©®]\s*\)\s*)")
RODAPE_PROVA = re.compile(r"^\s*(?:SISTEMAS\s+D\w*|[A-ZÀ-Ú ]*INFORMA[ÇC][ÃA]O|EXAME NACIONAL.*|ESTUDANTES)\s*$")
QUESTIONARIO = re.compile(r"QUEST\s*I\s*ON[ÁA]RIO\s+DE\s+PERCEP", re.I)
LIGATURA = re.compile(r"(?<=\w)(ti|tí|fi|fí|fl|tt|ff)\s(?=[a-zà-ú])|\b(fi|fl|tt|ff)\s(?=[a-zà-ú])")
REFERENCIA = re.compile(r"(Dispon[ií]vel em|Acesso em|\(adaptado\)|\bp\.\s*\d|,\s*(19|20)\d{2}\.?\s*$)", re.I)
# a marca d'agua tem variantes (VALIDINEP, VALIDIN3P...) e aparece truncada no fim das linhas
MARCA_DAGUA = re.compile(r"(?:VALID\s*IN\w?P\s*\d{0,4}|E[NM]ADE\s*20\d{2})+", re.I)
RUIDO = re.compile(r"^\*R\d+\*$|^[ÁA]rea livre$|^RASCUNHO$|^\d{1,3}$", re.I)


CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
FONTE_RUIM = re.compile("[ƀ-˿̀-ͯϢ-Ͽ]")  # letras de fonte sem mapeamento Unicode


def corrigir_ligaturas(t):
    """O PDF quebra 'ti', 'fi', 'fl', 'tt' com espaco ('questi onario' -> 'questionario'), codifica a ligadura
    'ti' como 'Ɵ' ('invesƟmento') e a 'tt' como 'Ʃ' ('TwiƩer'), e deixa caracteres de controle no texto."""
    t = CONTROLE.sub("", t.replace("Ɵ", "ti").replace("Ʃ", "tt"))
    while True:
        n = LIGATURA.sub(lambda m: m.group(1) or m.group(2), t)
        if n == t:
            return n
        t = n


def ilegivel(t):
    """Fonte com ToUnicode quebrado gera simbolos fora do alfabeto latino."""
    t = t.replace("Ɵ", "").replace("Ʃ", "")  # ligaturas conhecidas (ver corrigir_ligaturas), nao sao lixo
    # pagina com um trecho corrompido no meio de texto bom (ex.: uma figura com fonte quebrada)
    if len(FONTE_RUIM.findall(t)) >= 15:
        return True
    letras = [c for c in t if c.isalpha()]
    if len(letras) < 40:
        return False
    ruins = sum(1 for c in letras if ord(c) > 0x17F)
    return ruins / len(letras) > 0.15


def _cel(c):
    return " ".join((c or "").replace("|", "/").replace("\n", " ").split())


def _tem_linhas_de_tabela(pg):
    """Pre-filtro barato: uma tabela tem varias linhas horizontais/verticais longas (a deteccao completa custa ~0,3 s/pagina)."""
    longas = 0
    for d in pg.get_drawings():
        r = d["rect"]
        if (r.width >= 40 and r.height <= 2.5) or (r.height >= 20 and r.width <= 2.5):
            longas += 1
            if longas >= 4:
                return True
    return False


def _tabelas_da_pagina(pg):
    """Tabelas reais da pagina como [(bbox, markdown, texto_simples)]. Descarta caixas com texto corrido (um enunciado
    dentro de um quadro nao e tabela), caixas de 1 celula e quadros vazios."""
    if not _tem_linhas_de_tabela(pg):
        return []
    saida = []
    area_pg = pg.rect.width * pg.rect.height
    for t in pg.find_tables().tables:
        x0, y0, x1, y1 = t.bbox
        if (x1 - x0) * (y1 - y0) > 0.6 * area_pg:
            continue
        linhas = [[_cel(c) for c in r] for r in t.extract()]
        linhas = [r for r in linhas if any(r)]
        if len(linhas) < 2:
            continue
        n = max(len(r) for r in linhas)
        if n < 2:
            continue
        linhas = [r + [""] * (n - len(r)) for r in linhas]
        celulas = [c for r in linhas for c in r if c]
        if max(len(c) for c in celulas) > 160 or any(re.search(r"QUEST[ÃA]O\s*\d", c, re.I) for c in celulas):
            continue  # texto corrido ou cabecalho de questao dentro de um quadro
        cheias = len(celulas)
        if cheias < 4 or cheias < 0.5 * len(linhas) * n:
            continue
        md = ["| " + " | ".join(linhas[0]) + " |", "|" + "---|" * n] + ["| " + " | ".join(r) + " |" for r in linhas[1:]]
        saida.append((t.bbox, "\n".join(md), " ".join(c for r in linhas for c in r if c)))
    return saida


def tabelas_do_pdf(caminho):
    """{pagina: [(bbox, markdown, texto)]} de todo o PDF, com cache em disco (a deteccao custa ~10 s por prova)."""
    caminho = Path(caminho)
    cache = CACHE_TAB / f"{caminho.stem}-{caminho.stat().st_size}.json"
    if cache.exists():
        return {int(k): [tuple(t) for t in v] for k, v in json.loads(cache.read_text(encoding="utf-8")).items()}
    res = {}
    for i, pg in enumerate(pymupdf.open(caminho), 1):
        try:
            t = _tabelas_da_pagina(pg)
        except Exception:  # noqa: BLE001
            t = []
        if t:
            res[i] = [(list(b), md, tx) for b, md, tx in t]
    CACHE_TAB.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    return res


def _sobreposicao(b, bbox):
    """Fracao da area do bloco b que cai dentro do retangulo bbox."""
    ix = max(0.0, min(b[2], bbox[2]) - max(b[0], bbox[0]))
    iy = max(0.0, min(b[3], bbox[3]) - max(b[1], bbox[1]))
    area = max(1.0, (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / area


def _calha_ocr(pg, tp):
    """x da calha entre as colunas (None se a pagina tem uma coluna so). Entre 35% e 65% da largura, escolhe o x
    atravessado por menos palavras do OCR, exigindo texto dos dois lados."""
    w, h = pg.rect.width, pg.rect.height
    ws = [x for x in pg.get_text("words", textpage=tp) if 0.10 * h < x[1] < 0.92 * h]  # ignora cabecalho/rodape
    if len(ws) < 40:
        return None
    melhor = None
    for k in range(35, 66):
        x = k / 100 * w
        cruzam = sum(1 for p in ws if p[0] < x < p[2])
        esq = sum(1 for p in ws if p[2] <= x)
        dire = sum(1 for p in ws if p[0] >= x)
        if esq > 0.25 * len(ws) and dire > 0.25 * len(ws) and (melhor is None or cruzam < melhor[0]):
            melhor = (cruzam, x)
    return melhor[1] if melhor and melhor[0] / len(ws) < 0.02 else None


def _ocr_texto(pg, stem, i):
    """Blocos de texto de uma pagina escaneada. Em duas colunas, cada coluna passa pelo OCR separadamente
    (o OCR da pagina inteira intercala as linhas das duas colunas e mistura questoes vizinhas)."""
    cache = CACHE_OCR / f"{stem}-p{i}-col.json"
    if cache.exists():
        return [tuple(b) for b in json.loads(cache.read_text(encoding="utf-8"))]
    w, h = pg.rect.width, pg.rect.height
    tp = pg.get_textpage_ocr(language="por", dpi=300, full=True)
    calha = _calha_ocr(pg, tp)
    if calha is None:
        blocos = [tuple(b[:5]) + (b[5], 0) for b in pg.get_text("blocks", sort=True, textpage=tp) if b[6] == 0]
    else:
        blocos = []
        for rec in (pymupdf.Rect(0, 0, calha, h), pymupdf.Rect(calha, 0, w, h)):
            pix = pg.get_pixmap(dpi=300, clip=rec)
            pg2 = pymupdf.open("pdf", pix.pdfocr_tobytes(language="por"))[0]
            sx, sy = rec.width / pg2.rect.width, rec.height / pg2.rect.height
            for b in pg2.get_text("blocks", sort=True):
                if b[6] == 0:
                    blocos.append((rec.x0 + b[0] * sx, rec.y0 + b[1] * sy, rec.x0 + b[2] * sx, rec.y0 + b[3] * sy,
                                   b[4], b[5], 0))
    CACHE_OCR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(blocos, ensure_ascii=False), encoding="utf-8")
    return blocos


def _faixas_escuras(pg):
    """Retangulos (em coords da pagina) de tarjas escuras horizontais (titulo 'QUESTAO n' em branco sobre preto)."""
    import numpy as np
    dpi = 100
    pix = pg.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width) < 100
    wpx, esc = pix.width, 72.0 / dpi
    linhas = []  # (y, x0, x1) da maior sequencia escura da linha, se tiver >= 12% da largura
    for y in range(int(0.04 * pix.height), int(0.95 * pix.height)):
        d = np.concatenate(([0], a[y].astype(np.int8), [0]))
        ini, fim = np.where(np.diff(d) == 1)[0], np.where(np.diff(d) == -1)[0]
        if len(ini):
            k = int(np.argmax(fim - ini))
            if fim[k] - ini[k] >= 0.12 * wpx:
                linhas.append((y, int(ini[k]), int(fim[k])))
    faixas, atual = [], []
    for ln in linhas + [(10 ** 6, 0, 0)]:
        if atual and (ln[0] != atual[-1][0] + 1 or ln[1] > atual[-1][2] or ln[2] < atual[-1][1]):
            esp = len(atual)
            if 6 <= esp <= 45:
                x0, x1 = min(t[1] for t in atual), max(t[2] for t in atual)
                faixas.append(pymupdf.Rect(x0 * esc, atual[0][0] * esc, x1 * esc, (atual[-1][0] + 1) * esc))
            atual = []
        atual.append(ln)
    return faixas


def _ocr_blocos(pg, stem, i):
    """Texto OCR da pagina + titulos em tarja escura (o OCR da pagina inteira nao enxerga letra branca sobre preto:
    cada tarja e recortada, invertida e lida a parte)."""
    blocos = list(_ocr_texto(pg, stem, i))
    # Alguns PDFs tem a camada de texto embaralhada (fonte sem mapeamento), mas os titulos "QUESTAO n" saem legiveis
    # nela: a numeracao vem dai, mais confiavel que o OCR dos titulos (que le "QUESTAO OS", "155", "16o").
    titulos = []
    for b in pg.get_text("blocks"):
        if b[6] == 0 and b[4].strip():
            prim = b[4].strip().splitlines()[0]
            if HEAD.match(prim):
                titulos.append((b[0], b[1], b[2], b[3], prim.strip() + "\n", 0, 0))
    if titulos:
        novos = []
        for b in blocos:
            for t in titulos:
                if b[1] < t[3] + 2 and b[3] > t[1] - 2 and b[0] < t[2] + 40 and b[2] > t[0] - 40:
                    ls = b[4].splitlines()
                    if ls and HEAD_OCR.match(ls[0]):
                        b = (b[0], b[1], b[2], b[3], "\n".join(ls[1:]) + "\n", b[5], b[6])
                    break
            if b[4].strip():
                novos.append(b)
        blocos = novos
    cache = CACHE_OCR / f"{stem}-p{i}-bar.json"
    if cache.exists():
        extras = [tuple(b) for b in json.loads(cache.read_text(encoding="utf-8"))]
    else:
        extras = []
        for rec in _faixas_escuras(pg):
            if any(b[1] < rec.y1 and b[3] > rec.y0 and b[0] < rec.x1 and b[2] > rec.x0 and re.search(r"QUEST", b[4], re.I)
                   for b in blocos + titulos):
                continue  # o OCR normal ja leu este titulo
            pix = pg.get_pixmap(dpi=300, clip=rec, colorspace=pymupdf.csGRAY)
            pix.invert_irect(pix.irect)
            try:
                pg2 = pymupdf.open("pdf", pix.pdfocr_tobytes(language="por"))[0]
                txt = pg2.get_text().strip()
            except Exception:  # noqa: BLE001
                continue
            if re.match(r"QUEST", txt, re.I):
                extras.append((rec.x0, rec.y0, rec.x1, rec.y1, txt.replace("\n", " ") + "\n", 0, 0))
        CACHE_OCR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(extras, ensure_ascii=False), encoding="utf-8")
    extras = extras + titulos
    if extras:
        # recoloca cada titulo na sua coluna, pela altura
        meio = pg.rect.width * 0.5
        esq = [b for b in blocos if (b[0] + b[2]) / 2 < meio]
        dire = [b for b in blocos if (b[0] + b[2]) / 2 >= meio]
        duas = bool(esq and dire and abs(esq[0][0] - dire[0][0]) > pg.rect.width * 0.25 and
                    sum(1 for b in blocos if b[0] < meio < b[2]) < 0.1 * len(blocos))
        if duas:
            e2 = sorted(esq + [x for x in extras if (x[0] + x[2]) / 2 < meio], key=lambda b: b[1])
            d2 = sorted(dire + [x for x in extras if (x[0] + x[2]) / 2 >= meio], key=lambda b: b[1])
            blocos = e2 + d2
        else:
            blocos = sorted(blocos + extras, key=lambda b: b[1])
    return blocos


def ler_pdf(caminho, cabecalho):
    """Lista [(pagina, linha_original)] sem cabecalhos/rodapes/rascunho; tabelas viram marcadores [[TABELA:n]]."""
    doc = pymupdf.open(caminho)
    linhas, midia, paginas_ocr, tabelas = [], {}, set(), {}
    tabs_pdf = None
    for i, pg in enumerate(doc, 1):
        texto = pg.get_text()
        if re.search(r"\bRASCUNHO\b", texto, re.I) and len(texto) < 400:
            continue
        # blocos ordenados de cima para baixo; 1a linha do bloco = inicio de paragrafo
        brutas = []
        if ilegivel(texto):
            # camada de texto corrompida: OCR (Tesseract, portugues) sobre a imagem da pagina
            blocos_pg = _ocr_blocos(pg, Path(caminho).stem, i)
            paginas_ocr.add(i)
        else:
            blocos_pg = [b for b in pg.get_text("blocks", sort=True) if b[6] == 0]
        cab = [b for b in blocos_pg if HEAD.match(b[4].strip().splitlines()[0] if b[4].strip() else "")]
        if len(cab) >= 2 and abs(cab[0][0] - cab[1][0]) > pg.rect.width * 0.25:
            # pagina em 2 colunas: coluna esquerda inteira, depois a direita
            meio = pg.rect.width / 2
            blocos_pg.sort(key=lambda b: (0 if (b[0] + b[2]) / 2 < meio else 1, b[1]))
        tabs = []
        if i not in paginas_ocr:
            if tabs_pdf is None:
                tabs_pdf = tabelas_do_pdf(caminho)  # calculado uma vez por PDF e guardado em cache
            tabs = tabs_pdf.get(i, [])
        emitidas = {}
        for b in blocos_pg:
            k_tab = next((k for k, (bbox, _, _) in enumerate(tabs) if _sobreposicao(b, bbox) > 0.6), None)
            if k_tab is not None:  # o texto da tabela sai do fluxo; entra um marcador na posicao dela
                if k_tab not in emitidas:
                    n = len(tabelas) + 1
                    tabelas[n] = {"pagina": i, "markdown": tabs[k_tab][1], "texto": tabs[k_tab][2]}
                    emitidas[k_tab] = n
                    brutas.append(f" [[TABELA:{n}]]")
                continue
            ls = b[4].splitlines()
            brutas += [(" " + l.lstrip()) if k == 0 else l for k, l in enumerate(ls)]
        for ln in brutas:
            ln = MARCA_DAGUA.sub("", ln.replace("\t", " ").replace("­", "").replace("Ɵ", "ti"))
            for lig, rep in (("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬀ", "ff"), ("ﬃ", "ffi"), ("ﬄ", "ffl")):
                ln = ln.replace(lig, rep)
            ln = corrigir_ligaturas(ln)
            s = ln.strip()
            if not s or RUIDO.match(s) or (cabecalho and s.lower() == cabecalho.lower()):
                continue
            linhas.append((i, ln))
        m = _midia_pagina(pg)
        if m:
            midia[i] = m
    # Cadernos com enfeite vetorial em quase toda pagina (ex.: 2025) marcariam tudo como "diagrama": quando mais de
    # 80% das paginas tem esse sinal, ele e decoracao do layout e e descartado (imagens e tabelas reais ficam).
    vetoriais = [p for p, t in midia.items() if t == "diagrama_ou_tabela"]
    if len(doc) and len(vetoriais) > 0.8 * len(doc):
        for p in vetoriais:
            del midia[p]
    return linhas, midia, paginas_ocr, tabelas


def _midia_pagina(pg):
    """'imagem' (figura/foto >= 3% da pagina) ou 'diagrama_ou_tabela' (desenho vetorial relevante)."""
    area = pg.rect.width * pg.rect.height
    for im in pg.get_image_info():
        x0, y0, x1, y1 = im["bbox"]
        if (x1 - x0) * (y1 - y0) >= 0.03 * area:
            return "imagem"
    # Desenho vetorial: ignora tracos finos e formas do tamanho da pagina (fundo). Um diagrama/tabela
    # tem 13 a 80 formas; acima disso e a marca d'agua vetorial do INEP (2023), que nao permite distinguir.
    formas = [d["rect"] for d in pg.get_drawings()
              if min(d["rect"].width, d["rect"].height) > 4 and d["rect"].width * d["rect"].height < 0.5 * area]
    if 12 < len(formas) <= 80:
        return "diagrama_ou_tabela"
    return None


def configurar_ocr():
    tess = Path(r"C:\Program Files\Tesseract-OCR")
    if tess.exists() and str(tess) not in os.environ["PATH"]:
        os.environ["PATH"] += os.pathsep + str(tess)
    os.environ.setdefault("TESSDATA_PREFIX", str(Path(__file__).parent / "tessdata"))


HEAD_OCR = re.compile(r"^\s*QUEST[ÃA0]O\s*(DISCURSIVA\s*)?([0-9OoSsIl|B]{1,3})(?![0-9A-Za-zÀ-ú])", re.I)


def _numero_ocr(txt):
    """Numero de questao lido pelo OCR com confusoes comuns (O->0, S->5, l/I/|->1, B->8)."""
    s = txt.translate(str.maketrans("OoSsIl|B", "00551118"))
    n = int(s)
    return int(s[:2]) if n > 60 else n  # '155' -> 15 (lixo colado ao numero)


def blocos(linhas, ocr=False):
    """Divide pelas linhas 'QUESTAO [DISCURSIVA] n'. Em provas escaneadas aceita numeros lidos com ruido,
    desde que sigam a sequencia (maior que o anterior e no maximo 3 acima)."""
    marcas, ultimo = [], 0
    for idx, (pg, ln) in enumerate(linhas):
        m = HEAD.match(ln)
        if m:
            marcas.append((idx, bool(m.group(1)), int(m.group(2))))
            ultimo = int(m.group(2)) if not m.group(1) else ultimo
        elif ocr:
            m = HEAD_OCR.match(ln)
            if m:
                num = _numero_ocr(m.group(2))
                if m.group(1) or ultimo < num <= ultimo + 3:
                    marcas.append((idx, bool(m.group(1)), num))
                    ultimo = num if not m.group(1) else ultimo
    # titulo lido duas vezes (camada de texto + OCR): fica o ultimo, que e o que antecede o corpo
    marcas = [m for k, m in enumerate(marcas)
              if not (k + 1 < len(marcas) and marcas[k + 1][1:] == m[1:] and marcas[k + 1][0] - m[0] <= 3)]
    out = []
    if marcas:  # o questionario de percepcao reinicia a numeracao: ignorar tudo dele em diante
        for j in range(marcas[0][0], len(linhas)):
            if QUESTIONARIO.search(linhas[j][1]):
                linhas = linhas[:j]
                marcas = [m for m in marcas if m[0] < j]
                break
    # numeracao que reinicia (ex.: questionario de percepcao) marca o fim da prova
    maior = 0
    for k, (idx, disc, num) in enumerate(marcas):
        if not disc:
            if num < maior:
                linhas = linhas[:idx]
                marcas = marcas[:k]
                break
            maior = num
    for k, (idx, disc, num) in enumerate(marcas):
        fim = marcas[k + 1][0] if k + 1 < len(marcas) else len(linhas)
        corpo = linhas[idx + 1:fim]
        out.append({"disc": disc, "num": num, "pag_ini": linhas[idx][0], "linhas": corpo})
    return out


def alternativas(linhas, permitir_bolinha=False):
    """Acha a sequencia A..E; devolve (indice_inicio, dict)."""
    cand = [i for i, (_, l) in enumerate(linhas) if re.match(r"^A(\s+\S|\s*$)", l.strip())]
    for ini in reversed(cand):
        alts, esperado, atual = {}, "A", None
        for _, l in linhas[ini:]:
            s = l.strip()
            m = re.match(r"^([A-E])(?:\s+(.*))?$", s)
            if m and m.group(1) == esperado:
                atual = esperado
                alts[atual] = (m.group(2) or "").strip()
                esperado = chr(ord(esperado) + 1) if esperado != "E" else "F"
            elif atual:
                alts[atual] = (alts[atual] + " " + s).strip()
        if len(alts) in (4, 5):  # ENADE tem questoes com 4 alternativas (ex.: Medicina 2023)
            return ini, alts
    # provas antigas (OCR): alternativas marcadas por bolinha, sem letra
    cand = [i for i, (_, l) in enumerate(linhas) if BOLINHA.match(l)] if permitir_bolinha else []
    if permitir_bolinha and len(cand) < 5:
        # OCR ruim: a bolinha vem sozinha na linha ou colada na primeira palavra ("Oie", "OQ L11el").
        # So vale depois de uma linha de comando (ex.: "E correto apenas o que se afirma em") e com exatamente 5 marcas.
        cmd = [i for i, (_, l) in enumerate(linhas) if re.search(r"correto|correta|assinale|afirma|descreve|conclui", l, re.I)]
        for c0 in reversed(cmd):
            frouxas = [i for i in range(c0 + 1, len(linhas)) if BOLINHA_FROUXA.match(linhas[i][1])]
            if len(frouxas) >= 5:
                cand = frouxas[:5]  # lixo de rodape/margem depois das 5 marcas nao conta
                break
    if len(cand) >= 5:
        cand = cand[-5:]
        alts = {}
        limite = next((j for j in range(cand[-1] + 1, len(linhas)) if RODAPE_PROVA.match(linhas[j][1])), len(linhas)) \
            if permitir_bolinha else len(linhas)
        for k, c in enumerate(cand):
            fim = cand[k + 1] if k + 1 < 5 else limite
            partes = [BOLINHA_FROUXA.sub("", linhas[c][1], count=1).strip()] + [l.strip() for _, l in linhas[c + 1:fim]]
            alts["ABCDE"[k]] = " ".join(p for p in partes if p)
        return cand[0], alts
    return None, {}


def separar_texto(linhas):
    """Separa texto-base (ate a ultima referencia) do enunciado."""
    paragrafos, cur = [], []
    for _, l in linhas:
        if l.startswith(" ") and cur:
            paragrafos.append(" ".join(cur))
            cur = []
        cur.append(l.strip())
    if cur:
        paragrafos.append(" ".join(cur))
    ult = -1
    for i, p in enumerate(paragrafos[:-1]):
        if REFERENCIA.search(p):
            ult = i
    base = "\n\n".join(paragrafos[:ult + 1]).strip()
    enun = "\n\n".join(paragrafos[ult + 1:]).strip()
    return base, enun


def ler_gabarito(caminho):
    """Retorna {numero: letra|'ANULADA'|'***'}."""
    if not caminho:
        return {}
    txt = "\n".join(p.get_text() for p in pymupdf.open(caminho))
    toks = [t.strip() for t in txt.splitlines() if t.strip()]
    gab, i = {}, 0
    while i < len(toks) - 1:
        m = re.match(r"^(?:QUEST[ÃA]O\s+)?(DISCURSIVA\s+)?(\d{1,2})$", toks[i], re.I)
        if m and not m.group(1):
            v = toks[i + 1].upper()
            if re.fullmatch(r"[A-E]|ANULADA|\*+|-+", v):
                gab[int(m.group(2))] = v
                i += 2
                continue
        i += 1
    # a grade (2025) tem prioridade: o leitor acima casaria o ultimo numero de um bloco com a 1a letra do seguinte
    # (ex.: "5" seguido de "C"), produzindo um gabarito parcial e ERRADO
    grade = _gabarito_em_grade(toks)
    return grade if len(grade) >= 20 else gab


def _gabarito_em_grade(toks):
    """2025: blocos de numeros (1 2 3 4 5) seguidos de igual quantidade de respostas (C A D B C)."""
    gab, i = {}, 0
    while i < len(toks):
        nums = []
        while i < len(toks) and toks[i].isdigit():
            nums.append(int(toks[i])); i += 1
        resp = toks[i:i + len(nums)]
        if nums and len(resp) == len(nums) and all(re.fullmatch(r"[A-E]|ANULAD[OA]", r.upper()) for r in resp):
            for n, r in zip(nums, resp):
                gab[n] = "ANULADA" if r.upper().startswith("ANULAD") else r.upper()
            i += len(nums)
        elif not nums:
            i += 1
    return gab


def ler_padroes(caminho):
    """Lista de textos de padrao de resposta, na ordem das discursivas."""
    if not caminho:
        return []
    stem = Path(caminho).stem
    paginas = []
    for i, pg in enumerate(pymupdf.open(caminho), 1):
        t = pg.get_text()
        if ilegivel(t):  # padrao com fonte quebrada (ex.: 2022): le a pagina por OCR, com cache em disco
            cache = CACHE_OCR / f"{stem}-padrao-p{i}.txt"
            if cache.exists():
                t = cache.read_text(encoding="utf-8")
            else:
                configurar_ocr()
                t = pg.get_text(textpage=pg.get_textpage_ocr(language="por", dpi=300, full=True))
                CACHE_OCR.mkdir(parents=True, exist_ok=True)
                cache.write_text(t, encoding="utf-8")
        paginas.append(t)
    txt = corrigir_ligaturas("\n".join(paginas))
    partes = re.split(r"PADR[ÃA]O\s+(?:DE\s+)?RESPOSTA", txt, flags=re.I)[1:]
    out = []
    for p in partes:
        p = re.split(r"QUEST[ÃA]O\s+DISCURSIVA\s+\d", p, flags=re.I)[0]
        p = re.split(r"\n\s*(NOVEMBRO|FORMA[ÇC][ÃA]O GERAL|COMPONENTE ESPEC)", p, flags=re.I)[0]
        out.append(" ".join(p.split()))
    return out


def processar(ano, prova, gabarito, padrao, raiz, info, matriz=None):
    linhas, midia, paginas_ocr, tabelas = ler_pdf(prova, info["curso"])
    gab = ler_gabarito(gabarito)
    padroes = ler_padroes(padrao)
    validos, rejeitados = [], []
    disc_idx, vistos = 0, set()
    conferencia = {"concordam": 0, "divergem": 0}  # gabarito do PDF de gabarito x gabarito da matriz oficial
    for b in blocos(linhas, ocr=bool(paginas_ocr)):
        comp = "FG" if b["num"] <= (2 if b["disc"] else 8) else "CE"
        if matriz and not b["disc"] and b["num"] in matriz:
            m0 = matriz[b["num"]]
            comp = "FG" if (m0["competencia"] or m0["habilidade"]).startswith("FG_") else "CE"
        tipo = "discursiva" if b["disc"] else "objetiva"
        if b["disc"]:
            padrao_txt = padroes[disc_idx] if disc_idx < len(padroes) else None
            disc_idx += 1
        paginas = sorted({p for p, _ in b["linhas"]} | {b["pag_ini"]})
        ids_tab, corpo = [], []
        for pg_, ln in b["linhas"]:
            m_tab = re.fullmatch(r"\s*\[\[TABELA:(\d+)\]\]\s*", ln)
            if m_tab:
                ids_tab.append(int(m_tab.group(1)))
                paginas = sorted(set(paginas) | {tabelas[ids_tab[-1]]["pagina"]})
            else:
                corpo.append((pg_, ln))
        alts, ini = {}, None
        if not b["disc"]:
            ini, alts = alternativas(corpo, permitir_bolinha=any(p in paginas_ocr for p in paginas))
        base, enun = separar_texto(corpo[:ini] if ini is not None else corpo)
        g = gab.get(b["num"]) if not b["disc"] else None
        meta = matriz.get(b["num"]) if matriz and not b["disc"] else None
        if meta and g is not None:
            conferencia["concordam" if meta["gabarito"] == g else "divergem"] += 1
        doc = {
            "id": f"{ano}-{info['slug']}-{comp.lower()}-{'d' if b['disc'] else 'q'}{b['num']:02d}",
            "ano": ano, "area": info["area"], "curso": info["curso"], "grau": info["grau"],
            "componente": comp, "tipo_questao": tipo, "numero": b["num"],
            "anulada": g == "ANULADA",
            "texto_base": base, "enunciado": enun,
            "alternativas": alts if not b["disc"] else {},
            "gabarito": g if g and re.fullmatch(r"[A-E]", g) else None,
            "padrao_resposta": padrao_txt if b["disc"] else None,
            "tem_midia_nao_textual": bool(ids_tab) or any(p in midia for p in paginas),
            "midia": [{"pagina": tabelas[t]["pagina"], "tipo": "tabela", "conversao": "markdown",
                       "conteudo": tabelas[t]["markdown"]} for t in ids_tab]
                     + [{"pagina": p, "tipo": midia[p], "conversao": "pendente", "conteudo": None}
                        for p in paginas if p in midia
                        and not (midia[p] == "diagrama_ou_tabela" and any(tabelas[t]["pagina"] == p for t in ids_tab))],
            "tabelas_texto": " ".join(tabelas[t]["texto"] for t in ids_tab),
            "objetos_conhecimento": meta["objetos"] if meta else [],
            "competencias": [meta["competencia"]] if meta else [],
            "habilidades": [meta["habilidade"]] if meta else [],
            "fonte_metadados": "oficial" if meta else "ausente",
            "origem": {"pdf": str(prova.relative_to(raiz)).replace("\\", "/"),
                       "pagina_inicio": paginas[0], "pagina_fim": paginas[-1],
                       "pdf_gabarito": str(gabarito.relative_to(raiz)).replace("\\", "/") if gabarito else None,
                       "pdf_padrao_resposta": str(padrao.relative_to(raiz)).replace("\\", "/") if padrao else None},
            "extracao": "ocr" if any(p in paginas_ocr for p in paginas) else "texto",
            "extrator_versao": VERSAO,
        }
        motivo = None
        texto_all = doc["texto_base"] + doc["enunciado"] + "".join(alts.values())
        if ilegivel(texto_all):
            motivo = "texto_ilegivel_encoding_pdf (requer OCR)"
        elif not doc["enunciado"]:
            motivo = "enunciado_vazio"
        elif not b["disc"] and len(alts) not in (4, 5):
            motivo = f"alternativas_incompletas({len(alts)})"
        elif not b["disc"] and g is None:
            motivo = "sem_gabarito"
        elif not b["disc"] and g and re.fullmatch(r"[A-E]", g) and g not in alts:
            motivo = f"gabarito_{g}_sem_alternativa"
        if not motivo and doc["id"] in vistos:
            motivo = "id_duplicado"
        vistos.add(doc["id"])
        if motivo:
            rejeitados.append({"id": doc["id"], "motivo": motivo, "origem": doc["origem"],
                               "pagina": paginas[0]})
        else:
            validos.append(doc)
    # Portao de qualidade do OCR: provas escaneadas em duas colunas saem com o texto de questoes vizinhas
    # entrelacado. Cobertura baixa (poucas objetivas recuperadas em relacao ao gabarito) e o sinal disso;
    # nesse caso nada do PDF e indexado ate haver OCR por coluna.
    esperadas = sum(1 for v in gab.values() if re.fullmatch(r"[A-E]|ANULADA", v))
    obj_ok = sum(1 for d in validos if d["tipo_questao"] == "objetiva")
    cobertura = obj_ok / esperadas if esperadas else 1.0
    if paginas_ocr and cobertura < COBERTURA_MINIMA_OCR:
        motivo = f"ocr_cobertura_insuficiente({obj_ok}/{esperadas} objetivas; provavel mistura de colunas)"
        for d in validos:
            rejeitados.append({"id": d["id"], "motivo": motivo, "origem": d["origem"],
                               "pagina": d["origem"]["pagina_inicio"]})
        validos = []
    rel = {"pdf": prova.name, "ano": ano, "conferencia_gabarito_matriz": conferencia if matriz else None,
           "paginas_ocr": len(paginas_ocr), "cobertura_objetivas": round(cobertura, 3),
           "blocos": len(validos) + len(rejeitados),
           "validos": len(validos), "rejeitados": len(rejeitados),
           "gabarito_itens": len(gab), "padroes": len(padroes)}
    return validos, rejeitados, rel


def _aquecer_um(caminho):
    try:
        tabelas_do_pdf(caminho)
        return 1
    except Exception:  # noqa: BLE001
        return 0


def aquecer_tabelas(raw, processos=3):
    """Calcula em paralelo o cache de tabelas de todas as provas (so na primeira vez)."""
    from multiprocessing import Pool
    pdfs = sorted(Path(raw).glob("*/prova/*.pdf"))
    pdfs = [p for p in pdfs if "_MP_" not in p.name]
    with Pool(processos) as pool:
        feitos = sum(pool.imap_unordered(_aquecer_um, pdfs))
    print(f"cache de tabelas: {feitos} de {len(pdfs)} provas")


def main():
    aqui = Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(aqui / "data" / "raw"))
    ap.add_argument("--out", default=str(aqui / "data" / "processed"))
    ap.add_argument("--aquecer", action="store_true", help="so calcula o cache de tabelas (em paralelo) e sai")
    a = ap.parse_args()
    if a.aquecer:
        aquecer_tabelas(a.raw)
        return 0
    configurar_ocr()
    raw, out = Path(a.raw), Path(a.out)
    raiz = raw.parent.parent
    out.mkdir(parents=True, exist_ok=True)
    todos, rejs, rels = [], [], []
    for ydir in sorted(p for p in raw.iterdir() if p.is_dir() and p.name.isdigit()):
        ano = int(ydir.name)
        grupos = {}  # slug -> (info, PDFs de prova candidatos); o INEP as vezes repete a prova com outro nome
        for prova in sorted((ydir / "prova").glob("*.pdf")):
            if ano == 2025 and not re.search(r"_pv(_1)?\.pdf$", prova.name, re.I):
                continue  # 2025 tem varios cadernos por curso; so o primeiro e usado
            c = info_curso(prova)
            grupos.setdefault(c["slug"], (c, []))[1].append(prova)

        def par(tipo, prova, slug):
            d = ydir / tipo
            return melhor_par(prova, sorted(d.glob("*.pdf")), slug=slug) if d.exists() else None

        for slug, (info, provas) in sorted(grupos.items()):
            gab, pad = par("gabarito", provas[0], info["slug"]), par("padrao", provas[0], info["slug"])
            matriz = None
            if ano == 2025:
                mp = melhor_par(provas[0], sorted((ydir / "prova").glob("*_MP_*.pdf")), slug=None)
                gmap = ler_gabarito(gab)
                matriz = escolher_versao(ler_versoes(mp), gmap) if mp else None
                if matriz and concordancia(matriz, gmap) < 0.8:
                    matriz = None  # matriz que nao bate com o gabarito oficial nao pode gerar metadados
            tentativas = [processar(ano, pv, gab, pad, raiz, info, matriz) for pv in provas]
            melhor = max(tentativas, key=lambda t: len(t[0]))  # a prova com mais questoes validas
            v, r, rel = melhor
            for t in tentativas:
                if t is not melhor:
                    rels.append(dict(t[2], ignorado="outra prova do mesmo curso rendeu mais questoes"))
            rel.update(curso=info["curso"], area=info["area"], origem_cadastro=info["origem"])
            rel["gabarito_pdf"] = gab.name if gab else None
            rel["padrao_pdf"] = pad.name if pad else None
            todos += v; rejs += r; rels.append(rel)
            print(f"{ano} {slug:42} {rel.get('validos', 0):3} validos, {rel.get('rejeitados', 0):3} rejeitados  "
                  f"(OCR em {rel.get('paginas_ocr', 0)} pag.)")
    # o mesmo curso as vezes aparece com grafias diferentes entre anos ("Educacao Fisica", "Educacao fisica"):
    # o nome exibido passa a ser o mais frequente entre os documentos do mesmo slug
    from collections import Counter, defaultdict
    def _slug(d):
        return d["id"].split("-", 1)[1].rsplit("-", 2)[0]
    cont = defaultdict(Counter)
    for d in todos:
        cont[_slug(d)][d["curso"]] += 1
    canon = {sl: max(c.items(), key=lambda kv: (kv[1], sum(w[:1].isupper() for w in kv[0].split())))[0]
             for sl, c in cont.items()}
    for d in todos:
        d["curso"] = canon[_slug(d)]
    (out / "questoes.jsonl").write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in todos) + "\n", encoding="utf-8")
    (out / "rejeitadas.jsonl").write_text("\n".join(json.dumps(d, ensure_ascii=False) for d in rejs) + "\n", encoding="utf-8")
    (out / "relatorio.json").write_text(json.dumps(rels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total: {len(todos)} validos, {len(rejs)} rejeitados -> {out}")


if __name__ == "__main__":
    sys.exit(main())
