"""Author HEVI's synthetic-writing naturalness defect corpus.

Eleven defect classes, each with two positive passages and two clean controls.
The corpus is committed under ``tests/fixtures/writing_naturalness``; re-running
this generator reproduces the same bytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
OUTPUT = ROOT / "tests/fixtures/writing_naturalness"

CLASSES: tuple[str, ...] = (
    "REPETITIVE_PHRASE",
    "TEMPLATE_CADENCE",
    "GENERIC_TRANSITION",
    "EMPTY_INTENSIFIER",
    "SEMANTIC_REPETITION",
    "UNNATURAL_DIALOGUE",
    "OVER_EXPLANATION",
    "CLICHE_DENSITY",
    "STYLE_DRIFT",
    "PARAGRAPH_MONOTONY",
    "SYNTACTIC_MONOTONY",
)

# class -> (positives, negatives); each entry is (text, expected_location, style_profile)
CASES: dict[str, dict[str, list[tuple[str, str | None, dict[str, Any] | None]]]] = {
    "REPETITIVE_PHRASE": {
        "positive": [
            ("He ran ran ran toward the gate.", "sentence:1", None),
            ("the gate opened the gate opened the gate opened the yard", "sentence:1", None),
        ],
        "negative": [
            ("He walked toward the gate and waited.", None, None),
            ("The gate opened once. He stepped through. Rain began.", None, None),
        ],
    },
    "TEMPLATE_CADENCE": {
        "positive": [
            (
                "The gate opened slowly today. The yard lay empty. "
                "The wind carried salt. The road bent north. The bell rang twice.",
                "sentence:1",
                None,
            ),
            (
                "Mara waited by the harbour. Mara counted the boats. "
                "Mara watched the tide. Mara listened for steps. Mara held her breath.",
                "sentence:1",
                None,
            ),
        ],
        "negative": [
            ("The gate opened. He stepped through. Rain began.", None, None),
            (
                "The gate opened slowly. Rain fell. Then the wind turned. "
                "Mara waited. Ash arrived at dusk.",
                None,
                None,
            ),
        ],
    },
    "GENERIC_TRANSITION": {
        "positive": [
            (
                "Meanwhile the gate opened. Meanwhile the yard emptied. "
                "Meanwhile the wind fell.",
                "sentence:1",
                None,
            ),
            (
                "The bell rang. Suddenly the gate opened. Suddenly the yard emptied.",
                "sentence:2",
                None,
            ),
        ],
        "negative": [
            ("The gate opened. The yard emptied. The wind fell.", None, None),
            ("The bell rang. The gate opened. The yard emptied.", None, None),
        ],
    },
    "EMPTY_INTENSIFIER": {
        "positive": [
            ("It was very cold that morning by the gate.", "sentence:1", None),
            ("She was really tired after the long walk.", "sentence:1", None),
        ],
        "negative": [
            ("It was cold that morning by the gate.", None, None),
            ("She was tired after the long walk.", None, None),
        ],
    },
    "SEMANTIC_REPETITION": {
        "positive": [
            (
                "The gate opened. A gate closed. That gate held. One gate broke.",
                "sentence:1",
                None,
            ),
            (
                "The lantern burned. A lantern dimmed. That lantern smoked. One lantern died.",
                "sentence:1",
                None,
            ),
        ],
        "negative": [
            (
                "The gate opened. A door closed. That barrier held. One port broke.",
                None,
                None,
            ),
            (
                "The lantern burned. A candle dimmed. That torch smoked. One lamp died.",
                None,
                None,
            ),
        ],
    },
    "UNNATURAL_DIALOGUE": {
        "positive": [
            ('She said, "It is I who opened the gate."', "sentence:1", None),
            ('He said, "I am not able to open the gate."', "sentence:1", None),
        ],
        "negative": [
            ('She said, "I opened the gate."', None, None),
            ('He said, "I can\'t open the gate."', None, None),
        ],
    },
    "OVER_EXPLANATION": {
        "positive": [
            ("He left, which meant that the gate stayed shut.", "sentence:1", None),
            ("She ran, this is because the bell had rung.", "sentence:1", None),
        ],
        "negative": [
            ("He left. The gate stayed shut.", None, None),
            ("She ran. The bell had rung.", None, None),
        ],
    },
    "CLICHE_DENSITY": {
        "positive": [
            ("At the end of the day, the gate opened.", "sentence:1", None),
            ("Her heart of gold carried the whole crew.", "sentence:1", None),
        ],
        "negative": [
            ("By evening, the gate opened.", None, None),
            ("Her steady generosity carried the whole crew.", None, None),
        ],
    },
    "STYLE_DRIFT": {
        "positive": [
            (
                "The wind moved across the empty yard while the tall gate stood open before her.",
                "text:all",
                {"sentence_length": 4.0},
            ),
            (
                "Mara walked slowly along the harbour wall and counted every lantern on the pier.",
                "text:all",
                {"sentence_length": 3.0},
            ),
        ],
        "negative": [
            ("Mara crossed the quiet yard and reached the gate.", None, {"sentence_length": 9.0}),
            ("The gate stood open. She stepped through.", None, {"sentence_length": 5.0}),
        ],
    },
    "PARAGRAPH_MONOTONY": {
        "positive": [
            (
                "The gate opened. A yard stood empty.\n\n"
                "The wind rose. One road bent north.\n\n"
                "Mara waited. Ash watched her.",
                "paragraph:all",
                None,
            ),
            (
                "The bell rang. A door opened.\n\n"
                "The lamp dimmed. One shadow moved.\n\n"
                "Mara turned. Ash followed.",
                "paragraph:all",
                None,
            ),
        ],
        "negative": [
            (
                "The gate opened. A yard stood empty. The bell rang.\n\n"
                "The wind rose.\n\n"
                "Mara waited. Ash watched her. Rain fell.",
                None,
                None,
            ),
            (
                "The gate opened.\n\n"
                "The wind rose. A road bent north.\n\n"
                "Mara waited. Ash watched her. Rain fell.",
                None,
                None,
            ),
        ],
    },
    "SYNTACTIC_MONOTONY": {
        "positive": [
            ("The gate was open. A yard was empty. A wind was cold. The road was long.", "text:all", None),
            ("The bell was loud. A room was dark. A door was shut. The hall was still.", "text:all", None),
        ],
        "negative": [
            ("The gate stood open. A yard lay empty. A wind cut cold. The road bent long.", None, None),
            ("The bell rang loud. A room fell dark. A door swung shut. The hall went still.", None, None),
        ],
    },
}


def build() -> dict[str, list[dict[str, Any]]]:
    corpus: dict[str, list[dict[str, Any]]] = {}
    for defect_class in CLASSES:
        cases = CASES[defect_class]
        fixtures: list[dict[str, Any]] = []
        for index, (text, location, profile) in enumerate(cases["positive"], start=1):
            fixtures.append(
                {
                    "fixture_id": f"{defect_class}-POS-{index:02d}",
                    "defect_class": defect_class,
                    "case_type": "POSITIVE",
                    "text": text,
                    "style_profile": profile,
                    "expected_codes": [defect_class],
                    "expected_location": location,
                    "must_not_find": [],
                    "rationale": f"{defect_class} defect present in a real passage.",
                }
            )
        for index, (text, _location, profile) in enumerate(cases["negative"], start=1):
            fixtures.append(
                {
                    "fixture_id": f"{defect_class}-NEG-{index:02d}",
                    "defect_class": defect_class,
                    "case_type": "NEGATIVE",
                    "text": text,
                    "style_profile": profile,
                    "expected_codes": [],
                    "expected_location": None,
                    "must_not_find": [defect_class],
                    "rationale": f"Clean control that must not report {defect_class}.",
                }
            )
        corpus[defect_class] = fixtures
    return corpus


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    corpus = build()
    total = 0
    for defect_class in CLASSES:
        fixtures = corpus[defect_class]
        total += len(fixtures)
        (OUTPUT / f"{defect_class}.json").write_text(
            json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    (OUTPUT / "_index.json").write_text(
        json.dumps(
            {
                "class_count": len(CLASSES),
                "fixture_total": total,
                "classes": list(CLASSES),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {total} fixtures across {len(CLASSES)} classes to {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
