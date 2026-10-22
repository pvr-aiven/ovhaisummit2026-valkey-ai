"""Construit la base de connaissance : téléchargement des sources, nettoyage, découpage en chunks.

Usage :
  python -m demo.ingest            # télécharge les sources de sources.yaml et produit data/chunks.jsonl
  python -m demo.ingest --offline  # re-découpe uniquement à partir de data/corpus/ (pas de réseau)

Vous pouvez aussi déposer vos propres fichiers .md / .txt dans data/corpus/local/ : ils sont ajoutés
avec source=local et type=doc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import settings

UA = {"User-Agent": "valkey-ai-summit-demo/1.0"}


@dataclass
class Doc:
    doc_id: str
    url: str
    source: str
    type: str
    title: str
    text: str           # Markdown nettoyé


@dataclass
class Chunk:
    id: str
    doc_id: str
    url: str
    source: str
    type: str
    title: str
    section: str
    text: str
    position: int


# --------------------------------------------------------------------------- lecture des sources

def load_sources(path: Path) -> list[dict]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["sources"]


def doc_id_for(url: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1]).strip("-")[-60:]
    return f"{slug}-{hashlib.sha1(url.encode()).hexdigest()[:6]}"


# balises MDX/HTML des docs (ex. <code className="action">Public Cloud</code>, <ManagerLink …>)
_MDX = re.compile(r"</?(?:code|ManagerLink|a|span|div|br|strong|em|b|i|Tabs|TabItem|details|summary|sup|kbd)\b[^>]*>")


def strip_mdx(text: str) -> str:
    return _MDX.sub("", text)


_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def clean_markdown(raw: str) -> tuple[str, str]:
    """Retire le front matter, les bannières et les images. Retourne (titre, texte)."""
    title = ""
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n")
    m = _FRONT.match(raw)
    if m:
        t = re.search(r'^title:\s*"?(.*?)"?\s*$', m.group(1), re.M)
        title = t.group(1) if t else ""
        raw = raw[m.end():]
    lines = []
    for line in raw.splitlines():
        if line.startswith(("> For AI agents:", "> For the complete documentation index", ":::")):
            continue
        line = line.replace("<!-- -->", "").replace("\u200b", "")
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)            # images
        line = strip_mdx(line)
        line = re.sub(r"\[([^\]]+)\]\((?:[^)]*)\)", r"\1", line)     # liens -> texte
        line = re.sub(r"\[\]\([^)]*\)", "", line)                    # ancres vides (titres de la doc Aiven)
        lines.append(line.rstrip())
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if not title:
        h1 = re.search(r"^# (.+)$", text, re.M)
        title = h1.group(1).strip() if h1 else ""
    return title, text


def html_to_markdown(html: str) -> tuple[str, str]:
    """Extraction simple d'un article de blog : titres, paragraphes, listes, code."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg"]):
        tag.decompose()
    title = (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else
             (soup.title.get_text(strip=True) if soup.title else ""))
    root = soup.find("article") or soup.find("main") or soup.body or soup
    out = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt or txt in ("Loading code...", "Loading..."):
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            out.append("\n" + "#" * int(el.name[1]) + " " + txt)
        elif el.name == "li":
            out.append("- " + txt)
        elif el.name == "pre":
            out.append("```\n" + el.get_text() + "\n```")
        else:
            out.append(txt)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    # pied de page des articles aiven.io (newsletter, table des matières) : à exclure
    cut = re.split(r"\n#{1,4} (?:Stay updated with Aiven|Related resources)", text)[0].strip()
    return title, cut or text


def html_section_to_markdown(html: str, section_id: str) -> tuple[str, str]:
    """Extrait une section d'une page (ex. #ai-endpoints de la page des prix OVHcloud).

    Chaque ligne de tableau devient une phrase autonome : un chunk garde le modèle ET son prix.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id=section_id)
    if node is None:
        raise ValueError(f"section #{section_id} introuvable")
    for _ in range(8):  # remonter jusqu'au bloc qui contient les tableaux
        if node.find("table") or node.parent is None:
            break
        node = node.parent
    out, title = [], ""
    for el in node.find_all(["h2", "h3", "h4", "p", "table"]):
        if el.find_parent("table"):
            continue
        txt = el.get_text(" ", strip=True)
        if el.name in ("h2", "h3", "h4"):
            title = title or txt
            out.append(f"\n## {txt}")
        elif el.name == "p" and txt:
            out.append(txt)
        elif el.name == "table":
            rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in el.find_all("tr")]
            if len(rows) < 2:
                continue
            head = [re.sub(r"\s+", " ", h).replace("( ", "(") for h in rows[0]]
            for r in rows[1:]:
                if not r or not r[0]:
                    continue
                parts = [f"{h}: {v}" for h, v in zip(head[1:], r[1:]) if v and v != "-"]
                out.append(f"- {r[0]} : " + "; ".join(parts) + ".")
    return title, "\n".join(out).strip()


def catalog_to_markdown(models: list[dict]) -> tuple[str, str]:
    """Catalogue AI Endpoints (API publique) -> une section par modèle : usage, capacités, licence, contexte.
    Les prix ne sont pas repris ici (ils viennent de la page des prix, qui fait foi)."""
    title = "OVHcloud AI Endpoints – catalogue des modèles"
    out = [f"# {title}", "Catalogue des modèles OVHcloud AI Endpoints, accessibles via l'API compatible OpenAI "
           "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1 ."]
    for m in sorted(models, key=lambda x: (x.get("category_v2") or x.get("category") or "", x.get("name") or "")):
        md = m.get("metadata") or {}
        spec = md.get("model_specs") or {}
        cap = spec.get("capabilities") or {}
        pub = md.get("publishing_information") or {}
        params = (spec.get("model_parameters") or {}).get("params") or {}
        flags = [n for n, k in (("appel de fonctions (function calling)", "function_calling"), ("raisonnement", "reasoning"),
                                ("streaming", "streaming"), ("mode batch", "batch")) if cap.get(k)]
        lines = [f"\n## {m.get('name') or m['id']}",
                 f"Catégorie : {m.get('category_v2') or ''} / {m.get('category') or ''}. Éditeur : {pub.get('publisher', '?')}"
                 f" (série {pub.get('series', '?')}), licence {pub.get('licence_name', '?')}.",
                 f"Entrée : {', '.join(cap.get('input_modality') or [])} ; sortie : {', '.join(cap.get('output_modality') or [])}."]
        if flags:
            lines.append("Fonctionnalités : " + ", ".join(flags) + ".")
        ctx = params.get("context_size") or md.get("context_size")
        if ctx:
            lines.append(f"Taille de contexte : {ctx} tokens.")
        if params.get("output_dimension"):
            lines.append(f"Dimension des vecteurs : {params['output_dimension']} ; lot maximal : {params.get('max_batch_size', '?')} textes par appel.")
        if spec.get("nb_of_billion_parameters"):
            lines.append(f"Taille : {spec['nb_of_billion_parameters']} milliards de paramètres.")
        desc = re.sub(r"\s+", " ", m.get("description") or "").strip()
        if desc:
            lines.append(desc)
        out.append("\n".join(lines))
    return title, "\n".join(out)


def fetch(src: dict) -> Doc:
    import httpx

    url = src["url"]
    kind = src.get("kind", "page")
    if kind == "ai-endpoints-catalog":
        r = httpx.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        title, text = catalog_to_markdown(r.json())
        return Doc(doc_id_for(url), "https://endpoints.ai.cloud.ovh.net/catalog", src["source"], src["type"],
                   src.get("title") or title, text)
    if kind == "html-section":
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (demo)"}, timeout=30, follow_redirects=True)
        r.raise_for_status()
        title, text = html_section_to_markdown(r.text, src["section"])
        text = f"# {src.get('title') or title}\n{text}"
        return Doc(doc_id_for(url + "#" + src["section"]), f"{url}#{src['section']}", src["source"], src["type"],
                   src.get("title") or title or url, text)
    r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
    r.raise_for_status()
    is_html = "html" in r.headers.get("content-type", "") and not url.endswith(".md")
    title, text = html_to_markdown(r.text) if is_html else clean_markdown(r.text)
    return Doc(doc_id_for(url), url, src["source"], src["type"], src.get("title") or title or url, text)


# --------------------------------------------------------------------------- découpage

def split_sections(text: str) -> list[tuple[str, str]]:
    """Découpe par titres Markdown (#, ##, ###). Retourne [(chemin de section, contenu)]."""
    sections, path, buf = [], [], []
    in_code = False

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((" › ".join(path), body))
        buf.clear()

    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{1,3}) (.+)$", line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = path[: level - 1] + [re.sub(r"[*`]", "", m.group(2)).strip()]
        else:
            buf.append(line)
    flush()
    return sections


def pack(body: str, max_words: int, overlap: int) -> list[str]:
    """Regroupe les paragraphes jusqu'à ~max_words mots, avec un recouvrement entre morceaux."""
    # un bloc de code ``` reste un seul « paragraphe » (pas de fence coupée en deux)
    paras, buf, in_code = [], [], False
    for line in body.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and not line.strip():
            if buf:
                paras.append("\n".join(buf).strip())
                buf = []
        else:
            buf.append(line)
    if buf:
        paras.append("\n".join(buf).strip())
    paras = [p for p in paras if p]
    step = max(1, max_words - overlap)
    chunks, cur = [], []
    for p in paras:
        words = p.split()
        if len(words) > max_words:  # paragraphe trop long : on vide d'abord le morceau en cours
            if cur and any(x.strip() for x in cur):
                chunks.append("\n\n".join(cur))
            cur = []
            for i in range(0, len(words), step):
                chunks.append(" ".join(words[i:i + max_words]))
            continue
        if sum(len(x.split()) for x in cur) + len(words) > max_words and cur:
            chunks.append("\n\n".join(cur))
            tail = " ".join(chunks[-1].split()[-overlap:]) if overlap else ""
            cur = [tail] if tail else []
        cur.append(p)
    if cur and any(x.strip() for x in cur):
        chunks.append("\n\n".join(cur))
    return [c for c in chunks if len(c.split()) >= 12]  # ignore les fragments trop courts


def chunk_doc(doc: Doc, max_words: int, overlap: int, min_words: int = 60) -> list[Chunk]:
    """Les sections trop courtes sont fusionnées avec la suivante : un chunk doit porter assez de contexte."""
    merged: list[tuple[str, str]] = []
    carry_sec, carry = "", ""
    for section, body in split_sections(strip_mdx(doc.text)):  # aussi pour un corpus déjà en cache
        if carry:
            body = carry + "\n\n" + (f"{section.split(' › ')[-1]}\n" if section else "") + body
            section = carry_sec
        if len(body.split()) < min_words:
            carry_sec, carry = section, body
            continue
        merged.append((section, body))
        carry_sec, carry = "", ""
    if carry:
        merged.append((carry_sec, carry))
    out = []
    for section, body in merged:
        for piece in pack(body, max_words, overlap):
            n = len(out)
            out.append(Chunk(f"{doc.doc_id}:{n}", doc.doc_id, doc.url, doc.source, doc.type,
                             doc.title, section, piece, n))
    return out


# Sections de pied de page présentes sur toutes les pages OVHcloud : aucun contenu utile, et des
# doublons qui remontent dans la recherche
BOILERPLATE = re.compile(r"(^|› )(feedback|we want your feedback!?|go further|stay updated with aiven)$", re.I)


def dedupe(chunks: list[Chunk]) -> list[Chunk]:
    seen, out = set(), []
    for c in chunks:
        if BOILERPLATE.search(c.section.strip()):
            continue
        key = re.sub(r"\s+", " ", c.text).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


# --------------------------------------------------------------------------- main

def local_docs() -> list[Doc]:
    folder = settings.corpus_dir / "local"
    docs = []
    for f in sorted(folder.glob("*")) if folder.exists() else []:
        if f.suffix.lower() in (".md", ".txt"):
            title, text = clean_markdown(f.read_text(encoding="utf-8"))
            docs.append(Doc(doc_id_for(f.name), "", "local", "doc", title or f.stem, text))
    return docs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="ne pas télécharger, réutiliser data/corpus/")
    args = ap.parse_args()

    settings.corpus_dir.mkdir(parents=True, exist_ok=True)
    cache = settings.corpus_dir / "docs.jsonl"
    docs: list[Doc] = []
    if args.offline:
        if not cache.exists():
            raise SystemExit("Aucun corpus en cache : lancer d'abord sans --offline.")
        docs = [Doc(**json.loads(line)) for line in cache.read_text(encoding="utf-8").splitlines()]
    else:
        previous = {}
        if cache.exists():  # en cas d'échec réseau, on garde la version déjà téléchargée
            previous = {d["url"]: Doc(**d) for d in map(json.loads, cache.read_text(encoding="utf-8").splitlines())}
        failed = []
        for src in load_sources(settings.sources_file):
            for attempt in range(3):
                try:
                    d = fetch(src)
                    docs.append(d)
                    print(f"  ✔ {d.source:14} {len(d.text.split()):6} mots  {d.title[:70]}")
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        if src["url"] in previous:
                            docs.append(previous[src["url"]])
                            print(f"  ! {src['url']} : {exc} -> version en cache conservée")
                        else:
                            failed.append(src["url"])
                            print(f"  ✘ {src['url']} : {exc}")
        cache.write_text("\n".join(json.dumps(asdict(d), ensure_ascii=False) for d in docs), encoding="utf-8")
        if failed:
            print(f"! {len(failed)} source(s) en échec : base incomplète. Relancer `make ingest` avec une meilleure connexion.")
    docs += local_docs()

    chunks = dedupe([c for d in docs for c in chunk_doc(d, settings.chunk_words, settings.chunk_overlap)])
    with open(settings.chunks_file, "w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    by_src: dict[str, int] = {}
    for c in chunks:
        by_src[c.source] = by_src.get(c.source, 0) + 1
    print(f"OK : {len(docs)} documents, {len(chunks)} chunks -> {settings.chunks_file}  {by_src}")


if __name__ == "__main__":
    main()
