from __future__ import annotations

import argparse
import ast
import re
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, NamedTuple, Optional, Union

import polib


__version__ = "4.0.0"

CLASS_DECORATOR_NAMES = ("cog_i18n",)
FUNCTION_DECORATOR_NAMES = ("command", "group")
DEFAULT_KEYWORD_SPECS = (
    "_:1,1t",
    "gettext_noop:1,1t",
    # These should be included in default keywords once support gets added to Red.
    #
    # "ngettext:1,2,3t",
    # "pgettext:1c,2,2t",
    # "npgettext:1c,2,3,4t",
)


def parse_int(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"{text!r} is not a valid integer.") from None


class KeywordInfo(NamedTuple):
    keyword: str
    arg_singular: int = 0
    arg_plural: Optional[int] = None
    arg_context: Optional[int] = None
    total_arg_count: Optional[int] = None
    comment: str = ""

    def __eq__(self, other: KeywordInfo) -> int:
        return self.keyword == other.keyword and self.total_arg_count == other.total_arg_count

    def __hash__(self) -> int:
        return hash((self.keyword, self.total_arg_count))

    @property
    def max_arg_number(self):
        return max(self.arg_singular, self.arg_plural or 0, self.arg_context or 0)

    @classmethod
    def from_spec(cls, keyword_spec: str) -> KeywordInfo:
        keyword, _, arg_info = keyword_spec.partition(":")
        if not arg_info:
            return cls(keyword)

        comments = []
        arg_singular = None
        arg_plural = None
        arg_context = None
        total_arg_count = None

        pos = len(arg_info)
        while (pos := pos - 1) >= 0:
            char = arg_info[pos]
            if char == '"':
                try:
                    start_pos = arg_info.rindex('"', None, pos) + 1
                except ValueError:
                    raise ValueError("Couldn't find starting quote of a comment string.") from None
                comments.append(arg_info[start_pos:pos])
                pos = start_pos - 2
                if pos >= 0 and arg_info[pos] != ",":
                    raise ValueError("Expected a comma before the starting quote.")
                continue

            # position of the first digit of the number
            start_pos = arg_info.rfind(",", None, pos) + 1

            if arg_info[pos] == "t":
                if total_arg_count is not None:
                    raise ValueError("Total argument count can only be specified once.")
                total_arg_count = parse_int(arg_info[start_pos:pos])
            elif arg_info[pos] == "c":
                if arg_context is not None:
                    raise ValueError("There can only be one context argument specified.")
                arg_context = parse_int(arg_info[start_pos:pos]) - 1
            else:
                # increment `pos` to properly include last digit of the number
                pos += 1
                if arg_singular is None:
                    arg_singular = parse_int(arg_info[start_pos:pos]) - 1
                elif arg_plural is None:
                    arg_plural = arg_singular
                    arg_singular = parse_int(arg_info[start_pos:pos]) - 1
                else:
                    raise ValueError("There cannot be more than two normal arguments specified.")

            pos = start_pos - 1

        if arg_singular is None:
            raise ValueError(
                "A singular form argument needs to be specified"
                " when providing an argument specification after the colon."
            )

        args = [arg_singular]
        if arg_plural is not None:
            args.append(arg_plural)
            if arg_plural < 0:
                raise ValueError(
                    "The specified argument number for plural form argument is invalid."
                    " Argument numbers start from 1."
                )
        if arg_singular < 0:
            raise ValueError(
                "The specified argument number for singular form argument is invalid."
                " Argument numbers start from 1."
            )
        if arg_context is not None:
            args.append(arg_context)
            if arg_context < 0:
                raise ValueError(
                    "The specified argument number for context argument is invalid."
                    " Argument numbers start from 1."
                )

        if len(args) != len(set(args)):
            raise ValueError(
                "The same argument number cannot be used for multiple argument types."
            )

        ret = cls(
            keyword=keyword,
            arg_singular=arg_singular,
            arg_plural=arg_plural,
            arg_context=arg_context,
            total_arg_count=total_arg_count,
            comment="\n".join(reversed(comments)),
        )
        if total_arg_count is not None:
            if total_arg_count < 1:
                raise ValueError("The total argument count cannot be lower than 1.")
            if total_arg_count <= ret.max_arg_number:
                raise ValueError(
                    "The total argument count cannot be lower than"
                    " any of the specified argument numbers."
                )

        return ret


def parse_keyword_specs(keyword_specs: Iterable[str]) -> Dict[str, List[KeywordInfo]]:
    parsed = {}
    for keyword_spec in keyword_specs:
        keyword_info = KeywordInfo.from_spec(keyword_spec)
        keywords = parsed.setdefault(keyword_info.keyword, set())
        if keyword_info in keywords:
            keyword = keyword_info.keyword
            total_arg_count = keyword_info.total_arg_count
            if keyword_info.total_arg_count is None:
                raise ValueError(
                    f"A keyword {keyword!r} with no total argument count"
                    " has been specified more than once."
                )
            raise ValueError(
                f"A keyword {keyword!r} with a total argument count {total_arg_count}"
                " has been specified more than once."
            )
        keywords.add(keyword_info)
    return {
        keyword: sorted(keywords, key=lambda ki: (ki.total_arg_count is None, ki.total_arg_count))
        for keyword, keywords in parsed.items()
    }


class Options:
    def __init__(
        self,
        *,
        omit_empty: bool = False,
        keyword_specs: Iterable[str] = DEFAULT_KEYWORD_SPECS,
        comment_tag: str = "Translators: ",
        docstrings: bool = False,
        cmd_docstrings: bool = False,
        relative_to_cwd: bool = False,
        output_dir: str = "locales",
        output_filename: str = "messages.pot",
    ) -> None:
        self.omit_empty = omit_empty
        self.keywords = parse_keyword_specs(keyword_specs)
        self.comment_tag = comment_tag.lstrip()
        self.docstrings = docstrings
        self.cmd_docstrings = cmd_docstrings
        self.relative_to_cwd = relative_to_cwd
        self.output_dir = output_dir
        self.output_filename = output_filename

    @classmethod
    def from_args(cls, namespace: argparse.Namespace) -> Options:
        if namespace.include_default_keywords:
            namespace.keyword_specs.extend(DEFAULT_KEYWORD_SPECS)
        return cls(
            omit_empty=namespace.omit_empty,
            keyword_specs=namespace.keyword_specs,
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
        msgid_plural: Optional[str] = None,
        msgctxt: Optional[str] = None,
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

        msgid_plural = msgid_plural or ""
        msgctxt = msgctxt or None
        comment = comment or ""

        entry = self.current_potfile.find(msgid, msgctxt=msgctxt)
        if is_docstring:
            flags = ["docstring"]
        else:
            flags = []
        if entry is None:
            self.current_potfile.append(
                polib.POEntry(
                    msgid=msgid,
                    msgid_plural=msgid_plural,
                    msgctxt=msgctxt,
                    comment=comment,
                    occurrences=[occurrence],
                    flags=flags,
                )
            )
        else:
            if bool(entry.msgid_plural) != bool(msgid_plural):
                if entry.msgid_plural:
                    singular_occurence = occurrence
                    plural_occurence = entry.occurrences[0]
                else:
                    singular_occurence = entry.occurrences[0]
                    plural_occurence = occurrence
                    entry.msgid_plural = msgid_plural
                print(
                    f"warning: msgid {entry.msgid} is used both with and without plural form:\n"
                    f"  - Example occurrence without plural form: {singular_occurence}\n"
                    f"  - Example occurrence with plural form: {plural_occurence}",
                    file=sys.stderr,
                )
            if not entry.comment:
                entry.comment = comment
            elif comment:
                entry.comment = f"{entry.comment}\n{comment}"
            if not entry.flags:
                entry.flags = flags
            entry.occurrences.append(occurrence)
            entry.occurrences.sort()


class MessageExtractor(ast.NodeVisitor):
    COMMENT_RE = re.compile(r"[\t ]*(#(?P<comment>.*))?")

    def __init__(self, source: str, potfile_manager: POTFileManager) -> None:
        self.source = source
        self.potfile_manager = potfile_manager
        self.options = potfile_manager.options
        # {line_number: comment contents}
        self.translator_comments: Dict[int, str] = {}

    def collect_comments(self) -> None:
        comment_tag = self.options.comment_tag
        current_comment = []
        pattern = self.COMMENT_RE
        for lineno, line in enumerate(self.source.splitlines(), 1):
            if match := pattern.fullmatch(line):
                comment = match["comment"]
                if comment is None:
                    # regex matched a whitespace-only line which we want to ignore
                    continue
                comment = comment.strip()
                # Collect a (potentially first) comment when we're either
                # already collecting comments or we encounter a comment that starts with the tag.
                if current_comment or comment.startswith(comment_tag):
                    current_comment.append(comment)
            # regex doesn't match - this line is neither whitespace nor comment
            elif current_comment:
                # We're currently collecting comments so this is the time to save.
                self.translator_comments[lineno] = "\n".join(current_comment)
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
            keywords = self.options.keywords.get(node.func.id)
            if keywords is None:
                return self.generic_visit(node)
        elif type(node.func) is ast.Attribute:
            keywords = self.options.keywords.get(node.func.attr)
            if keywords is None:
                return self.generic_visit(node)
        else:
            return self.generic_visit(node)

        if node.keywords:
            self.print_error(node, "Seen unexpected keyword arguments in gettext call")
            return self.generic_visit(node)

        try:
            keyword_info = self.get_keyword_info(keywords, node)
        except ValueError:
            self.print_error(
                node, "The gettext call doesn't match any set argument specification."
            )
            return self.generic_visit(node)

        try:
            arg_singular = self.get_literal_string_from_call(node, keyword_info.arg_singular)
            arg_plural = self.get_literal_string_from_call(node, keyword_info.arg_plural)
            arg_context = self.get_literal_string_from_call(node, keyword_info.arg_context)
        except ValueError as exc:
            self.print_error(node, str(exc))
        else:
            comments = []
            for commentable_node in (node, arg_singular, arg_plural, arg_context):
                if commentable_node is not None:
                    comment = self.translator_comments.pop(commentable_node.lineno, None)
                    if comment is not None:
                        comments.append(comment)

            if keyword_info.comment:
                comments.append(keyword_info.comment)

            self.add_entry(
                arg_singular,
                arg_plural,
                arg_context,
                comment="\n".join(comments),
                starting_node=node,
            )

        return self.generic_visit(node)

    def get_keyword_info(self, keywords: List[KeywordInfo], node: ast.Call) -> KeywordInfo:
        for keyword_info in keywords:
            total_arg_count = keyword_info.total_arg_count
            if total_arg_count is not None:
                if len(node.args) != total_arg_count:
                    continue
            elif len(node.args) < keyword_info.max_arg_number:
                continue
            return keyword_info
        raise ValueError("Can't find a matching argument specification.")

    def get_literal_string_from_call(
        self, node: ast.Call, arg_number: Optional[int]
    ) -> ast.Constant:
        if arg_number is None:
            return None
        arg = node.args[arg_number]
        string_node = self.get_literal_string(arg)
        if string_node is not None:
            return string_node
        else:
            raise ValueError(f"Seen unexpected type for argument {arg_number+1} in gettext call")

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
        node_plural: Optional[ast.Constant] = None,
        node_context: Optional[ast.Constant] = None,
        *,
        comment: str = "",
        starting_node: Optional[ast.AST] = None,
        is_docstring: bool = False,
    ) -> None:
        if starting_node is None:
            starting_node = node
        self.potfile_manager.add_entry(
            node.value,
            node_plural and node_plural.value,
            node_context and node_context.value,
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
        "--keyword",
        "-k",
        action="append",
        default=[],
        dest="keyword_specs",
        help=(
            "Specify keyword spec as an additional keyword to be looked for."
            " This follows xgettext's keywordspec format with the exclusion of support for"
            " GNOME glib syntax.\n"
            "To disable default keywords, use `--no-default-keywords` flag."
        ),
    )
    parser.add_argument(
        "--no-default-keywords",
        action="store_false",
        dest="include_default_keywords",
        help="Don't include default keywords.",
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

    try:
        options = Options.from_args(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    potfile_manager = POTFileManager(options)

    # slurp through all the files
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
