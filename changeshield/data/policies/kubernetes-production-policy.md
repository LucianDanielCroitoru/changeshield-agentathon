# Kubernetes Production Release Policy

**Policy owner:** Platform Reliability Team  
**Applies to:** Kubernetes production workloads  
**Policy version:** 1.0  
**Classification:** Demo policy — non-confidential  

## Purpose

This policy defines the minimum controls required before deploying a
Kubernetes workload to production.

## K8S-PROD-01: Resource requests and limits

Every production container must define:

- CPU request
- Memory request
- CPU limit
- Memory limit

A deployment without defined resource requests cannot be approved for
production because the scheduler cannot reliably reserve capacity.

## K8S-PROD-02: Health checks

Every production service must define:

- A readiness probe
- A liveness probe

A missing readiness probe can route traffic to an unready workload.
A missing liveness probe can leave an unhealthy workload running.

## K8S-PROD-03: CPU reduction protection

Reducing a CPU request for a production service requires:

- Load-test evidence
- Staging validation
- SRE approval

If the service is business-critical, the default decision is BLOCK
until these conditions are met.

## K8S-PROD-04: Safe rollout strategy

Business-critical production services must use:

- A rolling update with controlled surge/unavailability, or
- A canary deployment with limited initial traffic

A deployment strategy that allows all replicas to become unavailable
must be blocked.

## K8S-PROD-05: Rollback readiness

Every production deployment must include:

- A known stable previous version
- A rollback command or automated rollback procedure
- A defined health-check observation period

A deployment without rollback information must not be approved for
unattended production execution.

## K8S-PROD-06: Autoscaling validation

If a workload relies on Horizontal Pod Autoscaler:

- Resource requests must be defined
- Minimum and maximum replicas must be configured
- The target utilization threshold must be documented

HPA does not compensate for missing requests, probes, or unsafe
rollout settings.

## K8S-PROD-07: Required release decision

The Kubernetes Release Safety Agent must return one of these decisions:

- `APPROVE` — all baseline controls are present
- `APPROVE_WITH_GUARDRAILS` — canary, staging evidence, or SRE review is required
- `BLOCK` — critical policy violation, unsafe rollout, missing rollback, or insufficient evidence

## K8S-PROD-08: Human approval and execution boundary

The agent must never run `kubectl apply`, `helm upgrade`, `kubectl rollout
restart`, or `kubectl rollout undo`.

For medium, high, or critical risk findings, the agent must require
explicit approval from an authorised SRE, platform engineer, or change
approver.
