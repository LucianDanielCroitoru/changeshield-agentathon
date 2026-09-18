# ChangeShield IaC Production Governance Policy

## Scope

This policy governs Terraform and infrastructure-as-code changes proposed
for production environments. ChangeShield evaluates supplied scenario data
only. It does not authenticate to Azure, execute Terraform, modify cloud
resources, or inspect a live subscription.

## Decision levels

- **APPROVE**: No blocking governance or security findings are present.
- **REVIEW**: A non-blocking governance concern requires explicit review.
- **BLOCK**: A high-risk security, exposure, encryption, approval, or
  rollback condition prevents production execution.

## Required production controls

### IAC-PROD-01: Public data exposure

Production storage, databases, queues, and secrets services must not permit
anonymous public access unless a documented security exception is present.

A change is **BLOCKED** when:

- public data access is enabled;
- anonymous blob, object, file, or container access is enabled; or
- no documented security exception is supplied.

### IAC-PROD-02: Network access restriction

Production data services must restrict network access using private endpoints,
approved virtual networks, service endpoints, or an explicit approved firewall
allowlist.

A change is **BLOCKED** when public network access is enabled for all networks
without a documented, approved exception.

### IAC-PROD-03: Transport encryption

Production services that support TLS must enforce TLS 1.2 or later.

A change is **BLOCKED** when the minimum TLS version is below 1.2.

### IAC-PROD-04: Encryption at rest

Sensitive production data must use an approved encryption-at-rest configuration.
Where the scenario requires customer-managed keys, the key reference and key
management approval must be present.

A change is **BLOCKED** when customer-managed encryption is required but absent.

### IAC-PROD-05: Mandatory ownership tags

Production resources must include the `Environment`, `Owner`, and `CostCenter`
tags so operational ownership and cost accountability are traceable.

A change requires **REVIEW** when mandatory tags are absent. It becomes
**BLOCK** if missing ownership prevents safe operation or exception handling.

### IAC-PROD-06: Production change approval

Production IaC changes affecting data exposure, networking, or encryption require
explicit security approval before execution.

A change is **BLOCKED** when the required approval is absent.

### IAC-PROD-07: Rollback and recovery plan

Production IaC changes must include a documented rollback or recovery plan,
including the previous secure configuration and the validation period.

A change is **BLOCKED** when the plan is absent for a change that affects
data exposure, networking, encryption, or availability.
