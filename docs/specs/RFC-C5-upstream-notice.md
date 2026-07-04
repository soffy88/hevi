# [obase] 需求：`fal_balance_probe` + provider 健康/余额活状态（3O §C5）

**目标仓库**：`helios-plat/obase`（基线 tag `v0.16.1`）
**建议版本**：`v0.17.0`（MINOR，纯新增)
**性质**：新增网络原语 + 一个轻量活状态存储;**下游 hevi 无法在应用层稳妥自建**(应归 L0 基座/Aegis,不该在 hevi 另建监控)。
**来源**：hevi SaaS · 见 `3O-new-elements-manifest.md §C5`。

---

## TL;DR

L0 路由要从"盲的静态表"升级为"交易所",需要**活的状态**:哪个 provider 还有余额/健康。obase 现有 `ProviderContractRegistry`(静态单价)+ `circuit_breaker`,但**没有余额/健康的动态状态**;`provider_health_check` 是 oprim 里的二元探针,不查余额、不做滚动 403 率。本提案给 obase 增:

1. `fal_balance_probe(*, config) -> {balance_usd, ok, source}` —— 查 fal balance API,查不到用滚动 403 率代理。
2. 一个轻量 **provider 健康/余额状态存储**(读写 `{name: {balance_usd, health, updated_at}}`),供路由/熔断读。**告警归 Aegis**,本提案只出探针 + 状态。

## 1. 问题

- fal / DashScope 双欠费(403)这次是账单——系统对余额是**盲的**,只能靠 403 事后感知。
- obase `provider_contract.py`:`ProviderContract{unit_cost_usd,...}` + `ProviderContractRegistry.derive_pricing()` → 静态 `PricingTable`。**无 balance/health 字段**。
- `oprim.provider_health_check` 只回二元健康,不查余额、不滚动 403 率。

## 2. 为什么放 obase(而非 hevi)

余额探针是**网络/运行时**关注点,路由器要的"活状态"是 L0 基座职责(SSOT §4-3 明确"归 Aegis runtime management,不在 hevi 建监控")。在 hevi 自建会重复造监控、且每个下游各建一套。放 obase 让所有下游共用一份。

## 3. 提案

```python
# obase 新增网络原语
async def fal_balance_probe(*, config: dict | None = None) -> dict:
    """→ {"balance_usd": float | None, "ok": bool, "source": "api" | "403_rate"}
    查 fal balance API;查不到(端点未开放/鉴权)则用滚动 403 率做代理指标。"""

# obase 轻量活状态(可挂在 ProviderContractRegistry 旁或独立)
class ProviderLiveState:
    def update(self, name: str, *, balance_usd: float | None = None,
               health: float | None = None) -> None: ...
    def get(self, name: str) -> dict:   # {balance_usd, health, updated_at}
        ...
```

- 探针周期性写 `ProviderLiveState`;路由器 `route(shot)` 只在 `health>阈 && balance>阈` 的 provider 里选。
- **告警**(低阈 → 通知)归 Aegis runtime,消费 `ProviderLiveState`,不在本提案。

## 4. 向后兼容 / 风险

- 纯新增(新函数 + 新类),现有 obase API 零变化。
- 探针失败降级为 403 率代理,不崩;活状态无数据时路由退回静态表(现行为)。

## 5. 请 obase owner 决策

1. `fal_balance_probe` 归 obase 网络层 OK?还是只出通用 `balance_probe(provider, ...)` 接口 + fal 适配?
2. `ProviderLiveState` 挂 `ProviderContractRegistry` 还是独立;持久化(Aegis 供给)还是进程内缓存?
3. Aegis 与 obase 的边界:探针+状态在 obase,告警在 Aegis —— 确认这条切法。
4. 目标版本 tag。

---

*下游背景*：hevi 未在应用层自建 provider 监控(刻意)。C5 是 L0"交易所"(成本感知路由)的活状态前置;成本侧 `ProviderContractRegistry` + `video_cost_proposal` 已在,缺的就是这份动态余额/健康。
