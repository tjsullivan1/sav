# Entra and Managed Identities for Production Access

The public UI and API require Entra authentication restricted to the owner or a one-member
allowlist, while the worker has no public ingress. Each role uses its managed identity with
least-privilege access: the UI holds a narrow API role, the worker reads external-provider secrets
from Key Vault, and Azure OpenAI access uses RBAC rather than an API key. This keeps a personal
tool private without distributing long-lived credentials.
