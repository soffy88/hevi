# P0 phase gates

This file records the required evidence at the end of each P0 phase.  A
phase is coherent only when its files, schema, migration, tests and legacy
compatibility status are recorded.

## P0.0

PHASE=P0.0  
FILES_CHANGED=`docs/architecture/production-domain-inventory.md`, `docs/architecture/ADR-canonical-film-production-domain.md`, this file  
NEW_SCHEMA=none  
MIGRATIONS=none  
TESTS_ADDED=none  
TESTS_PASSED=inventory reviewed against RC6 source  
TESTS_FAILED=none  
LEGACY_COMPATIBILITY=baseline unchanged; unrelated dirty worktree excluded in a separate clean worktree  
KNOWN_GAPS=canonical domain not yet implemented  
COMMIT=docs(production-domain): inventory RC6 semantics and freeze ADR

## P0.2

PHASE=P0.2  
FILES_CHANGED=`hevi/production_graph/adapters/` and `tests/test_production_graph_adapters.py`  
NEW_SCHEMA=Tongjian and Script2Video narrative adapter contracts  
MIGRATIONS=none; adapters target the existing immutable revision snapshot  
TESTS_ADDED=source-span preservation, causal edge mapping, cross-event ordering, stable legacy identity mapping  
TESTS_PASSED=8 focused tests including P0.1 and legacy graph contracts  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=Tongjian `ChapterIR` and Script2Video `NovelPlan` remain unchanged and can still be consumed by their old workflows  
KNOWN_GAPS=Cinematic/Studio/Vault/Canvas adapters and dual-read API follow in P0.3/P0.4/P0.13  
COMMIT=feat(narrative-graph): adapt legacy narrative schemas

## P0.1

PHASE=P0.1  
FILES_CHANGED=`hevi/production_graph/ids.py`, `hevi/production_graph/domain.py`, `hevi/production_graph/contracts.py`, `hevi/production_graph/repository.py`, `hevi/production_graph/__init__.py`, `tests/test_production_domain_core.py`  
NEW_SCHEMA=canonical Pydantic graph records and immutable `ProductionGraphSnapshot`; legacy execution-plan imports re-export the canonical plan  
MIGRATIONS=reuses RC6 `productions` and `production_revisions`; canonical snapshots are persisted under the existing immutable revision row  
TESTS_ADDED=stable ID namespace, source span validation, revision isolation/parenting, referential integrity, legacy execution-plan DAG compatibility  
TESTS_PASSED=6 focused tests  
TESTS_FAILED=0  
LEGACY_COMPATIBILITY=existing `tests/test_production_graph_contracts.py` passes; old `ProductionGraphRepository` CRUD and execution-plan persistence API retained  
KNOWN_GAPS=canonical narrative/ontology adapters, readiness, compiler, runtime envelope and API are subsequent P0 phases  
COMMIT=feat(production-domain): add canonical IDs and revision graph core
