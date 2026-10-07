import json

import pytest

from pdm.models.caches import (
    EmptyCandidateInfoCache,
    EmptyHashCache,
    HashCache,
    JSONFileCache,
)


class TestJSONFileCache:
    def test_set_get_persists_across_instances(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = JSONFileCache(cache_file)
        cache.set("a", [1, 2, 3])
        cache.set("b", {"summary": "hello"})

        assert "a" in cache
        assert cache.get("a") == [1, 2, 3]

        reloaded = JSONFileCache(cache_file)
        assert reloaded.get("a") == [1, 2, 3]
        assert reloaded.get("b") == {"summary": "hello"}
        # A published generation is always one complete JSON document.
        assert json.loads(cache_file.read_text(encoding="utf-8")) == {
            "a": [1, 2, 3],
            "b": {"summary": "hello"},
        }

    def test_every_update_publishes_a_full_generation(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = JSONFileCache(cache_file)
        cache.set("a", 1)
        cache.set("b", 2)

        assert len(list(cache_file.parent.glob("atomic-write-*"))) == 0
        assert json.loads(cache_file.read_text()) == {"a": 1, "b": 2}

    def test_truncated_generation_salvages_other_entries(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = JSONFileCache(cache_file)
        cache.set("a", ["deps-a"])
        cache.set("b", ["deps-b"])
        cache.set("c", ["deps-c"])

        valid_prefix = cache_file.read_text(encoding="utf-8")
        # Simulate the process being killed inside the third entry's value.
        torn = valid_prefix[: valid_prefix.index('"c"') + 6]
        assert torn.endswith("[")
        cache_file.write_text(torn, encoding="utf-8")

        salvaged = JSONFileCache(cache_file)
        assert salvaged.get("a") == ["deps-a"]
        assert salvaged.get("b") == ["deps-b"]
        assert "c" not in salvaged

        # The cache can keep being filled and publishes a valid generation.
        salvaged.set("d", ["deps-d"])
        assert json.loads(cache_file.read_text(encoding="utf-8")) == {
            "a": ["deps-a"],
            "b": ["deps-b"],
            "d": ["deps-d"],
        }
        assert JSONFileCache(cache_file).get("a") == ["deps-a"]

    def test_truncated_nested_entry_is_dropped_alone(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache = JSONFileCache(cache_file)
        cache.set("a", 1)
        cache.set("nested", {"requires_python": ">=3.8", "deps": ["x", "y"]})
        content = cache_file.read_text(encoding="utf-8")
        # Tear the nested value right in the middle.
        head = content[: content.index('"nested"')]
        torn = head + '"nested": {"requires_python": ">=3.8", "dep'
        cache_file.write_text(torn, encoding="utf-8")

        salvaged = JSONFileCache(cache_file)
        assert salvaged.get("a") == 1
        assert "nested" not in salvaged

    def test_unreadable_cache_starts_empty_and_can_be_filled(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("this is not json at all", encoding="utf-8")

        cache = JSONFileCache(cache_file)
        assert "x" not in cache
        cache.set("x", "value")
        assert JSONFileCache(cache_file).get("x") == "value"

    def test_failed_write_keeps_last_valid_generation(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "cache.json"
        cache = JSONFileCache(cache_file)
        cache.set("a", 1)
        cache.set("b", 2)
        previous = cache_file.read_text(encoding="utf-8")

        def boom(*args, **kwargs):
            raise RuntimeError("write interrupted")

        monkeypatch.setattr(json, "dump", boom)
        with pytest.raises(RuntimeError):
            cache.set("c", 3)

        assert cache_file.read_text(encoding="utf-8") == previous
        reloaded = JSONFileCache(cache_file)
        assert reloaded.get("a") == 1
        assert reloaded.get("b") == 2
        assert "c" not in reloaded
        assert len(list(cache_file.parent.glob("atomic-write-*"))) == 0

    def test_non_object_json_is_ignored(self, tmp_path):
        cache_file = tmp_path / "cache.json"
        cache_file.write_text('["not", "a", "mapping"]', encoding="utf-8")
        cache = JSONFileCache(cache_file)
        assert "not" not in cache
        cache.set("k", "v")
        assert JSONFileCache(cache_file).get("k") == "v"


class TestHashCache:
    URL = "https://fixtures.test/artifacts/demo-0.0.1.tar.gz"
    HASH = "sha256:d57bf5e3b8723e4fc68275159dcc4ca983d86d4c84220a4d715d491401f27db2"

    def test_set_get_roundtrip(self, tmp_path):
        hash_cache = HashCache(tmp_path)
        assert hash_cache.get(self.URL) is None
        hash_cache.set(self.URL, self.HASH)
        assert hash_cache.get(self.URL) == self.HASH

    def test_torn_entry_is_discarded(self, tmp_path):
        hash_cache = HashCache(tmp_path)
        hash_cache.set(self.URL, self.HASH)
        path = hash_cache._get_path_for_key(self.URL)
        # Simulate an interrupted, half-written entry.
        path.write_text("sha256:d57bf5e3", encoding="utf-8")
        assert hash_cache.get(self.URL) is None

        # A fresh value can be published over the torn one.
        hash_cache.set(self.URL, self.HASH)
        assert hash_cache.get(self.URL) == self.HASH

    @pytest.mark.parametrize("content", ["", "   ", "garbage", "sha256:", "nothalfsig", "sha256:xyz"])
    def test_invalid_entries_are_ignored(self, tmp_path, content):
        hash_cache = HashCache(tmp_path)
        path = hash_cache._get_path_for_key(self.URL)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        assert hash_cache.get(self.URL) is None

    def test_failed_write_keeps_previous_value(self, tmp_path, monkeypatch):
        hash_cache = HashCache(tmp_path)
        hash_cache.set(self.URL, self.HASH)
        path = hash_cache._get_path_for_key(self.URL)

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr("pdm.models.caches.atomic_open_for_write", boom)
        with pytest.raises(RuntimeError):
            hash_cache.set(self.URL, "sha256:0000000000000000000000000000000000000000000000000000000000000000")
        assert path.read_text(encoding="utf-8") == self.HASH


class TestEmptyCaches:
    def test_empty_hash_cache_is_noop(self, tmp_path):
        hash_cache = EmptyHashCache(tmp_path)
        assert hash_cache.get("https://example.org/x.tar.gz") is None
        hash_cache.set("https://example.org/x.tar.gz", "sha256:abc")
        assert hash_cache.get("https://example.org/x.tar.gz") is None
        assert not any(tmp_path.rglob("*"))

    def test_empty_candidate_info_cache_is_noop(self, tmp_path):
        info_cache = EmptyCandidateInfoCache(tmp_path / "meta.json")
        with pytest.raises(KeyError):
            info_cache.get(None)
        info_cache.set(None, (["dep"], ">=3.8", "summary"))
        with pytest.raises(KeyError):
            info_cache.get(None)
