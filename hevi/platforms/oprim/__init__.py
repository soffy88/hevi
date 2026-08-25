"""oprim:平台管理无状态原子。不得 import oskill / omodul。"""

from __future__ import annotations

from hevi.platforms.oprim.extract import (
    extract_aweme_id,
    extract_aweme_id_from_url,
    extract_ks_photo_id_from_url,
    extract_note_id_from_url,
    extract_query_params,
    extract_sec_uid_from_url,
    extract_short_link,
    extract_urls,
    extract_xsec_token_from_url,
    identify_platform,
    is_short_link,
    looks_like_platform_url,
    normalize_share_text,
    parse_aweme_card,
    parse_note_card,
    strip_emoji,
)
from hevi.platforms.oprim.login import (
    cookie_str_from_state,
    has_a1,
    is_creator_cookie,
    platform_needs_creator_state,
    platform_supports_keyword_collection,
    resolve_browser_mode,
    validate_storage_state,
)
from hevi.platforms.oprim.risk import (
    classify_auth_failure,
    cooldown_for_error,
    cooldown_minutes_for,
    is_risk_status,
    next_risk_check_time,
    progressive_recovery_steps,
)
from hevi.platforms.oprim.signing import (
    abogus_available,
    sign_request,
)

__all__ = [
    "abogus_available",
    "classify_auth_failure",
    "cookie_str_from_state",
    "cooldown_for_error",
    "cooldown_minutes_for",
    "extract_ks_photo_id_from_url",
    "extract_note_id_from_url",
    "extract_query_params",
    "extract_sec_uid_from_url",
    "extract_short_link",
    "extract_urls",
    "extract_xsec_token_from_url",
    "has_a1",
    "identify_platform",
    "is_creator_cookie",
    "is_risk_status",
    "is_short_link",
    "looks_like_platform_url",
    "next_risk_check_time",
    "normalize_share_text",
    "parse_aweme_card",
    "parse_note_card",
    "platform_needs_creator_state",
    "platform_supports_keyword_collection",
    "progressive_recovery_steps",
    "resolve_browser_mode",
    "sign_request",
    "strip_emoji",
    "validate_storage_state",
]