import hashlib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from identity_helper import civ_id_for, legacy_civ_id_for


def test_distinct_keys_for_same_prefix_users():
    """alice123 and alice199 must NOT alias."""
    k1, d1 = civ_id_for("alice123")
    k2, d2 = civ_id_for("alice199")
    assert k1 != k2, f"collision: {k1} == {k2}"
    assert d1 == "alice1" and d2 == "alice1"


def test_legacy_slice_still_collides():
    """Documents the defect being retired."""
    assert legacy_civ_id_for("alice123") == legacy_civ_id_for("alice199")


def test_full_id_affects_key():
    """Changing any character of the full ID changes the key."""
    k1, _ = civ_id_for("alice123")
    k2, _ = civ_id_for("alice1234")
    assert k1 != k2


def test_deterministic():
    assert civ_id_for("bob") == civ_id_for("bob")


def test_empty_rejected():
    try:
        civ_id_for("")
        assert False, "expected ValueError"
    except ValueError:
        pass


if __name__ == "__main__":
    test_distinct_keys_for_same_prefix_users()
    test_legacy_slice_still_collides()
    test_full_id_affects_key()
    test_deterministic()
    test_empty_rejected()
    print("5/5 passed")
