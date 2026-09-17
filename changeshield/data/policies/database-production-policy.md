# Database Production Change Policy

**Policy owner:** Database Reliability Team  
**Applies to:** PostgreSQL production databases  
**Policy version:** 1.0  
**Classification:** Demo policy — non-confidential  

## Purpose

This policy defines the minimum controls required before applying
database schema changes to production systems.

## DB-PROD-01: Migration traceability

Every production migration must include:

- A unique migration identifier
- A change ticket or release identifier
- A clear business purpose
- An identified owner
- A tested rollback or compensating action

A migration without rollback information must not be approved for
unattended production execution.

## DB-PROD-02: High-write table protection

For tables classified as high-write or business-critical:

- Index creation must use `CREATE INDEX CONCURRENTLY`
- Blocking schema changes must be planned in a maintenance window
- The migration must be tested against representative staging data
- The expected lock impact must be documented

Examples of high-write or business-critical tables include:

- payments
- transactions
- orders
- invoices
- customer_sessions

## DB-PROD-03: Lock-risk classification

The following changes are classified as high risk:

- `CREATE INDEX` without `CONCURRENTLY` on a high-write table
- `ALTER TABLE` operations that may rewrite a large table
- Long-running transactions during deployment
- Foreign key validation on large active tables
- Schema changes with no rollback strategy

High-risk changes require DBA approval before production deployment.

## DB-PROD-04: Transaction boundaries

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block.

Migration tooling must either:

- Execute the statement outside a transaction, or
- Use a migration framework configuration that explicitly supports
  non-transactional migrations.

If this condition is not confirmed, the deployment must be blocked.

## DB-PROD-05: Connection and capacity safety

A release must not reduce database connection-pool capacity unless
load-test evidence confirms that production demand remains supported.

If connection usage is above 80% of the approved pool capacity,
database changes must be reviewed by a DBA before deployment.

## DB-PROD-06: Required deployment decision

The Database Migration Safety Agent must return one of these decisions:

- `APPROVE` — low-risk change with complete evidence
- `APPROVE_WITH_GUARDRAILS` — moderate risk; staging, canary, or DBA review required
- `BLOCK` — high-risk change, missing rollback, policy violation, or insufficient evidence

## DB-PROD-07: Human approval

The agent must never execute SQL, apply a migration, or modify a
production database.

For medium, high, or critical risk findings, the agent must require
explicit human approval from an authorised DBA or change approver.
