"""Gold behaviour for interactive film graph validation."""

from __future__ import annotations

from uuid import uuid4

from hevi.creative.omodul import InteractiveFilmGraph, InteractiveFilmModule
from hevi.obase.creative import Choice, Condition, InteractiveFilm, StoryNode


def _film(project_id, start, nodes, choices, *, variable_names=()):
    return InteractiveFilm(
        project_id=project_id,
        title="Owned Film",
        start_node_id=start.node_id,
        node_ids=tuple(node.node_id for node in nodes),
        choice_ids=tuple(choice.choice_id for choice in choices),
        variable_names=variable_names,
    )


def test_cycle_is_rejected_and_paths_terminate() -> None:
    project_id = uuid4()
    node_a = StoryNode(title="a")
    node_b = StoryNode(title="b")
    ending = StoryNode(title="end", ending=True)
    to_b = Choice(label="to-b", target_node_id=node_b.node_id)
    to_a = Choice(label="to-a", target_node_id=node_a.node_id)
    to_end = Choice(label="to-end", target_node_id=ending.node_id)
    node_a = node_a.model_copy(update={"choice_ids": (to_b.choice_id, to_end.choice_id)})
    node_b = node_b.model_copy(update={"choice_ids": (to_a.choice_id,)})
    choices = (to_b, to_a, to_end)
    film = _film(project_id, node_a, (node_a, node_b, ending), choices)
    module = InteractiveFilmModule()
    validation = module.validate(InteractiveFilmGraph(film, (node_a, node_b, ending), choices))
    assert validation.status == "FAIL"
    assert any(finding.code == "CYCLE" for finding in validation.findings)
    paths = module.enumerate_paths(
        InteractiveFilmGraph(film, (node_a, node_b, ending), choices), max_depth=10
    )
    assert paths == ((node_a.node_id, ending.node_id),)


def test_invalid_condition_is_rejected() -> None:
    project_id = uuid4()
    start = StoryNode(title="start")
    ending = StoryNode(title="end", ending=True)
    bad = Choice(
        label="bad",
        target_node_id=ending.node_id,
        condition=Condition(expression="ghost == 1", variable_refs=("ghost",)),
    )
    start = start.model_copy(update={"choice_ids": (bad.choice_id,)})
    film = _film(project_id, start, (start, ending), (bad,), variable_names=("flag",))
    validation = InteractiveFilmModule().validate(
        InteractiveFilmGraph(film, (start, ending), (bad,))
    )
    assert validation.status == "FAIL"
    assert any(finding.code == "INVALID_CONDITION" for finding in validation.findings)
