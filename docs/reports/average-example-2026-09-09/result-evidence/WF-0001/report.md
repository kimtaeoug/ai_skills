# WF-0001: SIMULATION: average([]) returns None; no UI/research/model

Status: failed (revision 9)

Reason: evidence_gate_failed
Policy version: 2
Execution seconds: 0.1807537078857422
Usage: {"cost_microusd": 0, "tokens": 0}
Unsettled reservations: 0

## Receipts

- [69edf1e7714ffa635e90a4912789575ae87b4e34cf7ff31d2e48c6d3559b0f99](artifacts/69edf1e7714ffa635e90a4912789575ae87b4e34cf7ff31d2e48c6d3559b0f99)

## Attempts

- DEV-01/attempt-1: done; route develop; reason verified
- TEST-01/attempt-1: failed; route code_test; reason evidence_gate_failed

## Policy changes

[
  {
    "after": {
      "approval_default": "deny",
      "approval_timeout_s": 600,
      "breaker": {
        "cooldown_s": 60,
        "failure_threshold": 3
      },
      "max_cost_microusd": 5000000,
      "max_loop_iterations": 3,
      "max_tokens": 100000,
      "max_tool_retries": 20,
      "retry": {
        "base_delay_s": 1,
        "cap_delay_s": 30,
        "max_attempts": 3,
        "max_elapsed_s": 180
      },
      "stage_timeout_s": 900,
      "tool_timeout_s": 120,
      "unknown_usage_policy": "awaiting_data",
      "workflow_timeout_s": 3600
    },
    "approver_id": "simulated-owner",
    "before": {
      "approval_default": "deny",
      "approval_timeout_s": 600,
      "breaker": {
        "cooldown_s": 60,
        "failure_threshold": 3
      },
      "max_cost_microusd": 5000000,
      "max_loop_iterations": 2,
      "max_tokens": 100000,
      "max_tool_retries": 20,
      "retry": {
        "base_delay_s": 1,
        "cap_delay_s": 30,
        "max_attempts": 3,
        "max_elapsed_s": 180
      },
      "stage_timeout_s": 900,
      "tool_timeout_s": 120,
      "unknown_usage_policy": "awaiting_data",
      "workflow_timeout_s": 3600
    },
    "reason": "Example workflow-local tuning at idle HIL boundary",
    "request": {
      "action_digest": "692e1f40ff98098c1e73a72d83e933ac8efdb01a23fa1e05d0bf9d100629622f",
      "delivered": true,
      "expires_at": 1788928005.1382139,
      "issued_at": 1788927405.1382139,
      "kind": "policy",
      "node_id": null,
      "payload": {
        "policy": {
          "approval_default": "deny",
          "approval_timeout_s": 600,
          "breaker": {
            "cooldown_s": 60,
            "failure_threshold": 3
          },
          "max_cost_microusd": 5000000,
          "max_loop_iterations": 3,
          "max_tokens": 100000,
          "max_tool_retries": 20,
          "retry": {
            "base_delay_s": 1,
            "cap_delay_s": 30,
            "max_attempts": 3,
            "max_elapsed_s": 180
          },
          "stage_timeout_s": 900,
          "tool_timeout_s": 120,
          "unknown_usage_policy": "awaiting_data",
          "workflow_timeout_s": 3600
        },
        "reason": "Example workflow-local tuning at idle HIL boundary"
      },
      "version_binding": {
        "code_fingerprint": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "contract_version": 1,
        "input_digest": "c82faf4b17c3c4d4ba02546cbf49789d5de1113a0300091403009ba59572c9f1",
        "plan_version": 1,
        "policy_version": 1,
        "workflow_id": "WF-0001"
      }
    },
    "version": 2
  }
]

## Limits

Trusted registered adapters only. Native provider hooks and human identity integration are not installed.
The SQLite state is authoritative; this report is a derived snapshot.
