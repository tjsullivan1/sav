# 📰 ➡️ 🎙️ Blog to Podcast

A Streamlit app that turns any public blog post into a podcast episode. It scrapes the
article with **Firecrawl**, summarizes it into a conversational script with **Azure OpenAI**
(via an [agno](https://github.com/agno-agi/agno) agent), and narrates it with **ElevenLabs**.

## 🏗️ Repository Structure

```
├── .github/
│   └── workflows/
│       ├── ci.yml                    # Lint, test, build & push image to ACR
│       └── dependabot.yml            # Dependency updates configuration
├── src/
│   └── blog_to_podcast/
│       ├── app.py                    # Streamlit UI
│       ├── __main__.py               # CLI entry point (`blog-to-podcast`)
│       ├── config.py                 # Settings resolved from env / sidebar
│       ├── summarizer.py             # Firecrawl scrape + Azure OpenAI summary
│       └── tts.py                    # ElevenLabs text-to-speech
├── tests/                            # pytest suite mirroring src/
├── Dockerfile                        # Multi-stage uv + Python 3.12 image
├── pyproject.toml                    # Project, ruff, and pytest config
└── uv.lock                           # Locked dependencies
```

## 🚀 Features

- **Blog scraping** — pulls the full content of any public blog URL via Firecrawl.
- **Summary generation** — an agno agent produces an engaging summary (≤ 2000 characters).
- **Podcast generation** — converts the summary to MP3 audio with an ElevenLabs voice.
- **Flexible credentials** — read from environment variables, overridable in the sidebar.
- **Container ready** — multi-stage Docker build with a health check and non-root user.

## 🛠️ Technology Stack

- **Language**: Python 3.12
- **UI**: Streamlit
- **Agent framework**: agno + Azure OpenAI (v1 API surface)
- **Scraping**: Firecrawl
- **TTS**: ElevenLabs
- **Tooling**: uv, ruff, pytest
- **CI/CD**: GitHub Actions → Azure Container Registry

## 🏁 Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/):
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Windows
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- API keys for **Azure OpenAI**, **ElevenLabs**, and **Firecrawl**.

### Local development

```bash
uv sync                      # create the virtualenv and install dependencies
cp .env.example .env         # optional: pre-fill credentials
uv run streamlit run src/blog_to_podcast/app.py
```

Then open http://localhost:8501, fill in any missing keys in the sidebar, paste a blog URL,
and click **🎙️ Generate Podcast**.

### Configuration

Every value can be supplied via environment variable or entered in the sidebar at runtime.

| Variable | Required | Description |
| --- | --- | --- |
| `AZURE_OPENAI_BASE_URL` | ✅ | v1 base URL, e.g. `https://<resource>.openai.azure.com/openai/v1/` |
| `AZURE_OPENAI_DEPLOYMENT` | ✅ | Chat model deployment name, e.g. `gpt-4o` |
| `AZURE_OPENAI_API_KEY` | ✅ | Azure OpenAI API key |
| `ELEVENLABS_API_KEY` | ✅ | ElevenLabs API key |
| `FIRECRAWL_API_KEY` | ✅ | Firecrawl API key |
| `ELEVENLABS_VOICE_ID` | — | Voice override (default `JBFqnCBsd6RMkjVDRZzb`) |
| `ELEVENLABS_MODEL_ID` | — | TTS model override (default `eleven_multilingual_v2`) |

### Tests and linting

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### Docker

```bash
docker build -t blog-to-podcast .
docker run --rm -p 8501:8501 --env-file .env blog-to-podcast
```

## 🙏 Credits

Adapted from the `ai_blog_to_podcast_agent` starter in
[Shubhamsaboo/awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps), using the
uv + Azure OpenAI variant from
[PR #1096](https://github.com/Shubhamsaboo/awesome-llm-apps/pull/1096).

## 📄 License

See [LICENSE](LICENSE).
