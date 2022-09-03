import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import libcst as cst
from libcst.metadata import PositionProvider
import polib


# performance boost + support for Python 3.10 and 3.11 syntax
os.environ["LIBCST_PARSER_TYPE"] = "native"

__version__ = "4.0.0"

CLASS_DECORATOR_NAMES = ("cog_i18n",)
FUNCTION_DECORATOR_NAMES = ("command", "group")
DEFAULT_KEYWORDS = ["_"]


class POTFileManager:
    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self._potfiles: Dict[Path, polib.POFile] = {}
        self.current_infile: Optional[Path] = None
        self._current_outfile: Optional[Path] = None
        self.current_potfile: Optional[polib.POFile] = None

    def set_current_file(self, path: Path) -> None:
        opts = self.options
        self.current_infile = path
        if opts.relative_to_cwd:
            current_dir = Path()
        else:
            current_dir = path.parent
        self._current_outfile = current_dir / opts.output_dir / opts.output_filename
        if self._current_outfile not in self._potfiles:
            self.current_potfile = polib.POFile()
            self._potfiles[self._current_outfile] = self.current_potfile
            self.current_potfile.metadata = {
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
        for outfile_path, potfile in self._potfiles.items():
            if not potfile and self.options.omit_empty:
                continue
            outfile_path.parent.mkdir(parents=True, exist_ok=True)
            potfile.sort(key=lambda e: e.occurrences[0])
            potfile.save(str(outfile_path))

    def add_entry(
        self,
        msgid: str,
        *,
        lineno: int,
        is_docstring: bool = False,
    ) -> None:
        if self.current_potfile is None:
            raise RuntimeError("There's no pot file set.")

        occurrence = (str(self.current_infile), lineno)

        if not msgid:
            print(
                f"{occurrence[0]}:{occurrence[1]}: warning: Empty msgid. Empty msgid is reserved"
                ' - gettext("") call returns po file metadata, not the empty string.',
                file=sys.stderr,
            )
            return

        entry = self.current_potfile.find(msgid)
        if is_docstring:
            flags = ["docstring"]
        else:
            flags = []
        if entry is None:
            self.current_potfile.append(
                polib.POEntry(
                    msgid=msgid,
                    occurrences=[occurrence],
                    flags=flags,
                )
            )
        else:
            if not entry.flags:
                entry.flags = flags
            entry.occurrences.append(occurrence)
            entry.occurrences.sort()


class MessageExtractor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    module: cst.Module

    def __init__(self, potfile_manager: POTFileManager) -> None:
        self.potfile_manager = potfile_manager
        self.options = potfile_manager.options

    def get_literal_string(
        self, node: cst.BaseExpression
    ) -> Union[cst.SimpleString, cst.ConcatenatedString, None]:
        if not isinstance(node, (cst.SimpleString, cst.ConcatenatedString)):
            return None
        # concatenated string may be None if some part of it is an f-string
        if node.evaluated_value is None:
            return None
        return node

    def get_docstring_node(
        self, node: Union[cst.Module, cst.ClassDef, cst.FunctionDef]
    ) -> Union[cst.SimpleString, cst.ConcatenatedString, None]:
        body = node.body
        expr: cst.BaseSuite | cst.BaseStatement | cst.BaseSmallStatement
        if isinstance(body, Sequence):
            if not body:
                return None
            expr = body[0]
        else:
            expr = body

        while isinstance(expr, (cst.BaseSuite, cst.SimpleStatementLine)):
            if not expr.body:
                return None
            expr = expr.body[0]
        if not isinstance(expr, cst.Expr):
            return None

        return self.get_literal_string(expr.value)

    def print_error(self, starting_node: cst.CSTNode, message: str) -> None:
        file = self.potfile_manager.current_infile
        lineno = self.get_metadata(PositionProvider, starting_node).start.line
        code = self.module.code_for_node(starting_node)
        print(f"*** {file}:{lineno}: {message}:\n{code}", file=sys.stderr)

    def visit_Call(self, node: cst.Call) -> None:
        if type(node.func) is cst.Name:
            if node.func.value not in self.options.keywords:
                return
        elif type(node.func) is cst.Attribute:
            if node.func.attr.value not in self.options.keywords:
                return
        else:
            return

        if len(node.args) != 1:
            self.print_error(
                node, "Seen unexpected amount of positional arguments in gettext call"
            )
            return
        arg = node.args[0]
        # argument needs to be positional
        if arg.keyword is not None:
            self.print_error(node, "Seen unexpected keyword arguments in gettext call")
            return
        if arg.star:
            self.print_error(
                node, "Seen unexpected variadic positional argument (*args) in gettext call"
            )
            return

        string_node = self.get_literal_string(arg.value)
        if string_node is not None:
            self.add_entry(string_node, starting_node=node)
        else:
            self.print_error(node, "Seen unexpected argument type in gettext call")

    def visit_Module(self, node: cst.Module) -> None:
        self.module = node
        if not self.options.docstrings:
            return

        docstring_node = self.get_docstring_node(node)
        if docstring_node is not None:
            self.add_entry(docstring_node, is_docstring=True)

    def visit_ClassDef(self, node: cst.ClassDef) -> None:
        self.handle_class_or_function(node)

    def visit_FunctionDef(self, node: cst.FunctionDef) -> None:
        self.handle_class_or_function(node)

    def handle_class_or_function(self, node: Union[cst.ClassDef, cst.FunctionDef]) -> None:
        if self.options.docstrings:
            pass
        elif self.options.cmd_docstrings:
            if isinstance(node, cst.ClassDef):
                decorator_names = CLASS_DECORATOR_NAMES
            else:
                decorator_names = FUNCTION_DECORATOR_NAMES

            for decorator in node.decorators:
                # @deco_name is not valid, it needs to be a call: @deco_name(...)
                deco = decorator.decorator
                if type(deco) is not cst.Call:
                    continue
                if type(deco.func) is cst.Name:
                    if deco.func.value in decorator_names:
                        break
                elif type(deco.func) is cst.Attribute:
                    # in `a.b.c()`, only `c` is checked
                    if deco.func.attr.value in decorator_names:
                        break
            else:
                return
        else:
            return

        docstring_node = self.get_docstring_node(node)
        if docstring_node is not None:
            self.add_entry(docstring_node, is_docstring=True)

    def add_entry(
        self,
        node: Union[cst.SimpleString, cst.ConcatenatedString],
        *,
        starting_node: Optional[cst.CSTNode] = None,
        is_docstring: bool = False,
    ) -> None:
        evaluated_value = node.evaluated_value
        if evaluated_value is None:
            return
        if starting_node is None:
            starting_node = node
        self.potfile_manager.add_entry(
            evaluated_value,
            lineno=self.get_metadata(PositionProvider, starting_node).start.line,
            is_docstring=is_docstring,
        )


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
        type=Path,
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
        help="Empty .pot files will not be outputted.",
    )
    parser.add_argument(
        "--output-dir",
        "-O",
        type=Path,
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
        help=("For directories passed as input, recurse through subdirectories as well."),
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

    all_infiles: List[Path] = []
    path: Path
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
            excluded_files = set(Path().glob(glob))
            all_infiles = [f for f in all_infiles if f not in excluded_files]

    # slurp through all the files
    potfile_manager = POTFileManager(options)
    for path in all_infiles:
        if options.verbose:
            print(f"Working on {path}")
        with path.open("rb") as fp:
            potfile_manager.set_current_file(path)
            try:
                module = cst.parse_module(fp.read())
            except cst.ParserSyntaxError as exc:
                print(f"{path}:", str(exc), file=sys.stderr)
            else:
                wrapper = cst.MetadataWrapper(module, unsafe_skip_copy=True)
                visitor = MessageExtractor(potfile_manager)
                wrapper.visit(visitor)

    # write the output
    potfile_manager.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
