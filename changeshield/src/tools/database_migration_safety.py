"""
ChangeShield Database Migration Safety Tool.

Read-only deterministic analysis for PostgreSQL production migrations.
The tool does not execute SQL or connect to a database.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


HIGH_RISK_TABLE_KEYWORDS = (
    "payment",
    "transaction",
    "order",
    "invoice",
    "customer_session",
)

POLICY_REFERENCES = {
    "traceability": "DB-PROD-01",
    "high_write": "DB-PROD-02",
    "lock_risk": "DB-PROD-03",
    "transaction": "DB-PROD-04",
    "capacity": "DB-PROD-05",
    "human_approval": "DB-PROD-07",
}


def load_scenario(scenario_path: str | Path) -> dict[str, Any]:
    """Load and validate a ChangeShield scenario JSON file."""
    path = Path(scenario_path)

    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    with path.open(encoding="utf-8") as file:
        scenario = json.load(file)

    required_keys = ("scenario_id", "environment", "database", "migration")
    missing_keys = [key for key in required_keys if key not in scenario]

    if missing_keys:
        raise ValueError(
            f"Scenario is missing required fields: {', '.join(missing_keys)}"
        )

    return scenario


def _is_high_write_or_critical(table_metadata: dict[str, Any]) -> bool:
    classification = str(table_metadata.get("classification", "")).lower()
    write_profile = str(table_metadata.get("write_profile", "")).lower()
    table_name = str(table_metadata.get("table", "")).lower()
    schema_name = str(table_metadata.get("schema", "")).lower()

    combined_name = f"{schema_name}.{table_name}"

    return (
        classification in {"business-critical", "critical"}
        or write_profile == "high-write"
        or any(keyword in combined_name for keyword in HIGH_RISK_TABLE_KEYWORDS)
    )


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


def analyze_migration(scenario: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluate a PostgreSQL migration against ChangeShield demo policies.

    Returns structured, deterministic findings. It never executes SQL.
    """
    database = scenario["database"]
    migration = scenario["migration"]
    release_context = scenario.get("release_context", {})
    table_metadata = database.get("table_metadata", {})

    sql = str(migration.get("sql", "")).upper()
    environment = str(scenario.get("environment", "")).lower()
    transactional = bool(migration.get("transactional", False))
    rollback_provided = bool(migration.get("rollback_provided", False))
    dba_approval = bool(release_context.get("dba_approval", False))
    staging_validated = bool(
        release_context.get("staging_validation_completed", False)
    )
    pool_usage = float(database.get("connection_pool_usage_percent", 0))
    high_write_or_critical = _is_high_write_or_critical(table_metadata)

    findings: list[dict[str, str]] = []
    policy_references: set[str] = set()
    risk_score = 0

    creates_index = "CREATE INDEX" in sql
    uses_concurrently = "CREATE INDEX CONCURRENTLY" in sql

    if creates_index and high_write_or_critical and not uses_concurrently:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["high_write"],
            "Non-concurrent index on high-write table",
            (
                "The migration creates an index without CONCURRENTLY on "
                f"{table_metadata.get('schema')}.{table_metadata.get('table')}."
            ),
            (
                "Use CREATE INDEX CONCURRENTLY and validate the execution "
                "plan in staging."
            ),
        )
        risk_score += 35

    if creates_index and uses_concurrently and transactional:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["transaction"],
            "Concurrent index inside transactional migration",
            (
                "CREATE INDEX CONCURRENTLY cannot run inside a PostgreSQL "
                "transaction block."
            ),
            (
                "Configure this migration as non-transactional or execute "
                "it outside a transaction."
            ),
        )
        risk_score += 30

    if not rollback_provided:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["traceability"],
            "Rollback plan is missing",
            (
                "The scenario declares rollback_provided=false and provides "
                "no rollback script."
            ),
            (
                "Attach a tested rollback or documented compensating action "
                "before production approval."
            ),
        )
        risk_score += 20

    if pool_usage > 80:
        _add_finding(
            findings,
            policy_references,
            "MEDIUM",
            POLICY_REFERENCES["capacity"],
            "Database connection pool is above the review threshold",
            (
                f"Connection pool usage is {pool_usage:.0f}%, above the "
                "80% DBA-review threshold."
            ),
            (
                "Review database capacity with a DBA and avoid concurrent "
                "high-impact changes during peak load."
            ),
        )
        risk_score += 15

    if not staging_validated:
        _add_finding(
            findings,
            policy_references,
            "MEDIUM",
            POLICY_REFERENCES["high_write"],
            "Staging validation is incomplete",
            (
                "The release context states that representative staging "
                "validation has not been completed."
            ),
            (
                "Test the migration using representative data and capture "
                "runtime, locking, and rollback evidence."
            ),
        )
        risk_score += 10

    if environment == "production" and not dba_approval:
        _add_finding(
            findings,
            policy_references,
            "HIGH",
            POLICY_REFERENCES["human_approval"],
            "Required DBA approval is missing",
            (
                "The change targets production and dba_approval=false."
            ),
            (
                "Obtain explicit approval from an authorised DBA or change "
                "approver before any production execution."
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

    recommended_actions = []
    for finding in findings:
        action = finding["recommended_action"]
        if action not in recommended_actions:
            recommended_actions.append(action)

    return {
        "tool_name": "analyze_database_migration",
        "analysis_mode": "read_only",
        "scenario_id": scenario["scenario_id"],
        "change_id": scenario.get("change_id"),
        "environment": scenario["environment"],
        "database_engine": database.get("engine"),
        "target_table": (
            f"{table_metadata.get('schema', 'unknown')}."
            f"{table_metadata.get('table', 'unknown')}"
        ),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "decision": decision,
        "dba_approval_required": environment == "production" and risk_score >= 40,
        "execution_permitted": False,
        "policy_references": sorted(policy_references),
        "findings": findings,
        "recommended_actions": recommended_actions,
    }


def main() -> None:
    """Run the tool against a scenario passed as the first CLI argument."""
    if len(sys.argv) != 2:
        print(
            "Usage: python database_migration_safety.py <scenario.json>",
            file=sys.stderr,
        )
        sys.exit(2)

    scenario = load_scenario(sys.argv[1])
    result = analyze_migration(scenario)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
