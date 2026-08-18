# Roadmap

The Blog to Podcast roadmap. Domain terms are defined in [`../CONTEXT.md`](../CONTEXT.md), and
hard-to-reverse decisions are recorded in [`adr/`](./adr).

## Phase 1 — local excellence (complete)

The local Streamlit tool generates Summary and Narration Episodes through a UI-independent
workflow. It retrieves Articles with Firecrawl, stitches long Narration audio with ffmpeg, retains
local Episode revisions, and asks for confirmation before expensive Narration work. Local
configuration, compose verification, documentation, and CI are aligned with this personal-use
workflow.

## Phase 2 — cloud and asynchronous generation

Phase 2 deploys the personal tool as a one-user Azure service without changing the core Episode
generation model.

### Foundation and delivery

- Deploy one parameterized production stack in Canada Central. Local compose remains the
  pre-production environment.
- Bootstrap protected Azure Storage Terraform state once with a documented Azure CLI procedure.
  Terraform manages every application resource after that boundary.
- Terraform owns the Azure resources and dedicated Entra application registrations. One-time
  directory permissions and consent are documented prerequisites.
- Pull requests run checks, build the image, and produce a read-only Terraform plan. Merges to
  `main` apply Terraform, publish an immutable SHA-tagged image to ACR, and deploy it through
  GitHub Actions OIDC. CI holds no Azure or provider secrets.

### Runtime and identity

- Use Azure Container Apps for three independently deployed roles from one immutable Python image:
  Streamlit UI, FastAPI API, and queue worker. Split role-specific images only when the compressed
  image exceeds 500 MiB or scale-from-zero consistently exceeds 30 seconds.
- Require Entra authentication on the public UI and API, restricted to the owner or an explicit
  one-member allowlist. The worker has no public ingress.
- The UI calls the API with its managed identity and a narrow API app role. Direct API clients
  present Entra user tokens and face the same identity allowlist.
- Do not add a VNet or private endpoints in phase 2. Use public service endpoints protected by
  Entra, managed identities, RBAC, HTTPS, and hardened service settings.
- Terraform provisions a dedicated Azure OpenAI resource and model deployment. Applications use
  least-privilege managed-identity access rather than an Azure OpenAI API key.
- Firecrawl and ElevenLabs keys remain Key Vault secrets readable only by the worker identity.

### Asynchronous Episode generation

- A `POST` to create an Episode returns `202 Accepted`, a Generation Job identifier, and a status
  URL. Clients poll status and retrieve completed Episodes through authenticated API routes.
- Generation Job statuses are `queued`, `retrieving`, `awaiting_confirmation`, `synthesizing`,
  `stitching`, `completed`, `failed`, and `cancelled`, each with a listener-readable message.
- Azure Storage Queue delivers work to a queue-scaled worker. Azure Table Storage tracks Generation
  Jobs and Episode metadata; Blob Storage holds completed audio and generated Scripts.
- An above-threshold Narration transitions to `awaiting_confirmation` after retrieval and
  estimation. An explicit confirmation requeues synthesis. Cancellation is permitted until
  synthesis starts.
- Allow one active worker and one Episode generation at a time; queue additional requests.
- Use idempotent at-least-once processing, bounded exponential retries for transient failures,
  safe terminal errors, and a poison queue for exhausted messages.
- Start the cloud Episode Store empty. Retain completed Episodes, metadata, and Scripts
  indefinitely; expire raw source material, temporary artifacts, and failed/cancelled Job records
  after 30 days.

### Observability

- Instrument API and worker with the Azure Monitor OpenTelemetry distribution. Export traces,
  metrics, logs, and exceptions to Application Insights/Azure Monitor.
- Correlate telemetry with Generation Job and Episode identity, never Article text, sensitive URLs,
  audio, or credentials.
- Keep Log Analytics data for 30 days. Alert by email on poison-queue messages, repeated worker
  failures, and unavailable public ingress.

## Deferred

- A second cloud environment, VNet/private endpoints, shared-user capabilities, and source-policy
  enforcement.
- Importing the local Episode Store into the cloud store.
- API percentage-complete estimates, browser-based streaming progress, and a replacement for
  Streamlit.
