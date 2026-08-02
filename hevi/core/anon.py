"""Layer 4 PII 脱敏(3O §5 Task 5.2):调起 oservi/omodul 前的用户身份伪名化。

``anon_user_ref`` 把真实 user_id 单向散列成 24 字符伪名;传给 omodul/oservi 的
``input_data`` 仅允许包含伪名,不允许真实身份标识。
"""

from __future__ import annotations

import hashlib

from hevi.core.config import settings


def anon_user_ref(user_id: str) -> str:
    """user_id → 24 字符伪名(SHA-256(salt:user_id) 截断)。

    salt 取自 settings.jwt_secret:换 key 即全量伪名失效(伪名只用于跨层关联,
    不用于持久身份),符合 Layer 4 与 omodul 之间的最小暴露原则。
    """
    salt = settings.jwt_secret or "hevi-anon"
    return hashlib.sha256(f"{salt}:{user_id}".encode()).hexdigest()[:24]


def sanitize_input_data(
    input_data: dict[str, object], *, user_id: str | None = None
) -> dict[str, object]:
    """清理传给 omodul/oservi 的 input_data:剔除身份键,注入 anon_user_ref。

    身份键(user_id/student_id/email/phone)一律不进入 3O 库;PII 扫描要求
    decision_trail/fingerprint 均不得携带真实身份。
    """
    _IDENTITY_KEYS = {"user_id", "student_id", "email", "phone", "phone_number"}
    cleaned: dict[str, object] = {k: v for k, v in input_data.items() if k not in _IDENTITY_KEYS}
    if user_id is not None:
        cleaned["anon_user_ref"] = anon_user_ref(user_id)
    return cleaned
