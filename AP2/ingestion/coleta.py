"""Coleta do acervo ENADE (RF01).

Le as paginas de provas e gabaritos do INEP, monta um manifesto
(data/manifest.jsonl) e, quando pedido, baixa os PDFs para data/raw/.

Uso:
  python coleta.py index                       # gera o manifesto
  python coleta.py size  [--year 2023]         # tamanho total via HEAD
  python coleta.py download --year 2023 [--only prova,gabarito,padrao]
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

BASE = ("https://www.gov.br/inep/pt-br/areas-de-atuacao/avaliacao-e-exames-"
        "educacionais/enade/provas-e-gabaritos/")
ANOS = [2025, 2023, 2022, 2021, 2019, 2018, 2017, 2016, 2015, 2014, 2013,
        2012, 2011, 2010, 2009, 2008, 2007, 2006, 2005, 2004]
ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.jsonl"
RAW = ROOT / "data" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (TP2-BigData; pesquisa academica)"}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self._href = None
        self._text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None


def classificar(rotulo, url):
    """Tipo do documento e variante (normal, ledor, ampliada, libras...)."""
    r, u = rotulo.lower(), url.lower()
    # a pasta da URL e o sinal mais confiavel (em 2018 a mesma prova aparece varias vezes com rotulos diferentes)
    if "/gabaritos/" in u:
        tipo = "gabarito"
    elif "/padrao_resposta/" in u:
        tipo = "padrao"
    elif "/provas/" in u:
        tipo = "prova"
    elif "padr" in r or "padrao" in u or "/pr_" in u or "pad_resp" in u or "prd_" in u:
        tipo = "padrao"
    elif "gabarito" in r or "gab" in u.rsplit("/", 1)[-1] or "_gb_" in u:
        tipo = "gabarito"
    else:
        tipo = "prova"
    variante = "normal"
    for v in ("ledor", "ampliada", "libras"):
        if v in r or v in u:
            variante = v
    return tipo, variante


def versao_do_caderno(rotulo, url):
    """Numero da versao do caderno (2025 tem ate 5 por curso: ..._PV_1.pdf, 'Prova 2'); None se nao houver."""
    m = re.search(r"_(?:pv|gb|prova|gabarito)_?(\d+)\.pdf", url.lower()) or re.search(r"(\d+)\s*$", rotulo)
    return int(m.group(1)) if m else None


def ano_do_arquivo(url, pagina):
    """O ano verdadeiro vem da URL: a aba de um ano no site do INEP as vezes lista arquivos de outro ano
    (a aba 2022 tem links para /2018/). Sem ano na URL, vale o da aba."""
    m = re.search(r"/(20\d{2})/", url) or re.search(r"/(20\d{2})_", url)
    return int(m.group(1)) if m else pagina


def indexar():
    por_url = {}  # global: o mesmo arquivo pode aparecer em abas de anos diferentes
    for ano in ANOS:
        req = urllib.request.Request(BASE + str(ano), headers=UA)
        html = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        p = Links()
        p.feed(html)
        for href, rotulo in p.links:
            if not href or not re.search(r"\.pdf($|\?)", href, re.I):
                continue
            url = href.replace("http://", "https://")
            tipo, variante = classificar(rotulo, url)
            e = por_url.get(url)
            if e is None:
                por_url[url] = {"ano": ano_do_arquivo(url, ano), "tipo": tipo, "variante": variante, "versao": versao_do_caderno(rotulo, url),
                                "rotulo": rotulo, "url": url, "arquivo": Path(urlparse(url).path).name}
            elif variante == "normal" and e["variante"] != "normal":
                e.update(variante="normal", rotulo=rotulo)
        time.sleep(0.5)
        print(f"aba {ano}: {len(por_url)} PDFs acumulados")
    entradas = sorted(por_url.values(), key=lambda e: (e["ano"], e["tipo"], e["arquivo"]))
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", encoding="utf-8") as f:
        for e in entradas:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"Manifesto: {MANIFEST} ({len(entradas)} PDFs)")


def carregar(ano=None, tipos=None, variantes=("normal",)):
    out = []
    for linha in MANIFEST.read_text(encoding="utf-8").splitlines():
        e = json.loads(linha)
        if ano and e["ano"] != ano:
            continue
        if tipos and e["tipo"] not in tipos:
            continue
        if variantes and e["variante"] not in variantes:
            continue
        out.append(e)
    return out


def tamanho(url):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        return int(urllib.request.urlopen(req, timeout=60).headers.get("Content-Length", 0))
    except Exception:
        return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["index", "size", "download"])
    ap.add_argument("--year", type=int)
    ap.add_argument("--only", default="prova,gabarito,padrao")
    ap.add_argument("--lista", help="JSON com a lista exata de PDFs a baixar (ex.: data/alvo_extracao.json)")
    a = ap.parse_args()
    tipos = set(a.only.split(","))

    if a.cmd == "index":
        indexar()
        return
    itens = json.loads(Path(a.lista).read_text(encoding="utf-8")) if a.lista else carregar(a.year, tipos)
    if a.cmd == "size":
        total = 0
        for e in itens:
            total += tamanho(e["url"])
        print(f"{len(itens)} arquivos, {total / 1e6:.1f} MB")
        return
    for e in itens:
        dest = RAW / str(e["ano"]) / e["tipo"] / e["arquivo"]
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(e["url"], headers=UA)
        try:
            dest.write_bytes(urllib.request.urlopen(req, timeout=120).read())
            print("ok ", dest.relative_to(ROOT))
        except Exception as ex:
            print("ERRO", e["url"], ex, file=sys.stderr)
        time.sleep(0.3)


if __name__ == "__main__":
    main()
