"""Local Blender command interface (Blender-MCP equivalent, no third-party addon).

3O layout:
  oskill_ops.py     pure functions: op schema/validation, engine presets, sample op builders
  bpy_runtime.py    runs *inside* Blender (bpy); executes a JSON op list
  obase_runner.py   external-tool adapter: blender --background --python bpy_runtime.py
  omodul_session.py orchestration: persistent scene session (ops replay) + render
  mcp_server.py     MCP stdio JSON-RPC server exposing the tools
"""
from .oskill_ops import validate_ops, ENGINE_PRESETS, bounce_ball_ops  # noqa: F401
