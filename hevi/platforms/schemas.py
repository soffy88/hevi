"""平台管理 3O 包的 schema 契约。

对齐 CreatorHub 的数据模型:账号/监控目标/内容记录/评论规则/发布任务/风控等级。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PlatformName(str, Enum):
    """支持的平台标识符。"""

    DOUYIN = "douyin"
    XIAOHONGSHU = "xhs"
    KUAISHOU = "kuaishou"
    SHIPINHAO = "shipinhao"


# ─────────── 账号 ───────────


class AccountProfile(BaseModel):
    """平台账号的持久化登录态摘要(不含敏感 Cookie 明文)。"""

    id: int | None = None
    platform: str
    nickname: str = ""
    sec_uid: str = ""
    user_id: str = ""
    avatar_url: str = ""
    status: str = "pending"  # pending | active | logged_out | risk
    has_creator_state: bool = False
    has_read_state: bool = False
    proxy: str = ""
    browser_mode: str = "auto"  # auto | patchright | cdp
    created_at: datetime | None = None
    last_check_at: datetime | None = None
    risk_level: str = "normal"  # normal | cool | warn | blocked
    risk_reason: str = ""
    risk_until: datetime | None = None
    export_group: str = "direct"
    cookies_count: int = 0

    def is_available(self) -> bool:
        return self.status == "active" and self.risk_level in ("normal",)

    def can_publish(self) -> bool:
        """是否具备发布所需的登录态(读取态 + 创作者态)。"""
        if not self.is_available():
            return False
        if self.platform in (PlatformName.DOUYIN.value, PlatformName.KUAISHOU.value,
                              PlatformName.SHIPINHAO.value):
            return self.has_creator_state or self.has_read_state
        return self.has_creator_state or self.has_read_state


# ─── 监控 ───


class MonitorTarget(BaseModel):
    """作品/评论/弹幕监控目标。"""

    id: int | None = None
    platform: str
    account_id: int | None = None
    kind: str = "work"  # work | comment | danmaku
    target_type: str = "user"  # user | work | keyword
    target_id: str = ""
    target_name: str = ""
    alias: str = ""
    group_name: str = ""
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    interval_seconds: int = 300
    backfill_count: int = 0
    max_records_total: int = 10000
    last_scan_at: datetime | None = None
    last_error: str = ""
    # 评论/弹幕专有
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    min_like_count: int = 0
    min_text_length: int = 0
    max_text_length: int = 0
    # 弹幕专有
    time_start_ms: int = 0
    time_end_ms: int = 0
    probe_step_seconds: int = 5
    max_scrolls: int = 30
    mode: str = "public"  # public | creator

    def matches_tags(self, group_name: str = "", tag: str = "") -> bool:
        if group_name and group_name != self.group_name:
            return False
        return not (tag and tag not in self.tags)


class ContentRecord(BaseModel):
    """已采集的内容记录。"""

    id: int | None = None
    platform: str
    aweme_id: str = ""
    note_id: str = ""
    title: str = ""
    desc: str = ""
    author: str = ""
    author_id: str = ""
    media_type: str = "video"  # video | image
    cover_url: str = ""
    media_urls: list[str] = Field(default_factory=list)
    local_path: str = ""
    download_status: str = "pending"  # pending | downloading | done | failed
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    create_time: int = 0
    xsec_token: str = ""
    tags: list[str] = Field(default_factory=list)
    monitor_id: int | None = None
    collected_at: datetime | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


# ─── 评论规则 ───


class CommentRule(BaseModel):
    """自动评论/回复规则。"""

    id: int | None = None
    platform: str
    name: str = ""
    mode: str = "auto_reply"  # auto_reply | auto_comment
    account_id: int
    target_kind: str = "self"  # self | work | keyword | creator
    keyword: str = ""
    sec_uid: str = ""
    aweme_id: str = ""
    note_id: str = ""
    xsec_token: str = ""
    templates: list[str] = Field(default_factory=list)
    use_ai: bool = False
    require_review: bool = False
    reply_filter: str = ""
    skip_keywords: str = ""
    daily_cap: int = 20
    min_gap_seconds: int = 90
    max_per_run: int = 5
    interval_seconds: int = 1800
    enabled: bool = False
    last_error: str = ""
    last_run_at: datetime | None = None


class CommentTask(BaseModel):
    """单条评论/回复任务。"""

    id: int | None = None
    platform: str
    rule_id: int | None = None
    account_id: int
    aweme_id: str = ""
    note_id: str = ""
    target_comment_id: str = ""
    target_nick: str = ""
    target_text: str = ""
    content: str = ""
    status: str = "draft"  # draft | pending | doing | done | failed | canceled
    result: str = ""
    error: str = ""
    method: str = "browser"  # browser | api
    scheduled_at: datetime | None = None
    done_at: datetime | None = None
    created_at: datetime | None = None


# ─── 发布任务 ───


class PublishTask(BaseModel):
    """跨平台发布任务。"""

    id: int | None = None
    platform: str
    account_id: int
    media_type: str = "images"  # images | video
    title: str = ""
    desc: str = ""
    topics: str = ""
    location: str = ""
    visibility: str = "public"
    allow_save: bool = True
    media_paths: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending | doing | done | failed | canceled
    result_url: str = ""
    error: str = ""
    source_platform: str = ""
    source_content_id: str = ""
    scheduled_at: datetime | None = None
    created_at: datetime | None = None
    done_at: datetime | None = None

    def is_available(self) -> bool:
        """检查发布任务是否可用(有媒体文件)。"""
        return bool(self.media_paths)


class PublishResult(BaseModel):
    """一次发布尝试的结果。"""

    status: str
    platform: str
    external_id: str | None = None
    url: str | None = None
    reason: str = ""
    trail: list[dict[str, Any]] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "platform": self.platform,
            "external_id": self.external_id,
            "url": self.url,
            "reason": self.reason,
            "trail": self.trail,
        }


# ─── 风控 ───


class RiskLevel(str, Enum):
    """风控等级。"""

    NORMAL = "normal"
    COOL = "cool"  # 冷却中
    WARN = "warn"  # 降级恢复
    BLOCKED = "blocked"  # 硬封禁


class RiskCategory(str, Enum):
    """平台错误分类。"""

    OK = "ok"
    RISK = "risk"
    AUTH = "auth"
    NETWORK = "network"
    UNKNOWN = "unknown"


def classify_platform_error(exc: BaseException | str) -> tuple[RiskCategory, str]:
    """把异常/错误串分类为风控/授权/网络/未知。

    对齐 CreatorHub 的 classify_platform_error 语义。
    """
    text = str(exc).lower()
    if any(k in text for k in ("403", "429", "461", "471", "captcha", "verify", "验证")):
        return RiskCategory.RISK, text
    if any(k in text for k in ("login", "auth", "cookie", "token", "登录态")):
        return RiskCategory.AUTH, text
    if any(k in text for k in ("connect", "timeout", "network", "dns", "proxy", "连接")):
        return RiskCategory.NETWORK, text
    return RiskCategory.UNKNOWN, text
