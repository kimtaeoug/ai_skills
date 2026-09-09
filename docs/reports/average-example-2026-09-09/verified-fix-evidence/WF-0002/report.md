# WF-0002: SIMULATION: average([]) returns None; no UI/research/model

Status: completed (revision 12)

Reason: receipt_committed
Policy version: 2
Execution seconds: 0.22721648216247559
Usage: {"cost_microusd": 0, "tokens": 0}
Unsettled reservations: 0

## Receipts

- [79c9ee199a03492be901c6f682230f0f2ce3c152c3014ba53f3306cab90d8bb4](artifacts/79c9ee199a03492be901c6f682230f0f2ce3c152c3014ba53f3306cab90d8bb4)
- [42532133536d797533fe4d868dafde90627828e58d37ef3d26eb70286b1f9d42](artifacts/42532133536d797533fe4d868dafde90627828e58d37ef3d26eb70286b1f9d42)
- [9b651948a5cf132b43e484e45cddea1c8a6cd1ee6779b31a5f914c6b76959883](artifacts/9b651948a5cf132b43e484e45cddea1c8a6cd1ee6779b31a5f914c6b76959883)

## Attempts

- DEV-01/attempt-1: done; route develop; reason verified
- TEST-01/attempt-1: done; route code_test; reason verified
- REPORT-01/attempt-1: done; route report; reason verified

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
      "action_digest": "1934bd85cf53b6ba5d5c51d59c02faea0b9812ceea45c6a3344f7949b4cd069e",
      "delivered": true,
      "expires_at": 1788928636.4464695,
      "issued_at": 1788928036.4464695,
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
        "workflow_id": "WF-0002"
      }
    },
    "version": 2
  }
]

## Limits

Trusted registered adapters only. Native provider hooks and human identity integration are not installed.
The SQLite state is authoritative; this report is a derived snapshot.
