import itertools
from typing import Tuple

import polib
import pytest

from redgettext import Options
from tests.utils import FILENAME, get_extractor, get_test_potfile


REAL_DOCSTRINGS = ('"""doc"""', "r'''doc'''", "R'doc'", 'u"doc"', "'d' 'o'\\\n'c'")
FAKE_DOCSTRINGS = ('b"""doc"""', 'f"""doc"""')
CLASS_DECORATORS = ("cog_i18n",)
FUNCTION_DECORATORS = ("command", "group")
INVALID_DECORATORS = ("commands", "staticmethod")

MODULE_TMPL = "{docstring}\n"
ASYNC_FUNCTION_TMPL = """\
async def func(arg1, arg2):
    {docstring}
"""
FUNCTION_TMPL = """\
def func(arg1, arg2):
    {docstring}
"""
CLASS_TMPL = """\
class Example:
    {docstring}
"""
ASYNC_METHOD_TMPL = """\
class Example:
    async def meth(self, arg1, arg2):
        {docstring}
"""
METHOD_TMPL = """\
class Example:
    def meth(self, arg1, arg2):
        {docstring}
"""
COMMAND_ASYNC_FUNCTION_TMPL = """\
@commands.{deco_name}()
async def func(arg1, arg2):
    {docstring}
"""
COMMAND_FUNCTION_TMPL = """\
@commands.{deco_name}()
@asyncio.coroutine
def func(arg1, arg2):
    {docstring}
"""
COMMAND_CLASS_TMPL = """\
@{deco_name}(_)
class Example(commands.Cog):
    {docstring}
"""
COMMAND_ASYNC_METHOD_TMPL = """\
class Example(commands.Cog):
    @commands.{deco_name}()
    async def meth(self, ctx, arg1, arg2):
        {docstring}
"""
COMMAND_METHOD_TMPL = """\
class Example(commands.Cog):
    @commands.{deco_name}()
    @asyncio.coroutine
    def meth(self, ctx, arg1, arg2):
        {docstring}
"""


def generate_code(template: str, lineno: int = 0, **kwargs: Tuple[str]) -> Tuple[str]:
    it = itertools.product(*kwargs.values())
    if not lineno:
        return tuple(template.format(**dict(zip(kwargs, product))) for product in it)
    return tuple((template.format(**dict(zip(kwargs, product))), lineno) for product in it)


class TestDocstrings:
    OPTIONS = Options(docstrings=True)

    @pytest.mark.parametrize(
        "source,lineno",
        (
            *generate_code(MODULE_TMPL, 1, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_FUNCTION_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(FUNCTION_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(CLASS_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_METHOD_TMPL, 3, docstring=REAL_DOCSTRINGS),
            *generate_code(METHOD_TMPL, 3, docstring=REAL_DOCSTRINGS),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                3,
                docstring=REAL_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, 4, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, 3, docstring=REAL_DOCSTRINGS, deco_name=CLASS_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL,
                4,
                docstring=REAL_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, 5, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
        ),
    )
    def test_real_docstrings(self, source: str, lineno: int) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile(
            polib.POEntry(msgid="doc", occurrences=[(FILENAME, lineno)], flags=["docstring"])
        )

    @pytest.mark.parametrize(
        "source",
        (
            *generate_code(MODULE_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(ASYNC_FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(CLASS_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(ASYNC_METHOD_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(METHOD_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                docstring=FAKE_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=CLASS_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
        ),
    )
    def test_fake_docstrings(self, source: str) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()


class TestCommandDocstrings:
    OPTIONS = Options(cmd_docstrings=True)

    @pytest.mark.parametrize(
        "source,lineno",
        (
            *generate_code(MODULE_TMPL, 1, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_FUNCTION_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(FUNCTION_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(CLASS_TMPL, 2, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_METHOD_TMPL, 3, docstring=REAL_DOCSTRINGS),
            *generate_code(METHOD_TMPL, 3, docstring=REAL_DOCSTRINGS),
        ),
    )
    def test_real_non_command_docstrings(self, source: str, lineno: int) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()

    @pytest.mark.parametrize(
        "source,lineno",
        (
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                3,
                docstring=REAL_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, 4, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, 3, docstring=REAL_DOCSTRINGS, deco_name=CLASS_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL,
                4,
                docstring=REAL_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, 5, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
        ),
    )
    def test_real_command_docstrings(self, source: str, lineno: int) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile(
            polib.POEntry(msgid="doc", occurrences=[(FILENAME, lineno)], flags=["docstring"])
        )

    @pytest.mark.parametrize(
        "source",
        (
            *generate_code(MODULE_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(ASYNC_FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(CLASS_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(ASYNC_METHOD_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(METHOD_TMPL, docstring=FAKE_DOCSTRINGS),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                docstring=FAKE_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=CLASS_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                docstring=FAKE_DOCSTRINGS,
                deco_name=INVALID_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, docstring=FAKE_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
        ),
    )
    def test_fake_docstrings(self, source: str) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()


class TestNoDocstrings:
    OPTIONS = Options()

    @pytest.mark.parametrize(
        "source",
        (
            *generate_code(MODULE_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_FUNCTION_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(FUNCTION_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(CLASS_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(ASYNC_METHOD_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(METHOD_TMPL, docstring=REAL_DOCSTRINGS),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                docstring=REAL_DOCSTRINGS,
                deco_name=FUNCTION_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, docstring=REAL_DOCSTRINGS, deco_name=CLASS_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, docstring=REAL_DOCSTRINGS, deco_name=FUNCTION_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_FUNCTION_TMPL,
                docstring=REAL_DOCSTRINGS,
                deco_name=INVALID_DECORATORS,
            ),
            *generate_code(
                COMMAND_FUNCTION_TMPL, docstring=REAL_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_CLASS_TMPL, docstring=REAL_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_ASYNC_METHOD_TMPL, docstring=REAL_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
            *generate_code(
                COMMAND_METHOD_TMPL, docstring=REAL_DOCSTRINGS, deco_name=INVALID_DECORATORS
            ),
        ),
    )
    def test_docstrings(self, source: str) -> None:
        extractor = get_extractor(source, self.OPTIONS)
        assert extractor.potfile_manager.current_potfile == get_test_potfile()
