"""Real browser acceptance for the Director Workbench.

Run with the real API and Next server:

    HEVI_P1_BROWSER=1 \
    HEVI_FRONTEND_URL=http://127.0.0.1:3000 \
    HEVI_BROWSER_API=http://127.0.0.1:8000 \
    pytest -m p1_browser tests/p1_browser/test_director_workbench_browser.py -q

The project is seeded through the authenticated API only to create a persisted
test object. Every product assertion and semantic edit after that point uses
visible Workbench controls.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import APIRequestContext, Page, expect, sync_playwright

pytestmark = pytest.mark.p1_browser


def _api_request(api: APIRequestContext, path: str, *, token: str, method: str = "GET", data=None):
    response = api.fetch(
        f"{os.environ.get('HEVI_BROWSER_API', 'http://127.0.0.1:8000')}{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}"},
        data=data,
    )
    assert response.ok, f"{method} {path}: {response.status} {response.text()}"
    return response.json()


def _browser_identity(api: APIRequestContext) -> tuple[str, dict[str, str]]:
    stamp = str(time.time_ns())
    response = api.post(
        f"{os.environ.get('HEVI_BROWSER_API', 'http://127.0.0.1:8000')}/api/auth/register",
        data={
            "email": f"p1-browser-{stamp}@gmail.com",
            "password": "P1-browser-acceptance-2026!",
            "display_name": "P1 Browser Director",
        },
    )
    assert response.ok, response.text()
    payload = response.json()
    return str(payload["token"]), payload["user"]


def _open_authenticated_page(playwright, token: str, user: dict[str, str], url: str, *, width=1440, height=900):
    browser = playwright.firefox.launch(headless=True)
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    page.goto(f"{url.split('/studio/')[0]}/login", wait_until="domcontentloaded")
    page.evaluate(
        "([token, user]) => { localStorage.setItem('hevi_token', token); localStorage.setItem('hevi_user', JSON.stringify(user)); }",
        [token, user],
    )
    page.goto(url, wait_until="networkidle")
    return browser, context, page


def test_real_workbench_core_reopen_and_visual_qa(tmp_path: Path) -> None:
    if os.environ.get("HEVI_P1_BROWSER") != "1":
        pytest.skip("explicit real browser gate: set HEVI_P1_BROWSER=1")
    frontend = os.environ.get("HEVI_FRONTEND_URL", "http://127.0.0.1:3000")
    with sync_playwright() as playwright:
        request = playwright.request.new_context()
        try:
            token, user = _browser_identity(request)
            project = _api_request(
                request,
                "/api/studio/projects",
                token=token,
                method="POST",
                data={
                    "title": "P1 Browser Historical Workbench",
                    "source_kind": "historical",
                    "creative_brief": "A persisted browser acceptance project.",
                    "aspect_ratio": "16:9",
                },
            )
            project_id = project["project"]["id"]
            revision_no = project["revision"]["revision_no"]
            browser = playwright.firefox.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.add_init_script(
                "() => {"
                f"localStorage.setItem('hevi_token', {json.dumps(token)});"
                f"localStorage.setItem('hevi_user', {json.dumps(json.dumps(user))});"
                "}"
            )
            page: Page = context.new_page()
            page.goto(f"{frontend}/login", wait_until="domcontentloaded")
            page.evaluate(
                "([token, user]) => { localStorage.setItem('hevi_token', token); localStorage.setItem('hevi_user', JSON.stringify(user)); }",
                [token, user],
            )
            page.goto(f"{frontend}/studio/projects/{project_id}", wait_until="networkidle")
            expect(page.get_by_test_id("director-workbench")).to_be_visible()
            expect(page.get_by_text(f"Revision {revision_no} ·", exact=False).first).to_be_visible()

            for tab in ("故事", "分镜", "资产", "质量", "时间线"):
                page.get_by_role("button", name=tab).click()
                expect(page.get_by_test_id("director-workbench")).to_be_visible()

            page.get_by_role("button", name="故事").click()
            brief = page.locator("#creative-brief")
            advanced = _api_request(
                request,
                f"/api/studio/projects/{project_id}",
                token=token,
                method="PATCH",
                data={
                    "title": "Concurrent Director Edit",
                    "base_revision_id": project["revision"]["id"],
                },
            )
            assert advanced["revision"]["revision_no"] == 2
            brief.fill("A persisted browser acceptance project with a revised scene.")
            page.get_by_role("button", name="保存为新 revision").click()
            expect(page.locator(".wb-inline-error")).to_contain_text("STALE_REVISION")
            page.get_by_role("button", name="刷新").click()
            brief = page.locator("#creative-brief")
            brief.fill("A persisted browser acceptance project with a revised scene.")
            page.get_by_role("button", name="保存为新 revision").click()
            expect(page.get_by_text("Revision 3 ·", exact=False).first).to_be_visible()
            persisted = _api_request(request, f"/api/studio/projects/{project_id}", token=token)
            assert persisted["revision"]["revision_no"] == 3

            page.screenshot(path=str(tmp_path / "workbench-1440.png"), full_page=True)
            page.set_viewport_size({"width": 1280, "height": 720})
            page.reload(wait_until="networkidle")
            expect(page.get_by_text("Revision 3 ·", exact=False).first).to_be_visible()
            page.screenshot(path=str(tmp_path / "workbench-1280.png"), full_page=True)
            assert (tmp_path / "workbench-1440.png").stat().st_size > 0
            assert (tmp_path / "workbench-1280.png").stat().st_size > 0
            context.close()
            browser.close()
        finally:
            request.dispose()


def test_real_historical_and_long_form_product_paths() -> None:
    """Product orchestration creates persisted graph state before the UI opens it."""
    if os.environ.get("HEVI_P1_BROWSER") != "1":
        pytest.skip("explicit real browser gate: set HEVI_P1_BROWSER=1")
    frontend = os.environ.get("HEVI_FRONTEND_URL", "http://127.0.0.1:3000")
    source = (
        "Chapter 1: The sealed route\n"
        "At dawn the envoy arrives at the old gate carrying a sealed dispatch.\n"
        "The warden warns that the road is watched, but the envoy keeps the letter hidden.\n\n"
        "Chapter 2: Storm crossing\n"
        "At night a storm closes the gate and the warden begins the pursuit.\n"
        "The envoy opens the dispatch beyond the gate and delivers its warning before the road clears."
    )
    with sync_playwright() as playwright:
        request = playwright.request.new_context()
        token, user = _browser_identity(request)
        try:
            historical = _api_request(
                request, "/api/studio/product/historical", token=token, method="POST",
                data={"title": "Browser Historical", "source_text": source},
            )
            long_form = _api_request(
                request, "/api/studio/product/long-form", token=token, method="POST",
                data={"title": "Browser Long Form", "source_text": source},
            )
            for result in (historical, long_form):
                assert result["project_id"] and result["revision_id"] and result["production_plan_id"]
                browser, context, page = _open_authenticated_page(
                    playwright, token, user, f"{frontend}/studio/projects/{result['project_id']}"
                )
                try:
                    expect(page.get_by_test_id("director-workbench")).to_be_visible()
                    page.get_by_role("button", name="故事").click()
                    expect(page.get_by_text("故事结构")).to_be_visible()
                    page.get_by_role("button", name="分镜").click()
                    expect(page.get_by_text("分镜板")).to_be_visible()
                    page.get_by_role("button", name="资产").click()
                    expect(page.get_by_text("资产与参考")).to_be_visible()
                finally:
                    context.close()
                    browser.close()
        finally:
            request.dispose()


def test_real_one_prompt_ui_product_path() -> None:
    if os.environ.get("HEVI_P1_BROWSER") != "1":
        pytest.skip("explicit real browser gate: set HEVI_P1_BROWSER=1")
    frontend = os.environ.get("HEVI_FRONTEND_URL", "http://127.0.0.1:3000")
    raw = "Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn."
    with sync_playwright() as playwright:
        request = playwright.request.new_context()
        token, user = _browser_identity(request)
        browser, context, page = _open_authenticated_page(playwright, token, user, f"{frontend}/studio/one-prompt")
        try:
            page.locator("#one-prompt-request").fill(raw)
            page.get_by_text("创建后运行 CPU preview render").click()
            page.get_by_role("button", name="创建 Production").click()
            expect(page.get_by_test_id("director-workbench")).to_be_visible(timeout=60000)
            project_id = page.url.rstrip("/").split("/")[-1]
            deadline = time.monotonic() + 90
            persisted = _api_request(request, f"/api/studio/projects/{project_id}", token=token)
            tasks = _api_request(request, "/api/studio/tasks", token=token)["tasks"]
            assert any(item["project_id"] == project_id for item in tasks)
            while time.monotonic() < deadline and not persisted["execution_attempts"][0]["artifact_ids"]:
                time.sleep(2)
                persisted = _api_request(request, f"/api/studio/projects/{project_id}", token=token)
            assert persisted["project"]["creative_brief"] == raw
            assert persisted["director_sessions"]
            assert persisted["execution_attempts"]
            assert persisted["execution_attempts"][0]["artifact_ids"]
            page.reload(wait_until="networkidle")
            expect(page.get_by_test_id("director-workbench")).to_be_visible()
        finally:
            context.close()
            browser.close()
            request.dispose()
