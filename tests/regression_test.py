from textwrap import dedent

import polib

from redgettext import Options
from tests.utils import FILENAME, get_extractor, get_test_potfile


def test_gettext_call_in_decorator_parameters_issue_6() -> None:
    source = """\
    class MyCog(commands.Cog):
        @app_commands.command(name="command", description=_("English description"))
        async def func(self):
            ...
    """
    extractor = get_extractor(dedent(source), Options())
    assert extractor.potfile_manager.current_potfile == get_test_potfile(
        polib.POEntry(msgid="English description", occurrences=[(FILENAME, 2)])
    )
