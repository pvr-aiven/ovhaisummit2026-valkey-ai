# Valkey & AI: your cache already searches

Breakout session at the **OVHcloud AI Summit 2026** (19 November 2026, Paris, Carrousel du Louvre), co-presented by:

- **Philippe VINCENT-ROYOL**, Solutions Architect at Aiven
- **Bastien BELLION**, Architect at OVHcloud

Hybrid search, RAG, semantic caching and agent memory with **Valkey 9.1 + Valkey Search**, on a 100% open source stack: Valkey in Docker, OVHcloud Managed Valkey or Aiven for Valkey; open models on OVHcloud AI Endpoints, or Ollama without Internet.

> 🇫🇷 Session présentée en français, slides en anglais. Les modes opératoires des démos sont en français.

## Slides

| | English | Français |
|---|---|---|
| PDF | [valkey-ai-summit2026-en.pdf](valkey-ai-summit2026-en.pdf) | [valkey-ai-summit2026.pdf](valkey-ai-summit2026.pdf) |
| PowerPoint | [valkey-ai-summit2026-en.pptx](valkey-ai-summit2026-en.pptx) | [valkey-ai-summit2026.pptx](valkey-ai-summit2026.pptx) |
| Source (Markdown) | [session-en.md](session-en.md) | [session.md](session.md) |

## Demos

| # | Demo | What it shows | UI |
|---|---|---|---|
| 1 | [Visual and hybrid search](demos/demo-1-recherche-visuelle/README.md) | 3,000 shoes, CLIP image embeddings, HNSW index, filters + KNN in one `FT.SEARCH`, search by photo or by French text | http://localhost:8000 |
| 2 | [End-to-end RAG assistant](demos/demo-2-rag/README.md) | BGE-M3 + Mistral Small 3.2, sourced answers, hybrid retrieval with filters, conversation history in a Valkey stream | http://localhost:8001 |
| 3 | [Semantic caching and routing](demos/demo-3-cache-routage/README.md) | exact + semantic cache, KNN router (small vs large model), live counters of tokens and euros saved | http://localhost:8002 |

Demos 1 and 3 have a **"Comment ça marche"** tab that replays, step by step, what happens in Valkey; demo 2 shows it in its **"Sous le capot"** panel.

### Quick start

Requirements: Docker with **Compose ≥ 2.24**, `make`, ~6 GB of disk space.

```bash
git clone git@github.com:pvr-aiven/ovhaisummit2026-valkey-ai.git
cd ovhaisummit2026-valkey-ai/demos/demo-1-recherche-visuelle
make prepare      # build, dataset, embeddings, index, checks (10-15 min the first time)
make up           # → http://localhost:8000
```

Demos 2 and 3 call OVHcloud AI Endpoints: copy `env/secrets.env.example` to `env/secrets.env` and paste your API key. Without a key, anonymous access works but is heavily rate-limited.

### Same commands, same targets

```bash
make <command> TARGET=local           # Valkey 9.1 in Docker (+ AI Endpoints for demos 2 and 3), default
make <command> TARGET=local-offline   # Valkey 9.1 in Docker, no Internet (Ollama for demos 2 and 3: `make ollama`)
make <command> TARGET=ovhcloud        # OVHcloud Managed Valkey 9.1 (+ AI Endpoints)
make <command> TARGET=aiven           # Aiven for Valkey
```

| Command | What it does |
|---|---|
| `make help` | list commands and the current target |
| `make prepare` | build, data, index and checks, all at once |
| `make up` / `make down` | start / stop the UI |
| `make reset` | reset the demo to its initial state |
| `make check` | check Valkey, the index, the models and latencies |
| `make cli` | `valkey-cli` on the current target |

For `ovhcloud` and `aiven`, copy `env/<target>.env.example` to `env/<target>.env` and fill in the service URI. Full details in [demos/README.md](demos/README.md) and each demo's README.

### Private network on OVHcloud

[infra/ovhcloud/](infra/ovhcloud/README.md) runs the three demos on OVHcloud with Terraform: Managed Valkey 9.1 with no public address, a VM without a public IP on the same private subnet, and a load balancer that only lets the allowed IPs reach the UIs.

## Repository layout

```
├── session.md, session-en.md     slide sources (FR / EN)
├── valkey-ai-summit2026*.pdf/pptx generated decks
├── images/                       diagrams (images/en/ for the English deck)
├── demos/
│   ├── demo-1-recherche-visuelle/
│   ├── demo-2-rag/
│   └── demo-3-cache-routage/
└── infra/ovhcloud/               Terraform: the demos on OVHcloud, in a private network
```

No secret is versioned: `*.env` files, keys and certificates are ignored by Git; only `*.env.example` templates are committed.

## Learn more

- [Valkey](https://valkey.io) and [Valkey Search](https://github.com/valkey-io/valkey-search)
- [OVHcloud Managed Databases for Valkey](https://www.ovhcloud.com/en/public-cloud/valkey/) and [AI Endpoints](https://endpoints.ai.cloud.ovh.net/)
- [Aiven for Valkey](https://aiven.io/valkey)
