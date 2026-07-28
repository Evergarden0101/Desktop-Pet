from desktop_pet.core.environment import Environment, SurfaceKind, WallKind
from desktop_pet.core.geometry import Rect, Vec2
from desktop_pet.core.physics import PhysicsBody, VelocityTracker
from desktop_pet.platform.null import NullBackend


def test_gravity_accelerates_downward():
    body = PhysicsBody(gravity=1000.0)
    body.integrate(0.1)
    assert body.velocity.y > 0
    assert body.position.y > 0


def test_landing_zeros_vertical_velocity():
    body = PhysicsBody()
    body.velocity = Vec2(5, 400)
    body.land(300)
    assert body.position.y == 300
    assert body.velocity.y == 0
    assert body.on_ground


def test_velocity_tracker_estimates_throw():
    tracker = VelocityTracker(window=1.0)
    tracker.add(0.0, Vec2(0, 0))
    tracker.add(0.1, Vec2(10, -5))
    v = tracker.velocity()
    assert v.x > 0 and v.y < 0


def test_environment_builds_surfaces_and_walls():
    env = Environment(NullBackend().snapshot())
    kinds = {s.kind for s in env.surfaces}
    assert SurfaceKind.FLOOR in kinds
    assert SurfaceKind.TASKBAR in kinds
    assert SurfaceKind.WINDOW in kinds
    assert any(w.kind == WallKind.WINDOW for w in env.walls)
    assert any(w.kind == WallKind.SCREEN for w in env.walls)


def test_ground_below_finds_window_top():
    env = Environment(NullBackend().snapshot())
    # A point above the sample editor window (x in 300..1000, top y=200).
    hit = env.ground_below(400, 50)
    assert hit is not None
    assert hit.y == 200  # lands on the window's top edge, not the floor


def test_ground_below_falls_through_to_floor():
    env = Environment(NullBackend().snapshot())
    # A column with no window above the floor.
    hit = env.ground_below(50, 10)
    assert hit is not None
    assert hit.surface.kind in (SurfaceKind.FLOOR, SurfaceKind.TASKBAR)


def test_nearest_wall_detects_window_edge():
    env = Environment(NullBackend().snapshot())
    # Sample editor left edge is at x=300, spanning y 200..680.
    wall = env.nearest_wall(Vec2(305, 300), radius=40)
    assert wall is not None
    assert abs(wall.x - 300) < 1e-6


def test_interactive_windows_toggle():
    snap = NullBackend().snapshot()
    env = Environment(snap, interactive_windows=False)
    assert all(s.kind != SurfaceKind.WINDOW for s in env.surfaces)
