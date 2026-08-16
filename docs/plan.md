# Plan

The near-term roadmap for Blog to Podcast. Terms used here (Article, Episode, Script, Script
Strategy, Episode Request, Episode Store) are defined in [`../CONTEXT.md`](../CONTEXT.md).
Decisions behind these choices are recorded in [`adr/`](./adr).

## Phase 1 — local excellence

Phase one is deliberately local-only. No cloud resources, no deployment. The goal is a tool that
is genuinely pleasant to run on one machine, structured so that phase two is re-wiring rather
than rewriting.

### 1. Prune inherited scaffolding

Remove `.platform-mode/`, `.github/prompts/`, `.github/instructions/`, and `utils/`. These came
from a web-application starter template and describe an architecture we are no longer building —
they mandate AKS and name Docker Hub as the container registry. Stale standards that contradict
the actual design are worse than no standards.

Reduce CI to lint and test. The `build-and-push` job depends on organisation variables created by
the bootstrap script being deleted, and pushes to a registry no infrastructure code describes.
It returns in phase two alongside the Terraform that creates the registry.

### 2. Configuration

Adopt `pydantic-settings`. Credentials resolve from the environment and an optional `.env` file,
replacing the hand-written `from_env` and `missing_fields` helpers and giving validation at
startup rather than empty-string checks. Remove the credential inputs from the Streamlit sidebar.

Separate credentials from the Episode Request. Credentials are infrastructure and come from the
environment; the Article, Script Strategy, and Voice are per-run choices supplied by whichever
entry point is asking.

### 3. Core seam

Extract `generate_episode(request) -> Episode`. Streamlit becomes a thin caller that handles
input and display only. Entry points own their own defaults — the planned API will default to
Narration where the UI does not — but the core always requires an explicit Script Strategy.

### 4. Both Script Strategies

Summary already exists as an agno-driven rewrite. Add Narration: scrape the Article, clean the
result for speech (navigation, code blocks, image captions), and keep it close to the source.
See [ADR 0001](./adr/0001-two-script-strategies-not-a-length-parameter.md).

### 5. Chunk and stitch

Split Scripts at paragraph boundaries into chunks sized to the active text-to-speech model's cap
(10,000 characters for the multilingual model, 40,000 for the faster ones), synthesize each, and
stitch the audio into one Episode. See
[ADR 0002](./adr/0002-chunk-long-scripts-rather-than-constrain-them.md).

### 6. Episode Store

Write Episodes to a local `episodes/` directory addressed by Article, Script Strategy, and Voice.
Serve from the store on a repeat request rather than re-paying for the scrape, the model, and
per-character speech synthesis. See [ADR 0003](./adr/0003-episodes-go-through-a-store.md).

### 7. Local development loop

`uv run` is the canonical everyday loop. Repair the devcontainer so it installs `uv` and reflects
this project rather than the inherited Python and Terraform image. Add a minimal compose file
whose only job is verifying the container image still works. Rewrite the README to match.

### 8. Tests

Cover chunk boundaries, Script Strategy selection, and Episode Store hit and miss.

## Phase 2 — cloud and async

Sequenced after phase one, in rough dependency order:

- **Terraform** for Container Apps, container registry, Key Vault, Storage, and Log Analytics,
  with OIDC and remote state. Azure Container Apps is the target: it hosts the current
  synchronous app and the later split worker without re-platforming, supports the WebSocket
  connections Streamlit needs, and scales to zero when idle.
- **CI/CD restored** — build, push, and deploy on merge, landing with the infrastructure that
  makes it meaningful.
- **Azure Storage backed Episode Store**, replacing the local directory implementation.
- **Entra authentication** in front of the app.
- **Async split** — move from a synchronous request to request-reply with a background worker,
  and add the API entry point that defaults to Narration.

## Open questions

- **Stitching mechanism** — ffmpeg in the image for clean joins, versus naive MP3 byte
  concatenation and the audible seams it can produce.
- **Does Streamlit survive phase 2**, or does the API plus a different front end replace it?
- **Cost guardrails on Narration** — whether to estimate and confirm spend before synthesizing a
  long Article.
