# M13 Trusted Discovery Evaluation

> 本报告只覆盖离线确定性 Fixture，不包含真实官网召回率，也不能扩展为真实网络验证 100% 准确。

- Cases: 9/9
- Thresholds passed: True

## Metrics

| Metric | Value | Passed |
| --- | ---: | --- |
| `official_verification_rate` | 1.000 | True |
| `non_job_false_acceptance_rate` | 0.000 | True |
| `dedupe_accuracy` | 1.000 | True |
| `search_snippet_pollution_rate` | 0.000 | True |
| `availability_status_accuracy` | 1.000 | True |
| `browser_handoff_success_rate` | 1.000 | True |

## Verification Failure Distribution

```json
{
  "lead_not_job_page": 1,
  "url_fetch_failed": 2
}
```
