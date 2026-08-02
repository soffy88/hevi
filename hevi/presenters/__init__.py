"""3O §3 Task 3.2:presenters 已收拢进 hevi.digital_human(models 侧)。

本包为兼容 shim:Presenter 模型与渲染能力归属 digital_human 域。
"""

from hevi.digital_human.models import Presenter
from hevi.presenters.repository import PresenterRepository

__all__ = ["Presenter", "PresenterRepository"]
