"""
ChangeShield Kubernetes Release Safety Tool.

Read-only deterministic policy analysis for Kubernetes production releases.
The tool does not connect to a cluster and never executes kubectl or Helm.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


POLICY_REFERENCES = {
    "resources": "K8S-PROD-01",
    "health_checks": "K8S-PROD-02",
    "cpu_reduction": "K8S-PROD-03",
    "rollout": "K8S-PROD-04",
    "rollback": "K8S-PROD-05",
    "autoscaling": "K8S-PROD-06",
    "approval": "K8S-PROD-08",
}


def load_scenario(scenario_path: str | Path) -> dict[str, Any]:
    """Load and validate a ChangeShield Kubernetes scenario."""
    path = Path(scenario_path)

    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with path.open(encoding="utf-8") as file:
        scenario = json.load(file)

    required_keys = (
        "scenario_id",
        "environment",
        "service",
        "release_context",
        "deployment",
    )
    missing_keys = [key for key in required_keys if key not in scenario]

    if missing_keys:
        raise ValueError(
            f"Scenario is missing required fields: {', '.join(missing_keys)}"
        )

    return scenario


def parse_cpu_millicores(value: str | None) -> int | None:
    """
    Convert Kubernetes CPU values to millicores.

    Examples:
    - 100m -> 100
    - 0.5  -> 500
    - 1    -> 1000
    """
    if not value:
        return None

    value = str(value).strip().lower()

    if value.endswith("m"):
        number = value[:-1]
        return int(number) if number.isdigit() else None

    if re.fullmatch(r"\d+(\.\d+)?", value):
        return int(float(value) * 1000)

    return None


def _add_finding(
    findings: list[dict[str, str]],
    policy_references: set[str],
    severity: str,
    policy: str,
    title: str,
    evidence: str,
    remediation: str,
) -> None:
    findings.append(
        {
            "severity": severity,
            "policy_reference": policy,
            "title": title,
            "evidence": evidence,
            "recommended_action": remediation,
        }
    )
    policy_references.add(policy)


def analyze_kubernetes_release(scenario: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate a Kubernetes release against ChangeShield demo policies.

    Returns structured deterministic findings.
    No Kubernetes API, kubectl, Helm, or cloud service is called.
    """
    service = scenario["service"]
    release_context = scenario["release_context"]
    deployment = scenario["deployment"]
    container = deployment.get("container", {})
    resources = container.get("resources", {})
    requests = resources.get("requests", {})
    limits = resources.get("limits", {})
    previous_resources = container.get("previous_resources", {})
    previous_requests = previous_resources.get("requests", {})
    strategy = deployment.get("strategy", {})
    hpa = deployment.get("hpa", {})

    environment = str(scenario.get("environment", "")).lower()
    classification = str(service.get("classification", "")).lower()
    business_critical = classification in {"business-critical", "critical"}

    replicas = int(deployment.get("replicas", 0))
    max_unavailable = strategy.get("max_unavailable", 0)

    if isinstance(max_unavailable, str) and max_unavailable.endswith("%"):
        max_unavailable_count = int(
            replicas * int(max_unavailable[:-1]) / 100
        )
    else:
        max_unavailable_count = int(max_unavailable)

    current_cpu = parse_cpu_millicores(requests.get("cpu"))
    previous_cpu = parse_cpu_millicores(previous_requests.get("cpu"))

    readiness_probe = container.get("readiness_probe")
    liveness_probe = container.get("liveness_probe")

    staging_validated = bool(
        release_context.get("staging_validation_completed", False)
    )
    load_test_available = bool(
        release_context.get("load_test_evidence_available", False)
    )
    rollback_provided = bool(
        release_context.get("rollback_plan_provided", False)
    )
    sre_approval = bool(release_context.get("sre_approval", False))

    findings: list[dict[str, str]] = []
    policy_references: set[str] = set()
    risk_score = 0

    if not requests.get("cpu") or not requests.get("memory"):
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["resources"],
            "Container resource requests are incomplete",
            "CPU and memory requests are required for production workloads.",
            (
                "Define CPU and memory requests based on measured workload "
                "requirements before production approval."
            ),
        )
        risk_score += 25

    if not limits.get("cpu") or not limits.get("memory"):
        _add_finding(
            findings,
            policy_references,
            "MEDIUM",
            POLICY_REFERENCES["resources"],
            "Container resource limits are incomplete",
            "CPU and memory limits are required by the production policy.",
            (
                "Define CPU and memory limits aligned with workload capacity "
                "and platform standards."
            ),
        )
        risk_score += 10

    if current_cpu is not None and previous_cpu is not None:
        if current_cpu < previous_cpu:
            reduction_percent = (
                (previous_cpu - current_cpu) / previous_cpu
            ) * 100

            severity = "HIGH" if business_critical else "MEDIUM"

            _add_finding(
                findings,
                policy_references,
                severity,
                POLICY_REFERENCES["cpu_reduction"],
                "Production CPU request was reduced",
                (
                    f"CPU request was reduced from {previous_cpu}m to "
                    f"{current_cpu}m ({reduction_percent:.0f}% reduction)."
                ),
                (
                    "Restore the approved CPU request or provide load-test "
                    "evidence, staging validation, and SRE approval."
                ),
            )
            risk_score += 30 if business_critical else 15

            if not load_test_available:
                _add_finding(
                    findings,
                    policy_references,
                    "HIGH" if business_critical else "MEDIUM",
                    POLICY_REFERENCES["cpu_reduction"],
                    "Load-test evidence is missing",
                    (
                        "CPU request was reduced but "
                        "load_test_evidence_available=false."
                    ),
                    (
                        "Run representative load tests before reducing "
                        "production CPU requests."
                    ),
                )
                risk_score += 15

            if not staging_validated:
                _add_finding(
                    findings,
                    policy_references,
                    "HIGH" if business_critical else "MEDIUM",
                    POLICY_REFERENCES["cpu_reduction"],
                    "Staging validation is incomplete",
                    (
                        "The release context declares "
                        "staging_validation_completed=false."
                    ),
                    (
                        "Validate the release in staging and capture "
                        "resource usage, error rate, and latency evidence."
                    ),
                )
                risk_score += 15

    if not readiness_probe:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["health_checks"],
            "Readiness probe is missing",
            (
                "The deployment has no readiness probe, so traffic may be "
                "sent to an unready application instance."
            ),
            (
                "Add a readiness probe that verifies the application can "
                "safely receive production traffic."
            ),
        )
        risk_score += 20

    if not liveness_probe:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["health_checks"],
            "Liveness probe is missing",
            (
                "The deployment has no liveness probe, so failed workloads "
                "may remain running without automatic recovery."
            ),
            (
                "Add a liveness probe that detects unrecoverable application "
                "failure."
            ),
        )
        risk_score += 20

    if replicas > 0 and max_unavailable_count >= replicas:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["rollout"],
            "Rolling update can make all replicas unavailable",
            (
                f"replicas={replicas} and max_unavailable="
                f"{max_unavailable_count}, allowing full service outage."
            ),
            (
                "Set max_unavailable below the replica count and use a "
                "controlled rolling update or canary rollout."
            ),
        )
        risk_score += 25

    if not rollback_provided:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["rollback"],
            "Rollback plan is missing",
            (
                "rollback_plan_provided=false and no rollback command is "
                "available."
            ),
            (
                "Document the stable version, rollback command, and "
                "health-check observation period before deployment."
            ),
        )
        risk_score += 20

    if hpa.get("enabled"):
        min_replicas = hpa.get("min_replicas")
        max_replicas = hpa.get("max_replicas")
        target_cpu = hpa.get("target_cpu_utilization_percent")

        if (
            min_replicas is None
            or max_replicas is None
            or target_cpu is None
        ):
            _add_finding(
                findings,
                policy_references,
                "MEDIUM",
                POLICY_REFERENCES["autoscaling"],
                "HPA configuration is incomplete",
                (
                    "HPA is enabled but min_replicas, max_replicas, or "
                    "target_cpu_utilization_percent is missing."
                ),
                (
                    "Complete the HPA configuration and validate scaling "
                    "behavior before production approval."
                ),
            )
            risk_score += 10

    if environment == "production" and not sre_approval:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["approval"],
            "Required SRE approval is missing",
            "The change targets production and sre_approval=false.",
            (
                "Obtain explicit approval from an authorised SRE, platform "
                "engineer, or change approver before production execution."
            ),
        )
        risk_score += 20

    risk_score = min(risk_score, 100)

    if risk_score >= 70:
        decision = "BLOCK"
        risk_level = "HIGH"
    elif risk_score >= 40:
        decision = "APPROVE_WITH_GUARDRAILS"
        risk_level = "MEDIUM"
    else:
        decision = "APPROVE"
        risk_level = "LOW"

    recommended_actions: list[str] = []

    for finding in findings:
        action = finding["recommended_action"]

        if action not in recommended_actions:
            recommended_actions.append(action)

    return {
        "tool_name": "analyze_kubernetes_release",
        "analysis_mode": "read_only",
        "scenario_id": scenario["scenario_id"],
        "change_id": scenario.get("change_id"),
        "environment": scenario["environment"],
        "service": service.get("name"),
        "current_stable_version": service.get("current_stable_version"),
        "target_version": service.get("target_version"),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "sre_approval_required": environment == "production" and risk_score >= 40,
        "execution_permitted": False,
        "policy_references": sorted(policy_references),
        "findings": findings,
        "recommended_actions": recommended_actions,
    }


def main() -> None:
    """Run the tool against a scenario passed as the first CLI argument."""
    if len(sys.argv) != 2:
        print(
            "Usage: python kubernetes_release_safety.py <scenario.json>",
            file=sys.stderr,
        )
        sys.exit(2)

    scenario = load_scenario(sys.argv[1])
    result = analyze_kubernetes_release(scenario)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
