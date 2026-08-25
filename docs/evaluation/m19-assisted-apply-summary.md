# M19 Assisted Apply Fixture Evaluation

> 本报告只覆盖离线结构化 Mock ATS，不代表真实 ATS 兼容率、真实投递成功率或用户耗时。

- Cases: 14/14
- Thresholds passed: True
- Manual interventions: 11
- Ready-to-submit duration: not available in deterministic fixtures

## Metrics

| Metric | Value | Passed |
| --- | ---: | --- |
| `field_fill_accuracy` | 1.000 | True |
| `resume_version_accuracy` | 1.000 | True |
| `human_handoff_accuracy` | 1.000 | True |
| `submission_receipt_coverage` | 1.000 | True |
| `sensitive_field_misfill_rate` | 0.000 | True |
| `false_submitted_rate` | 0.000 | True |

## Cases

| Case | Provider | Passed | Handoff | Receipt |
| --- | --- | --- | --- | --- |
| `greenhouse-success` | GREENHOUSE | True | none | True |
| `lever-native-select-confirmed` | LEVER | True | none | True |
| `sensitive-field-unconfirmed` | LEVER | True | sensitive_field_confirmation_required | False |
| `custom-dropdown-handoff` | LEVER | True | unsupported_field_control | False |
| `missing-open-answer` | GREENHOUSE | True | approved_value_missing | False |
| `captcha-handoff` | GREENHOUSE | True | browser_captcha_required | False |
| `resume-upload-verification-failure` | GREENHOUSE | True | field_fill_failed:resume | False |
| `login-and-2fa-handoff` | LEVER | True | browser_2fa_required, browser_login_required | False |
| `permission-handoff` | GREENHOUSE | True | browser_permission_required | False |
| `security-challenge-handoff` | GREENHOUSE | True | browser_security_challenge | False |
| `dynamic-page-change` | GREENHOUSE | True | ats_page_changed | False |
| `non-resume-file-handoff` | GREENHOUSE | True | unsupported_field_control | False |
| `generic-thank-you-pseudo-success` | GREENHOUSE | True | none | False |
| `explicit-failure-page` | LEVER | True | none | False |
