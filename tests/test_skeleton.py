import math

from desktop_pet.core.geometry import Vec2
from desktop_pet.core.skeleton import Bone, Skeleton
from desktop_pet.rig.body_parts import default_skeleton
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


def test_default_humanoid_stands_upright():
    sk = default_skeleton()
    sk.root_position = Vec2(0, 0)
    sk.solve()
    # Head should be above the root (negative Y), feet below (positive Y).
    assert sk.tip_scaled_of("head").y < -50
    assert sk.tip_scaled_of("foot_l").y > 50
    assert sk.tip_scaled_of("foot_r").y > 50


def test_stand_offset_is_positive_and_reasonable():
    sk = default_skeleton()
    offset = stand_offset_of(sk)
    # Roughly thigh+shin+foot lengths (40+38+14) minus geometry, should be big.
    assert 60 < offset < 130


def test_blend_moves_toward_target():
    sk = make_arm()
    sk.bones["upper"].local_angle = 0.0
    sk.blend({"upper": math.pi / 2}, 0.5)
    assert 0.0 < sk.bones["upper"].local_angle <= math.pi / 2
