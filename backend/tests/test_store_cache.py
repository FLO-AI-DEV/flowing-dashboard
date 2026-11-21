"""The cache serves a copy at once and re-reads in the background once it is half its life; Google failures keep the last copy."""
import time

from app import store


def test_refresh_ahead_serves_old_copy_while_reloading(monkeypatch):
    calls = []

    def loader():
        calls.append(time.time())
        time.sleep(0.2)                      # a slow Google read
        return len(calls)

    c = store.TTLCache()
    assert c.get("k", 1.0, loader).value == 1
    time.sleep(0.6)                          # past half its life, not yet expired
    t0 = time.time()
    assert c.get("k", 1.0, loader).value == 1       # answered immediately with the old copy
    assert time.time() - t0 < 0.1
    time.sleep(0.5)
    assert c.get("k", 1.0, loader).value == 2       # the background read landed


def test_failed_read_keeps_last_good_copy():
    state = {"fail": False}

    def loader():
        if state["fail"]:
            raise RuntimeError("quota")
        return "good"

    c = store.TTLCache()
    assert c.get("k", 0.2, loader).value == "good"
    time.sleep(0.25)
    state["fail"] = True
    e = c.get("k", 0.2, loader)
    assert e.value == "good" and e.error == "quota"
