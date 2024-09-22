import pytest

from redgettext import DEFAULT_KEYWORD_SPECS, KeywordInfo, parse_keyword_specs


@pytest.mark.parametrize(
    "keyword_spec,expected",
    (
        # no/empty argument spec
        ("gettext", KeywordInfo("gettext")),
        ("gettext:", KeywordInfo("gettext")),
        # default argument spec
        ("gettext:1", KeywordInfo("gettext", arg_singular=0)),
        # singular,plural
        ("ngettext:1,2", KeywordInfo("ngettext", arg_singular=0, arg_plural=1)),
        # singular,plural,context
        ("custom:1,2,3c", KeywordInfo("custom", arg_singular=0, arg_plural=1, arg_context=2)),
        # singular,plural,context,total
        (
            "custom:1,2,3c,3t",
            KeywordInfo("custom", arg_singular=0, arg_plural=1, arg_context=2, total_arg_count=3),
        ),
        # singular,plural,total
        (
            "ngettext:1,2,2t",
            KeywordInfo("ngettext", arg_singular=0, arg_plural=1, total_arg_count=2),
        ),
        # context,singular,plural,total
        (
            "npgettext:1c,2,3,3t",
            KeywordInfo(
                "npgettext", arg_singular=1, arg_plural=2, arg_context=0, total_arg_count=3
            ),
        ),
        # context,singular,total
        (
            "npgettext:1c,2,3t",
            KeywordInfo("npgettext", arg_singular=1, arg_context=0, total_arg_count=3),
        ),
        # comment,singular
        ('custom:"com",2', KeywordInfo("custom", arg_singular=1, comment="com")),
        # singular,comment,plural
        ('custom:1,"com",2', KeywordInfo("custom", arg_singular=0, arg_plural=1, comment="com")),
        # singular,plural,comment
        ('custom:1,2,"com"', KeywordInfo("custom", arg_singular=0, arg_plural=1, comment="com")),
        # singular,plural,comment,context,total,comment,comment
        (
            'custom:1,2,"com",3c,3t,"different com","com 3"',
            KeywordInfo(
                "custom",
                arg_singular=0,
                arg_plural=1,
                arg_context=2,
                total_arg_count=3,
                comment="com\ndifferent com\ncom 3",
            ),
        ),
        # singular,plural,context,total,comment
        (
            'custom:1,2,3c,3t,"com"',
            KeywordInfo(
                "custom",
                arg_singular=0,
                arg_plural=1,
                arg_context=2,
                total_arg_count=3,
                comment="com",
            ),
        ),
        # singular,context,comment,plural
        (
            'custom:1,3c,"com",2',
            KeywordInfo("custom", arg_singular=0, arg_plural=1, arg_context=2, comment="com"),
        ),
        # singular,context,plural
        ("custom:1,3c,2", KeywordInfo("custom", arg_singular=0, arg_plural=1, arg_context=2)),
        # singular,context,plural,comment
        (
            'custom:1,3c,2,"com"',
            KeywordInfo("custom", arg_singular=0, arg_plural=1, arg_context=2, comment="com"),
        ),
        # context,singular
        ("custom:3c,2", KeywordInfo("custom", arg_singular=1, arg_context=2)),
    ),
)
def test_passing(keyword_spec: str, expected: KeywordInfo) -> None:
    output = KeywordInfo.from_spec(keyword_spec)
    assert tuple(expected) == tuple(output)


@pytest.mark.parametrize(
    "keyword_spec",
    (
        "custom:1,2,1t",
        "custom:2,1,1t",
        "custom:1,2,3c,2t",
        "custom:1,3,2c,2t",
        "custom:2,1,3c,2t",
        "custom:2,3,1c,2t",
        "custom:3,1,2c,2t",
        "custom:3,2,1c,2t",
    ),
)
def test_failing_too_low_total_arg_count(keyword_spec: str) -> None:
    pattern = r".* argument count cannot be lower than any .*"
    with pytest.raises(ValueError, match=pattern):
        KeywordInfo.from_spec(keyword_spec)


@pytest.mark.parametrize("keyword_spec", ("_:2c", "_:2c,2t", "_:2t,2c", '_:"comment"'))
def test_failing_singular_form_not_specified(keyword_spec: str) -> None:
    with pytest.raises(ValueError, match=r".* singular form argument needs to be specified .*"):
        KeywordInfo.from_spec(keyword_spec)


@pytest.mark.parametrize("keyword_spec", ("_:c", "_:text", "_:3c2", '_:"text', '_:"blah'))
def test_failing_bad_integer(keyword_spec: str) -> None:
    with pytest.raises(ValueError, match=r"^'.*' is not a valid integer\.$"):
        KeywordInfo.from_spec(keyword_spec)


@pytest.mark.parametrize("keyword_spec", ('_:"', '_:text"', '_:text",1', '_:2,"', '_:1,",2'))
def test_failing_missing_starting_quote(keyword_spec: str) -> None:
    with pytest.raises(ValueError, match=r".* starting quote .*"):
        KeywordInfo.from_spec(keyword_spec)


@pytest.mark.parametrize("keyword_spec", ("_:0", "_:1,-1", "_:1,2,-5c"))
def test_failing_numbers_below_1(keyword_spec: str) -> None:
    with pytest.raises(ValueError, match=r".* Argument numbers start from 1\.$"):
        KeywordInfo.from_spec(keyword_spec)


@pytest.mark.parametrize("keyword_spec", ("_:1,1", "_:1,1,1c", "_:1,1,2c", "_:1,2,1c", "_:2,1,1c"))
def test_duplicate_numbers(keyword_spec: str) -> None:
    with pytest.raises(ValueError, match=r".* same argument number cannot be used .*"):
        KeywordInfo.from_spec(keyword_spec)


def test_parse_keyword_specs_order() -> None:
    keywords = parse_keyword_specs(("_:1,2,3c,4t", "_:1", "_:1,2,3t", "_:2,2t"))
    assert [2, 3, 4, None] == [ki.total_arg_count for ki in keywords["_"]]


def test_parse_keyword_specs_failing_same_total_count_twice() -> None:
    with pytest.raises(
        ValueError, match=r".* total argument count 3 has been specified more than once\.$"
    ):
        parse_keyword_specs(("_:2,1,3t", "_:1,2,3t"))


def test_parse_keyword_specs_failing_no_total_count_twice() -> None:
    with pytest.raises(
        ValueError, match=r".* no total argument count has been specified more than once\.$"
    ):
        parse_keyword_specs(("_:2,1", "_:1,2"))


@pytest.mark.parametrize("keyword_spec", DEFAULT_KEYWORD_SPECS)
def test_default_keyword_specs(keyword_spec: str) -> None:
    KeywordInfo.from_spec(keyword_spec)
