"""Tests for window-selection logic (the pure picker; the Win32 calls aren't
exercised in CI). Guards the self-capture bug where the 'Judgment' query matched
our own 'judgment-assist' overlay instead of the game."""
from judgment_assist.capture.window import _select_window


def test_prefers_exact_title_over_substring_even_if_bigger():
    # overlay matches the substring and is (here) larger, but the game is exact
    matches = [(1, "judgment-assist", 100_000), (2, "Judgment", 50_000)]
    assert _select_window(matches, "judgment") == (2, "Judgment")


def test_falls_back_to_largest_when_no_exact_match():
    matches = [(1, "judgment-assist", 769 * 76), (2, "Judgment - Steam", 1920 * 1080)]
    assert _select_window(matches, "judgment") == (2, "Judgment - Steam")


def test_none_when_no_matches():
    assert _select_window([], "judgment") is None
