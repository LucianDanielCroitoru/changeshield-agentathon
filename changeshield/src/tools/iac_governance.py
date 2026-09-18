"""
ChangeShield IaC Production Governance Tool.

This module deterministically evaluates supplied Terraform/IaC scenario data.
It is read-only: it does not execute Terraform, call Azure APIs, or alter
cloud infrastructure.

Usage:
    python changeshield/src/tools/iac_governance.py \
        changeshield/data/scenarios/high-risk-payment-platform-iac.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


TOOL_NAME = "analyze_iac_governance"

POLICY_REFERENCES = [
    "IAC-PROD-01",
    "IAC-PROD-02",
    "IAC-PROD-03",
    "IAC-PROD-04",
    "IAC-PROD-05",
    "IAC-PROD-06",
    "IAC-PROD-07",
]

REQUIRED_TAGS = {"Environment", "Owner", "CostCenter"}

TLS_RANK = {
    "TLS1_0": 1.0,
    "TLS1_1": 1.1,
    "TLS1_2": 1.2,
    "TLS1_3": 1.3,
}


def load_scenario(path: str | Path) -> dict[str, Any]:
    """Load an IaC scenario from a JSON file."""
    with Path(path).open(encoding="utf-8") as scenario_file:
        return json.load(scenario_file)


def finding(
    policy: str,
    severity: str,
    title: str,
    evidence: str,
    recommendation: str,
) -> dict[str, str]:
    """Build a consistent, serializable policy finding."""
    return {
        "policy_reference": policy,
        "severity": severity,
        "title": title,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def tls_value(value: str | None) -> float:
    """Return a comparable TLS version value; unknown values fail closed."""
    return TLS_RANK.get(value or "", 0.0)


def analyze_iac_governance(scenario: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate production IaC governance controls deterministically.

    The score is capped at 100. A high-severity finding blocks execution.
    """
    findings: list[dict[str, str]] = []
    resources = scenario.get("resources", [])
    controls = scenario.get("change_controls", {})
    environment = scenario.get("environment", "unknown")

    for resource in resources:
        resource_name = resource.get("name", "unnamed-resource")
        resource_type = resource.get("resource_type", "unknown-resource")
        label = f"{resource_type}.{resource_name}"

        if resource.get("allow_blob_public_access") is True:
            findings.append(
                finding(
                    "IAC-PROD-01",
                    "HIGH",
                    "Anonymous public data access is enabled",
                    f"{label} sets allow_blob_public_access=true.",
                    "Disable anonymous public access or provide an approved "
                    "security exception with compensating controls.",
                )
            )

        public_network = resource.get("public_network_access_enabled")
        default_action = resource.get("network_default_action")

        if public_network is True and default_action == "Allow":
            findings.append(
                finding(
                    "IAC-PROD-02",
                    "HIGH",
                    "Public network access allows all networks",
                    f"{label} enables public network access with "
                    "network_default_action=Allow.",
                    "Disable public network access and use a private endpoint "
                    "or an approved restricted firewall allowlist.",
                )
            )

        configured_tls = resource.get("minimum_tls_version")

        if tls_value(configured_tls) < 1.2:
            findings.append(
                finding(
                    "IAC-PROD-03",
                    "HIGH",
                    "Minimum TLS version is below TLS 1.2",
                    f"{label} sets minimum_tls_version={configured_tls!r}.",
                    "Set the minimum TLS version to TLS1_2 or later.",
                )
            )

        if (
            resource.get("customer_managed_key_required") is True
            and resource.get("customer_managed_key_configured") is not True
        ):
            findings.append(
                finding(
                    "IAC-PROD-04",
                    "HIGH",
                    "Required customer-managed encryption key is absent",
                    f"{label} requires a customer-managed key but none is configured.",
                    "Configure an approved customer-managed key and record "
                    "the required key-management approval.",
                )
            )

        tags = resource.get("tags") or {}
        missing_tags = sorted(REQUIRED_TAGS - set(tags))

        if missing_tags:
            findings.append(
                finding(
                    "IAC-PROD-05",
                    "MEDIUM",
                    "Mandatory production resource tags are missing",
                    f"{label} is missing tags: {', '.join(missing_tags)}.",
                    "Add Environment, Owner, and CostCenter tags before "
                    "production execution.",
                )
            )

    if controls.get("security_approval_present") is not True:
        findings.append(
            finding(
                "IAC-PROD-06",
                "HIGH",
                "Required security approval is missing",
                "security_approval_present=false for this production IaC change.",
                "Obtain explicit approval from an authorised security or "
                "platform approver before any Terraform apply.",
            )
        )

    exposure_or_encryption_change = any(
        resource.get("allow_blob_public_access") is True
        or (
            resource.get("public_network_access_enabled") is True
            and resource.get("network_default_action") == "Allow"
        )
        or tls_value(resource.get("minimum_tls_version")) < 1.2
        or (
            resource.get("customer_managed_key_required") is True
            and resource.get("customer_managed_key_configured") is not True
        )
        for resource in resources
    )

    if exposure_or_encryption_change and controls.get("rollback_plan_present") is not True:
        findings.append(
            finding(
                "IAC-PROD-07",
                "HIGH",
                "Rollback and recovery plan is missing",
                "rollback_plan_present=false for a change affecting data "
                "exposure, networking, or encryption.",
                "Document the previous secure configuration, rollback steps, "
                "owner, validation checks, and observation period.",
            )
        )

    high_count = sum(item["severity"] == "HIGH" for item in findings)
    medium_count = sum(item["severity"] == "MEDIUM" for item in findings)

    risk_score = min(100, high_count * 20 + medium_count * 5)

    if high_count:
        decision = "BLOCK"
        risk_level = "HIGH"
    elif medium_count:
        decision = "REVIEW"
        risk_level = "MEDIUM"
    else:
        decision = "APPROVE"
        risk_level = "LOW"

    security_approval_required = (
        environment == "production"
        and (
            high_count > 0
            or any(
                resource.get("data_classification") == "sensitive"
                for resource in resources
            )
        )
    )

    return {
        "tool_name": TOOL_NAME,
        "analysis_mode": "read_only",
        "scenario_id": scenario.get("scenario_id"),
        "change_id": scenario.get("change_id"),
        "environment": environment,
        "service": scenario.get("service"),
        "change_type": scenario.get("change_type"),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "security_approval_required": security_approval_required,
        "execution_permitted": decision == "APPROVE",
        "policy_references": POLICY_REFERENCES,
        "findings": findings,
        "safety_boundary": {
            "terraform_executed": False,
            "azure_api_called": False,
            "infrastructure_modified": False,
            "live_subscription_inspected": False,
        },
    }


def main() -> None:
    """Run a local, read-only IaC governance assessment."""
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python iac_governance.py <scenario.json>"
        )

    scenario = load_scenario(sys.argv[1])
    result = analyze_iac_governance(scenario)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
