"""oskill:平台管理技能层。每个技能组合 ≥2 个 oprim 原语。不得 import omodul。"""

from __future__ import annotations

from hevi.layer4_legacy.platforms.oskill_impl.account import (
    AccountManager,
    load_account_state,
    save_account_state,
    verify_account,
)
from hevi.layer4_legacy.platforms.oskill_impl.comment import (
    create_comment_rule,
    execute_comment_rule,
    parse_comment_target,
)
from hevi.layer4_legacy.platforms.oskill_impl.content import (
    collect_content,
    download_media,
    monitor_targets,
)
from hevi.layer4_legacy.platforms.oskill_impl.risk import (
    RiskController,
    apply_cooldown,
    check_account_risk,
    schedule_recovery,
)
from hevi.layer4_legacy.platforms.oskill_impl.share_downloader import (
    ShareDownloader,
    parse_share_text,
    resolve_share_link,
)

__all__ = [
    "AccountManager",
    "RiskController",
    "ShareDownloader",
    "apply_cooldown",
    "check_account_risk",
    "collect_content",
    "create_comment_rule",
    "download_media",
    "execute_comment_rule",
    "load_account_state",
    "monitor_targets",
    "parse_comment_target",
    "parse_share_text",
    "resolve_share_link",
    "save_account_state",
    "schedule_recovery",
    "verify_account",
]
