import pytest
import yaml

from dispogen.config import Config, ConfigError, _deep_merge


def test_client_overrides_default_without_dropping_siblings():
    merged = _deep_merge({"quota": {"fn_probes": 5, "fp_probes": 5}},
                         {"quota": {"fp_probes": 8}})
    assert merged["quota"] == {"fn_probes": 5, "fp_probes": 8}


def test_list_values_replace_rather_than_merge():
    # Appending would make it impossible for a client to shorten an inherited
    # list — e.g. to drop an FP slot their taxonomy cannot supply.
    merged = _deep_merge({"a": [1, 2, 3]}, {"a": [9]})
    assert merged["a"] == [9]


def test_missing_key_raises_rather_than_returning_none(cfg):
    with pytest.raises(ConfigError, match="inputs.taxonomy.nope"):
        cfg.get("inputs.taxonomy.nope")
    assert cfg.get("inputs.taxonomy.nope", "fallback") == "fallback"


def test_half_written_client_config_fails_at_load(repo):
    p = repo / "config" / "clients" / "broken.yaml"
    p.write_text(yaml.safe_dump({"client": {"name": "broken"}}), encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        Config.load("broken", repo)
    assert "client.anchor" in str(e.value)
    assert "inputs.taxonomy.path" in str(e.value)


def test_unknown_client_lists_what_is_available(repo):
    with pytest.raises(ConfigError, match="testco"):
        Config.load("nosuchclient", repo)


def test_salt_defaults_but_is_env_driven(cfg, monkeypatch):
    monkeypatch.delenv("DISPOGEN_DEID_SALT", raising=False)
    assert cfg.salt == "dispogen-default-salt"
    monkeypatch.setenv("DISPOGEN_DEID_SALT", "s3cret")
    assert cfg.salt == "s3cret"
