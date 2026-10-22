"""English versions of the session diagrams (same layout and colours as the French PNGs).

Usage: python3 make_en_diagrams.py  → writes images/en/*.png
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BLUE, LIGHT, GREY, DASH = "#000E9D", "#E8EBFF", "#5A5F73", "#4A5BFF"
GREEN, MINT, ORANGE = "#0B8A4E", "#7FE0A0", "#FFB27A"
OUT = Path(__file__).parent / "en"
W, H = 1320, 850


def canvas():
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    return fig, ax


def box(ax, x, y, w, h, fill="white", edge=BLUE, lw=2.5, r=18, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fill, ec=edge, lw=lw, ls=ls))


def text(ax, x, y, s, size=14, color=BLUE, weight="normal", ha="center", family="DejaVu Sans"):
    ax.text(x, y, s, fontsize=size, color=color, weight=weight, ha=ha, va="center", family=family)


def arrow(ax, p, q, color=BLUE, lw=2.5):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=24, color=color, lw=lw,
                                 shrinkA=0, shrinkB=0))


def node(ax, x, y, w, h, title, sub, fill="white", tsize=19, ssize=13.5, subcolor=None):
    box(ax, x, y, w, h, fill=fill)
    dark = fill == BLUE
    text(ax, x + w / 2, y + h * 0.40, title, tsize, "white" if dark else BLUE, "bold")
    text(ax, x + w / 2, y + h * 0.69, sub, ssize, "white" if dark else (subcolor or GREY))


def save(fig, name):
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / name, dpi=100, facecolor="white")
    plt.close(fig)


def rag():
    fig, ax = canvas()
    box(ax, 45, 60, 1230, 745, edge=DASH, lw=2, r=22, ls=(0, (4, 3)))
    text(ax, 79, 94, "OVHcloud region (EU)", 17, DASH, "bold", ha="left")
    node(ax, 76, 160, 238, 160, "Documents", "PDF, docs, blog", subcolor=BLUE)
    node(ax, 440, 160, 316, 160, "AI Endpoints", "BGE-M3 · embeddings", fill=LIGHT)
    node(ax, 874, 314, 378, 206, "Managed Valkey 9.1", "Search · history · cache", fill=BLUE, tsize=21, ssize=14.5)
    node(ax, 76, 591, 238, 160, "User", "asks a question", subcolor=BLUE)
    node(ax, 440, 591, 316, 160, "RAG application", "orchestration", fill=LIGHT)
    node(ax, 874, 591, 378, 160, "AI Endpoints", "Mistral Small 3.2 · LLM", fill=LIGHT)
    arrow(ax, (314, 240), (440, 240)); text(ax, 377, 210, "① chunking", 14, GREY)
    arrow(ax, (756, 273), (874, 360)); text(ax, 838, 290, "② HSET", 14, GREY, ha="left")
    arrow(ax, (724, 593), (874, 489)); text(ax, 812, 560, "③ FT.SEARCH", 14, GREY, ha="left")
    arrow(ax, (314, 671), (440, 671))
    arrow(ax, (756, 702), (874, 702)); text(ax, 815, 680, "④ prompt", 14, GREY)
    save(fig, "rag-architecture.png")


def embeddings():
    fig, ax = canvas()
    rows = [(194, "“A very happy person”", "[0.12, -0.48, 0.91, …]"),
            (386, "“A happy girl”", "[0.10, -0.45, 0.88, …]"),
            (578, "“I love dogs”", "[-0.73, 0.22, 0.05, …]")]
    box(ax, 525, 129, 270, 515, fill=BLUE, edge=BLUE)
    text(ax, 660, 325, "Embedding\nmodel", 20, "white", "bold")
    text(ax, 660, 487, "BGE-M3", 14, "white")
    for y, s, v in rows:
        box(ax, 53, y - 57, 393, 114)
        text(ax, 249, y, s, 15, BLUE, "bold")
        arrow(ax, (452, y), (517, y))
        arrow(ax, (801, y), (865, y))
        text(ax, 885, y, v, 16, BLUE, ha="left", family="DejaVu Sans Mono")
    text(ax, 660, 739, "Close in meaning  →  close in vector space", 21, BLUE, "bold")
    save(fig, "embeddings.png")


def agent_memory():
    fig, ax = canvas()
    box(ax, 456, 53, 811, 744, r=20)
    text(ax, 861, 84, "One Valkey 9.1", 23, BLUE, "bold")
    items = [("Semantic cache", "vectors + TTL: skip the model call", "demo 3"),
             ("Semantic router", "vectorised examples: pick the model", "demo 3"),
             ("Working memory", "hash + TTL: current task state", None),
             ("Episodic memory", "stream: history, action log", "demo 2"),
             ("Semantic memory", "indexed vectors: knowledge, facts", "demo 2")]
    for i, (t, s, badge) in enumerate(items):
        y = 130 + i * 123
        node(ax, 494, y, 611, 98, t, s, fill=LIGHT, tsize=19, ssize=13)
        arrow(ax, (313, 417), (490, y + 49))
        if badge:
            box(ax, 1122, y + 27, 122, 44, fill=GREEN, edge=GREEN, r=12)
            text(ax, 1183, y + 49, badge, 13.5, "white", "bold")
    node(ax, 45, 330, 269, 175, "Agent", "plans · acts · observes", tsize=22, ssize=15.5, subcolor=BLUE)
    box(ax, 60, 606, 240, 162, fill=BLUE, edge=BLUE)
    text(ax, 180, 664, "LLM", 21, "white", "bold")
    text(ax, 180, 720, "small or large,\npicked by the router", 14.5, "white")
    arrow(ax, (180, 505), (180, 602))
    text(ax, 195, 556, "if the cache\nhad no answer", 14, GREY, ha="left")
    save(fig, "agent-memory.png")


def routing():
    fig, ax = canvas()
    node(ax, 45, 345, 215, 145, "Query", "“Sum up this mail”", tsize=19, ssize=12.5, subcolor=BLUE)
    node(ax, 301, 345, 191, 145, "Embedding", "BGE-M3", fill=LIGHT, tsize=19)
    box(ax, 533, 252, 332, 330, fill=BLUE, edge=BLUE)
    text(ax, 699, 301, "Valkey: KNN", 21, "white", "bold")
    text(ax, 699, 357, "5 nearest examples", 14, "white")
    for i, (lab, sc) in enumerate([("simple", "0.91"), ("simple", "0.88"), ("simple", "0.85"),
                                   ("complex", "0.62"), ("simple", "0.60")]):
        c = ORANGE if lab == "complex" else MINT
        text(ax, 616, 411 + i * 31, lab, 14, c, ha="left", family="DejaVu Sans Mono")
        text(ax, 733, 411 + i * 31, sc, 14, c, ha="left", family="DejaVu Sans Mono")
    node(ax, 983, 130, 292, 144, "Small model", "Mistral Small 3.2", fill=LIGHT, tsize=19)
    node(ax, 983, 561, 292, 144, "Large model", "gpt-oss-120b", fill=LIGHT, tsize=19)
    arrow(ax, (260, 417), (299, 417)); arrow(ax, (492, 417), (531, 417))
    arrow(ax, (865, 329), (983, 213)); arrow(ax, (865, 505), (983, 621))
    text(ax, 1128, 312, "if majority “simple”", 15, GREY)
    text(ax, 1128, 515, "if “complex”\nor score < threshold", 15, GREY)
    box(ax, 115, 699, 780, 98)
    text(ax, 505, 748, "Wrong route? Add the query as a new example", 14.5, BLUE, "bold")
    arrow(ax, (600, 699), (642, 584), color=DASH)
    save(fig, "semantic-routing.png")


if __name__ == "__main__":
    for f in (rag, embeddings, agent_memory, routing):
        f()
    print("→", OUT)
