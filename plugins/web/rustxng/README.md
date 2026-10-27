# RustXNG Web Search Provider for Hermes

This plugin provides a RustXNG web search backend for Hermes. RustXNG is a SearXNG-compatible metasearch engine written in Rust with the same API surface.

## Quick Start

### 1. Start a RustXNG Instance

You can run RustXNG via Docker (recommended) or build from source.

#### Docker (Recommended)
```bash
# Build and start
python rustxng_manager.py docker-build
python rustxng_manager.py start --mode docker

# Or manually:
docker build -t rustxng:local /path/to/hermes-agent/plugins/rustxng
docker run -d -p 8888:8888 --name rustxng-hermes rustxng:local
```

#### From Source
```bash
# Build from source (requires Rust toolchain)
python rustxng_manager.py build

# Then run manually:
/path/to/rustxng --port 8888
```

### 2. Configure Hermes

Add to your `~/.hermes/config.yaml`:

```yaml
web:
  search_backend: "rustxng"
  backend: "rustxng"  # fallback for both search and extract
```

And set the environment variable (or add to `~/.hermes/.env`):

```bash
RUSTXNG_URL=http://localhost:8888
```

### 3. Verify

```bash
hermes tools
# Should show "RustXNG" as an available web search provider

# Test search
hermes chat "search for rust programming language"
```

## Features

- **SearXNG API Compatible** - Same `/search?q=...&format=json` endpoint and response format
- **200+ Search Engines** - Google, Bing, DuckDuckGo, Brave, GitHub, arXiv, PubMed, etc.
- **Privacy Respecting** - No tracking, images proxied, IP hidden from upstream
- **Fast** - ~0.03s startup, ~13MiB memory, ~0.27s for 169 engines
- **Self-Hosted** - Full control over your search infrastructure

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `RUSTXNG_URL` | RustXNG instance URL | Required |
| `web.search_backend` | Explicit search backend | `rustxng` |
| `web.backend` | Shared fallback | `rustxng` |

## Search Syntax

RustXNG supports SearXNG bang syntax:

- `!wikipedia rust` - Search only Wikipedia
- `!github tokio` - Search only GitHub
- `!arxiv quantum computing` - Search only arXiv
- `!youtube rust tutorial` - Search only YouTube

## Time Range Filters

- `time_range=day` - Past 24 hours
- `time_range=week` - Past week
- `time_range=month` - Past month
- `time_range=year` - Past year

## API Usage

```bash
# JSON results
curl 'http://localhost:8888/search?q=rust&format=json'

# Past day only
curl 'http://localhost:8888/search?q=rust&time_range=day&format=json'

# Specific site
curl 'http://localhost:8888/search?q=%21github+tokio&format=json'
```

## Management Commands

```bash
# Check status
python rustxng_manager.py status

# Stop
python rustxng_manager.py stop

# Rebuild
python rustxng_manager.py build
python rustxng_manager.py docker-build
```

## Troubleshooting

### "SEARXNG_URL is not set" / "RUSTXNG_URL is not set"
Make sure the environment variable is set in your shell or `~/.hermes/.env`:
```bash
echo 'RUSTXNG_URL=http://localhost:8888' >> ~/.hermes/.env
```

### Connection Refused
Check if RustXNG is running:
```bash
python rustxng_manager.py status
# Or manually:
curl http://localhost:8888/search?q=test&format=json
```

### Build Fails
Ensure Rust is installed:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source ~/.cargo/env
cargo --version
```

## License

AGPL-3.0-or-later (same as RustXNG and SearXNG).

## References

- [RustXNG Repository](https://github.com/zapabob/RustXNG)
- [SearXNG Documentation](https://docs.searxng.org/)
- [Hermes Web Search Providers](../)