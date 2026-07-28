import math

import pytest

from desktop_pet.core.geometry import Vec2
from desktop_pet.core.skeleton import Bone, Skeleton
from desktop_pet.rig.body_parts import BODY_STYLES, default_skeleton
from desktop_pet.rig.skeleton_utils import stand_offset_of


def make_arm():
    return Skeleton(
        [
            Bone("shoulder", length=0.0, parent=None, rest_angle=0.0),
            Bone("upper", length=10.0, parent="shoulder", rest_angle=0.0),
            Bone("fore", length=10.0, parent="upper", rest_angle=0.0),
        ]
    )


def test_fk_chains_positions():
    sk = make_arm()
    sk.root_position = Vec2(0, 0)
    sk.solve()
    # Straight chain along +X: fore tip should be at length sum.
    assert abs(sk.tip_scaled_of("fore").x - 20.0) < 1e-6
    assert abs(sk.tip_scaled_of("fore").y) < 1e-6


def test_fk_respects_scale():
    sk = make_arm()
    sk.scale = 2.0
    sk.solve()
    assert abs(sk.tip_scaled_of("fore").x - 40.0) < 1e-6


def test_two_bone_ik_reaches_target():
    sk = make_arm()
    sk.root_position = Vec2(0, 0)
    target = Vec2(12, 6)  # within reach (max 20)
    reachable = sk.solve_two_bone_ik("upper", "fore", target)
    sk.solve()
    assert reachable
    tip = sk.tip_scaled_of("fore")
    assert tip.distance_to(target) < 1e-3


def test_two_bone_ik_out_of_range_stretches():
    sk = make_arm()
    target = Vec2(100, 0)  # far out of reach
    reachable = sk.solve_two_bone_ik("upper", "fore", target)
    sk.solve()
    assert not reachable
    # Arm should point straight at the target, fully extended (~20 units).
    tip = sk.tip_scaled_of("fore")
    assert abs(tip.length() - 20.0) < 1e-3
    assert tip.normalized().distance_to(Vec2(1, 0)) < 1e-3


@pytest.mark.parametrize("style", sorted(BODY_STYLES))
def test_humanoid_styles_stand_upright(style):
    """Every body style must rest with the head up and both feet below the root."""
    sk = default_skeleton(style)
    sk.root_position = Vec2(0, 0)
    sk.solve()
    head_tip = sk.tip_scaled_of("head").y
    assert head_tip < -20, "head should be above the pelvis"
    for foot in ("foot_l", "foot_r"):
        assert sk.tip_scaled_of(foot).y > 20, f"{foot} should be below the pelvis"
    # Feet should be roughly level with each other, or the pet stands lopsided.
    assert abs(sk.tip_scaled_of("foot_l").y - sk.tip_scaled_of("foot_r").y) < 12


@pytest.mark.parametrize("style", sorted(BODY_STYLES))
def test_stand_offset_matches_leg_length(style):
    sk = default_skeleton(style)
    offset = stand_offset_of(sk)
    legs = sk.bones["thigh_l"].length + sk.bones["shin_l"].length
    # The pelvis-to-floor distance is essentially the leg chain, plus the ankle.
    assert legs * 0.75 < offset < legs * 1.35


def test_cute_style_has_a_bigger_head_than_human():
    cute = default_skeleton("cute")
    human = default_skeleton("human")

    def heads_tall(sk):
        return stand_offset_of(sk) / sk.bones["head"].length

    # Chibi proportions mean fewer head-lengths of leg.
    assert heads_tall(cute) < heads_tall(human)


def test_blend_moves_toward_target():
    sk = make_arm()
    sk.bones["upper"].local_angle = 0.0
    sk.blend({"upper": math.pi / 2}, 0.5)
    assert 0.0 < sk.bones["upper"].local_angle <= math.pi / 2
