from pathlib import Path

from yaml import dump

from modules.Debug import log
from modules.FontValidator import FontValidator
from modules.MediaInfoSet import MediaInfoSet
from modules.PreferenceParser import PreferenceParser
from modules.global_objects import (
    set_font_validator,
    set_media_info_set,
    set_preference_parser,
)


def _is_font_file_missing(font_path: str) -> bool:
    """Determine whether the provided font file path can be resolved."""

    candidate = Path(font_path)
    if candidate.exists():
        return False

    return len(tuple(candidate.parent.glob(f'{candidate.name}*'))) != 1


def write_missing_font_report(
    preferences_file: Path,
    output_file: Path,
    *,
    is_docker: bool,
) -> None:
    """Write a YAML report of shows that reference missing font files."""

    missing_fonts: dict[str, set[str]] = {}

    parser = PreferenceParser(preferences_file, is_docker)
    if parser.valid:
        set_preference_parser(parser)
        set_font_validator(FontValidator())
        set_media_info_set(MediaInfoSet())

        for show in parser.iterate_series_files():
            font_file = show._base_yaml.get('font', {}).get('file') # pylint: disable=protected-access
            if not isinstance(font_file, str):
                continue

            if _is_font_file_missing(font_file):
                missing_fonts.setdefault(str(show.series_info), set()).add(font_file)
    else:
        log.warning('Writing empty missing font report due to invalid preferences')


    report_data = {
        show: sorted(fonts)
        for show, fonts in sorted(missing_fonts.items(), key=lambda item: item[0])
    }

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open('w', encoding='utf-8') as file_handle:
        dump(report_data, file_handle, allow_unicode=True, width=160)

    log.info(f'Wrote missing font report to "{output_file.resolve()}"')

    return None
