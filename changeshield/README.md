# ChangeShield

**ChangeShield** is a read-only, fail-closed multi-agent governance system for high-risk production releases.

It evaluates proposed changes across three operational domains before a human authorises production execution:

- Database migrations
- Kubernetes releases
- Infrastructure as Code (IaC)

ChangeShield does not deploy applications, apply Terraform, run database migrations, or modify cloud infrastructure. It produces deterministic policy findings, required remediation, and an evidence-based release decision.

## The problem

A production release frequently combines multiple dependent changes:

- A database migration can lock a high-write table, exceed operational capacity, or lack a rollback path.
- A Kubernetes rollout can reduce capacity, omit health probes, or allow all replicas to become unavailable.
- An IaC change can expose sensitive data publicly, weaken transport security, or bypass required encryption and approval controls.

These risks are often reviewed separately. A release may appear safe to one domain reviewer while still being unsafe overall.

ChangeShield addresses this by combining domain-specific policy engines with a fail-closed production release coordinator.

## Solution overview

ChangeShield separates deterministic policy enforcement from AI-generated reporting.

```text
                         Controlled JSON scenarios
                                   |
          +------------------------+------------------------+
          |                        |                        |
          v                        v                        v
+----------------------+ +----------------------+ +----------------------+
| Database Migration   | | Kubernetes Release   | | IaC Governance       |
| Safety Tool          | | Safety Tool          | | Tool                 |
|                      | |                      | |                      |
| Deterministic policy | | Deterministic policy | | Deterministic policy |
+----------+-----------+ +----------+-----------+ +----------+-----------+
           |                        |                        |
           +------------------------+------------------------+
                                    |
                                    v
                 +--------------------------------------+
                 | Production Release Orchestrator       |
                 | Fail-closed: any BLOCK => BLOCK      |
                 +------------------+-------------------+
                                    |
                                    v
               +--------------------------------------------+
               | Microsoft Foundry agent reporting/tracing   |
               | Human-readable evidence and remediation    |
               +--------------------------------------------+
```

The local policy tools are authoritative for:

- Findings and evidence
- Risk score and risk level
- Required human approvals
- Release decision
- Execution permission

Microsoft Foundry agents call those tools and transform the deterministic output into structured reports. The language model cannot turn a tool decision from `BLOCK` into `APPROVE`.

## Microsoft Foundry implementation

ChangeShield provisions four versioned Microsoft Foundry agents, all using the `gpt-5.4-mini` model deployment.

| Agent | Role | Deterministic tool |
|---|---|---|
| `changeshield-database-migration-safety-agent` | Assesses PostgreSQL production migration risk | `analyze_migration` |
| `changeshield-kubernetes-release-safety-agent` | Assesses Kubernetes production release risk | `analyze_kubernetes_release` |
| `changeshield-iac-governance-agent` | Assesses Terraform/IaC production governance risk | `analyze_iac_governance` |
| `changeshield-production-release-orchestrator` | Consolidates specialist results into a release verdict | `analyze_production_release` |

For the consolidated demonstration, the orchestrator invokes the same deterministic local policy engines used by the specialist agents. This keeps enforcement reproducible, efficient, and independent of model judgment.

## Safety and decision model

### Fail-closed rule

A release is blocked if any specialist returns `BLOCK`, or if required release-level controls are missing.

```text
Database BLOCK
      OR
Kubernetes BLOCK
      OR
IaC BLOCK
      OR
Missing consolidated production approval
      OR
Missing integrated rollback plan
      =
Consolidated release BLOCK
```

The orchestrator never overrides, dilutes, or reinterprets a specialist `BLOCK`.

### Read-only boundary

ChangeShield is an advisory governance system. It does not:

- Execute SQL, database migrations, or connect to a production database
- Run `kubectl`, Helm, rollout, restart, rollback, or health-check commands
- Run `terraform plan`, `terraform apply`, `terraform destroy`, or Terraform imports
- Access Azure Resource Manager, Azure APIs, live subscriptions, or Terraform backends
- Modify databases, Kubernetes clusters, cloud resources, or infrastructure
- Fabricate approvals, exceptions, validation results, telemetry, or remediation evidence
- Authorise a production change without deterministic policy approval and human review

Every report labels the assessment as read-only. Production execution remains a human-controlled activity after all remediation and required approvals are complete.

## Specialist policy coverage

| Domain | Blocking examples evaluated |
|---|---|
| Database migration | Non-concurrent index creation on a high-write table, missing rollback plan, incomplete staging validation, high connection-pool usage, missing DBA approval |
| Kubernetes release | Unsafe CPU-request reduction, missing load-test evidence, incomplete staging validation, missing readiness/liveness probes, unsafe `max_unavailable`, missing SRE approval |
| IaC governance | Anonymous blob access, unrestricted public network access, TLS below 1.2, missing customer-managed key, missing ownership tags, missing Security approval, missing rollback plan |

The policy documents are stored in [`data/policies/`](data/policies/). Controlled scenario inputs are stored in [`data/scenarios/`](data/scenarios/).

## Demonstration scenario

`CS-REL-001` models a high-risk production release named:

```text
payment-platform-production-release
```

It consolidates three deliberately unsafe specialist scenarios:

| Domain | Scenario | Result |
|---|---|---|
| Database | `CS-DB-001` | `BLOCK` |
| Kubernetes | `CS-K8S-001` | `BLOCK` |
| IaC | `CS-IAC-001` | `BLOCK` |

The consolidated deterministic decision is:

```text
Decision: BLOCK
Consolidated risk score: 100/100
Risk level: HIGH
Execution requested: true
Execution permitted: false
Blocking specialists: database, kubernetes, iac
```

The local orchestration assessment produced **22 findings**:

- 5 database migration findings
- 8 Kubernetes release findings
- 7 IaC governance findings
- 2 release-level orchestration control gaps

The Foundry orchestrator report required remediation across all three domains and explicitly prevented production execution.

## Evidence highlights

### Database migration

The database specialist blocked the release because the proposed migration included a non-concurrent index on high-write table `payments.transactions`, lacked rollback documentation, had connection-pool usage of 86%, had incomplete staging validation, and lacked required DBA approval.

### Kubernetes release

The Kubernetes specialist blocked the release because CPU requests were reduced from `500m` to `100m` without load-test evidence, readiness and liveness probes were absent, `max_unavailable=3` with three replicas could make all replicas unavailable, rollback planning was absent, and SRE approval was missing.

### IaC governance

The IaC specialist blocked the release because the proposed storage account allowed anonymous blob access and unrestricted public networking, used `TLS1_0`, lacked the required customer-managed key, omitted `Owner` and `CostCenter` tags, and had no Security approval or rollback/recovery plan.

### Consolidated decision

The orchestrator retained all specialist blocks and also identified missing consolidated production approval and an integrated rollback plan spanning database, Kubernetes, and IaC changes.

## Run locally

### Prerequisites

- Python 3.10 or later
- A Python virtual environment
- Dependencies for the optional Foundry agent wrappers

```bash
python -m venv .venv
source .venv/bin/activate

pip install azure-ai-projects azure-identity python-dotenv openai
```

### Run deterministic specialist tools

```bash
python changeshield/src/tools/database_migration_safety.py \
  changeshield/data/scenarios/high-risk-payment-migration.json

python changeshield/src/tools/kubernetes_release_safety.py \
  changeshield/data/scenarios/high-risk-payment-api-release.json

python changeshield/src/tools/iac_governance.py \
  changeshield/data/scenarios/high-risk-payment-platform-iac.json
```

### Run consolidated orchestration locally

This command invokes all three local policy engines. It does not require Foundry, Azure access, a Kubernetes cluster, a database, or Terraform.

```bash
python - <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, str(Path("changeshield/src").resolve()))

from agents.release_orchestrator import analyze_production_release

result = analyze_production_release("CS-REL-001")

print("Decision:", result["decision"])
print("Risk score:", f'{result["consolidated_risk_score"]}/100')
print("Blocking specialists:", ", ".join(result["blocking_specialists"]))
print("All findings:", len(result["all_findings"]))
print("Execution permitted:", result["execution_permitted"])
PY
```

Expected result:

```text
Decision: BLOCK
Risk score: 100/100
Blocking specialists: database, kubernetes, iac
All findings: 22
Execution permitted: False
```

## Run with Microsoft Foundry

Foundry is optional for deterministic local validation. It is used to provision versioned agents, call local function tools, generate structured reports, and collect execution traces.

Create a local `factory/.env` file. Do not commit it.

```text
PROJECT_CONNECTION_STRING=<your-foundry-project-connection-string>
MODEL_DEPLOYMENT_NAME=gpt-5.4-mini
```

Run an individual specialist agent:

```bash
python changeshield/src/agents/database_migration_agent.py CS-DB-001

python changeshield/src/agents/kubernetes_release_agent.py CS-K8S-001

python changeshield/src/agents/iac_governance_agent.py CS-IAC-001
```

Run the consolidated orchestrator:

```bash
python changeshield/src/agents/release_orchestrator.py CS-REL-001
```

The orchestrator calls `analyze_production_release`, which invokes the three deterministic policy engines in-process. It does not connect to production systems or execute production actions.

## Microsoft Foundry evidence

### Azure and model deployment

| Evidence | Description |
|---|---|
| [Azure resource group](docs/screenshots/01-azure-resource-group.png) | Foundry, Foundry project, Application Insights, and Log Analytics resources |
| [Model deployment](docs/screenshots/02-foundry-model-deployment.png) | `gpt-5.4-mini` deployment with `Succeeded` status |
| [Model playground verification](docs/screenshots/03-foundry-model-playground-verification.png) | Successful Foundry model response |

### Agent and trace evidence

| Agent | Playground | Traces |
|---|---|---|
| Database Migration Safety | [Configuration](docs/screenshots/04-database-agent-playground.png) | [Completed traces](docs/screenshots/05-database-agent-traces.png) |
| Kubernetes Release Safety | [Configuration](docs/screenshots/06-kubernetes-agent-playground.png) | [Completed traces](docs/screenshots/07-kubernetes-agent-traces.png) |
| IaC Governance | [Configuration](docs/screenshots/08-iac-governance-agent-playground.png) | [Completed traces](docs/screenshots/09-iac-governance-agent-traces.png) |
| Production Release Orchestrator | [Configuration](docs/screenshots/10-release-orchestrator-playground.png) | [Completed traces](docs/screenshots/11-release-orchestrator-traces.png) |

### Recorded trace costs

The Foundry trace screenshots show successful tool and report phases.

| Agent | Demonstrated approximate cost |
|---|---:|
| Kubernetes Release Safety Agent | €0.0021 |
| IaC Governance Agent | €0.0031 |
| Production Release Orchestrator | €0.0031 |

Costs are trace estimates from the demonstrated runs and vary with model pricing, token usage, and deployment configuration.

Additional textual evidence is stored in [`docs/`](docs/):

- `high-risk-analysis-output.json`
- `high-risk-kubernetes-analysis-output.json`
- `high-risk-iac-governance-analysis-output.json`
- `high-risk-production-release-orchestration-output.json`
- `kubernetes-agent-foundry-output.md`
- `iac-governance-agent-foundry-output.md`
- `production-release-orchestrator-foundry-output.md`

## Repository structure

```text
changeshield/
├── data/
│   ├── policies/
│   │   ├── database-production-policy.md
│   │   ├── kubernetes-production-policy.md
│   │   └── iac-production-governance-policy.md
│   └── scenarios/
│       ├── high-risk-payment-migration.json
│       ├── high-risk-payment-api-release.json
│       ├── high-risk-payment-platform-iac.json
│       └── high-risk-production-release.json
├── docs/
│   ├── screenshots/
│   ├── high-risk-analysis-output.json
│   ├── high-risk-kubernetes-analysis-output.json
│   ├── high-risk-iac-governance-analysis-output.json
│   ├── high-risk-production-release-orchestration-output.json
│   └── *-foundry-output.md
├── src/
│   ├── agents/
│   │   ├── database_migration_agent.py
│   │   ├── kubernetes_release_agent.py
│   │   ├── iac_governance_agent.py
│   │   └── release_orchestrator.py
│   └── tools/
│       ├── database_migration_safety.py
│       ├── kubernetes_release_safety.py
│       └── iac_governance.py
└── README.md
```

## Limitations and next steps

This implementation intentionally uses controlled, simulated scenario data. It is a governance and decision-support prototype, not a production deployment controller.

Potential next steps include:

- Parse real Terraform plans, Kubernetes manifests, and database migration diffs.
- Add CI/CD pull-request and release-pipeline integration.
- Add signed, versioned policy-as-code packs.
- Add least-privilege read-only integrations for approved inventory, telemetry, and change-management systems.
- Add role-based human approvals, expiring exceptions, and audit retention.
- Add evaluation datasets for policy accuracy, false positives, regressions, and report quality.
- Validate remediation evidence before allowing reassessment.
- Add a controlled human-in-the-loop execution workflow that remains separate from the policy assessment layer.

## Security note

Do not commit `factory/.env`, API keys, connection strings, access tokens, subscription identifiers, or live production configuration. The committed scenarios are intentionally simulated and contain no live credentials.
