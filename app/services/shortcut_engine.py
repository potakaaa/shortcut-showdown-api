"""Shortcut challenge engine: dataset and sequence generator.

Provides a small dataset of shortcut challenges and a helper to generate
randomized sequences for a game room. Each challenge contains a `prompt`
and an `expectedKeys` list, and may optionally include equivalent
`expectedKeyVariants` that should be accepted for the same action.
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Sequence

from app.services.shortcut_dataset import get_default_dataset


def _canonicalize_keys(keys: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(str(key).strip().lower() for key in keys if str(key).strip()))


def challenge_accepts_keys(
    challenge: Dict[str, Any],
    provided_keys: Sequence[str],
) -> bool:
    """Return True when `provided_keys` match the primary or alternate bindings."""
    provided = _canonicalize_keys(provided_keys)
    expected = challenge.get("expectedKeys", [])
    if _canonicalize_keys(expected) == provided:
        return True

    variants = challenge.get("expectedKeyVariants", [])
    if not isinstance(variants, list):
        return False

    for variant in variants:
        if _canonicalize_keys(variant) == provided:
            return True
    return False


def generate_shortcut_sequence(
    count: int = 10, rng: random.Random | None = None
) -> List[Dict[str, Any]]:
    """Return a randomized sequence of shortcut challenges.

    - If `count` <= number of available unique challenges, a random sample
      without replacement is returned.
    - If `count` is larger, items are chosen with replacement so a sequence
      of the requested length is always produced.
    Each returned challenge is a shallow copy of the source with an added
    `index` field indicating its position in the sequence.
    """
    rng = rng or random
    if count <= 0:
        return []
    dataset = get_default_dataset()
    if count <= len(dataset):
        seq = rng.sample(dataset, count)
    else:
        seq = [rng.choice(dataset) for _ in range(count)]

    result: List[Dict[str, Any]] = []
    for idx, item in enumerate(seq):
        entry = dict(item)
        entry["index"] = idx
        result.append(entry)
    return result


def mask_challenge_for_player(challenge: Dict[str, Any]) -> Dict[str, Any]:
    """Return the public view of a challenge (remove internal answers)."""
    return {
        k: v
        for k, v in challenge.items()
        if k not in {"expectedKeys", "expectedKeyVariants"}
    }


def publicize_challenges(challenges: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a list of challenges safe to send to clients."""
    return [mask_challenge_for_player(ch) for ch in challenges]
