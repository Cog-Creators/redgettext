#! /usr/bin/env python3
# -*- coding: iso-8859-1 -*-
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
import bisect
import pathlib
import sys
import time
import tokenize
from collections import OrderedDict
from typing import Any, Callable, Dict, List, NamedTuple, Optional, TextIO, Tuple

__version__ = "2.1"

DEFAULT_KEYWORDS = ["_"]

# The normal pot-file header. msgmerge and Emacs's po-mode work better if it's
# there.
POT_HEADER = """\
# SOME DESCRIPTIVE TITLE.
# Copyright (C) YEAR ORGANIZATION
# FIRST AUTHOR <EMAIL@ADDRESS>, YEAR.
#
msgid ""
msgstr ""
"Project-Id-Version: PACKAGE VERSION\\n"
"POT-Creation-Date: %(time)s\\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\\n"
"Language-Team: LANGUAGE <LL@li.org>\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=%(charset)s\\n"
"Content-Transfer-Encoding: %(encoding)s\\n"
"Generated-By: redgettext %(version)s\\n"

"""


ESCAPES = {"\\": r"\\", "\t": r"\t", "\r": r"\r", "\n": r"\n", '"': r"\""}


def escape(s: str) -> str:
    ret = ""
    for char in s:
        if char in ESCAPES:
            char = ESCAPES[char]
        ret += char
    return ret


def is_literal_string(s: str) -> bool:
    return s[0] in "'\"" or (s[0] in "rRuU" and s[1] in "'\"")


def safe_eval(s: str) -> Any:
    # unwrap quotes, safely
    return eval(s, {"__builtins__": {}}, {})


def normalize(s: str) -> str:
    # This converts the various Python string types into a format that is
    # appropriate for .po files, namely much closer to C style.
    lines = s.split("\n")
    if len(lines) == 1:
        s = '"' + escape(s) + '"'
    else:
        if not lines[-1]:
            del lines[-1]
            lines[-1] = lines[-1] + "\n"
        for i in range(len(lines)):
            lines[i] = escape(lines[i])
        line_term = '\\n"\n"'
        s = '""\n"' + line_term.join(lines) + '"'
    return s


class _MessageContextEntry(NamedTuple):
    file: pathlib.Path
    lineno: int
    is_docstring: bool

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, _MessageContextEntry):
            raise TypeError(f"Cannot compare with type {type(other)!r}")
        if self.file == other.file:
            return self.lineno < other.lineno
        else:
            return self.file < other.file

    def __gt__(self, other: Any) -> bool:
        return not self <= other


_MsgIDDict = Dict[str, List[_MessageContextEntry]]


class TokenEater:
    def __init__(self, options: argparse.Namespace):
        self.__options: argparse.Namespace = options
        self.__messages: Dict[pathlib.Path, _MsgIDDict] = {}
        self.__state: Callable[[int, str, int], None] = self.__waiting
        self.__data: List[Any] = []
        self.__lineno: int = -1
        self.__fresh_module: bool = True
        self.__cur_infile: Optional[pathlib.Path] = None
        self.__cur_outfile: Optional[pathlib.Path] = None
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

    def __waiting(self, ttype: int, string: str, lineno: int) -> None:
        opts = self.__options
        # Do docstring extractions, if enabled
        if opts.docstrings:
            # module docstring?
            if self.__fresh_module:
                if ttype == tokenize.STRING and is_literal_string(string):
                    self.__add_entry(safe_eval(string), lineno, is_docstring=True)
                    self.__fresh_module = False
                elif ttype not in (tokenize.COMMENT, tokenize.NL):
                    self.__fresh_module = False
            # class or method docstring?
            elif ttype == tokenize.NAME and string in ("class", "def"):
                self.__state = self.__suite_seen
        # cog or command docstring?
        elif opts.cmd_docstrings and ttype == tokenize.OP and string == "@":
            self.__state = self.__decorator_seen
        elif ttype == tokenize.NAME and string in opts.keywords:
            self.__state = self.__keyword_seen

    # noinspection PyUnusedLocal
    def __decorator_seen(self, ttype: int, string: str, lineno: int) -> None:
        # skip over any enclosure pairs until we see the colon
        if ttype == tokenize.NAME and string in ("command", "group", "cog_i18n"):
            self.__state = self.__suite_seen
        elif ttype == tokenize.NEWLINE:
            self.__state = self.__waiting

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

        entry = _MessageContextEntry(self.__cur_infile, lineno, is_docstring)
        # noinspection PyUnusedLocal
        msgid_dict: _MsgIDDict
        if self.__cur_outfile in self.__messages:
            msgid_dict = self.__messages[self.__cur_outfile]
        else:
            self.__messages[self.__cur_outfile] = msgid_dict = {}

        if msg in msgid_dict:
            bisect.insort(msgid_dict[msg], entry)
        else:
            msgid_dict[msg] = [entry]

    def set_cur_file(self, path: pathlib.Path) -> None:
        opts = self.__options
        self.__cur_infile = path
        if opts.relative_to_cwd:
            cur_dir = pathlib.Path()
        else:
            cur_dir = path.parent
        self.__cur_outfile = cur_dir / opts.output_dir / opts.output_filename
        self.__fresh_module = True

    def write(self) -> None:
        time_str = time.strftime("%Y-%m-%d %H:%M%z")
        for outfile_path, msgid_dict in self.__messages.items():
            outfile_path.parent.mkdir(parents=True, exist_ok=True)
            with outfile_path.open("w", encoding="utf-8") as fp:
                self.__write_outfile(fp, msgid_dict, time_str)

    def __write_outfile(self, fp: TextIO, msgid_dict: _MsgIDDict, time_str: str):
        opts = self.__options
        print(
            POT_HEADER
            % {
                "time": time_str,
                "version": __version__,
                "charset": "UTF-8",
                "encoding": "8bit",
            },
            file=fp,
        )

        # Sort the entries.
        # The entry lists for each msgid are already sorted,
        # so we'll just sort by the first entry in each list
        try:
            sorted_msgid_items: List[Tuple[str, _MessageContextEntry]] = sorted(
                msgid_dict.items(), key=lambda tup: tup[1][0]
            )
        except TypeError:
            print(msgid_dict)
            sys.exit(1)
        msgid_dict = OrderedDict(sorted_msgid_items)
        for msgid, entry_list in msgid_dict.items():
            if opts.include_context:
                # Add the reference comment.
                # Fit as many locations on one line, as long as the
                # resulting line length doesn't exceed 'options.width'.
                loc_line = "#:"
                for entry in entry_list:
                    ref = f" {entry.file}:{entry.lineno}"
                    if len(loc_line) + len(ref) <= opts.width:
                        loc_line = loc_line + ref
                    else:
                        print(loc_line, file=fp)
                        loc_line = "#:" + ref
                if len(loc_line) != "#:":
                    print(loc_line, file=fp)

                # If the entry was gleaned out of a docstring, then add a
                # comment stating so. This is to aid translators who may wish
                # to skip translating some unimportant docstrings.
                # We're assuming that if one entry was a docstring, then all
                # other entries of the same msgid are docstrings too.
                if any(e.is_docstring for e in entry_list):
                    print("#, docstring", file=fp)

            print("msgid", normalize(msgid), file=fp)
            print('msgstr ""\n', file=fp)


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
        help=(
            "Exclude a glob of files from the list of `infiles`. These excluded files "
            "will not be worked on. This pattern is treated as relative to the current "
            "working directory."
        )
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
        excluded_files = set(pathlib.Path().glob(options.excluded_files))
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
