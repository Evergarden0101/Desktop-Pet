from desktop_pet.config import AppConfig, CharacterPack


def test_appconfig_roundtrip(tmp_path):
    cfg = AppConfig(scale=1.75, walk_speed=123.0, enabled_behaviors=["idle", "climb"])
    path = tmp_path / "config.json"
    cfg.save(str(path))
    loaded = AppConfig.load(str(path))
    assert loaded.scale == 1.75
    assert loaded.walk_speed == 123.0
    assert loaded.enabled_behaviors == ["idle", "climb"]


def test_appconfig_ignores_unknown_keys():
    cfg = AppConfig.from_dict({"scale": 2.0, "totally_unknown": 5})
    assert cfg.scale == 2.0
    assert not hasattr(cfg, "totally_unknown")


def test_appconfig_defaults_when_missing(tmp_path):
    path = tmp_path / "missing.json"
    cfg = AppConfig.load(str(path))
    assert cfg.scale == 1.0
    assert path.exists()  # a default file is written


def test_character_pack_load_defaults(tmp_path):
    pack = CharacterPack.load(str(tmp_path))
    assert pack.extraction == {"method": "auto_humanoid"}
    assert pack.source_image == "texture.png"


def test_character_pack_manifest_roundtrip(tmp_path):
    pack = CharacterPack(
        name="Hero",
        directory=str(tmp_path),
        scale=1.2,
        extraction={"method": "regions", "regions": {}},
        author="tester",
    )
    pack.save_manifest()
    reloaded = CharacterPack.load(str(tmp_path))
    assert reloaded.name == "Hero"
    assert reloaded.scale == 1.2
    assert reloaded.extraction["method"] == "regions"
    assert reloaded.author == "tester"
