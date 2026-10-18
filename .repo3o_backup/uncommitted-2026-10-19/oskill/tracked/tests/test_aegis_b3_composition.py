"""B3 tests: retrieve_runbook, synthesize_action_plan, verify_health_after_action,
caddy_route_add (composition oskill elements — mock oprim callables).
"""

import json
from unittest.mock import MagicMock, patch

from oskill.caddy_route_add import CaddyRouteAddResult, caddy_route_add
from oskill.retrieve_runbook import RetrieveRunbookResult, retrieve_runbook
from oskill.synthesize_action_plan import ActionPlanResult, synthesize_action_plan
from oskill.verify_health_after_action import (
    HealthVerifyResult,
    verify_health_after_action,
    verify_health_after_action_detail,
)

# ─── retrieve_runbook ─────────────────────────────────────────────────────────


class TestRetrieveRunbook:
    def _make_fns(self, raw_results):
        encode_fn = MagicMock(return_value=[0.1, 0.2, 0.3])
        search_fn = MagicMock(return_value=raw_results)
        return encode_fn, search_fn

    def test_returns_result_model(self):
        encode_fn, search_fn = self._make_fns(
            [{"id": "rb1", "title": "OOM fix", "content": "restart", "score": 0.9, "tags": []}]
        )
        result = retrieve_runbook(
            query="OOM kill", vector_encode_fn=encode_fn, vector_search_fn=search_fn
        )
        assert isinstance(result, RetrieveRunbookResult)
        assert len(result.results) == 1

    def test_encodes_query(self):
        encode_fn, search_fn = self._make_fns([])
        retrieve_runbook(
            query="nginx restart", vector_encode_fn=encode_fn, vector_search_fn=search_fn
        )
        encode_fn.assert_called_once_with("nginx restart")

    def test_calls_search_with_vector(self):
        encode_fn, search_fn = self._make_fns([])
        encode_fn.return_value = [0.5, 0.6]
        retrieve_runbook(
            query="test", vector_encode_fn=encode_fn, vector_search_fn=search_fn, top_k=3
        )
        call_kwargs = search_fn.call_args[1]
        assert call_kwargs["vector"] == [0.5, 0.6]
        assert call_kwargs["top_k"] == 6  # top_k * 2

    def test_filters_below_min_score(self):
        encode_fn, search_fn = self._make_fns(
            [
                {"id": "r1", "title": "A", "content": "c", "score": 0.8, "tags": []},
                {"id": "r2", "title": "B", "content": "c", "score": 0.3, "tags": []},
            ]
        )
        result = retrieve_runbook(
            query="q",
            vector_encode_fn=encode_fn,
            vector_search_fn=search_fn,
            min_score=0.5,
        )
        assert len(result.results) == 1
        assert result.results[0].runbook_id == "r1"

    def test_results_sorted_by_score_desc(self):
        encode_fn, search_fn = self._make_fns(
            [
                {"id": "r1", "title": "A", "content": "c", "score": 0.6, "tags": []},
                {"id": "r2", "title": "B", "content": "c", "score": 0.9, "tags": []},
            ]
        )
        result = retrieve_runbook(
            query="q", vector_encode_fn=encode_fn, vector_search_fn=search_fn, min_score=0.1
        )
        assert result.results[0].score > result.results[1].score

    def test_top_k_limits_results(self):
        encode_fn, search_fn = self._make_fns(
            [
                {
                    "id": f"r{i}",
                    "title": f"T{i}",
                    "content": "c",
                    "score": 0.9 - i * 0.01,
                    "tags": [],
                }
                for i in range(10)
            ]
        )
        result = retrieve_runbook(
            query="q",
            vector_encode_fn=encode_fn,
            vector_search_fn=search_fn,
            top_k=3,
            min_score=0.1,
        )
        assert len(result.results) <= 3

    def test_total_candidates_reflects_raw_count(self):
        raw = [
            {"id": f"r{i}", "title": "T", "content": "c", "score": 0.9, "tags": []}
            for i in range(7)
        ]
        encode_fn, search_fn = self._make_fns(raw)
        result = retrieve_runbook(
            query="q", vector_encode_fn=encode_fn, vector_search_fn=search_fn, min_score=0.1
        )
        assert result.total_candidates == 7

    def test_uses_text_field_fallback(self):
        encode_fn, search_fn = self._make_fns(
            [{"id": "r1", "title": "T", "text": "runbook body", "score": 0.8, "tags": []}]
        )
        result = retrieve_runbook(
            query="q", vector_encode_fn=encode_fn, vector_search_fn=search_fn, min_score=0.5
        )
        assert result.results[0].content == "runbook body"

    def test_empty_results_when_all_filtered(self):
        encode_fn, search_fn = self._make_fns(
            [{"id": "r1", "title": "T", "content": "c", "score": 0.1, "tags": []}]
        )
        result = retrieve_runbook(
            query="q",
            vector_encode_fn=encode_fn,
            vector_search_fn=search_fn,
            min_score=0.9,
        )
        assert result.results == []


# ─── synthesize_action_plan ───────────────────────────────────────────────────


class TestSynthesizeActionPlan:
    def _json_llm(self, steps):
        def llm(prompt):
            return json.dumps(steps)

        return llm

    def test_returns_result_model(self):
        steps = [
            {
                "plugin_id": "restart",
                "params": {},
                "description": "Restart service",
                "rationale": "OOM",
            }
        ]
        result = synthesize_action_plan(symptom="OOM kill", llm_fn=self._json_llm(steps))
        assert isinstance(result, ActionPlanResult)
        assert len(result.steps) == 1

    def test_step_numbers_sequential(self):
        steps = [
            {"plugin_id": "p1", "params": {}, "description": "step1", "rationale": "r1"},
            {"plugin_id": "p2", "params": {}, "description": "step2", "rationale": "r2"},
        ]
        result = synthesize_action_plan(symptom="test", llm_fn=self._json_llm(steps))
        assert result.steps[0].step_number == 1
        assert result.steps[1].step_number == 2

    def test_max_steps_respected(self):
        steps = [
            {"plugin_id": f"p{i}", "params": {}, "description": f"s{i}", "rationale": "r"}
            for i in range(10)
        ]
        result = synthesize_action_plan(symptom="test", llm_fn=self._json_llm(steps), max_steps=3)
        assert len(result.steps) <= 3

    def test_context_includes_signal_class(self):
        prompts = []

        def llm(p):
            prompts.append(p)
            return "[]"

        synthesize_action_plan(symptom="crash", llm_fn=llm, signal_class="infrastructure")
        assert "infrastructure" in prompts[0]

    def test_context_includes_runbook(self):
        prompts = []

        def llm(p):
            prompts.append(p)
            return "[]"

        synthesize_action_plan(symptom="crash", llm_fn=llm, runbook_context="Restart nginx")
        assert "Restart nginx" in prompts[0]

    def test_llm_returns_plain_text_parsed_gracefully(self):
        def llm(p):
            return "I recommend restarting the service"

        result = synthesize_action_plan(symptom="crash", llm_fn=llm)
        assert result.steps == []
        assert result.llm_reasoning is not None

    def test_llm_returns_json_in_text_extracted(self):
        steps = [
            {"plugin_id": "scale", "params": {"n": 2}, "description": "Scale", "rationale": "load"}
        ]

        def llm(p):
            return f"Here is the plan:\n{json.dumps(steps)}\nEnd."

        result = synthesize_action_plan(symptom="high load", llm_fn=llm)
        assert len(result.steps) == 1
        assert result.steps[0].plugin_id == "scale"

    def test_llm_list_return_used_directly(self):
        steps = [{"plugin_id": "restart", "params": {}, "description": "R", "rationale": "R"}]
        result = synthesize_action_plan(symptom="test", llm_fn=lambda p: steps)
        assert len(result.steps) == 1

    def test_available_plugins_in_context(self):
        prompts = []

        def llm(p):
            prompts.append(p)
            return "[]"

        synthesize_action_plan(
            symptom="test", llm_fn=llm, available_plugins=["restart_service", "scale_up"]
        )
        assert "restart_service" in prompts[0]


# ─── verify_health_after_action ───────────────────────────────────────────────


class TestVerifyHealthAfterAction:
    def _healthy_hc(self):
        hc = MagicMock()
        hc.healthy = True
        hc.status_code = 200
        hc.error = None
        return hc

    def _unhealthy_hc(self):
        hc = MagicMock()
        hc.healthy = False
        hc.status_code = 503
        hc.error = "service unavailable"
        return hc

    def test_returns_true_when_healthy(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = self._healthy_hc()
            assert verify_health_after_action(service_url="http://svc", interval_seconds=0) is True

    def test_returns_false_when_always_unhealthy(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = self._unhealthy_hc()
            result = verify_health_after_action(
                service_url="http://svc", retries=2, interval_seconds=0
            )
            assert result is False

    def test_retries_until_healthy(self):
        hc_unhealthy = self._unhealthy_hc()
        hc_healthy = self._healthy_hc()
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.side_effect = [hc_unhealthy, hc_unhealthy, hc_healthy]
            result = verify_health_after_action(
                service_url="http://svc", retries=5, interval_seconds=0
            )
            assert result is True
            assert mock_hc.call_count == 3

    def test_exception_handled_continues_retry(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.side_effect = [ConnectionError("refused"), self._healthy_hc()]
            result = verify_health_after_action(
                service_url="http://svc", retries=3, interval_seconds=0
            )
            assert result is True

    def test_detail_healthy_true_on_success(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = self._healthy_hc()
            result = verify_health_after_action_detail(
                service_url="http://svc", retries=3, interval_seconds=0
            )
            assert isinstance(result, HealthVerifyResult)
            assert result.healthy is True
            assert result.final_status_code == 200

    def test_detail_unhealthy_false_on_failure(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = self._unhealthy_hc()
            result = verify_health_after_action_detail(
                service_url="http://svc", retries=2, interval_seconds=0
            )
            assert result.healthy is False
            assert result.attempts == 2

    def test_detail_elapsed_ms_nonnegative(self):
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = self._healthy_hc()
            result = verify_health_after_action_detail(
                service_url="http://svc", retries=1, interval_seconds=0
            )
            assert result.elapsed_ms >= 0

    def test_wrong_status_code_not_healthy(self):
        hc = MagicMock()
        hc.healthy = True
        hc.status_code = 201  # not 200
        hc.error = None
        with patch("oskill.verify_health_after_action.network_http_health") as mock_hc:
            mock_hc.return_value = hc
            result = verify_health_after_action(
                service_url="http://svc",
                retries=2,
                interval_seconds=0,
                expected_status=200,
            )
            assert result is False


# ─── caddy_route_add ─────────────────────────────────────────────────────────


class TestCaddyRouteAdd:
    def _healthy_hc(self):
        hc = MagicMock()
        hc.healthy = True
        hc.status_code = 200
        hc.error = None
        return hc

    def _unhealthy_hc(self):
        hc = MagicMock()
        hc.healthy = False
        hc.status_code = 503
        hc.error = "svc down"
        return hc

    def test_ok_on_success(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 5}
            mock_hc.return_value = self._healthy_hc()
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={"match": [], "handle": []},
                service_url="http://myapp",
                health_interval_sec=0,
            )
            assert isinstance(result, CaddyRouteAddResult)
            assert result.status == "ok"
            assert result.health_check_passed is True
            assert result.routes_total == 5

    def test_failed_when_caddy_raises(self):
        with patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add:
            mock_add.side_effect = ConnectionError("caddy unreachable")
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
            )
            assert result.status == "failed"
            assert result.error is not None
            assert "caddy_route_add_atomic failed" in result.error

    def test_failed_when_health_check_fails(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 3}
            mock_hc.return_value = self._unhealthy_hc()
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                health_retries=2,
                health_interval_sec=0,
            )
            assert result.status == "failed"
            assert result.health_check_passed is False

    def test_health_retried_until_pass(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 4}
            mock_hc.side_effect = [self._unhealthy_hc(), self._unhealthy_hc(), self._healthy_hc()]
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                health_retries=5,
                health_interval_sec=0,
            )
            assert result.status == "ok"
            assert mock_hc.call_count == 3

    def test_routes_total_propagated(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 12}
            mock_hc.return_value = self._healthy_hc()
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                health_interval_sec=0,
            )
            assert result.routes_total == 12

    def test_health_exception_handled(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 1}
            mock_hc.side_effect = [ConnectionError("refused"), self._healthy_hc()]
            result = caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                health_retries=3,
                health_interval_sec=0,
            )
            assert result.status == "ok"

    def test_server_name_forwarded(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 1}
            mock_hc.return_value = self._healthy_hc()
            caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                server_name="myserver",
                health_interval_sec=0,
            )
            call_kwargs = mock_add.call_args[1]
            assert call_kwargs["server_name"] == "myserver"

    def test_position_forwarded(self):
        with (
            patch("oskill.caddy_route_add.caddy_route_add_atomic") as mock_add,
            patch("oskill.caddy_route_add.network_http_health") as mock_hc,
        ):
            mock_add.return_value = {"status": "ok", "routes_total": 2}
            mock_hc.return_value = self._healthy_hc()
            caddy_route_add(
                admin_url="http://localhost:2019",
                route={},
                service_url="http://myapp",
                position=0,
                health_interval_sec=0,
            )
            call_kwargs = mock_add.call_args[1]
            assert call_kwargs["position"] == 0
