"""
ChangeShield Database Migration Safety Agent.

Creates a Microsoft Foundry agent that must use a deterministic,
read-only policy-check tool before producing a release recommendation.

Usage:
    python changeshield/src/agents/database_migration_agent.py CS-DB-001
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

from tools.database_migration_safety import analyze_migration, load_scenario


load_dotenv(ENV_PATH)

PROJECT_CONNECTION_STRING = os.getenv("PROJECT_CONNECTION_STRING")
MODEL_DEPLOYMENT_NAME = os.getenv("MODEL_DEPLOYMENT_NAME", "gpt-5.4-mini")

SCENARIO_PATHS = {
    "CS-DB-001": SCENARIOS_DIR / "high-risk-payment-migration.json",
}


def analyze_database_migration(scenario_id: str) -> str:
    """
    Perform a read-only deterministic policy analysis for an approved
    ChangeShield demo scenario. No SQL is executed.
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
    result = analyze_migration(scenario)
    return json.dumps(result)


ANALYZE_DATABASE_MIGRATION_TOOL = FunctionTool(
    name="analyze_database_migration",
    description=(
        "Run a deterministic, read-only PostgreSQL migration safety analysis "
        "for an approved ChangeShield scenario. This tool returns the "
        "authoritative policy findings, risk score, decision, required "
        "approvals, and recommended actions. It never executes SQL."
    ),
    parameters={
        "type": "object",
        "properties": {
            "scenario_id": {
                "type": "string",
                "enum": ["CS-DB-001"],
                "description": (
                    "The ChangeShield scenario identifier to analyze."
                ),
            }
        },
        "required": ["scenario_id"],
        "additionalProperties": False,
    },
    strict=True,
)


class DatabaseMigrationSafetyAgent:
    """Foundry agent wrapper for the ChangeShield database specialist."""

    def __init__(self) -> None:
        self.agent: Any = None
        self.client: AIProjectClient | None = None
        self.openai: Any = None

    def create(self) -> Any:
        """Create a versioned Database Migration Safety Agent in Foundry."""
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
You are ChangeShield Database Migration Safety Agent.

Your purpose is to assess PostgreSQL production migration risk for
authorised ChangeShield scenarios and produce an evidence-based report
for a DBA or change approver.

Mandatory operating rules:
1. You MUST call analyze_database_migration before writing a final report.
2. The tool output is authoritative for the risk score, decision,
   policy references, and approval requirement.
3. Never execute SQL, never claim that SQL was executed, and never
   suggest bypassing change-management controls.
4. Never change a tool decision from BLOCK to APPROVE.
5. Do not invent policies, evidence, thresholds, database facts, or
   deployment results.
6. Clearly distinguish confirmed evidence from likely operational impact.
7. If the tool reports execution_permitted=false, state that the agent
   is advisory and read-only.
8. For a BLOCK decision, provide a concise remediation plan and require
   explicit DBA approval before any production execution.

Use this exact report structure:

CHANGE ASSESSMENT
Scenario ID:
Change ID:
Environment:
Target database object:

DECISION
Decision:
Risk score:
Risk level:
DBA approval required:
Execution permitted:

CONFIRMED EVIDENCE
- ...

POLICY REFERENCES
- ...

LIKELY OPERATIONAL IMPACT
- ...

REQUIRED REMEDIATION
1. ...

SAFETY BOUNDARY
- ...
"""

        self.agent = self.client.agents.create_version(
            agent_name="changeshield-database-migration-safety-agent",
            definition=PromptAgentDefinition(
                model=MODEL_DEPLOYMENT_NAME,
                instructions=instructions,
                tools=[ANALYZE_DATABASE_MIGRATION_TOOL],
            ),
        )

        return self.agent

    def run(self, scenario_id: str) -> str:
        """Run the agent and resolve all requested function-tool calls."""
        if not self.agent or not self.openai:
            raise RuntimeError("Call create() before run().")

        conversation = self.openai.conversations.create()

        try:
            response = self.openai.responses.create(
                input=(
                    "Assess ChangeShield scenario "
                    f"'{scenario_id}'. You must call the "
                    "analyze_database_migration tool before responding."
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
                    if call.name == "analyze_database_migration":
                        arguments = json.loads(call.arguments)
                        output = analyze_database_migration(
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
        """Close the SDK client without deleting the Foundry agent version."""
        if self.client:
            self.client.close()


def main() -> None:
    """Create and run the agent for a selected ChangeShield scenario."""
    scenario_id = sys.argv[1] if len(sys.argv) > 1 else "CS-DB-001"

    if scenario_id not in SCENARIO_PATHS:
        available = ", ".join(SCENARIO_PATHS)
        raise SystemExit(
            f"Unknown scenario: {scenario_id}. Available: {available}"
        )

    print("=== ChangeShield Database Migration Safety Agent ===")
    print(f"Model deployment: {MODEL_DEPLOYMENT_NAME}")
    print("Creating agent in Microsoft Foundry...")

    agent = DatabaseMigrationSafetyAgent()
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
