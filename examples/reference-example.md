---
name: example-reference-monitoring-dashboards
description: 例:项目监控面板地址,用户问到性能/可用性时可查
metadata:
  type: reference
---

# 监控面板速查

**用途**:用户问"API P99 latency 多少"、"昨天的错误率"、"上周容量水位" → Claude 知道去哪看。

## 各服务监控地址

| 服务 | 监控地址 | 看什么 |
|---|---|---|
| API Gateway | `https://grafana.example.com/d/api-gateway` | RPS / P50/P99 latency / 错误率 |
| User Service | `https://grafana.example.com/d/user-svc` | DB connections / cache hit rate |
| Payment Worker | `https://grafana.example.com/d/payment-worker` | queue depth / processing time |

## 日志查询

```bash
# 用 Loki/ES query 找特定 trace
curl -G "https://logs.example.com/loki/api/v1/query_range" \
  --data-urlencode "query={app=\"api-gateway\"} |= \"trace_id=ABC\""
```

## 告警

- 紧急(P0): #oncall-critical Slack
- 高(P1): #oncall-high  
- 中低: PagerDuty + Email

**注意**:Claude 不应该自己跑 query / 改告警规则。**只提供地址,让用户/团队自己看**。
