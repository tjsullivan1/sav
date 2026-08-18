"""Static contract tests for the Azure delivery workflow."""

from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/ci.yml")


def test_pull_request_delivery_uses_oidc_and_plan_only() -> None:
    """Ensure pull-request infrastructure validation cannot mutate Azure."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "id-token: write" in workflow
    assert "azure/login@v2" in workflow
    assert "vars.AZURE_CLIENT_ID != ''" in workflow
    assert "client-id: ${{ vars.AZURE_CLIENT_ID }}" in workflow
    assert "tenant-id: ${{ vars.AZURE_TENANT_ID }}" in workflow
    assert "subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}" in workflow
    assert "terraform plan -input=false -lock=false -out=tfplan" in workflow
    assert "terraform apply" not in workflow


def test_delivery_workflow_does_not_accept_stored_azure_credentials() -> None:
    """Reject long-lived Azure credential inputs in CI configuration."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "AZURE_CREDENTIALS" not in workflow
    assert "credentials:" not in workflow
    assert "client-secret:" not in workflow
    assert "secrets.AZURE_" not in workflow
