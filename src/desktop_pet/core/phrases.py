"""Speech-bubble phrase pools, mixing English and Chinese.

Behaviours ask :func:`pick` for a random line in a *category*; the pool mixes
languages so the pet chatters bilingually out of the box. Character packs can
extend or replace categories via ``behaviors.phrases`` in ``character.json``
(merged by :func:`merged_pool`).
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

PhrasePool = Dict[str, List[str]]

PHRASES: PhrasePool = {
    "greet": ["hi!", "你好呀~", "hello~", "我来啦!", "hi there!"],
    "idle": [
        "nice day~",
        "今天天气不错",
        "hmm...",
        "发呆中……",
        "la la la~",
        "有点无聊呀",
        "what's next?",
        "陪我玩嘛~",
        "*stretch*",
    ],
    "climb": ["up we go!", "爬上去看看!", "almost there...", "加油加油!", "好高呀!"],
    "sit": ["nice view!", "坐一会儿~", "so comfy~", "歇歇脚", "风景不错~"],
    "sleep": ["zzz...", "好困……", "nap time~", "晚安~", "睡一会儿……"],
    "wake": ["I'm up!", "睡醒啦!", "*yawn*", "精神满满!"],
    "feed": ["yum!", "好吃!", "thanks!", "谢谢款待~", "美味!"],
    "poke": ["hehe~", "干嘛戳我呀", "hi!", "痒痒的!", "again, again!"],
    "drag": ["wheee!", "放我下来~", "flying!", "别扔我呀!", "我会飞啦!"],
    "land_hard": ["oof!", "好痛……", "ouch!", "摔疼了啦!"],
    "chase": ["wait for me!", "等等我~", "catch you!", "跑不掉的~"],
    "summon": ["here!", "我来啦!", "you called?", "召唤成功!"],
    "hungry": ["I'm hungry...", "肚子饿了……", "feed me?", "想吃东西……"],
    "tired": ["so tired...", "好累……", "need a nap...", "想睡觉了……"],
    "walk": ["off we go~", "散步去咯", "walking, walking~", "看看那边有什么"],
    "blocked": ["a wall!", "有堵墙!", "can't pass...", "过不去呀"],
}


def pick(rng: random.Random, category: str, pool: Optional[PhrasePool] = None) -> str:
    """Return a random phrase from ``category`` (empty string if unknown)."""
    source = pool or PHRASES
    options = source.get(category) or PHRASES.get(category) or []
    if not options:
        return ""
    return rng.choice(options)


def merged_pool(overrides: Optional[Dict[str, List[str]]]) -> PhrasePool:
    """Merge character-pack phrase overrides over the built-in pool."""
    if not overrides:
        return PHRASES
    merged = dict(PHRASES)
    for key, values in overrides.items():
        if isinstance(values, list) and values:
            merged[key] = [str(v) for v in values]
    return merged
