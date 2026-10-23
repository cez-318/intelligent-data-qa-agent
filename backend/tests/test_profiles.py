import pytest

from improved.profiles import active_profile


def test_default_profile_preserves_existing_names(monkeypatch):
    monkeypatch.delenv('DATA_AGENT_PROFILE', raising=False)
    profile = active_profile()
    assert profile.name == 'fixture'
    assert profile.column_collection == 'data-agent-column'
    assert profile.conf.name == 'conf'


def test_retail_isolated_and_cannot_use_arbitrary_path(monkeypatch):
    monkeypatch.setenv('DATA_AGENT_PROFILE', 'retail_ii')
    profile = active_profile()
    assert profile.dw_database == 'dw_retail_ii'
    assert profile.meta_database == 'meta_retail_ii'
    assert profile.column_collection != 'data-agent-column'
    assert profile.conf.name == 'retail_ii'
    monkeypatch.setenv('DATA_AGENT_PROFILE', '../../other')
    with pytest.raises(ValueError, match='UNKNOWN_DATA_PROFILE'):
        active_profile()
