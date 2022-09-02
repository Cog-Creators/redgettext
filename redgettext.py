from __future__ import annotations

import argparse
import ast
import sys
import time
import tokenize
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Union

import polib


__version__ = "4.0.0"

CLASS_DECORATOR_NAMES = ("cog_i18n",)
FUNCTION_DECORATOR_NAMES = ("command", "group")
DEFAULT_KEYWORDS = ["_"]


class Options:
    def __init__(
        self,
        *,
        omit_empty: bool = False,
        keywords: List[str] = DEFAULT_KEYWORDS,
        comment_tag: str = "Translators: ",
        docstrings: bool = False,
        cmd_docstrings: bool = False,
        relative_to_cwd: bool = False,
        output_dir: str = "locales",
        output_filename: str = "messages.pot",
    ) -> None:
        self.omit_empty = omit_empty
        self.keywords = keywords
        self.comment_tag = comment_tag.lstrip()
        self.docstrings = docstrings
        self.cmd_docstrings = cmd_docstrings
        self.relative_to_cwd = relative_to_cwd
        self.output_dir = output_dir
        self.output_filename = output_filename

    @classmethod
    def from_args(cls, namespace: argparse.Namespace) -> Options:
        return cls(
            omit_empty=namespace.omit_empty,
            keywords=namespace.keywords,
            docstrings=namespace.docstrings,
            cmd_docstrings=namespace.cmd_docstrings,
        )


class POTFileManager:
    def __init__(self, options: Options) -> None:
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
            self.current_potfile.metadata = self.get_potfile_metadata()

    @staticmethod
    def get_potfile_metadata() -> Dict[str, str]:
        return {
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
        comment: Optional[str] = None,
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

        comment = comment or ""

        entry = self.current_potfile.find(msgid)
        if is_docstring:
            flags = ["docstring"]
        else:
            flags = []
        if entry is None:
            self.current_potfile.append(
                polib.POEntry(
                    msgid=msgid,
                    comment=comment,
                    occurrences=[occurrence],
                    flags=flags,
                )
            )
        else:
            if not entry.comment:
                entry.comment = comment
            elif comment:
                entry.comment = f"{entry.comment}\n{comment}"
            if not entry.flags:
                entry.flags = flags
            entry.occurrences.append(occurrence)
            entry.occurrences.sort()


class MessageExtractor(ast.NodeVisitor):
    def __init__(self, source: str, potfile_manager: POTFileManager) -> None:
        self.source = source
        self.potfile_manager = potfile_manager
        self.options = potfile_manager.options
        # {line_number: comment contents}
        self.translator_comments: Dict[int, str] = {}

    def collect_comments(self) -> None:
        comment_tag = self.options.comment_tag
        current_comment = []
        for token in tokenize.generate_tokens(StringIO(self.source).readline):
            if token.type == tokenize.COMMENT:
                comment = token.string[1:].strip()
                if current_comment or comment.startswith(comment_tag):
                    current_comment.append(comment)
            elif current_comment and token.type not in (tokenize.NL, tokenize.NEWLINE):
                self.translator_comments[token.start[0]] = "\n".join(current_comment)
                current_comment.clear()

    @classmethod
    def extract_messages(cls, source: str, potfile_manager: POTFileManager) -> MessageExtractor:
        module = ast.parse(source)
        self = cls(source, potfile_manager)
        self.collect_comments()
        self.visit(module)
        file = self.potfile_manager.current_infile
        for lineno in self.translator_comments:
            print(f"{file}:{lineno}: unused translator comment", file=sys.stderr)
        return self

    def get_literal_string(self, node: ast.AST) -> Optional[ast.Constant]:
        if type(node) is ast.Constant and isinstance(node.value, str):
            return node
        else:
            return None

    def get_docstring_node(
        self, node: Union[ast.Module, ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef]
    ) -> Optional[ast.Constant]:
        body = node.body
        if not body:
            return None
        expr = body[0]
        if type(expr) is not ast.Expr:
            return None

        return self.get_literal_string(expr.value)

    def print_error(self, starting_node: ast.AST, message: str) -> None:
        file = self.potfile_manager.current_infile
        code = ast.get_source_segment(self.source, starting_node, padded=True)
        print(f"*** {file}:{starting_node.lineno}: {message}:\n{code}", file=sys.stderr)

    def visit_Call(self, node: ast.Call) -> None:
        if type(node.func) is ast.Name:
            if node.func.id not in self.options.keywords:
                return self.generic_visit(node)
        elif type(node.func) is ast.Attribute:
            if node.func.attr not in self.options.keywords:
                return self.generic_visit(node)
        else:
            return self.generic_visit(node)

        if len(node.args) != 1:
            self.print_error(
                node, "Seen unexpected amount of positional arguments in gettext call"
            )
            return self.generic_visit(node)

        if node.keywords:
            self.print_error(node, "Seen unexpected keyword arguments in gettext call")
            return self.generic_visit(node)

        arg = node.args[0]
        string_node = self.get_literal_string(arg)
        if string_node is not None:
            comments = []
            for commentable_node in (node, string_node):
                if commentable_node is not None:
                    comment = self.translator_comments.pop(commentable_node.lineno, None)
                    if comment is not None:
                        comments.append(comment)

            self.add_entry(string_node, comment="\n".join(comments), starting_node=node)
        else:
            self.print_error(node, "Seen unexpected argument type in gettext call")

        return self.generic_visit(node)

    def visit_Module(self, node: ast.Module) -> None:
        if not self.options.docstrings:
            return self.generic_visit(node)

        docstring_node = self.get_docstring_node(node)
        if docstring_node is not None:
            self.add_entry(docstring_node, is_docstring=True)

        return self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.handle_class_or_function(node)
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.handle_class_or_function(node)
        return self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.handle_class_or_function(node)
        return self.generic_visit(node)

    def handle_class_or_function(
        self, node: Union[ast.ClassDef, ast.AsyncFunctionDef, ast.FunctionDef]
    ) -> None:
        if self.options.docstrings:
            pass
        elif self.options.cmd_docstrings:
            if isinstance(node, ast.ClassDef):
                decorator_names = CLASS_DECORATOR_NAMES
            else:
                decorator_names = FUNCTION_DECORATOR_NAMES

            for deco in node.decorator_list:
                # @deco_name is not valid, it needs to be a call: @deco_name(...)
                if type(deco) is not ast.Call:
                    continue
                if type(deco.func) is ast.Name:
                    if deco.func.id in decorator_names:
                        break
                elif type(deco.func) is ast.Attribute:
                    # in `a.b.c()`, only `c` is checked
                    if deco.func.attr in decorator_names:
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
        node: ast.Constant,
        *,
        comment: str = "",
        starting_node: Optional[ast.AST] = None,
        is_docstring: bool = False,
    ) -> None:
        if starting_node is None:
            starting_node = node
        self.potfile_manager.add_entry(
            node.value,
            comment=comment,
            lineno=starting_node.lineno,
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

    args = _parse_args(args)

    # TODO: Make these an option
    args.keywords = DEFAULT_KEYWORDS

    if args.version:
        print(f"redgettext {__version__}")
        return 0

    if not args.infiles:
        print("You must include at least one input file or directory.")
        return 1

    all_infiles: List[Path] = []
    path: Path
    for path in args.infiles:
        if path.is_dir():
            if args.recursive:
                all_infiles.extend(path.glob("**/*.py"))
            else:
                all_infiles.extend(path.glob("*.py"))
        else:
            all_infiles.append(path)

    # filter excluded files
    if args.excluded_files:
        for glob in args.excluded_files:
            excluded_files = set(Path().glob(glob))
            all_infiles = [f for f in all_infiles if f not in excluded_files]

    # slurp through all the files
    options = Options.from_args(args)
    potfile_manager = POTFileManager(options)
    for path in all_infiles:
        if args.verbose:
            print(f"Working on {path}")
        with path.open("r") as fp:
            potfile_manager.set_current_file(path)
            try:
                MessageExtractor.extract_messages(fp.read(), potfile_manager)
            except SyntaxError as exc:
                if exc.text is None:
                    msg = f"{exc.__class__.__name__}: {exc}"
                else:
                    msg = "{0.text}\n{1:>{0.offset}}\n{2}: {0}".format(
                        exc, "^", type(exc).__name__
                    )
                print(f"{path}:", msg, file=sys.stderr)

    # write the output
    potfile_manager.write()
    return 0


if __name__ == "__main__":
    sys.exit(main())
