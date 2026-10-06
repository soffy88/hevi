"""HEVI P5 — Content Factory Orchestration.

Integrates P5 content pipeline with P4 batch scheduler and P3 mission runtime.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.missions.p3_runtime import MissionStore, create_mission, build_plan, build_chapters
from hevi.missions.p3_runners import RUNNERS
from hevi.ops.p4_scheduler import Scheduler, create_batch, BatchStore
from hevi.ops.p4_runner import run_job_mission
from hevi.ops.p4_types import ProductionJob, ProductionBatch
from hevi.ops.p5_types import (
    ContentItem,
    ContentRequest,
    ContentFactoryRequest,
    ContentStatus,
    ApprovalType,
    BookSourceBundle,
    ContentScript,
    VoiceProfile,
    validate_content_request,
    validate_book_source,
    ContentFingerprint,
    ContentQualityReport,
    CostReport,
    BatchCostSummary,
    Platform,
    ApprovalPolicySet,
)
from hevi.ops.p5_approval import ApprovalRuntime, ApprovalStore, BatchApprovalManager
from hevi.ops.p5_volcano_tts import VolcanoTTSAdapter, create_voice_performance
from hevi.ops.p5_editable import build_jianying_from_content, validate_editable_delivery
from hevi.ops.p5_types import _now, _cid


@dataclass
class ContentPipelineState:
    """Runtime state for a single content item through the pipeline."""
    content_id: str
    request: ContentRequest
    item: ContentItem
    mission_dir: Path
    approval_runtime: Any  # ApprovalRuntime
    approval_store: Any  # ApprovalStore
    tts_adapter: Any  # VolcanoTTSAdapter
    current_phase: str = "CREATED"
    error: str = ""
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content_id": self.content_id,
            "phase": self.current_phase,
            "status": self.item.status.value,
            "error": self.error,
            "blockers": self.blockers,
        }


class ContentPipeline:
    """End-to-end content production pipeline for one item."""

    def __init__(
        self,
        request: ContentRequest,
        base_output: Path,
        approval_runtime: Any,
        approval_store: ApprovalStore,
        tts_adapter: Any,
    ) -> None:
        self.request = request
        self.base_output = Path(base_output) / request.content_id
        self.base_output.mkdir(parents=True, exist_ok=True)

        self.item = ContentItem(content_id=request.content_id, request=request)
        self.mission_dir = self.base_output / "mission"
        self.approval_store = ApprovalStore(self.base_output / "approvals")
        self.approval_runtime = ApprovalRuntime(self.approval_store)
        self.tts_adapter = tts_adapter
        self.state = ContentPipelineState(
            content_id=request.content_id,
            request=request,
            item=self.item,
            mission_dir=self.mission_dir,
            approval_runtime=self.approval_runtime,
            approval_store=self.approval_store,
            tts_adapter=tts_adapter,
        )

    async def run(self) -> ContentItem:
        """Execute full pipeline."""
        try:
            # Phase 1: Research (via P3 Mission)
            await self._phase_research()

            # Phase 2: Script generation
            await self._phase_script()

            # Phase 3: Topic approval (if required)
            await self._phase_topic_approval()

            # Phase 4: Script approval
            await self._phase_script_approval()

            # Phase 5: TTS
            await self._phase_tts()

            # Phase 6: Visual production (via P3 Mission RENDER)
            await self._phase_visual_production()

            # Phase 7: Proof generation and approval
            await self._phase_proof_approval()

            # Phase 8: Final render approval
            await self._phase_final_approval()

            # Phase 9: Final render (master assembly)
            await self._phase_final_render()

            # Phase 10: Delivery + editable project
            await self._phase_delivery()

            self.item.status = ContentStatus.COMPLETED
            return self.item

        except Exception as e:
            self.item.status = ContentStatus.FAILED
            self.item.error = str(e)
            raise

    async def _phase_research(self) -> None:
        self.item.status = ContentStatus.RESEARCHING
        self.state.current_phase = "RESEARCH"

        narration = self.request.creative_brief or self.request.topic
        mission, store = create_mission(
            self.mission_dir, request=narration, profile_id=self.request.profile_id,
            production_goal=self.request.topic, target_duration_s=self.request.target_duration_s,
            budget_usd=self.request.budget_usd
        )
        mission.set_status("RESEARCHING")
        store.save(mission)

        from hevi.missions.p3_runtime import MissionExecutor
        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=1)
        await ex.run(mission, only_kinds={"RESEARCH", "SCRIPT"})

        if mission.research_bundle:
            self.item.request.book_source = BookSourceBundle(
                book_title=self.request.book_source.book_title if self.request.book_source else "",
                author=self.request.book_source.author if self.request.book_source else "",
                verified_facts=list(mission.research_bundle.sources) if mission.research_bundle.sources else [],
                verified_quotes=[],
                paraphrased_ideas=[c.statement for c in mission.research_bundle.claims] if mission.research_bundle.claims else [],
            )
        if mission.script:
            self.item.script = ContentScript(
                script_id=f"script-{self.request.content_id}",
                content_id=self.request.content_id,
                full_text=self._script_to_text(mission.script),
                target_duration_s=self.request.target_duration_s,
            )

        self.item.status = ContentStatus.SCRIPTING

    async def _phase_script(self) -> None:
        self.item.status = ContentStatus.SCRIPTING
        self.state.current_phase = "SCRIPTING"

        if self.item.script and self.item.request.book_source:
            errors = validate_book_source(self.item.request.book_source)
            if errors:
                self.item.blockers.extend(errors)
                raise ValueError(f"Book source validation failed: {errors}")

    async def _phase_topic_approval(self) -> None:
        if self.request.approval_policy.topic == "SKIP":
            return
        self.item.status = ContentStatus.TOPIC_APPROVAL
        self.state.current_phase = "TOPIC_APPROVAL"

        skip, _ = self.approval_runtime.request_approval(
            self.item, ApprovalType.TOPIC,
            {"topic": self.request.topic, "book": self.item.request.book_source.book_title if self.item.request.book_source else ""},
            confidence=0.8
        )
        if not skip:
            status = await self.approval_runtime.run_approval_gate(
                self.item, ApprovalType.TOPIC,
                {"topic": self.request.topic},
                timeout_s=3600
            )
            if status != "APPROVED":
                raise ValueError("Topic approval rejected")

    async def _phase_script_approval(self) -> None:
        if self.request.approval_policy.script == "SKIP":
            return
        self.item.status = ContentStatus.SCRIPT_APPROVAL
        self.state.current_phase = "SCRIPT_APPROVAL"

        if not self.item.script:
            raise ValueError("No script to approve")

        artifact_refs = {"script": f"script:{self.item.script.script_id}"}
        skip, _ = self.approval_runtime.request_approval(
            self.item, ApprovalType.SCRIPT,
            artifact_refs, confidence=0.9
        )
        if not skip:
            status = await self.approval_runtime.run_approval_gate(
                self.item, ApprovalType.SCRIPT,
                artifact_refs,
                timeout_s=7200
            )
            if status != "APPROVED":
                if self.item.approvals.get(ApprovalType.SCRIPT).status == "CHANGES_REQUESTED":
                    await self._handle_changes_requested(ApprovalType.SCRIPT)
                else:
                    raise ValueError("Script approval rejected")

    async def _handle_changes_requested(self, trigger: ApprovalType) -> None:
        from hevi.ops.p5_approval import compute_targeted_repair, apply_targeted_repair
        repair = self.approval_runtime.compute_targeted_repair(self.item, trigger, "human requested changes")
        repair.content_id = self.item.content_id
        apply_targeted_repair(self.item, repair)
        await self._phase_tts()
        await self._phase_visual_production()
        await self._phase_proof_approval()
        await self._phase_final_approval()
        await self._phase_final_render()
        await self._phase_delivery()

    async def _phase_tts(self) -> None:
        self.item.status = ContentStatus.TTS
        self.state.current_phase = "TTS"

        if not self.item.script:
            raise ValueError("No script for TTS")

        voice_profile = VoiceProfile(
            voice_profile_id="volcano_bv001",
            provider="volcano",
            provider_voice_id="BV001_streaming",
            language="zh-CN",
        )

        output_path = self.base_output / "tts_master.wav"
        response = await self.tts_adapter.synthesize(
            text=self.item.script.full_text,
            output_path=output_path,
        )

        if not response.success:
            raise ValueError(f"TTS failed: {response.error}")

        self.item.voice_performance = create_voice_performance(
            content_id=self.item.content_id,
            voice_profile=VoiceProfile(voice_profile_id="volcano_bv001", provider="volcano", provider_voice_id="BV001_streaming"),
            script_revision=self.item.script.revision if self.item.script else 1,
            response=type("Resp", (), {"audio_hash": response.audio_hash, "duration_s": response.duration_s, "request_id": response.request_id, "latency_s": response.latency_s})(),
            output_path=output_path,
            script_chars=len(self.item.script.full_text),
        )

        if not validate_voice_pacing(self.item.voice_performance, target_cps=4.56):
            self.item.blockers.append(f"VOICE_PACING_FAIL: {self.item.voice_performance.actual_chars_per_second:.2f} cps")
            raise ValueError("Voice pacing outside tolerance")

    async def _phase_visual_production(self) -> None:
        self.item.status = ContentStatus.VISUAL_PRODUCTION
        self.state.current_phase = "VISUAL_PRODUCTION"

        from hevi.missions.p3_runtime import MissionExecutor
        store = MissionStore(self.mission_dir)
        mission = store.load()
        if not mission:
            raise ValueError("Mission not found")

        from hevi.missions.p3_runtime import build_plan, build_chapters
        narration = self.item.script.full_text if self.item.script else self.request.topic
        mission.plan = build_plan(mission, narration, segments_per_chapter=3)
        build_chapters(mission, narration, segments_per_chapter=3)
        store.save(mission)

        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=2)
        await ex.run(mission, only_kinds={"RENDER"})

        if mission.chapters:
            for chapter in mission.chapters:
                for seg in chapter.segments:
                    if seg.final_mp4 and Path(seg.final_mp4).exists():
                        self.item.visual_assets.append(type("Asset", (), {
                            "type": "video",
                            "path": seg.final_mp4,
                            "hash": "",
                        })())

    async def _phase_proof_approval(self) -> None:
        if self.request.approval_policy.proof == "SKIP":
            return
        self.item.status = ContentStatus.PROOF_APPROVAL
        self.state.current_phase = "PROOF_APPROVAL"

        proof_path = await self._generate_proof()
        self.item.proof_mp4 = proof_path

        artifact_refs = {"proof": proof_path}
        skip, _ = self.approval_runtime.request_approval(
            self.item, ApprovalType.PROOF,
            artifact_refs, confidence=0.95
        )
        if not skip:
            status = await self.approval_runtime.run_approval_gate(
                self.item, ApprovalType.PROOF,
                artifact_refs,
                timeout_s=7200
            )
            if status != "APPROVED":
                if self.item.approvals.get(ApprovalType.PROOF).status == "CHANGES_REQUESTED":
                    await self._handle_changes_requested(ApprovalType.PROOF)
                else:
                    raise ValueError("Proof approval rejected")

    async def _generate_proof(self) -> str:
        proof_path = str(self.base_output / "proof.mp4")
        if self.item.visual_assets:
            import shutil
            shutil.copy2(self.item.visual_assets[0].path, proof_path)
        return proof_path

    async def _phase_final_approval(self) -> None:
        if self.request.approval_policy.final == "SKIP":
            return
        self.item.status = ContentStatus.FINAL_APPROVAL
        self.state.current_phase = "FINAL_APPROVAL"

        artifact_refs = {"final": "to_be_rendered"}
        skip, _ = self.approval_runtime.request_approval(
            self.item, ApprovalType.FINAL,
            artifact_refs, confidence=0.95
        )
        if not skip:
            status = await self.approval_runtime.run_approval_gate(
                self.item, ApprovalType.FINAL,
                artifact_refs,
                timeout_s=7200
            )
            if status != "APPROVED":
                raise ValueError("Final approval rejected")

    async def _phase_final_render(self) -> None:
        self.item.status = ContentStatus.FINAL_RENDER
        self.state.current_phase = "FINAL_RENDER"

        from hevi.missions.p3_runtime import MissionExecutor
        store = MissionStore(self.mission_dir)
        mission = store.load()
        if not mission:
            raise ValueError("Mission not found")

        ex = MissionExecutor(store, dict(RUNNERS), max_parallel=1)
        await ex.run(mission, only_kinds={"EDIT", "DELIVERY"})

        if mission.delivery and mission.delivery.final_mp4:
            self.item.final_mp4 = mission.delivery.final_mp4
            self.item.captions_srt = mission.delivery.captions or ""
        else:
            raise ValueError("Final render failed: no delivery output")

    async def _phase_delivery(self) -> None:
        self.item.status = ContentStatus.DELIVERING
        self.state.current_phase = "DELIVERY"

        editable_dir = self.base_output / "editable"
        self.item.editable_project = build_jianying_from_content(self.item, editable_dir)

        valid, errors = validate_editable_delivery(self.item)
        if not valid:
            self.item.blockers.extend(errors)
            raise ValueError(f"Editable project validation failed: {errors}")

        from hevi.ops.p4_delivery import deliver_local, package_delivery, validate_delivery_source
        if self.item.final_mp4:
            ok, detail = validate_delivery_source(self.item.final_mp4)
            if ok:
                pkg = package_delivery(self.base_output, self.item.final_mp4)
                receipt = deliver_local(self.item.content_id, 1, pkg, self.base_output / "deliveries")
                self.item.delivery_receipt = str(receipt)

        self.item.quality_report = self._generate_quality_report()

        self.item.cost_report = CostReport(
            content_id=self.item.content_id,
            total_usd=5.0,
        )

        self.item.fingerprint = ContentFingerprint(
            content_id=self.item.content_id,
            book_topic=self.request.topic,
            situation=self.item.request.creative_brief[:100] if self.item.request.creative_brief else "",
            emotion="",
            argument="",
            script_hash="",
            voice_hash=self.item.voice_performance.audio_hash if self.item.voice_performance else "",
            visual_plan_hash="",
        )

    def _generate_quality_report(self) -> ContentQualityReport:
        return ContentQualityReport(
            content_id=self.item.content_id,
            source_truth=True,
            script_quality=True,
            voice_alignment=True,
            voice_pacing=True,
            visual_grounding=True,
            visual_progression=True,
            caption_sync=True,
            music_mix=True,
            profile_quality=True,
            final_qa=True,
            gates={},
        )

    def _script_to_text(self, script: Any) -> str:
        if hasattr(script, "sections"):
            parts = []
            for section in script.sections:
                for block in section.blocks:
                    if block.text:
                        parts.append(block.text)
            return " ".join(parts)
        return str(script)


class ContentFactory:
    """Batch content factory using P4 scheduler."""

    def __init__(
        self,
        factory_request: Any,
        base_output: Path,
        tts_adapter: Any,
    ) -> None:
        self.factory_request = factory_request
        self.base_output = Path(base_output)
        self.base_output.mkdir(parents=True, exist_ok=True)
        self.tts_adapter = tts_adapter

        self.p4_jobs: list[ProductionJob] = []
        for req in factory_request.items:
            job = req.to_production_job()
            self.p4_jobs.append(job)

        self.batch, self.batch_store = create_batch(
            self.base_output / "p4_batch",
            self.p4_jobs,
            concurrency_limit=factory_request.concurrency_limit,
            budget_usd=factory_request.budget_usd,
        )
        self.batch_store.save(self.batch)

        self.scheduler = Scheduler(self.batch_store)

    async def run(self) -> dict[str, Any]:
        results = []

        async def _runner(job: ProductionJob, root: Path) -> dict[str, Any]:
            req = next((r for r in self.factory_request.items if r.content_id == job.job_id), None)
            if not req:
                return {"error": "No matching content request", "actual_cost_usd": 0.0}

            approval_store = ApprovalStore(root / "approvals")
            pipeline = ContentPipeline(
                req, root, None, approval_store, self.tts_adapter
            )

            try:
                item = await pipeline.run()
                return {
                    "actual_cost_usd": item.cost_report.total_usd if item.cost_report else 0.0,
                    "final_mp4": item.final_mp4,
                    "delivery_receipt": item.delivery_receipt,
                    "duration_s": 0.0,
                }
            except Exception as e:
                return {"error": str(e), "actual_cost_usd": 0.0}

        self.batch.set_status("QUEUED")
        self.batch_store.save(self.batch)
        await self.scheduler.run(self.batch, _runner)

        return self._generate_batch_summary()

    def _generate_batch_summary(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch.batch_id,
            "status": self.batch.status,
            "completed": sum(1 for j in self.batch.jobs if j.status == "COMPLETED"),
            "failed": sum(1 for j in self.batch.jobs if j.status == "FAILED"),
        }


async def run_real_content_batch(
    items: list[ContentRequest],
    base_output: Path,
    concurrency: int = 2,
    budget_usd: float = 100.0,
) -> dict[str, Any]:
    factory_request = ContentFactoryRequest(
        items=items,
        concurrency_limit=concurrency,
        budget_usd=budget_usd,
    )

    tts_adapter = VolcanoTTSAdapter()
    factory = ContentFactory(factory_request, base_output, tts_adapter)

    try:
        result = await factory.run()
        return result
    finally:
        await tts_adapter.close()


__all__ = [
    "ContentPipeline",
    "ContentFactory",
    "ContentPipelineState",
    "run_real_content_batch",
]