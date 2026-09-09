# WF-0002: SIMULATION: average([]) returns None; no UI/research/model

Status: completed (revision 12)

Reason: receipt_committed
Policy version: 2
Execution seconds: 0.24506878852844238
Usage: {"cost_microusd": 0, "tokens": 0}
Unsettled reservations: 0

## Receipts

- [aee459928b387eea117e476f6546b497d95ba7f8bd6708116a9b9908d171279f](artifacts/aee459928b387eea117e476f6546b497d95ba7f8bd6708116a9b9908d171279f)
- [d35b714862b835a8e7d8c9ac7a69caaf0ee762dba71a710197b74310a041f85e](artifacts/d35b714862b835a8e7d8c9ac7a69caaf0ee762dba71a710197b74310a041f85e)
- [60052e026086837e4d95f7068d1e33faab3f726d0f303c35efb0841fe3905f6a](artifacts/60052e026086837e4d95f7068d1e33faab3f726d0f303c35efb0841fe3905f6a)

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
      "action_digest": "56f6915236b9365f955d3c5aa1c39c7db3b5165d354ca9847270550a344684f3",
      "delivered": true,
      "expires_at": 1788928005.3623462,
      "issued_at": 1788927405.3623462,
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
