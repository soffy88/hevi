"""Tests for the Infinite Creation delta2 graft (A1-A5 gates, B1-B2 fake contracts)."""

import pytest

from hevi.capabilities import (
    agent_runtime_definition_gate as a3,
)
from hevi.capabilities import (
    code_film_style_contract as prior_b3,
)
from hevi.capabilities import (
    codefilm_category_coverage_gate as a1,
)
from hevi.capabilities import (
    codefilm_generation_record_schema as b2,
)
from hevi.capabilities import (
    custom_style_admission_gate as a2,
)
from hevi.capabilities import (
    external_runtime_config_schema as b1,
)
from hevi.capabilities import list_capabilities
from hevi.capabilities import (
    reference_media_numbering_gate as a4,
)
from hevi.capabilities import (
    voice_chain_discipline_gate as a5,
)
from hevi.capabilities.errors import CapabilityError


def _small_index():
    return {
        "styles": [
            {"id": "ink-wash", "category": "hand_drawn", "folder": "ink-wash"},
            {"id": "blueprint", "category": "graphic_typography", "folder": "blueprint"},
        ]
    }


def _full_66_index():
    styles = []
    for category, count in a1.REVIEWED_BREAKDOWN.items():
        for n in range(count):
            slug = category.replace("_", "-")
            styles.append({"id": f"{slug}-{n}", "category": category, "folder": f"{slug}-{n}"})
    return {"styles": styles, "claimed_total": 66}


def test_a1_pass_mismatch_breakdown_and_render_claim():
    report = a1.check_codefilm_category_coverage(_small_index())
    assert report["verdict"] == "pass"
    assert report["style_count"] == 2
    assert report["missing_categories"]
    assert a1.CATEGORIES == prior_b3.CATEGORIES
    assert sum(a1.REVIEWED_BREAKDOWN.values()) == 66

    claimed = dict(_small_index(), claimed_total=3)
    assert a1.check_codefilm_category_coverage(claimed)["verdict"] == "fail"

    wrong = _full_66_index()
    wrong["styles"] = [
        *wrong["styles"][:-1],
        {"id": "film-era-9", "category": "film_era", "folder": "film-era-9"},
    ]
    assert a1.check_codefilm_category_coverage(wrong)["verdict"] == "fail"
    assert a1.check_codefilm_category_coverage(_full_66_index())["verdict"] == "pass"

    rendered = dict(_small_index(), render_verification={"per_style_rendered": True})
    report = a1.check_codefilm_category_coverage(rendered)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "unverified_render_claim" for i in report["issues"])

    duplicate = {
        "styles": [
            {"id": "ink-wash", "category": "hand_drawn", "folder": "ink-wash"},
            {"id": "ink-wash", "category": "hand_drawn", "folder": "ink-wash"},
        ]
    }
    assert a1.check_codefilm_category_coverage(duplicate)["verdict"] == "fail"
    unknown = {"styles": [{"id": "nope", "category": "not_a_category", "folder": "nope"}]}
    assert a1.check_codefilm_category_coverage(unknown)["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        a1.check_codefilm_category_coverage("not an index")


def test_a2_custom_admission():
    custom = {
        "id": "my-ink",
        "category": "hand_drawn",
        "is_custom": True,
        "base_declaration": {"base_id": "ink-wash", "overridden_fields": ["palette"]},
        "source": "caller supplied",
    }
    assert a2.check_custom_style_admission(custom)["verdict"] == "pass"
    assert a2.check_custom_style_admission(custom, builtin_ids=["other"])["verdict"] == "pass"
    assert a2.check_custom_style_admission(custom, builtin_ids=["my-ink"])["verdict"] == "fail"

    no_base = dict(custom)
    del no_base["base_declaration"]
    assert a2.check_custom_style_admission(no_base)["verdict"] == "fail"
    no_source = dict(custom)
    del no_source["source"]
    assert a2.check_custom_style_admission(no_source)["verdict"] == "fail"
    claiming = dict(custom, claims_builtin=True)
    assert a2.check_custom_style_admission(claiming)["verdict"] == "fail"
    self_base = dict(custom)
    self_base["base_declaration"] = {"base_id": "my-ink", "overridden_fields": ["palette"]}
    assert a2.check_custom_style_admission(self_base)["verdict"] == "fail"

    builtin = {
        "id": "ink-wash",
        "category": "hand_drawn",
        "is_custom": False,
        "claims_builtin": True,
    }
    assert a2.check_custom_style_admission(builtin)["verdict"] == "fail"
    builtin["builtin_index"] = "reviewed index"
    assert a2.check_custom_style_admission(builtin)["verdict"] == "pass"


def _runtime(name="claude"):
    return {
        "name": name,
        "cli_command": f"{name} run",
        "detection": "which command present",
        "mcp_config_copy": True,
        "account_via_own_cli": True,
    }


def test_a3_runtime_definitions():
    definition = {
        "mode": "mixed",
        "builtin_runtime": "openclaude",
        "runtimes": [
            _runtime(),
            {
                "name": "custom",
                "cli_command": "my-agent run",
                "detection": "binary present",
                "mcp_config_copy": False,
                "account_via_own_cli": True,
                "custom_command": "my-agent run",
            },
        ],
    }
    report = a3.check_agent_runtime_definitions(definition)
    assert report["verdict"] == "pass"
    assert report["runtime_count"] == 2

    unknown = {"runtimes": [_runtime("mystery")]}
    assert a3.check_agent_runtime_definitions(unknown)["verdict"] == "fail"
    no_command = {"runtimes": [dict(_runtime(), cli_command="")]}
    assert a3.check_agent_runtime_definitions(no_command)["verdict"] == "fail"
    creds = {"runtimes": [dict(_runtime(), credentials_in_config=True)]}
    assert a3.check_agent_runtime_definitions(creds)["verdict"] == "fail"
    skill = {"runtimes": [dict(_runtime(), generates_skill=True)]}
    assert a3.check_agent_runtime_definitions(skill)["verdict"] == "fail"
    routed = {"runtimes": [dict(_runtime(), account_via_own_cli=False)]}
    assert a3.check_agent_runtime_definitions(routed)["verdict"] == "fail"
    builtin_mode = {
        "mode": "builtin",
        "builtin_runtime": "something-else",
        "runtimes": [_runtime()],
    }
    assert a3.check_agent_runtime_definitions(builtin_mode)["verdict"] == "fail"
    duplicate = {"runtimes": [_runtime(), _runtime()]}
    assert a3.check_agent_runtime_definitions(duplicate)["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        a3.check_agent_runtime_definitions({"runtimes": []})


def _refs(images=1, audios=1, videos=0):
    return {
        "plan_id": "plan-1",
        "ref_images": [{"ref_id": f"ref_image_{i}", "asset_id": f"img-{i}"} for i in range(images)],
        "ref_audios": [{"ref_id": f"ref_audio_{i}", "asset_id": f"aud-{i}"} for i in range(audios)],
        "ref_videos": [{"ref_id": f"ref_video_{i}", "asset_id": f"vid-{i}"} for i in range(videos)],
    }


def test_a4_reference_media_numbering():
    assert a4.check_reference_media_numbering(_refs())["verdict"] == "pass"
    assert (
        a4.check_reference_media_numbering(_refs(images=9, audios=3, videos=3))["verdict"] == "pass"
    )

    gap = _refs(images=2)
    gap["ref_images"][1]["ref_id"] = "ref_image_5"
    assert a4.check_reference_media_numbering(gap)["verdict"] == "fail"
    assert a4.check_reference_media_numbering(_refs(images=10))["verdict"] == "fail"
    assert a4.check_reference_media_numbering(_refs(audios=4))["verdict"] == "fail"
    assert a4.check_reference_media_numbering(_refs(videos=4))["verdict"] == "fail"
    no_asset = _refs()
    del no_asset["ref_images"][0]["asset_id"]
    assert a4.check_reference_media_numbering(no_asset)["verdict"] == "fail"
    extra = _refs()
    extra["surprise"] = []
    assert a4.check_reference_media_numbering(extra)["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        a4.check_reference_media_numbering({"ref_images": "not a list"})


def test_a5_voice_chain_discipline():
    stock = {"voice_requests": [{"kind": "stock", "voice_id": "v1"}]}
    assert a5.check_voice_chain_discipline(stock)["verdict"] == "pass"

    authorized = {
        "voice_requests": [{"kind": "authorized_custom", "authorization": "consent ref 7"}]
    }
    assert a5.check_voice_chain_discipline(authorized)["verdict"] == "pass"
    no_auth = {"voice_requests": [{"kind": "authorized_custom"}]}
    assert a5.check_voice_chain_discipline(no_auth)["verdict"] == "fail"

    regen = {"voice_requests": [{"kind": "regeneration", "fallback_narration": "read this aloud"}]}
    assert a5.check_voice_chain_discipline(regen)["verdict"] == "pass"
    no_fallback = {"voice_requests": [{"kind": "regeneration"}]}
    assert a5.check_voice_chain_discipline(no_fallback)["verdict"] == "fail"

    nested_clone = {
        "voice_requests": [{"kind": "stock"}],
        "tools": {"clone_voice": {"voice_id": "v9"}},
    }
    report = a5.check_voice_chain_discipline(nested_clone)
    assert report["verdict"] == "fail"
    assert any(i["code"] == "clone_blocked" for i in report["issues"])
    kind_clone = {"voice_requests": [{"kind": "clone"}]}
    assert a5.check_voice_chain_discipline(kind_clone)["verdict"] == "fail"
    cloned_flag = {"voice_requests": [{"kind": "stock", "cloned": True}]}
    assert a5.check_voice_chain_discipline(cloned_flag)["verdict"] == "fail"
    with pytest.raises(CapabilityError):
        a5.check_voice_chain_discipline({"voice_requests": []})


def _b1_config():
    return {
        "mode": "mixed",
        "builtin_runtime": "openclaude",
        "runtimes": [_runtime(), _runtime("codex")],
        "mcp_config": {"transport": "stdio", "framing": "ndjson"},
    }


def test_b1_external_runtime_config_schema():
    report = b1.compile_external_runtime_config_contract(_b1_config())
    assert report["verdict"] == "pass"
    assert report["contract"]["executed_here"] is False
    assert report["contract"]["spawned_here"] is False
    assert report["contract"]["runtime_names"] == ["claude", "codex"]

    bad_runtime = _b1_config()
    bad_runtime["runtimes"] = [_runtime("mystery")]
    with pytest.raises(CapabilityError):
        b1.compile_external_runtime_config_contract(bad_runtime)
    creds = _b1_config()
    creds["api_token"] = "must-not-appear"
    with pytest.raises(CapabilityError):
        b1.compile_external_runtime_config_contract(creds)
    bad_mcp = _b1_config()
    bad_mcp["mcp_config"] = {"transport": "http", "framing": "ndjson"}
    with pytest.raises(CapabilityError):
        b1.compile_external_runtime_config_contract(bad_mcp)


def _b2_record():
    return {
        "record_id": "rec-1",
        "style_id": "ink-wash",
        "category": "hand_drawn",
        "materials": [
            {"kind": "image", "ref": "img-1"},
            {"kind": "document", "ref": "doc-1"},
        ],
        "operations": [
            {"op": "query"},
            {"op": "regenerate", "source_record_id": "rec-0"},
        ],
        "rendered_here": False,
    }


def test_b2_codefilm_generation_record_schema():
    report = b2.compile_codefilm_generation_record(_b2_record())
    assert report["verdict"] == "pass"
    assert report["contract"]["executed_here"] is False
    assert report["contract"]["generated_here"] is False

    no_source = _b2_record()
    no_source["operations"] = [{"op": "regenerate"}]
    with pytest.raises(CapabilityError):
        b2.compile_codefilm_generation_record(no_source)
    no_scope = _b2_record()
    no_scope["operations"] = [{"op": "batch_delete"}]
    with pytest.raises(CapabilityError):
        b2.compile_codefilm_generation_record(no_scope)
    no_target = _b2_record()
    no_target["operations"] = [{"op": "stop"}]
    with pytest.raises(CapabilityError):
        b2.compile_codefilm_generation_record(no_target)
    rendered = _b2_record()
    rendered["rendered_here"] = True
    with pytest.raises(CapabilityError):
        b2.compile_codefilm_generation_record(rendered)
    bad_kind = _b2_record()
    bad_kind["materials"] = [{"kind": "hologram", "ref": "x"}]
    with pytest.raises(CapabilityError):
        b2.compile_codefilm_generation_record(bad_kind)


def test_delta2_capabilities_registered():
    names = {c.name for c in list_capabilities()}
    for name in (
        "qa.codefilm_category_coverage_gate",
        "qa.custom_style_admission_gate",
        "qa.agent_runtime_definition_gate",
        "qa.reference_media_numbering_gate",
        "qa.voice_chain_discipline_gate",
        "video.external_runtime_config_schema",
        "video.codefilm_generation_record_schema",
    ):
        assert name in names
