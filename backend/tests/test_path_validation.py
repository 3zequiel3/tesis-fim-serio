"""Unit tests for core/path_validation.py (D91/RN-185, change backend-input-validation-hardening)."""

import fnmatch

import pytest

from app.core.path_validation import (
    MAX_PATH_LENGTH,
    MAX_WATCH_PATHS,
    PathValidationError,
    validate_rule_pattern,
    validate_watch_paths,
)


def _code(fn, arg) -> tuple[str, int | None]:
    with pytest.raises(PathValidationError) as exc:
        fn(arg)
    return exc.value.code, exc.value.index


# ── validate_rule_pattern ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pattern",
    [
        "/etc/*",
        "/",
        "!/var/log/*.log",
        "/etc/a..b",
        "/etc/[abc]*.conf",
        "/etc/[!.]*",
        "/etc/[]a]x",
        "/proc/[0-9]*",
        "/" + "a" * (MAX_PATH_LENGTH - 1),
    ],
)
def test_valid_patterns(pattern):
    validate_rule_pattern(pattern)


@pytest.mark.parametrize(
    ("pattern", "code"),
    [
        ("", "pattern_empty"),
        ("   ", "pattern_empty"),
        ("!", "pattern_empty"),
        ("relative/path", "pattern_not_absolute"),
        ("../x", "pattern_not_absolute"),
        ("!tmp/*", "pattern_not_absolute"),
        ("/etc/../../etc/passwd", "pattern_parent_segment"),
        ("/../../etc/passwd", "pattern_parent_segment"),
        ("!/etc/..", "pattern_parent_segment"),
        ("/etc/a\nb", "pattern_control_char"),
        ("/etc/a\tb", "pattern_control_char"),
        ("/etc/a\x00b", "pattern_control_char"),
        ("/etc/a\x7fb", "pattern_control_char"),
        ("/" + "a" * MAX_PATH_LENGTH, "pattern_too_long"),
        ("/etc/[", "pattern_invalid_glob"),
        ("/etc/[abc", "pattern_invalid_glob"),
        ("/etc/[]", "pattern_invalid_glob"),
        ("/etc/[!]", "pattern_invalid_glob"),
    ],
)
def test_invalid_patterns(pattern, code):
    assert _code(validate_rule_pattern, pattern) == (code, None)


def test_pattern_length_counts_the_negation_prefix():
    # "!" + 1023 chars = 1024 -> ok; one more -> too long.
    validate_rule_pattern("!/" + "a" * (MAX_PATH_LENGTH - 2))
    assert _code(validate_rule_pattern, "!/" + "a" * (MAX_PATH_LENGTH - 1))[0] == "pattern_too_long"


def test_pattern_exact_boundaries():
    validate_rule_pattern("/" + "a" * 1023)  # 1024 chars
    assert _code(validate_rule_pattern, "/" + "a" * 1024)[0] == "pattern_too_long"  # 1025


def test_pattern_check_order():
    # relative wins over '..', '..' wins over control, control wins over length
    assert _code(validate_rule_pattern, "a/../b")[0] == "pattern_not_absolute"
    assert _code(validate_rule_pattern, "/../\n")[0] == "pattern_parent_segment"
    assert _code(validate_rule_pattern, "/\n" + "a" * 2000)[0] == "pattern_control_char"
    assert _code(validate_rule_pattern, "/[" + "a" * 2000)[0] == "pattern_too_long"


def test_message_is_spanish_and_error_is_a_value_error():
    with pytest.raises(ValueError) as exc:
        validate_rule_pattern("x")
    assert isinstance(exc.value, PathValidationError)
    assert "absoluta" in exc.value.message
    assert exc.value.to_detail() == {"code": "pattern_not_absolute", "message": exc.value.message}


# ── fnmatch coherence (task 1.3) ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("pattern", "inside", "outside"),
    [
        ("/etc/[abc]x", "/etc/ax", "/etc/dx"),
        ("/etc/[!.]x", "/etc/ax", "/etc/.x"),
        ("/etc/[]a]x", "/etc/]x", "/etc/bx"),
        ("/etc/[]a]x", "/etc/ax", "/etc/[x"),
        ("/proc/[0-9]", "/proc/7", "/proc/a"),
    ],
)
def test_accepted_class_patterns_behave_as_classes(pattern, inside, outside):
    validate_rule_pattern(pattern)
    assert fnmatch.fnmatch(inside, pattern)
    assert not fnmatch.fnmatch(outside, pattern)


def test_unclosed_class_is_literal_in_fnmatch_which_is_why_it_is_rejected():
    assert fnmatch.fnmatch("/etc/[", "/etc/[")  # fnmatch treats it as literal
    assert _code(validate_rule_pattern, "/etc/[")[0] == "pattern_invalid_glob"


# ── validate_watch_paths ──────────────────────────────────────────────────────


def test_valid_watch_paths():
    validate_watch_paths(["/etc", "/var/www", "/"])
    validate_watch_paths(["/opt/no-existe"])
    validate_watch_paths([f"/p{i}" for i in range(MAX_WATCH_PATHS)])


def test_empty_and_too_many():
    assert _code(validate_watch_paths, []) == ("watch_paths_empty", None)
    assert _code(validate_watch_paths, [f"/p{i}" for i in range(MAX_WATCH_PATHS + 1)]) == (
        "watch_paths_too_many",
        None,
    )


@pytest.mark.parametrize(
    ("paths", "code", "index"),
    [
        (["/etc", "var/www"], "watch_path_not_absolute", 1),
        (["relative"], "watch_path_not_absolute", 0),
        (["", "/etc"], "watch_path_empty", 0),
        (["/srv/../etc"], "watch_path_parent_segment", 0),
        (["/etc", "/a\nb"], "watch_path_control_char", 1),
        (["/a\x00b"], "watch_path_control_char", 0),
        (["/" + "a" * MAX_PATH_LENGTH], "watch_path_too_long", 0),
        (["/etc", "/etc/"], "watch_path_duplicate", 1),
        (["/etc/", "/etc"], "watch_path_duplicate", 1),
        (["/", "/"], "watch_path_duplicate", 1),
    ],
)
def test_invalid_watch_paths(paths, code, index):
    assert _code(validate_watch_paths, paths) == (code, index)


def test_watch_path_boundaries_and_literals():
    validate_watch_paths(["/" + "a" * 1023])
    validate_watch_paths(["/a..b", "/a.."])  # '..' only matters as a whole segment
    validate_watch_paths(["/"])  # the root alone is valid
    # '/' and '//' do not collide with '/etc'
    validate_watch_paths(["/", "/etc"])


def test_watch_path_detail_has_index():
    with pytest.raises(PathValidationError) as exc:
        validate_watch_paths(["/etc", "x"])
    assert exc.value.to_detail() == {
        "code": "watch_path_not_absolute",
        "message": exc.value.message,
        "index": 1,
    }
