"""The D-21 rule: UCF-Crime event times from UCA (OMNI-603).

UCA (UCF-Crime Annotation, Yuan et al., CVPR 2024) times **every** event described in a
video, not only the crime, so the crime's segment is picked:

  1. Each anomaly class has a list of word patterns naming its act (CLASS_PATTERNS).
  2. A video's event is the UCA segment with the **earliest start** whose description
     matches one of its class's patterns (UCA's segments are not in time order).
  3. No segment matches: the video has no event time. Nothing is guessed.

Moved here unchanged from `scripts/uca_event_times.py` so the UCF-Crime loader and the
agreement script apply the same rule.
"""

import json
import re
from pathlib import Path

# Word patterns naming each class's act, matched case-insensitively on word starts.
CLASS_PATTERNS: dict[str, list[str]] = {
    "Abuse": [r"hit", r"beat", r"kick", r"punch", r"slap", r"slam", r"push", r"struck", r"strangl",
              r"chok", r"drag", r"abus", r"threw .* (to|on) the (ground|floor|bed)"],
    "Arrest": [r"arrest", r"handcuff", r"pressed", r"pinned", r"subdu", r"controll", r"detain",
               r"pushed .* (down|ground)", r"escort", r"pulled .* out of"],
    "Arson": [r"fire", r"burn", r"ignit", r"lit", r"flame", r"blaz", r"pour", r"sprinkl"],
    "Assault": [r"beat", r"hit", r"punch", r"kick", r"stab", r"struck", r"knock", r"attack", r"slash",
                r"push", r"slap", r"strangl"],
    "Burglary": [r"broke", r"break", r"pry", r"pried", r"smash", r"kicked (in|open)", r"forc", r"climb",
                 r"stole", r"steal", r"crowbar"],
    "Explosion": [r"explo", r"blast", r"blew", r"detonat"],
    "Fighting": [r"fight", r"fought", r"punch", r"kick", r"beat", r"hit", r"push", r"knock", r"struggl",
                 r"scuffl", r"brawl", r"wrestl"],
    "RoadAccidents": [r"collid", r"collision", r"crash", r"hit", r"knock", r"overturn", r"rolled over",
                      r"accident", r"struck", r"ran over", r"run over"],
    "Robbery": [r"gun", r"knife", r"pistol", r"weapon", r"threat", r"rob", r"grab", r"snatch", r"forc",
                r"held up", r"point"],
    "Shooting": [r"shot", r"shoot", r"gun", r"pistol", r"rifle", r"fired"],
    "Shoplifting": [r"(put|stuff|tuck|hid|slipp)\w* .* (pocket|bag|pants|skirt|coat|clothes|purse|backpack|waist|sleeve)",
                    r"conceal", r"hid", r"stole", r"steal"],
    "Stealing": [r"stole", r"steal", r"pry", r"pried", r"broke", r"unlock", r"took away", r"(rode|drove|carried) away",
                 r"took .* (from|out of)", r"lift"],
    "Vandalism": [r"smash", r"kick", r"spray", r"paint", r"threw", r"broke", r"break", r"damag", r"destroy",
                  r"graffiti", r"scratch", r"knock", r"overturn"],
}
COMPILED = {c: re.compile(r"\b(" + "|".join(p) + r")", re.IGNORECASE) for c, p in CLASS_PATTERNS.items()}

UCA_SPLITS = ("Train", "Val", "Test")


def class_of(name: str) -> str:
    """`Robbery048_x264` -> `Robbery`; `Normal_Videos_003_x264` -> `Normal`."""
    if name.startswith("Normal"):
        return "Normal"
    return re.match(r"([A-Za-z]+)\d", name).group(1)


def pick_event(event_class: str, entry: dict) -> tuple[float, float, str] | None:
    """The rule: the earliest-starting UCA segment whose description names the class's act.
    Returns (start_s, end_s, sentence), or None when no segment matches (no event time)."""
    pattern = COMPILED.get(event_class)
    if pattern is None:
        return None
    hits = [(a, b, s) for (a, b), s in zip(entry["timestamps"], entry["sentences"], strict=True) if pattern.search(s)]
    return min(hits, key=lambda h: (h[0], h[1])) if hits else None


def load_uca(json_dir: Path) -> dict[str, tuple[str, dict]]:
    """Every UCA video, `name -> (UCA split, entry)`. UCA's own split is returned for
    reference only: it is not the official UCF-Crime split and is never used as one."""
    out = {}
    for split in UCA_SPLITS:
        for name, entry in json.loads((json_dir / f"UCFCrime_{split}.json").read_text(encoding="utf-8")).items():
            if name in out:
                raise ValueError(f"UCA names {name} in two splits")
            out[name] = (split, entry)
    return out
