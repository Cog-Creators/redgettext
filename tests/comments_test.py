import polib

from redgettext import Options
from tests.utils import FILENAME, get_extractor, get_test_potfile

OPTIONS = Options()
SOURCE = """\
# Translators: comment A1
_('A') + _('B')

# Translators: comment A2
_('A'
# Translators: comment B1
) + _('B')

# Translators: comment A3
_('A') + _(
    # Translators: comment B2
    'B'
)

# Translators: comment A4
_(
# Translators: comment A5
'A') + _('B')

# Translators: comment AM1
_('A'
'multiline'
# Translators: comment B3
) + _('B')

# Translators: comment C
# multi-line
_('C')

# Translators: comment D

# handles whitespace between

# as long as there's no code between

_('D')
"""


def test_comments() -> None:
    extractor = get_extractor(SOURCE, OPTIONS)
    expected = get_test_potfile(
        polib.POEntry(
            msgid="A",
            occurrences=[(FILENAME, 2), (FILENAME, 5), (FILENAME, 10), (FILENAME, 16)],
            comment=(
                "Translators: comment A1\n"
                "Translators: comment A2\n"
                "Translators: comment A3\n"
                "Translators: comment A4\n"
                "Translators: comment A5"
            ),
        ),
        polib.POEntry(
            msgid="B",
            occurrences=[
                (FILENAME, 2),
                (FILENAME, 7),
                (FILENAME, 10),
                (FILENAME, 18),
                (FILENAME, 24),
            ],
            comment="Translators: comment B1\nTranslators: comment B2\nTranslators: comment B3",
        ),
        polib.POEntry(
            msgid="Amultiline",
            occurrences=[(FILENAME, 21)],
            comment="Translators: comment AM1",
        ),
        polib.POEntry(
            msgid="C", occurrences=[(FILENAME, 28)], comment="Translators: comment C\nmulti-line"
        ),
        polib.POEntry(
            msgid="D",
            occurrences=[(FILENAME, 36)],
            comment=(
                "Translators: comment D\n"
                "handles whitespace between\n"
                "as long as there's no code between"
            ),
        ),
    )
    assert str(extractor.potfile_manager.current_potfile) == str(expected)
    assert extractor.potfile_manager.current_potfile == expected
