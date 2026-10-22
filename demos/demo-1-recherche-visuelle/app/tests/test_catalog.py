"""Tests unitaires (sans serveur Valkey) : construction des requêtes et lecture des réponses."""
from demo import catalog
from demo.catalog import Filters
from demo.prepare_dataset import synth_price, synth_stock, PRICE_RANGES
from demo.valkey_client import normalize_url


def test_slug():
    assert catalog.slug("Sports Shoes") == "sports_shoes"
    assert catalog.slug(" Navy-Blue ") == "navy_blue"


def test_empty_filter_gives_pure_knn():
    assert catalog.build_filter(Filters()) == ""
    assert catalog.build_knn_query(Filters(), 12) == "*=>[KNN 12 @embedding $vec AS score]"


def test_hybrid_filter():
    f = Filters(gender="Women", categories=["Sports Shoes", "Heels"], price_max=100, in_stock=True)
    assert catalog.build_filter(f) == (
        "@gender:{women} @category:{sports_shoes | heels} @price:[-inf 100] @stock:[1 +inf]"
    )
    q = catalog.build_knn_query(f, 8, ef_runtime=50)
    assert q.startswith("(@gender:{women}")
    assert q.endswith(")=>[KNN 8 @embedding $vec EF_RUNTIME 50 AS score]")


def test_price_bounds_and_text():
    assert catalog.build_filter(Filters(price_min=20.5)) == "@price:[20.5 +inf]"
    assert catalog.build_filter(Filters(text="running; DROP *")) == "@name:running @name:drop"


def test_knn_args_and_display():
    vec = b"\x00" * 512 * 4
    args = catalog.knn_search_args(Filters(gender="men"), vec, 5)
    assert args[:3] == ["FT.SEARCH", "idx:products", "(@gender:{men})=>[KNN 5 @embedding $vec AS score]"]
    assert args[args.index("PARAMS") + 3] == vec
    assert args[-2:] == ["DIALECT", "2"]
    ret = args.index("RETURN")
    assert args[ret + 1] == str(len(catalog.RETURN_FIELDS) + 1) and args[ret + 2 + len(catalog.RETURN_FIELDS)] == "score"
    shown = catalog.display_command(args)
    assert "<vecteur 512 x float32>" in shown and "\x00" not in shown


def test_browse_without_filter_uses_catch_all():
    assert catalog.browse_args(Filters(), 0, 10)[2] == "@price:[-inf +inf]"


def test_create_index_args():
    args = catalog.create_index_args()
    i = args.index("HNSW")
    assert args[i + 1] == "12"  # 6 paires attribut/valeur
    assert args[i + 2: i + 14:2] == ["TYPE", "DIM", "DISTANCE_METRIC", "M", "EF_CONSTRUCTION", "EF_RUNTIME"]
    assert "TEXT" not in catalog.create_index_args(with_text=False)


def test_parse_search_reply():
    raw = [2,
           b"product:1", [b"name", b"Nike Air", b"price", b"89.99", b"stock", b"3", b"score", b"0.1"],
           b"product:2", [b"name", b"Puma", b"price", b"49.99", b"stock", b"0", b"score", b"0.25"]]
    total, docs = catalog.parse_search_reply(raw)
    assert total == 2 and [d["key"] for d in docs] == ["product:1", "product:2"]
    assert docs[0]["price"] == 89.99 and docs[1]["stock"] == 0
    assert docs[0]["similarity"] == 0.9 and "score" not in docs[0]


def test_parse_nocontent_reply():
    total, docs = catalog.parse_search_reply([2, b"product:1", b"product:2"])
    assert total == 2 and [d["key"] for d in docs] == ["product:1", "product:2"]


def test_normalize_url():
    assert normalize_url("valkey://localhost:6379") == "redis://localhost:6379"
    assert normalize_url("valkeys://u:p@h:1") == "rediss://u:p@h:1"
    assert normalize_url("rediss://h:1") == "rediss://h:1"


def test_synthetic_price_and_stock_are_deterministic():
    lo, hi = PRICE_RANGES["sports shoes"]
    p = synth_price("123", "Sports Shoes")
    assert lo <= p <= hi and p == synth_price("123", "Sports Shoes")
    stocks = [synth_stock(str(i)) for i in range(1000)]
    assert 0.1 < stocks.count(0) / 1000 < 0.3 and max(stocks) <= 40
