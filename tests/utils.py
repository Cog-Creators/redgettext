from pathlib import Path

import polib

from redgettext import MessageExtractor, Options, POTFileManager

FILENAME = "file.py"


def get_extractor(source: str, options: Options = Options()) -> MessageExtractor:
    potfile_manager = POTFileManager(options)
    potfile_manager.set_current_file(Path(FILENAME))
    return MessageExtractor.extract_messages(source, potfile_manager)


def get_test_potfile(*entries) -> polib.POFile:
    potfile = polib.POFile()
    potfile.metadata = POTFileManager.get_potfile_metadata()
    potfile.extend(entries)
    return potfile
