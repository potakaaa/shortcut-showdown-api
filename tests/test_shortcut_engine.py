"""Unit tests for shortcut sequence generation and challenge masking helpers."""

from __future__ import annotations

import random

from app.services.shortcut_engine import (
    generate_shortcut_sequence,
    mask_challenge_for_player,
    publicize_challenges,
)


def test_generate_shortcut_sequence_returns_empty_for_non_positive_count() -> None:
    assert generate_shortcut_sequence(0) == []
    assert generate_shortcut_sequence(-3) == []


def test_generate_shortcut_sequence_adds_sequential_indexes() -> None:
    seq = generate_shortcut_sequence(5, rng=random.Random(123))

    assert len(seq) == 5
    assert [item["index"] for item in seq] == [0, 1, 2, 3, 4]
    assert all("prompt" in item for item in seq)
    assert all("expectedKeys" in item for item in seq)


def test_generate_shortcut_sequence_supports_larger_count() -> None:
    seq = generate_shortcut_sequence(20, rng=random.Random(7))

    assert len(seq) == 20
    assert seq[0]["index"] == 0
    assert seq[-1]["index"] == 19


def test_mask_and_publicize_hide_expected_keys() -> None:
    challenge = {
        "prompt": "Copy selected text",
        "expectedKeys": ["ctrl", "c"],
        "index": 0,
    }
    masked = mask_challenge_for_player(challenge)
    assert masked == {"prompt": "Copy selected text", "index": 0}
    assert "expectedKeys" in challenge

    challenges = [challenge, {"prompt": "Paste", "expectedKeys": ["ctrl", "v"], "index": 1}]
    public = publicize_challenges(challenges)
    assert public == [
        {"prompt": "Copy selected text", "index": 0},
        {"prompt": "Paste", "index": 1},
    ]
    assert all("expectedKeys" in item for item in challenges)
