from typing import Any

# credits/价格 advisor 占位, Wiki 按商业模式定
# paddle_price_id 由 Wiki 在 Paddle 后台创建后填入
CREDIT_PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "credits": 1000,
        "price_usd": 9.9,
        "paddle_price_id": "pri_01j00000000000000000000001",  # Dummy
    },
    "pro": {
        "credits": 5000,
        "price_usd": 39.9,
        "paddle_price_id": "pri_01j00000000000000000000002",
    },
    "business": {
        "credits": 20000,
        "price_usd": 129.0,
        "paddle_price_id": "pri_01j00000000000000000000003",
    },
}


def get_plan(plan_id: str) -> dict[str, Any]:
    """Retrieve plan configuration by ID."""
    if plan_id not in CREDIT_PLANS:
        raise ValueError(f"Unknown plan: {plan_id}")
    return CREDIT_PLANS[plan_id]
