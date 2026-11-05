"""The box detector's prompts from a search query (OMNI-X02, D-42). Here, not in ai_workers,
because query builds the prompts it sends and ai_workers labels the boxes with them.

    "a blue car" -> ["a blue car", "car"]

The query as typed, then the prompt for each object word it contains. A fixed list, not tuned.
"""

import re
from collections.abc import Sequence

OBJECT_WORDS = {
    "person": "person", "man": "person", "woman": "person", "people": "person",
    "car": "car", "vehicle": "car", "truck": "car", "van": "car",
    "bike": "bicycle", "bicycle": "bicycle",
    "bag": "bag", "box": "box", "object": "object",
}
OBJECT_PROMPTS = frozenset(OBJECT_WORDS.values())


def prompts_for(query: str) -> list[str]:
    """The query as typed, then each object word's prompt (once, in order of appearance)."""
    text = query.strip()
    prompts = [text] if text else []
    for word in re.findall(r"[a-z]+", text.lower()):
        prompt = OBJECT_WORDS.get(word)
        if prompt is not None and prompt not in prompts:
            prompts.append(prompt)
    return prompts


def label_for(prompt: str, prompts: Sequence[str]) -> str:
    """The label shown is the prompt that matched, except that a box matched by a longer
    prompt (the whole query) takes the first object word among the prompts: *car*, not
    *a blue car* (D-42)."""
    if prompt in OBJECT_PROMPTS:
        return prompt
    return next((p for p in prompts if p in OBJECT_PROMPTS), prompt)
