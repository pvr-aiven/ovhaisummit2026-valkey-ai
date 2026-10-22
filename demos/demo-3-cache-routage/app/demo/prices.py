"""Prix AI Endpoints (€ HT par million de tokens), lus sur la page des prix OVHcloud.

`make prices` met à jour data/prices.json ; à défaut, on utilise les valeurs relevées le 12/10/2026.
"""
from __future__ import annotations

import json
import re

from .config import settings

PRICES_URL = "https://www.ovhcloud.com/fr/public-cloud/prices/"
# Relevé du 12/10/2026, section #ai-endpoints de la page des prix (HT, €/1M tokens : entrée, sortie)
DEFAULT_PRICES = {
    "Meta-Llama-3_3-70B-Instruct": (0.67, 0.67), "Mistral-7B-Instruct-v0.3": (0.10, 0.10),
    "Mistral-Nemo-Instruct-2407": (0.13, 0.13), "Mistral-Small-3.2-24B-Instruct-2506": (0.09, 0.28),
    "Qwen2.5-VL-72B-Instruct": (0.91, 0.91), "Qwen3-32B": (0.08, 0.23), "Qwen3-Coder-30B-A3B-Instruct": (0.06, 0.22),
    "Qwen3.5-397B-A17B": (0.60, 3.60), "Qwen3.5-9B": (0.10, 0.15), "Qwen3.6-27B": (0.40, 2.70),
    "Qwen3.8-27B": (0.40, 2.70), "gpt-oss-120b": (0.08, 0.40), "gpt-oss-20b": (0.04, 0.15), "bge-m3": (0.01, 0.0),
}


def _euro(txt: str) -> float | None:
    t = txt.strip().lower()
    if t in ("gratuit", "free"):
        return 0.0
    m = re.search(r"(\d+(?:[.,]\d+)?)", t)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_prices(html: str) -> dict[str, tuple[float, float]]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="ai-endpoints")
    if node is None:
        raise ValueError("section #ai-endpoints introuvable")
    for _ in range(8):
        if node.find("table") or node.parent is None:
            break
        node = node.parent
    out = {}
    for table in node.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        if not rows or len(rows[0]) != 3:  # tableaux « modèle | entrée | sortie » uniquement (pas Whisper, à l'heure)
            continue
        for r in rows[1:]:
            if len(r) >= 2 and r[0]:
                pin = _euro(r[1])
                pout = _euro(r[2]) if len(r) > 2 else 0.0
                if pin is not None:
                    out[r[0]] = (pin, pout or 0.0)
    return out


def refresh() -> dict:
    import httpx

    r = httpx.get(PRICES_URL, headers={"User-Agent": "Mozilla/5.0 (demo)"}, timeout=30, follow_redirects=True)
    r.raise_for_status()
    prices = parse_prices(r.text)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.prices_file.write_text(json.dumps(prices, indent=1, ensure_ascii=False))
    return prices


def load() -> dict[str, tuple[float, float]]:
    try:
        return {k: tuple(v) for k, v in json.loads(settings.prices_file.read_text()).items()}
    except Exception:  # noqa: BLE001
        return dict(DEFAULT_PRICES)


def cost(model: str, tokens_in: int, tokens_out: int, table: dict | None = None) -> float:
    """Coût en € HT d'un appel."""
    p_in, p_out = (table or load()).get(model, (0.0, 0.0))
    return (tokens_in or 0) / 1e6 * p_in + (tokens_out or 0) / 1e6 * p_out


if __name__ == "__main__":  # python -m demo.prices
    p = refresh()
    print(f"{len(p)} prix relevés -> {settings.prices_file}")
    for m in (settings.simple_price_model, settings.complex_price_model):
        print(f"  {m:40} entrée {p.get(m, ('?', '?'))[0]} €/M · sortie {p.get(m, ('?', '?'))[1]} €/M")
