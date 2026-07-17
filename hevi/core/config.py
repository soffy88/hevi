import sys

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "hevi"
    app_version: str = "6.0.0"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://hevi:hevi@localhost:5432/hevi"
    redis_url: str = "redis://localhost:6379/0"

    # HEVI-SPEC-03 资产库(hevi-vault docker-compose 项目,独立于上面的主库/主 MinIO)
    vault_database_url: str = "postgresql://hevi:hevi@localhost:5441/hevi_vault"
    vault_minio_endpoint: str = "localhost:9000"
    vault_minio_access_key: str = "hevi"
    vault_minio_secret_key: str = "hevi1234"
    vault_minio_secure: bool = False

    # HEVI-EXEC-01 §0:「智伯索地」C-P0 单 run 预算熔断线(soffy 选定区间 $5-10 的上限)
    tongjian_run_budget_usd: float = 10.0

    # Stored as str; parsed to list[str] by _cors_list() in main.py.
    # Accepts: "*", "https://a.com", "https://a.com,https://b.com", or JSON '["https://a.com"]'
    cors_origins: str = "*"

    # CosyVoice TTS (local GPU) configuration
    cosyvoice_model_dir: str = "/opt/cosyvoice/model"
    cosyvoice_use_watermark: bool = False

    # L5 角色卡参考图(SDXL 本地文生图,tongjian §5.1 步骤3-4)。权重 ~7GB,
    # 根分区(/)只剩 20G 空闲,故缓存目录放 /data 而非默认 ~/.cache/huggingface。
    sdxl_model_dir: str = "/data/models/huggingface"

    # LibLib.tv (libtv) agent-im:电影级生视频专业平台。hevi 产出加厚剧本 → 中继给 agent-im
    # 出片(见 hevi/video/libtv_service.py)。key 走 .env,不硬编码。
    libtv_access_key: str = ""
    libtv_im_base: str = "https://im.liblib.tv"

    # 剧本场数上限(测试用):加厚剧本后一段故事常产出 10+ 场 → 下游 50+ 镜、~4min 成片,
    # 渲染久且接近 tongjian_run_budget_usd 熔断线。设一个正整数只取前 N 场做快速小规模验证
    # (剧本层截断,下游 design/scene_stage/shot 全派生自它,一处生效)。None/0 = 不限(全量)。
    director_max_scenes: int | None = None

    # 剧本 LLM 自审-修订(2026-07-16):初稿产出后再跑一道"审核员挑毛病并改好"的二遍
    # (见 screenplay.py::_REVIEW_PROMPT)。实测质量显著提升(10→13 场、画面从概要变分镜级)。
    # 总延迟 ~106s > 同步反代 100s,故②剧本阶段已改后台任务(_run_screenplay_generate,
    # 前端轮询 screenplay_generating),这里可安全开启。关掉则只出初稿、省一次 LLM 调用。
    screenplay_llm_review: bool = True

    # INC-002 单镜表演密度档:给每个镜头 LLM 生成 performance_track(镜头内部表演时间轴)的深度。
    # L0=不生成(默认,inert,走 action_beats 老路);L1 eyeline+emotional+body;L2 +facial+camera;
    # L3 +muscle。每镜一次 LLM 调用(并发),开高档会显著加长分镜生成时间与花费,按需开。
    performance_track_tier: str = "L0"

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    @field_validator("jwt_secret")
    @classmethod
    def jwt_secret_required(cls, v: str) -> str:
        if not v:
            print("FATAL: JWT_SECRET must be set in .env", file=sys.stderr)
            sys.exit(1)
        return v

    # Cost settings
    ltx2_price_usd: float = 0.04  # per second (legacy; 2D pricing in pricing_table.py)
    ltx2_default_tier: str = "fast"  # fal.ai tier: "fast" | "pro"
    # ¥0.24/s 720p ÷ 7.25 CNY/USD; source: Alibaba Cloud billing 2026-06
    wan_price_usd: float = 0.033  # per second
    cost_limit_per_task_usd: float = 50.0
    max_duration_per_task_s: float = 3600.0
    credits_per_usd: int = 100
    # 三层预算熔断第3层(HEVI 路线图 Phase1 #30):全局每日聚合上限,跟 cost_limit_per_task_usd
    # (单任务)、用户 credit 余额(BillingService)是独立的三层。None = 未配置,不做这层检查
    # (向后兼容——不是每个部署都想开,具体额度没有客观默认值,需要显式配置才生效)。
    daily_budget_usd: float | None = None

    # L3 体检闭环(§7-4):确定性体检/评分卡不及格 → 定向返工的封顶轮数(0=关,只 log 不返工)。
    # 只在不合格时触发,合格片零额外开销;可用 task config_json["auto_rework_rounds"] 覆盖。
    auto_rework_max_rounds: int = 1
    rework_consistency_floor: float = 0.75
    # 设计文档 §4.3:单个镜头的重试次数硬上限——跟 auto_rework_max_rounds(整任务返工
    # 轮数)是两个维度:一轮返工可能同时点名好几个镜头,这个上限管的是"这一个镜头"
    # 累计被重烧了几次,超限即视为该镜头降级交付,不再消耗算力空转。
    shot_retry_max: int = 3

    # Paddle
    paddle_api_key: str | None = None
    paddle_webhook_secret: str | None = None
    paddle_environment: str = "sandbox"


settings = Settings()
