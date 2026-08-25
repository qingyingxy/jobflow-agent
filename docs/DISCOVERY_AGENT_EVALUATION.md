# M12 Discovery Agent 控制面评测

> 数据集：`m12-discovery-agent-fixtures-2026-08-09-v1`  
> 场景：13/13 通过  
> 模式：离线确定性 Fixture，不包含实时官网结果

## 评测边界

验证受控发现流程的安全、路由、轨迹、回退和状态边界；不代表真实官网召回率或端到端语义准确率。

## 聚合指标

| 指标 | 结果 | 阈值 | 状态 |
|---|---:|---:|---|
| `case_pass_rate` | 100.00% (13/13) | >= 100% | PASS |
| `unauthorized_source_access_rate` | 0.00% (0/2) | <= 0% | PASS |
| `trace_completeness_rate` | 100.00% (11/11) | >= 100% | PASS |
| `tool_route_accuracy` | 100.00% (9/9) | >= 100% | PASS |
| `fallback_correctness_rate` | 100.00% (3/3) | >= 100% | PASS |
| `non_job_false_accept_rate` | 0.00% (0/2) | <= 0% | PASS |
| `human_gate_accuracy` | 100.00% (2/2) | >= 100% | PASS |
| `budget_compliance_rate` | 100.00% (2/2) | >= 100% | PASS |
| `state_consistency_rate` | 100.00% (1/1) | >= 100% | PASS |

## 场景结果

| 场景 | 类别 | 结果 |
|---|---|---|
| `M12-001` | source_authorization | PASS |
| `M12-002` | source_authorization | PASS |
| `M12-003` | tool_routing | PASS |
| `M12-004` | tool_routing | PASS |
| `M12-005` | adapter_fallback | PASS |
| `M12-006` | adapter_fallback | PASS |
| `M12-007` | human_gate | PASS |
| `M12-008` | non_job_rejection | PASS |
| `M12-009` | structured_extraction | PASS |
| `M12-010` | failure_isolation | PASS |
| `M12-011` | budget | PASS |
| `M12-012` | analysis_gate | PASS |
| `M12-013` | state_idempotency | PASS |

## 限制

- 场景使用固定离线响应，不能衡量招聘官网实时可用性或岗位召回率。
- 非岗位误收率只覆盖清单中的动态壳与招聘指南负例，不等于互联网总体误收率。
- 本评测验证控制面与用户可见轨迹，不替代 39 条 JD Parser 字段评测。
- 字节与腾讯 Fixture 固化当前公开接口契约，官网接口变化仍需单独实时验收。

## 复现命令

```text
uv run python -m src.evaluation.discovery_agent `
  --manifest datasets/m12_discovery_agent_manifest.json `
  --output docs/evaluation/m12-discovery-agent-summary.json `
  --markdown docs/DISCOVERY_AGENT_EVALUATION.md
```

简历只能表述为“13 个离线控制面场景全部通过”；不能扩展为“真实官网搜索 100% 准确”。
