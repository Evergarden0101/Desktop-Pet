import math

from desktop_pet.core.geometry import Rect, Vec2, clamp, lerp, lerp_angle, smoothstep


def test_vec_arithmetic():
    a = Vec2(3, 4)
    assert a.length() == 5
    assert (a * 2) == Vec2(6, 8)
    assert (2 * a) == Vec2(6, 8)
    assert (a - Vec2(1, 1)) == Vec2(2, 3)
    assert a.normalized().length() == 1  # pragma: no branch


def test_vec_rotation_and_angle():
    v = Vec2(1, 0).rotated(math.pi / 2)
    assert abs(v.x) < 1e-9 and abs(v.y - 1) < 1e-9
    assert abs(Vec2.from_angle(math.pi).x + 1) < 1e-9


def test_clamp_and_lerp():
    assert clamp(5, 0, 3) == 3
    assert clamp(-1, 0, 3) == 0
    assert clamp(2, 3, 0) == 2  # tolerates swapped bounds
    assert lerp(0, 10, 0.5) == 5
    assert smoothstep(0.5) == 0.5


def test_lerp_angle_wraps_shortest_arc():
    # from 170deg to -170deg should cross +/-180, i.e. +20deg not -340deg.
    a = math.radians(170)
    b = math.radians(-170)
    result = lerp_angle(a, b, 0.5)
    # midpoint should be near +/-180 (pi), not near 0.
    assert abs(abs(result) - math.pi) < 0.2


def test_rect_geometry():
    r = Rect(0, 0, 100, 50)
    assert r.right == 100 and r.bottom == 50
    assert r.center == Vec2(50, 25)
    assert r.contains(Vec2(10, 10))
    assert not r.contains(Vec2(200, 10))
    assert r.intersects(Rect(90, 40, 20, 20))
    assert not r.intersects(Rect(200, 200, 10, 10))


def test_rect_bounding():
    r = Rect.bounding([Vec2(-1, 2), Vec2(3, -4), Vec2(0, 0)])
    assert r.left == -1 and r.top == -4 and r.right == 3 and r.bottom == 2
