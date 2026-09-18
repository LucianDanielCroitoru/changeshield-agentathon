"""
ChangeShield IaC Governance Agent.

Creates a Microsoft Foundry agent that evaluates authorised ChangeShield
Terraform/IaC scenarios through a deterministic, read-only policy tool.

Usage:
    python changeshield/src/agents/iac_governance_agent.py CS-IAC-001
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

from tools.iac_governance import analyze_iac_governance, load_scenario


load_dotenv(ENV_PATH)

PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")

SCENARIO_PATHS = {
    "CS-IAC-001": SCENARIOS_DIR / "high-risk-payment-platform-iac.json",
}


def analyze_iac_governance_tool(scenario_id: str) -> str:
    """
    Run deterministic, read-only IaC governance analysis for an authorised
    ChangeShield scenario. No Terraform command or Azure API is invoked.
    """
    scenario_path = SCENARIO_PATHS.get(scenario_id)

    if not scenario_path:
        return json.dumps(
            {
                "error": (
                    f"Scenario '{scenario_id}' is not available. "
                    f"Allowed scenarios: {', '.join(SCENARIO_PATHS)}"
                )
            }
        )

    scenario = load_scenario(scenario_path)
    result = analyze_iac_governance(scenario)
    return json.dumps(result)


ANALYZE_IAC_GOVERNANCE_TOOL = FunctionTool(
    name="analyze_iac_governance",
    description=(
        "Run a deterministic, read-only production IaC governance assessment "
        "for an approved ChangeShield scenario. It returns authoritative "
        "security findings, risk score, decision, required approvals, and "
        "remediation. It never executes Terraform, contacts Azure APIs, or "
        "modifies cloud infrastructure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scenario_id": {
                "type": "string",
                "enum": ["CS-IAC-001"],
                "description": (
                    "The approved ChangeShield IaC scenario to analyze."
                ),
            }
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
    strict=True,
)


class IaCGovernanceAgent:
    """Foundry agent wrapper for the ChangeShield IaC specialist."""

    def __init__(self) -> None:
        self.agent: Any = None
        self.client: AIProjectClient | None = None
        self.openai: Any = None

    def create(self) -> Any:
        """Create a versioned IaC Governance Agent in Microsoft Foundry."""
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
You are ChangeShield IaC Governance Agent.

Your purpose is to assess Terraform and infrastructure-as-code changes for
authorised ChangeShield production scenarios. Produce an evidence-based,
read-only governance assessment for a security engineer, platform engineer,
or production change approver.

Mandatory operating rules:
1. You MUST call analyze_iac_governance before writing a final report.
2. The tool output is authoritative for risk score, decision, policy
   references, required approvals, evidence, and remediation.
3. Never run terraform plan, terraform apply, terraform destroy, terraform
   import, or any shell command.
4. Never access Azure Resource Manager, Azure APIs, an Azure subscription,
   a Terraform backend, or a live infrastructure environment.
5. Never claim that Terraform was executed, a plan was applied, a resource
   was changed, a subscription was inspected, or a rollback was performed.
6. Never change a tool decision from BLOCK to APPROVE.
7. Do not invent security exceptions, compensating controls, ownership tags,
   policy approvals, rollout evidence, Terraform plan results, or cloud
   resource configuration.
8. Clearly distinguish confirmed evidence from likely security or
   operational impact.
9. If execution_permitted=false, state that the assessment is advisory and
   read-only.
10. For a BLOCK decision, require explicit Security or Platform approval
    after the listed remediation is complete and before any Terraform apply.

Use this exact report structure:

IAC GOVERNANCE ASSESSMENT
Scenario ID:
Change ID:
Environment:
Service:
Change type:

DECISION
Decision:
Risk score:
Risk level:
Security approval required:
Execution permitted:

CONFIRMED EVIDENCE
- ...

POLICY REFERENCES
- ...

LIKELY SECURITY AND OPERATIONAL IMPACT
- ...

REQUIRED REMEDIATION
1. ...

SAFETY BOUNDARY
- ...
"""

        self.agent = self.client.agents.create_version(
            agent_name="changeshield-iac-governance-agent",
            definition=PromptAgentDefinition(
                model=MODEL_DEPLOYMENT_NAME,
                instructions=instructions,
                tools=[ANALYZE_IAC_GOVERNANCE_TOOL],
            ),
        )

        return self.agent

    def run(self, scenario_id: str) -> str:
        """Run the agent and resolve all requested local function calls."""
        if not self.agent or not self.openai:
            raise RuntimeError("Call create() before run().")

        conversation = self.openai.conversations.create()

        try:
            response = self.openai.responses.create(
                input=(
                    "Assess ChangeShield IaC governance scenario "
                    f"'{scenario_id}'. You must call the "
                    "analyze_iac_governance tool before responding."
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
                    if call.name == "analyze_iac_governance":
                        arguments = json.loads(call.arguments)
                        output = analyze_iac_governance_tool(
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
        """Close local SDK resources without deleting Foundry agent versions."""
        if self.client:
            self.client.close()


def main() -> None:
    """Create and run the agent for one authorised demo scenario."""
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "CS-IAC-001"

    if scenario_id not in SCENARIO_PATHS:
        available = ", ".join(SCENARIO_PATHS)
        raise SystemExit(
            f"Unknown scenario: {scenario_id}. Available: {available}"
        )

    print("=== ChangeShield IaC Governance Agent ===")
    print(f"Model deployment: {MODEL_DEPLOYMENT_NAME}")
    print("Creating agent in Microsoft Foundry...")

    agent = IaCGovernanceAgent()
    created_agent = agent.create()

    print(
        "Created agent: "
        f"{created_agent.name} "
        f"(version {created_agent.version})"
    )
    print(f"\nAssessing scenario: {scenario_id}\n")

    result = agent.run(scenario_id)
    print(result)

    agent.close()


if __name__ == "__main__":
    main()
