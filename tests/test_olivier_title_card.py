from pathlib import Path

from modules.cards.OlivierTitleCard import OlivierTitleCard


class FakeImageMagick:
    """Minimal ImageMagick replacement for text measurement/escaping."""

    @staticmethod
    def escape_chars(string):
        if string is None:
            return None

        for char in ('\\', '"', '`', '%'):
            string = string.replace(char, f'\\{char}')
        return string

    @staticmethod
    def get_text_dimensions(command):
        label_command = next((part for part in command if part.startswith('label:')), 'label:""')
        text = label_command.split('label:"', 1)[1].rstrip('"')
        width = float(len(text) * 10)
        return width, 10.0


def test_olivier_spacing_offset_respects_multiple_spaces():
    card = OlivierTitleCard(
        source_file=Path('source.png'),
        card_file=Path('out.png'),
        title_text='Title',
        episode_text='Episode:   One',
        image_magick=FakeImageMagick(),
    )

    expected_prefix_width = len('Episode:') * 10
    expected_spacing_width = len('   ') * 10

    assert card.episode_text_spacing == '   '
    assert card.episode_text_offset == expected_prefix_width + expected_spacing_width
