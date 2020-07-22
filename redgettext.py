#! /usr/bin/env python3
# redgettext was originally forked from version 1.5 of pygettext,
# taken directly from Python Release 3.6.5, by Toby Harradine
# <tobyharradine@gmail.com>
#
# pygettext was originally written by Barry Warsaw <barry@python.org>
#
# Minimally patched to make it even more xgettext compatible
# by Peter Funk <pf@artcom-gmbh.de>
#
# 2002-11-22 Jürgen Hermann <jh@web.de>
# Added checks that _() only contains string literals, and
# command line args are resolved to module lists, i.e. you
# can now pass a filename, a module or package name, or a
# directory (including globbing chars, important for Win32).
# Made docstring fit in 80 chars wide displays using pydoc.
#
# Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008,
# 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017 Python Software
# Foundation; All Rights Reserved

import argparse
import pathlib
import sys
import time
import tokenize
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import polib
except ImportError:
    polib = None

__version__ = "3.3"

DEFAULT_KEYWORDS = ["_"]


def is_literal_string(s: str) -> bool:
    return s[0] in "'\"" or (s[0] in "rRuU" and s[1] in "'\"")


def safe_eval(s: str) -> Any:
    # unwrap quotes, safely
    return eval(s, {"__builtins__": {}}, {})


class TokenEater:
    def __init__(self, options: argparse.Namespace):
        self.__options: argparse.Namespace = options
        self.__state: Callable[[int, str, int], None] = self.__waiting
        self.__data: List[Any] = []
        self.__lineno: int = -1
        self.__fresh_module: bool = True
        self.__cur_infile: Optional[pathlib.Path] = None
        self.__cur_outfile: Optional[pathlib.Path] = None
        self.__potfiles: Dict[pathlib.Path, polib.POFile] = {}
        self.__enclosure_count: int = 0

    def __call__(
        self,
        ttype: int,
        string: str,
        start: Tuple[int, int],
        end: Tuple[int, int],
        line: int,
    ) -> None:
        self.__state(ttype, string, start[0])

    @property
    def __cur_potfile(self) -> polib.POFile:
        return self.__potfiles.get(self.__cur_outfile)

    def __waiting(self, ttype: int, string: str, lineno: int) -> None:
        opts = self.__options
        # Do docstring extractions, if enabled
        if opts.docstrings:
            # module docstring?
            if self.__fresh_module:
                if ttype == tokenize.STRING and is_literal_string(string):
                    self.__add_entry(safe_eval(string), lineno, is_docstring=True)
                    self.__fresh_module = False
                    return
                elif ttype not in (tokenize.COMMENT, tokenize.NL):
                    self.__fresh_module = False
            # class or method docstring?
            elif ttype == tokenize.NAME and string in ("class", "def"):
                self.__state = self.__suite_seen
                return
        # cog or command docstring?
        if opts.cmd_docstrings:
            if ttype == tokenize.OP and string == "@":
                self.__state = self.__decorator_seen
                return
            elif ttype == tokenize.NAME and string == "class":
                self.__state = self.__class_seen
                return
        if ttype == tokenize.NAME and string in opts.keywords:
            self.__state = self.__keyword_seen

    # noinspection PyUnusedLocal
    def __decorator_seen(self, ttype: int, string: str, lineno: int) -> None:
        # Look for the @command(), @group() or @cog_i18n() decorators
        if ttype == tokenize.NAME and string in ("command", "group", "cog_i18n"):
            self.__state = self.__suite_seen
        elif ttype == tokenize.NEWLINE:
            self.__state = self.__waiting

    # noinspection PyUnusedLocal
    def __class_seen(self, ttype: int, string: str, lineno: int) -> None:
        # Look for the `translator` subclass kwarg
        if self.__enclosure_count == 1:
            if ttype == tokenize.NAME and string == "translator":
                self.__state = self.__suite_seen
                return
        if ttype == tokenize.OP:
            if string == ":" and self.__enclosure_count == 0:
                # we see a colon and we're not in an enclosure: end of def/class
                self.__state = self.__waiting
            elif string in "([{":
                self.__enclosure_count += 1
            elif string in ")]}":
                self.__enclosure_count -= 1

    # noinspection PyUnusedLocal
    def __suite_seen(self, ttype: int, string: str, lineno: int) -> None:
        if ttype == tokenize.OP:
            if string == ":" and self.__enclosure_count == 0:
                # we see a colon and we're not in an enclosure: end of def/class
                self.__state = self.__suite_docstring
            elif string in "([{":
                self.__enclosure_count += 1
            elif string in ")]}":
                self.__enclosure_count -= 1

    def __suite_docstring(self, ttype: int, string: str, lineno: int) -> None:
        # ignore any intervening noise
        if ttype == tokenize.STRING and is_literal_string(string):
            self.__add_entry(safe_eval(string), lineno, is_docstring=True)
            self.__state = self.__waiting
        elif ttype not in (tokenize.NEWLINE, tokenize.INDENT, tokenize.COMMENT):
            # there was no class docstring
            self.__state = self.__waiting

    def __keyword_seen(self, ttype: int, string: str, lineno: int) -> None:
        if ttype == tokenize.OP and string == "(":
            self.__data = []
            self.__lineno = lineno
            self.__state = self.__open_seen
        else:
            self.__state = self.__waiting

    # noinspection PyUnusedLocal
    def __open_seen(self, ttype: int, string: str, lineno: int) -> None:
        if ttype == tokenize.OP and string == ")":
            # We've seen the last of the translatable strings.  Record the
            # line number of the first line of the strings and update the list
            # of messages seen.  Reset state for the next batch.  If there
            # were no strings inside _(), then just ignore this entry.
            if self.__data:
                self.__add_entry("".join(self.__data))
            self.__state = self.__waiting
        elif ttype == tokenize.STRING and is_literal_string(string):
            self.__data.append(safe_eval(string))
        elif ttype not in [
            tokenize.COMMENT,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.NEWLINE,
            tokenize.NL,
        ]:
            # warn if we see anything else than STRING or whitespace
            print(
                '*** %(file)s:%(lineno)s: Seen unexpected token "%(token)s"'
                % {"token": string, "file": self.__cur_infile, "lineno": self.__lineno},
                file=sys.stderr,
            )
            self.__state = self.__waiting

    def __add_entry(
        self, msg: str, lineno: Optional[int] = None, is_docstring: bool = False
    ) -> None:
        if lineno is None:
            lineno: int = self.__lineno

        entry = next(
            (entry for entry in self.__cur_potfile if entry.msgid == msg), None
        )
        occurrence = (str(self.__cur_infile), lineno)
        if is_docstring:
            flags = ["docstring"]
        else:
            flags = []
        if entry is None:
            self.__cur_potfile.append(
                polib.POEntry(
                    msgid=msg,
                    occurrences=[occurrence],
                    flags=flags,
                )
            )
        else:
            entry.occurrences.append(occurrence)
            entry.occurrences.sort()

    def set_cur_file(self, path: pathlib.Path) -> None:
        opts = self.__options
        self.__cur_infile = path
        if opts.relative_to_cwd:
            cur_dir = pathlib.Path()
        else:
            cur_dir = path.parent
        self.__fresh_module = True
        self.__cur_outfile = cur_dir / opts.output_dir / opts.output_filename
        if self.__cur_outfile not in self.__potfiles:
            self.__potfiles[self.__cur_outfile] = cur_potfile = polib.POFile()
            cur_potfile.metadata = {
                "Project-Id-Version": "PACKAGE VERSION",
                "POT-Creation-Date": time.strftime("%Y-%m-%d %H:%M%z"),
                "PO-Revision-Date": "YEAR-MO-DA HO:MI+ZONE",
                "Last-Translator": "FULL NAME <EMAIL@ADDRESS>",
                "Language-Team": "LANGUAGE <LL@li.org>",
                "MIME-Version": "1.0",
                "Content-Type": "text/plain; charset=UTF-8",
                "Content-Transfer-Encoding": "8bit",
                "Generated-By": f"redgettext {__version__}",
            }

    def write(self) -> None:
        for outfile_path, potfile in self.__potfiles.items():
            if not potfile and self.__options.omit_empty:
                continue
            outfile_path.parent.mkdir(parents=True, exist_ok=True)
            potfile.sort(key=lambda e: e.occurrences[0])
            potfile.save(str(outfile_path))


def _parse_args(args: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="redgettext",
        description="pygettext for Red-DiscordBot.",
        usage="%(prog)s [OPTIONS] INFILE [INFILE ...]",
    )
    parser.add_argument(
        "infiles",
        nargs="*",
        metavar="INFILE",
        type=pathlib.Path,
        help=(
            "An input file or directory. When a directory is specified, strings "
            "will be extracted from all `.py` submodules. Can be multiple."
        ),
    )
    parser.add_argument(
        "--command-docstrings",
        "-c",
        action="store_true",
        dest="cmd_docstrings",
        help=(
            "Extract all cog and command docstrings. Has no effect when used with the "
            "-D option."
        ),
    )
    parser.add_argument(
        "--docstrings",
        "-D",
        action="store_true",
        help="Extract all module, class, function and method docstrings.",
    )
    parser.add_argument(
        "--exclude-files",
        "-X",
        metavar="PATTERN",
        dest="excluded_files",
        action="append",
        help=(
            "Exclude a glob of files from the list of `infiles`. These excluded files "
            "will not be worked on. This pattern is treated as relative to the current "
            "working directory. You can use this flag multiple times."
        ),
    )
    parser.add_argument(
        "--include-context",
        "-n",
        action="store_true",
        default=True,
        help=(
            "Include contextual comments for msgid entries. This is the default. "
            "Opposite of --no-context."
        ),
    )
    parser.add_argument(
        "--omit-empty",
        action="store_true",
        help="Empty .pot files will not be outputted."
    )
    parser.add_argument(
        "--output-dir",
        "-O",
        type=pathlib.Path,
        metavar="DIR",
        default="locales",
        help=(
            "Output files will be placed in DIR. Default is `locales`. Specify `.` to "
            "output in the same directory."
        ),
    )
    parser.add_argument(
        "--output-filename",
        "-o",
        metavar="FILENAME",
        default="messages.pot",
        help="Rename the default output file from messages.pot to FILENAME.",
    )
    parser.add_argument(
        "--no-context",
        "-N",
        action="store_false",
        dest="include_context",
        help="Don't include contextual comments for msgid entries.",
    )
    parser.add_argument(
        "--recursive",
        "-r",
        action="store_true",
        help=(
            "For directories passed as input, recurse through subdirectories as well."
        ),
    )
    parser.add_argument(
        "--relative-to-cwd",
        "-R",
        action="store_true",
        help=(
            "Output directory will be relative to the current working directory "
            "instead of the directory being translated."
        ),
    )
    parser.add_argument("--verbose", "-v", action="count", help="Be more verbose.")
    parser.add_argument(
        "--version",
        "-V",
        action="store_true",
        help="Print the version of %(prog)s and exit.",
    )
    parser.add_argument(
        "--width",
        "-w",
        type=int,
        metavar="COLUMNS",
        default=79,
        help="Set the width of output to COLUMNS.",
    )

    return parser.parse_args(args)


def main(args: Optional[List[str]] = None) -> int:
    if args is None:
        args = sys.argv[1:]

    options = _parse_args(args)

    # TODO: Make these an option
    options.keywords = DEFAULT_KEYWORDS

    if options.version:
        print(f"redgettext {__version__}")
        return 0

    if not options.infiles:
        print("You must include at least one input file or directory.")
        return 1

    all_infiles: List[pathlib.Path] = []
    # noinspection PyUnusedLocal
    path: pathlib.Path
    for path in options.infiles:
        if path.is_dir():
            if options.recursive:
                all_infiles.extend(path.glob("**/*.py"))
            else:
                all_infiles.extend(path.glob("*.py"))
        else:
            all_infiles.append(path)

    # filter excluded files
    if options.excluded_files:
        for glob in options.excluded_files:
            excluded_files = set(pathlib.Path().glob(glob))
            all_infiles = [f for f in all_infiles if f not in excluded_files]

    # slurp through all the files
    eater = TokenEater(options)
    for path in all_infiles:
        if options.verbose:
            print("Working on %s" % path)
        with path.open("rb") as fp:
            eater.set_cur_file(path)
            try:
                tokens = tokenize.tokenize(fp.readline)
                for _token in tokens:
                    eater(*_token)
            except tokenize.TokenError as e:
                print(
                    "%s: %s, line %d, column %d"
                    % (e.args[0], path, e.args[1][0], e.args[1][1]),
                    file=sys.stderr,
                )

    # write the output
    eater.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
