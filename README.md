# Blog to Podcast

Blog to Podcast is a local Streamlit tool that turns an eligible public article into a concise,
conversational audio summary or a speech-cleaned, near-verbatim narration. Firecrawl retrieves the
article, Azure OpenAI (through [agno](https://github.com/agno-agi/agno)) writes summaries, and
ElevenLabs synthesizes the audio.

Generated episodes are retained locally in `.sav/episodes/`. Repeating a request reuses the stored
audio when available. When normalized article content is supplied with a new fingerprint, the app
retains a new revision and marks it as `UPDATED CONTENT` for listeners. Select **Check for updated
article content** to retrieve the source again and detect a new revision.

## Episode generation

The UI delegates episode creation to the UI-independent `EpisodeGenerationWorkflow`. An
`EpisodeRequest` carries the article, script strategy, and voice selection, while credentials stay
in runtime configuration. The UI requires an explicit strategy selection. Summary Episodes use
agno/Azure OpenAI for a conversational rewrite; Narration Episodes retain the article substance
while cleaning Markdown material unsuitable for speech. Narration splits long scripts at paragraph
boundaries and uses ffmpeg to stitch synthesized chunks into one playable Episode.

Before a Narration run above the configured character threshold, the UI displays its estimated
character count and listening duration. Select the confirmation box and run it again to begin
synthesis. Configure the threshold and model cap with `NARRATION_CONFIRMATION_THRESHOLD`,
`NARRATION_CHARACTERS_PER_MINUTE`, and `ELEVENLABS_TTS_CHARACTER_CAP`.

## Local development

Install [uv](https://docs.astral.sh/uv/) and
[FFmpeg](https://ffmpeg.org/download.html) (which provides `ffprobe`), then use them for the normal
development workflow:

```powershell
uv sync
Copy-Item .env.example .env
uv run streamlit run src/blog_to_podcast/app.py
```

Open <http://localhost:8501>. Credentials are loaded from your environment and, when present, the
local `.env` file. They are never entered through the application UI. The app identifies missing
required variables at startup.

| Variable | Required | Description |
| --- | --- | --- |
| `AZURE_OPENAI_BASE_URL` | Yes | v1 base URL, such as `https://<resource>.openai.azure.com/openai/v1/` |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | Chat model deployment name |
| `AZURE_OPENAI_API_KEY` | Yes | Azure OpenAI API key |
| `ELEVENLABS_API_KEY` | Yes | ElevenLabs API key |
| `FIRECRAWL_API_KEY` | Yes | Firecrawl API key |
| `ELEVENLABS_VOICE_ID` | No | Default Voice ID; the UI can override it for an Episode |
| `ELEVENLABS_MODEL_ID` | No | Text-to-speech model override |

Run checks with:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Local container verification

Build and run the production image locally with Docker Compose:

```powershell
docker compose up --build
```

Compose reads `.env` when it exists. Stop the application with `docker compose down`.

## Azure delivery bootstrap

The production Terraform foundation uses an Azure AD-protected remote state backend and GitHub
Actions OIDC; it does not use stored Azure credentials. Follow the one-time
[Terraform state and GitHub OIDC bootstrap](docs/terraform-bootstrap.md) before opening a pull
request that changes infrastructure.

## Cloud Summary smoke path

After deploying an immutable image tag and setting the worker's Azure OpenAI, Firecrawl, and
ElevenLabs secrets, submit an authenticated `summary` request to
`POST /v1/generation-jobs`. Poll the returned `status_url` until its status is `completed`, then
retrieve `GET /v1/generation-jobs/{id}/episode` with the same Entra bearer token. Submit the same
request again to verify the worker reports the retained Episode as ready without regenerating it.

## Cloud UI

The public Streamlit Container App is protected by Container Apps Entra authentication and the
configured `owner_object_id`. After the owner signs in, the UI obtains its own managed-identity
token for the Episode API; it never forwards the browser token or loads provider credentials.
Submit an Episode Request, select **Refresh Job Status** while it is running, choose **Cancel Job**
before synthesis if needed, and play or download the completed Episode from the authenticated UI.

## Personal-use source boundary

Use this tool only for public content you are entitled to process. Respect site terms, robots
controls, authentication and paywalls, and rate limits. It does not bypass those controls.

## License

See [LICENSE](LICENSE).
