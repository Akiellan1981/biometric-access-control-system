from acs.core.fingerprint.mock import MockFingerprint


def test_enroll_and_search():
    s = MockFingerprint()
    slot = s.enroll()
    assert slot == 0 and s.count() == 1

    assert s.search() is None          # nothing queued
    s.simulate_touch(slot, 88)
    m = s.search()
    assert m.slot == slot and m.confidence == 88
    assert s.search() is None          # consumed


def test_delete():
    s = MockFingerprint()
    slot = s.enroll()
    assert s.delete(slot) and s.count() == 0
