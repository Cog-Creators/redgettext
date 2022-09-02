import ast
from textwrap import dedent
from typing import Tuple

import polib
import pytest

from redgettext import Options
from tests.utils import FILENAME, get_extractor, get_test_potfile


class TestGettextCalls:
    OPTIONS = Options()

    @pytest.mark.parametrize(
        "source",
        (
            '''_("""t""" r'ex' u't')''',
            """obj._("text")""",
            """\
            _(
                "t"
                "e"
                "xt"
            )
            """,
            '''f"{_('text')}"''',
            '''rf"{_('text')}"''',
            '''f"""{f"{_('text')}"}"""''',
            '''f"{obj._('text')}"''',
        ),
    )
    def test_gettext(self, source: str) -> None:
        extractor = get_extractor(dedent(source), self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile(
            polib.POEntry(msgid="text", occurrences=[(FILENAME, 1)])
        )

    def test_gettext_call_on_call(self) -> None:
        extractor = get_extractor("""type(str)('text')""", self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    def test_gettext_fstrings_with_wrong_input(self) -> None:
        extractor = get_extractor('''f"{_(f'text {repl}')}"''', self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    def test_gettext_wrong_input_type(self) -> None:
        extractor = get_extractor("""_(1)""", self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    def test_gettext_multiple_args(self) -> None:
        extractor = get_extractor("""_('foo', 'bar')""", self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    def test_gettext_kwargs(self) -> None:
        extractor = get_extractor("""_('foo', bar='baz')""", self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    def test_gettext_with_partially_wrong_expression(self) -> None:
        extractor = get_extractor("""_(f'foo') + _('bar')""", self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile(
            polib.POEntry(msgid="bar", occurrences=[(FILENAME, 1)])
        )


def parse_call(source: str, entry: polib.POEntry) -> Tuple[str, ast.Call, polib.POEntry]:
    node = ast.parse(source).body[0].value
    assert type(node) is ast.Call
    return source, node, entry


class TestKeywordSpecGettextCalls:
    OPTIONS = Options(
        keyword_specs=(
            "_:2,2t",
            "_:1,2,3t",
            "_:1,2,3c,4t",
            "_:1",
        ),
    )

    @pytest.mark.parametrize(
        "source,node,entry",
        (
            parse_call(
                '_("singular")', polib.POEntry(msgid="singular", occurrences=[(FILENAME, 1)])
            ),
            parse_call(
                '_("ignored", "singular")',
                polib.POEntry(msgid="singular", occurrences=[(FILENAME, 1)]),
            ),
            parse_call(
                '_("singular", "plural", "ignored")',
                polib.POEntry(
                    msgid="singular", msgid_plural="plural", occurrences=[(FILENAME, 1)]
                ),
            ),
            parse_call(
                '_("singular", "plural", "context", "ignored")',
                polib.POEntry(
                    msgid="singular",
                    msgid_plural="plural",
                    msgctxt="context",
                    occurrences=[(FILENAME, 1)],
                ),
            ),
        ),
    )
    def test_keyword_info_resolution(
        self, source: str, node: ast.Call, entry: polib.POEntry
    ) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile(entry)
