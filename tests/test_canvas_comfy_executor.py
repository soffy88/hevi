"""Tests for pipeline.canvas_comfy_executor (fake-server level only).

Every test here talks to a local fake ComfyUI server implemented in
this file (stdlib http.server). No real ComfyUI server is contacted,
no GPU is used, and no media is generated: a "done" result here
proves the submit/poll/cancel/error discipline, never a real
generation. The fake server is deliberately named FAKE in every
test name that depends on it.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hevi.capabilities.canvas_comfy_executor import (
    build_image_graph,
    execute_canvas_workflow,
    interrupt,
    snap_to_grid,
    submit_and_poll,
    translate_video_node,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import get


# ---------------------------------------------------------------- fake server

class _FakeComfy:
    """Configurable fake ComfyUI: /prompt, /history/<id>, /interrupt."""

    def __init__(self, *, mode="ok", polls_before_done=2):
        self.mode = mode
        self.polls_before_done = polls_before_done
        self.prompt_calls = []
        self.history_calls = []
        self.interrupt_calls = 0
        self._poll_counts = {}
        self._server = None
        self._thread = None
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw or b"{}")
                except ValueError:
                    payload = {}
                if self.path == "/prompt":
                    fake.prompt_calls.append(payload)
                    self._send(200, {"prompt_id": "fake-prompt-1", "node_errors": {}})
                elif self.path == "/interrupt":
                    fake.interrupt_calls += 1
                    self._send(200, {})
                else:
                    self._send(404, {"error": "unknown endpoint"})

            def do_GET(self):
                if self.path.startswith("/history/"):
                    prompt_id = self.path.split("/history/")[1]
                    fake.history_calls.append(prompt_id)
                    count = fake._poll_counts.get(prompt_id, 0) + 1
                    fake._poll_counts[prompt_id] = count
                    if fake.mode == "never":
                        self._send(404, {})
                    elif fake.mode == "error":
                        self._send(200, {
                            prompt_id: {
                                "status": {
                                    "status_str": "error",
                                    "completed": False,
                                    "messages": [
                                        ["execution_error", {
                                            "node_id": "5",
                                            "exception_type": "RuntimeError",
                                            "exception_message": "fake boom",
                                        }]
                                    ],
                                },
                                "outputs": {},
                            }
                        })
                    elif count >= fake.polls_before_done:
                        self._send(200, {
                            prompt_id: {
                                "status": {"status_str": "success", "completed": True},
                                "outputs": {
                                    "7": {"images": [{"filename": "canvas_00001_.png"}]}
                                },
                            }
                        })
                    else:
                        self._send(200, {})
                else:
                    self._send(404, {})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"

    def __enter__(self):
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        return False


def _video_template():
    return {
        "nodes": {
            "1": {"class_type": "CheckpointLoaderSimple",
                  "inputs": {"ckpt_name": "template.ckpt"}},
            "2": {"class_type": "CLIPTextEncode",
                  "inputs": {"clip": ["1", 1], "text": ""}},
            "3": {"class_type": "KSampler",
                  "inputs": {"seed": 0, "steps": 8, "model": ["1", 0]}},
            "4": {"class_type": "EmptyLatentImage",
                  "inputs": {"width": 512, "height": 512, "batch_size": 16}},
            "5": {"class_type": "SaveImage",
                  "inputs": {"images": ["3", 0]}},
        },
        "inject": [
            {"node": "2", "field": "text", "source": "prompt"},
            {"node": "3", "field": "seed", "source": "seed"},
            {"node": "4", "field": "width", "source": "width"},
            {"node": "4", "field": "height", "source": "height"},
            {"node": "1", "field": "ckpt_name", "source": "checkpoint"},
            {"node": "4", "field": "batch_size", "source": "frames"},
        ],
    }


def _model():
    return {
        "model_id": "fake-video",
        "install": [
            {"loader": "CheckpointLoaderSimple", "field": "ckpt_name",
             "folder": "checkpoints", "files": ["template.ckpt"]}
        ],
    }


def _snapshot():
    return {
        "source": "fake-object-info",
        "loaders": {"CheckpointLoaderSimple": ["template.ckpt", "other.ckpt"]},
    }


def _workflow():
    return {
        "nodes": [
            {"node_id": "frame", "type": "first_frame", "inputs": [], "params": {}},
            {"node_id": "clip", "type": "video", "inputs": ["frame"], "params": {
                "template": "vid", "prompt": "a cat walks", "seed": 7,
                "width": 500, "height": 290, "checkpoint": "template.ckpt",
                "frames": 24,
            }},
        ]
    }


# ---------------------------------------------------------------- builder unit

def test_snap_to_grid_rounds_to_32_and_rejects_bad_sizes():
    assert snap_to_grid(500) == 512
    assert snap_to_grid(512) == 512
    assert snap_to_grid(290) == 288
    assert snap_to_grid(33) == 32
    for bad in (0, -32, "512", 512.5, True):
        with pytest.raises(CapabilityError):
            snap_to_grid(bad)


def test_translate_video_node_injects_and_snaps_sizes():
    graph = translate_video_node(
        _workflow()["nodes"][1], {"vid": _video_template()}
    )
    assert graph["2"]["inputs"]["text"] == "a cat walks"
    assert graph["3"]["inputs"]["seed"] == 7
    assert graph["4"]["inputs"]["width"] == 512
    assert graph["4"]["inputs"]["height"] == 288
    assert graph["1"]["inputs"]["ckpt_name"] == "template.ckpt"
    assert graph["4"]["inputs"]["batch_size"] == 24


def test_translate_video_node_rejects_missing_prompt_and_unknown_template():
    node = {"node_id": "v", "type": "video", "inputs": [],
            "params": {"template": "vid"}}
    with pytest.raises(CapabilityError):
        translate_video_node(node, {"vid": _video_template()})
    node2 = {"node_id": "v", "type": "video", "inputs": [],
             "params": {"template": "nope", "prompt": "x"}}
    with pytest.raises(CapabilityError):
        translate_video_node(node2, {"vid": _video_template()})


def test_translate_video_node_rejects_inject_target_that_does_not_exist():
    template = _video_template()
    template["inject"] = [
        {"node": "2", "field": "no_such_field", "source": "prompt"}
    ]
    node = {"node_id": "v", "type": "video", "inputs": [],
            "params": {"template": "vid", "prompt": "x"}}
    with pytest.raises(CapabilityError):
        translate_video_node(node, {"vid": template})


def test_translate_video_node_rejects_non_video_node_and_unknown_source():
    node = {"node_id": "s", "type": "script", "inputs": [], "params": {}}
    with pytest.raises(CapabilityError):
        translate_video_node(node, {})
    template = _video_template()
    template["inject"] = [
        {"node": "2", "field": "text", "source": "mystery"}
    ]
    node2 = {"node_id": "v", "type": "video", "inputs": [],
             "params": {"template": "vid", "prompt": "x"}}
    with pytest.raises(CapabilityError):
        translate_video_node(node2, {"vid": template})


def test_build_image_graph_snaps_and_requires_checkpoint():
    graph = build_image_graph(
        prompt="a cat", seed=3, width=500, height=290,
        checkpoint="sd.ckpt", negative_prompt="blurry",
    )
    assert graph["4"]["inputs"]["width"] == 512
    assert graph["4"]["inputs"]["height"] == 288
    assert graph["1"]["inputs"]["ckpt_name"] == "sd.ckpt"
    assert graph["2"]["inputs"]["text"] == "a cat"
    with pytest.raises(CapabilityError):
        build_image_graph(
            prompt="a cat", seed=3, width=512, height=512, checkpoint="  "
        )


# ---------------------------------------------------------------- fake server

def test_fake_server_submit_and_poll_returns_outputs():
    with _FakeComfy(polls_before_done=2) as fake:
        result = submit_and_poll(
            fake.base_url,
            {"1": {"class_type": "SaveImage", "inputs": {}}},
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["prompt_id"] == "fake-prompt-1"
    assert result["outputs"]["7"]["images"][0]["filename"] == "canvas_00001_.png"
    assert len(fake.history_calls) >= 2


def test_fake_server_execution_error_carries_raw_history_verbatim():
    with _FakeComfy(mode="error") as fake:
        with pytest.raises(CapabilityError) as excinfo:
            submit_and_poll(
                fake.base_url,
                {"1": {"class_type": "SaveImage", "inputs": {}}},
                poll_interval_s=0.01, timeout_s=5.0,
            )
    assert "fake boom" in str(excinfo.value)
    assert "execution_error" in str(excinfo.value)


def test_fake_server_timeout_attempts_interrupt_then_raises():
    with _FakeComfy(mode="never") as fake:
        with pytest.raises(CapabilityError) as excinfo:
            submit_and_poll(
                fake.base_url,
                {"1": {"class_type": "SaveImage", "inputs": {}}},
                poll_interval_s=0.01, timeout_s=0.05,
            )
    assert "timed out" in str(excinfo.value)
    assert fake.interrupt_calls == 1


def test_fake_server_interrupt_posts_once():
    with _FakeComfy() as fake:
        report = interrupt(fake.base_url)
    assert report["interrupted"] is True
    assert fake.interrupt_calls == 1


def test_fake_server_unreachable_base_url_is_named():
    with pytest.raises(CapabilityError) as excinfo:
        submit_and_poll(
            "http://127.0.0.1:1",
            {"1": {"class_type": "SaveImage", "inputs": {}}},
            poll_interval_s=0.01, timeout_s=1.0,
        )
    assert "127.0.0.1:1" in str(excinfo.value)


# ---------------------------------------------------------------- whole run

def test_fake_server_execute_workflow_marks_video_done_and_skips_frame_node():
    with _FakeComfy() as fake:
        result = execute_canvas_workflow(
            _workflow(), {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=_snapshot(),
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["verdict"] == "pass"
    assert result["nodes"]["clip"]["status"] == "done"
    assert result["nodes"]["clip"]["artifact"] == "canvas_00001_.png"
    assert result["nodes"]["frame"]["status"] == "skipped"
    assert result["nodes"]["frame"]["reason"] == "not_a_video_node"
    assert result["submitted"] == ["fake-prompt-1"]
    by_id = {n["node_id"]: n for n in result["workflow"]["nodes"]}
    assert by_id["clip"]["status"] == "done"
    assert by_id["frame"]["status"] == "pending"
    assert len(fake.prompt_calls) == 1


def test_fake_server_execute_workflow_upstream_failure_skips_downstream():
    workflow = {
        "nodes": [
            {"node_id": "a", "type": "video", "inputs": [], "params": {
                "template": "vid", "prompt": "first", "checkpoint": "template.ckpt"}},
            {"node_id": "b", "type": "video", "inputs": ["a"], "params": {
                "template": "vid", "prompt": "second", "checkpoint": "template.ckpt"}},
        ]
    }
    with _FakeComfy(mode="error") as fake:
        result = execute_canvas_workflow(
            workflow, {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=_snapshot(),
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["verdict"] == "fail"
    assert result["nodes"]["a"]["status"] == "failed"
    assert result["nodes"]["b"]["status"] == "skipped"
    assert result["nodes"]["b"]["reason"] == "upstream_failed"
    assert len(fake.prompt_calls) == 1


def test_fake_server_execute_workflow_seed_batch_submits_one_per_seed():
    workflow = {
        "nodes": [
            {"node_id": "clip", "type": "video", "inputs": [], "params": {
                "template": "vid", "prompt": "seeded",
                "checkpoint": "template.ckpt"}},
        ]
    }
    with _FakeComfy() as fake:
        result = execute_canvas_workflow(
            workflow, {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=_snapshot(),
            seed_batches={"clip": {"base_seed": 10, "count": 2}},
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["verdict"] == "pass"
    assert len(fake.prompt_calls) == 2
    seeds = [c["prompt"]["3"]["inputs"]["seed"] for c in fake.prompt_calls]
    assert seeds == [10, 11]


def test_execute_refused_before_submit_when_model_file_missing():
    snapshot = {"source": "fake", "loaders": {"CheckpointLoaderSimple": []}}
    with _FakeComfy() as fake:
        result = execute_canvas_workflow(
            _workflow(), {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=snapshot,
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["verdict"] == "fail"
    assert len(fake.prompt_calls) == 0
    assert any(f["code"] == "model_file_missing" for f in result["failures"])


def test_execute_refused_before_submit_when_snapshot_missing():
    with _FakeComfy() as fake:
        result = execute_canvas_workflow(
            _workflow(), {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=None,
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert result["verdict"] == "fail"
    assert len(fake.prompt_calls) == 0


def test_execute_rejects_cyclic_workflow_without_submitting():
    workflow = {
        "nodes": [
            {"node_id": "a", "type": "video", "inputs": ["b"], "params": {
                "template": "vid", "prompt": "x"}},
            {"node_id": "b", "type": "video", "inputs": ["a"], "params": {
                "template": "vid", "prompt": "x"}},
        ]
    }
    with _FakeComfy() as fake:
        with pytest.raises(CapabilityError):
            execute_canvas_workflow(
                workflow, {"vid": _video_template()},
                base_url=fake.base_url, model=_model(), snapshot=_snapshot(),
            )
    assert len(fake.prompt_calls) == 0


def test_execute_does_not_mutate_input_workflow():
    workflow = _workflow()
    before = json.dumps(workflow, sort_keys=True)
    with _FakeComfy() as fake:
        execute_canvas_workflow(
            workflow, {"vid": _video_template()},
            base_url=fake.base_url, model=_model(), snapshot=_snapshot(),
            poll_interval_s=0.01, timeout_s=5.0,
        )
    assert json.dumps(workflow, sort_keys=True) == before


def test_capability_registered():
    cap = get("pipeline.canvas_comfy_executor")
    assert cap is not None
    assert "fake" in cap.description.lower() or "Fake" in cap.description
