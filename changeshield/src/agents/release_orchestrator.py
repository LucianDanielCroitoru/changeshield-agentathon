"""
ChangeShield Production Release Orchestrator.

Collects deterministic, read-only specialist assessments for database,
Kubernetes, and infrastructure-as-code changes. A Foundry agent may turn
the consolidated evidence into an executive report, but it cannot execute
or approve a release blocked by any specialist.

Usage:
    python changeshield/src/agents/release_orchestrator.py CS-REL-001
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai.types.responses.response_input_param import FunctionCallOutput


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPO_ROOT / "changeshield" / "src"
SCENARIOS_DIR = REPO_ROOT / "changeshield" / "data" / "scenarios"
ENV_PATH = REPO_ROOT / "factory" / ".env"

sys.path.insert(0, str(SRC_ROOT))

from tools.database_migration_safety import (
    analyze_migration,
    load_scenario as load_database_scenario,
)
from tools.kubernetes_release_safety import (
    analyze_kubernetes_release,
    load_scenario as load_kubernetes_scenario,
)
from tools.iac_governance import (
    analyze_iac_governance,
    load_scenario as load_iac_scenario,
)


load_dotenv(ENV_PATH)

PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")

RELEASE_SCENARIO_PATHS = {
    "CS-REL-001": SCENARIOS_DIR / "high-risk-production-release.json",
}

DATABASE_SCENARIO_PATHS = {
    "CS-DB-001": SCENARIOS_DIR / "high-risk-payment-migration.json",
}

KUBERNETES_SCENARIO_PATHS = {
    "CS-K8S-001": SCENARIOS_DIR / "high-risk-payment-api-release.json",
}

IAC_SCENARIO_PATHS = {
    "CS-IAC-001": SCENARIOS_DIR / "high-risk-payment-platform-iac.json",
}


def load_release_scenario(path: str | Path) -> dict[str, Any]:
    """Load the consolidated release scenario from JSON."""
    with Path(path).open(encoding="utf-8") as scenario_file:
        return json.load(scenario_file)


def specialist_error(
    specialist: str,
    scenario_id: str | None,
    message: str,
) -> dict[str, Any]:
    """Create a fail-closed specialist result for invalid orchestration input."""
    return {
        "specialist": specialist,
        "scenario_id": scenario_id,
        "decision": "BLOCK",
        "risk_level": "HIGH",
        "risk_score": 100,
        "execution_permitted": False,
        "findings": [
            {
                "policy_reference": "ORCH-PROD-01",
                "severity": "HIGH",
                "title": "Specialist assessment could not be completed",
                "evidence": message,
                "recommendation": (
                    "Correct the scenario mapping and rerun the read-only "
                    "assessment before requesting production execution."
                ),
            }
        ],
    }


def run_database_specialist(scenario_id: str | None) -> dict[str, Any]:
    """Run the local database policy tool for its authorised scenario."""
    scenario_path = DATABASE_SCENARIO_PATHS.get(scenario_id or "")

    if not scenario_path:
        return specialist_error(
            "database",
            scenario_id,
            "No authorised database scenario mapping was found.",
        )

    result = analyze_migration(load_database_scenario(scenario_path))
    result["specialist"] = "database"
    return result


def run_kubernetes_specialist(scenario_id: str | None) -> dict[str, Any]:
    """Run the local Kubernetes policy tool for its authorised scenario."""
    scenario_path = KUBERNETES_SCENARIO_PATHS.get(scenario_id or "")

    if not scenario_path:
        return specialist_error(
            "kubernetes",
            scenario_id,
            "No authorised Kubernetes scenario mapping was found.",
        )

    result = analyze_kubernetes_release(
        load_kubernetes_scenario(scenario_path)
    )
    result["specialist"] = "kubernetes"
    return result


def run_iac_specialist(scenario_id: str | None) -> dict[str, Any]:
    """Run the local IaC policy tool for its authorised scenario."""
    scenario_path = IAC_SCENARIO_PATHS.get(scenario_id or "")

    if not scenario_path:
        return specialist_error(
            "iac",
            scenario_id,
            "No authorised IaC scenario mapping was found.",
        )

    result = analyze_iac_governance(load_iac_scenario(scenario_path))
    result["specialist"] = "iac"
    return result


def risk_level_from_score(score: int) -> str:
    """Translate the maximum specialist score to a consolidated risk level."""
    if score >= 70:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def analyze_production_release(scenario_id: str) -> dict[str, Any]:
    """
    Run all required specialists and calculate a fail-closed release verdict.

    The decision is BLOCK if any specialist blocks or if required release
    controls are absent. This function is deterministic and read-only.
    """
    release_path = RELEASE_SCENARIO_PATHS.get(scenario_id)

    if not release_path:
        return {
            "error": (
                f"Release scenario '{scenario_id}' is not available. "
                f"Allowed scenarios: {', '.join(RELEASE_SCENARIO_PATHS)}"
            )
        }

    release = load_release_scenario(release_path)
    scenario_map = release.get("specialist_scenarios", {})
    controls = release.get("release_controls", {})

    specialist_results = [
        run_database_specialist(scenario_map.get("database")),
        run_kubernetes_specialist(scenario_map.get("kubernetes")),
        run_iac_specialist(scenario_map.get("iac")),
    ]

    orchestration_findings: list[dict[str, str]] = []

    if controls.get("change_approver_present") is not True:
        orchestration_findings.append(
            {
                "policy_reference": "ORCH-PROD-02",
                "severity": "HIGH",
                "title": "Consolidated production change approval is missing",
                "evidence": "change_approver_present=false.",
                "recommendation": (
                    "Obtain explicit approval from the accountable production "
                    "change approver after all specialist remediation is complete."
                ),
            }
        )

    if controls.get("consolidated_rollback_plan_present") is not True:
        orchestration_findings.append(
            {
                "policy_reference": "ORCH-PROD-03",
                "severity": "HIGH",
                "title": "Consolidated release rollback plan is missing",
                "evidence": "consolidated_rollback_plan_present=false.",
                "recommendation": (
                    "Document an integrated rollback plan covering database, "
                    "Kubernetes, and IaC changes, including owners and validation."
                ),
            }
        )

    specialist_blocks = [
        result["specialist"]
        for result in specialist_results
        if result.get("decision") == "BLOCK"
    ]

    max_specialist_score = max(
        (int(result.get("risk_score", 100)) for result in specialist_results),
        default=0,
    )

    has_high_orchestration_finding = any(
        finding["severity"] == "HIGH"
        for finding in orchestration_findings
    )

    decision = (
        "BLOCK"
        if specialist_blocks or has_high_orchestration_finding
        else "APPROVE"
    )

    all_findings = [
        {
            "specialist": result["specialist"],
            **finding,
        }
        for result in specialist_results
        for finding in result.get("findings", [])
    ] + [
        {
            "specialist": "orchestrator",
            **finding,
        }
        for finding in orchestration_findings
    ]

    return {
        "tool_name": "analyze_production_release",
        "analysis_mode": "read_only",
        "scenario_id": release.get("scenario_id"),
        "change_id": release.get("change_id"),
        "environment": release.get("environment"),
        "release_name": release.get("release_name"),
        "execution_requested": controls.get("execution_requested", False),
        "consolidated_risk_score": max_specialist_score,
        "risk_level": risk_level_from_score(max_specialist_score),
        "decision": decision,
        "execution_permitted": False,
        "blocking_specialists": specialist_blocks,
        "specialist_results": specialist_results,
        "orchestration_findings": orchestration_findings,
        "all_findings": all_findings,
        "safety_boundary": {
            "database_contacted": False,
            "kubernetes_cluster_contacted": False,
            "terraform_executed": False,
            "azure_api_called": False,
            "infrastructure_modified": False,
            "production_execution_performed": False,
        },
    }


def analyze_production_release_tool(scenario_id: str) -> str:
    """Serialize the deterministic release assessment for the Foundry tool."""
    return json.dumps(analyze_production_release(scenario_id))


ANALYZE_PRODUCTION_RELEASE_TOOL = FunctionTool(
    name="analyze_production_release",
    description=(
        "Run all authorised ChangeShield production-release specialist "
        "assessments and return a deterministic, read-only consolidated "
        "decision. It combines database migration, Kubernetes release, and "
        "IaC governance findings. Any specialist BLOCK is authoritative and "
        "prevents release execution. It never contacts production systems."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scenario_id": {
                "type": "string",
                "enum": ["CS-REL-001"],
                "description": (
                    "The authorised consolidated ChangeShield release scenario."
                ),
            }
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
    strict=True,
)


class ReleaseOrchestrator:
    """Foundry agent wrapper for ChangeShield's release-risk coordinator."""

    def __init__(self) -> None:
        self.agent: Any = None
        self.client: AIProjectClient | None = None
        self.openai: Any = None

    def create(self) -> Any:
        """Create the versioned release orchestrator in Microsoft Foundry."""
        if not PROJECT_CONNECTION_STRING:
            raise RuntimeError(
                "PROJECT_CONNECTION_STRING is missing. "
                "Verify factory/.env and Challenge 0 setup."
            )

        self.client = AIProjectClient(
            endpoint=PROJECT_CONNECTION_STRING,
            credential=DefaultAzureCredential(),
        )
        self.openai = self.client.get_openai_client()

        instructions = """
You are the ChangeShield Production Release Orchestrator.

Your purpose is to consolidate deterministic safety assessments from the
Database Migration, Kubernetes Release, and IaC Governance specialists for
an authorised production-release scenario.

Mandatory operating rules:
1. You MUST call analyze_production_release before writing a final report.
2. The tool output is authoritative. Never change its decision, risk score,
   specialist findings, or safety boundary.
3. A BLOCK from any specialist is a mandatory release BLOCK. Never dilute,
   override, or reinterpret a specialist BLOCK.
4. Never execute SQL, database migrations, kubectl, Helm, Terraform, cloud
   APIs, or shell commands.
5. Never claim that any production system, cluster, database, subscription,
   resource, deployment, rollout, migration, apply, rollback, or health
   check was contacted or executed.
6. Do not invent approvals, exceptions, test evidence, monitoring evidence,
   rollback plans, ownership, or remediation completion.
7. Clearly separate confirmed evidence from likely release impact.
8. If execution_permitted=false, state that this is advisory and read-only.
9. Provide a practical remediation sequence, but do not authorize execution.

Use this exact report structure:

PRODUCTION RELEASE SAFETY ASSESSMENT
Release scenario:
Change ID:
Environment:
Release:

CONSOLIDATED DECISION
Decision:
Consolidated risk score:
Risk level:
Execution requested:
Execution permitted:
Blocking specialists:

SPECIALIST VERDICTS
- Database:
- Kubernetes:
- IaC:

CONFIRMED BLOCKING EVIDENCE
- ...

ORCHESTRATION CONTROL GAPS
- ...

LIKELY RELEASE IMPACT
- ...

REQUIRED REMEDIATION SEQUENCE
1. ...

SAFETY BOUNDARY
- ...
"""

        self.agent = self.client.agents.create_version(
            agent_name="changeshield-production-release-orchestrator",
            definition=PromptAgentDefinition(
                model=MODEL_DEPLOYMENT_NAME,
                instructions=instructions,
                tools=[ANALYZE_PRODUCTION_RELEASE_TOOL],
            ),
        )

        return self.agent

    def run(self, scenario_id: str) -> str:
        """Run the orchestrator and resolve the requested local function call."""
        if not self.agent or not self.openai:
            raise RuntimeError("Call create() before run().")

        conversation = self.openai.conversations.create()

        try:
            response = self.openai.responses.create(
                input=(
                    "Assess consolidated ChangeShield production release "
                    f"scenario '{scenario_id}'. You must call "
                    "analyze_production_release before responding."
                ),
                conversation=conversation.id,
                extra_body={
                    "agent_reference": {
                        "name": self.agent.name,
                        "type": "agent_reference",
                    }
                },
            )

            while True:
                function_calls = [
                    item
                    for item in response.output
                    if item.type == "function_call"
                ]

                if not function_calls:
                    break

                tool_outputs = []

                for call in function_calls:
                    if call.name == "analyze_production_release":
                        arguments = json.loads(call.arguments)
                        output = analyze_production_release_tool(
                            arguments["scenario_id"]
                        )
                    else:
                        output = json.dumps(
                            {"error": f"Unknown tool: {call.name}"}
                        )

                    tool_outputs.append(
                        FunctionCallOutput(
                            type="function_call_output",
                            call_id=call.call_id,
                            output=output,
                        )
                    )

                response = self.openai.responses.create(
                    input=tool_outputs,
                    conversation=conversation.id,
                    extra_body={
                        "agent_reference": {
                            "name": self.agent.name,
                            "type": "agent_reference",
                        }
                    },
                )

            return response.output_text

        finally:
            self.openai.conversations.delete(
                conversation_id=conversation.id
            )

    def close(self) -> None:
        """Close local resources without deleting a Foundry agent version."""
        if self.client:
            self.client.close()


def main() -> None:
    """Create and run the coordinator for an authorised release scenario."""
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "CS-REL-001"

    if scenario_id not in RELEASE_SCENARIO_PATHS:
        available = ", ".join(RELEASE_SCENARIO_PATHS)
        raise SystemExit(
            f"Unknown release scenario: {scenario_id}. Available: {available}"
        )

    print("=== ChangeShield Production Release Orchestrator ===")
    print(f"Model deployment: {MODEL_DEPLOYMENT_NAME}")
    print("Creating agent in Microsoft Foundry...")

    orchestrator = ReleaseOrchestrator()
    created_agent = orchestrator.create()

    print(
        "Created agent: "
        f"{created_agent.name} "
        f"(version {created_agent.version})"
    )
    print(f"\nAssessing release scenario: {scenario_id}\n")

    report = orchestrator.run(scenario_id)
    print(report)

    orchestrator.close()


if __name__ == "__main__":
    main()
