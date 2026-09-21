"""Application composition shared by API and durable worker processes."""

from __future__ import annotations

from hevi.production.adapters import ProductionAdapterRegistry, configure_default_adapters


def configure_application_adapters() -> ProductionAdapterRegistry:
    """Install the application adapters without coupling the registry to API code."""
    from hevi.api.routers.cinematic import execute_task as cinematic_task_adapter
    from hevi.api.routers.director_pipeline import (
        execute_task as director_tongjian_task_adapter,
    )
    from hevi.api.routers.explainer import execute_task as explainer_task_adapter
    from hevi.api.routers.history_series import (
        execute_animation_task as history_animation_task_adapter,
    )
    from hevi.api.routers.tongjian import execute_task as tongjian_task_adapter
    from hevi.audio.task_adapter import execute_voice_studio_task
    from hevi.director.graph_render import execute_task as director_graph_task_adapter
    from hevi.season_planner.production import execute_shortdrama_task
    from hevi.studio.slate import execute_lot_task

    return configure_default_adapters(
        director_graph=director_graph_task_adapter,
        director_tongjian=director_tongjian_task_adapter,
        explainer=explainer_task_adapter,
        shortdrama=execute_shortdrama_task,
        tongjian=tongjian_task_adapter,
        voice_studio_tts=execute_voice_studio_task,
        lot=execute_lot_task,
        cinematic_animation=cinematic_task_adapter,
        history_animation=history_animation_task_adapter,
    )
