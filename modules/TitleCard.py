from pathlib import Path
from re import match, sub, IGNORECASE

import inspect
import types
from typing import Any, Literal, Optional, TYPE_CHECKING, Union, get_args, get_origin

from modules import global_objects
from modules.BaseCardType import BaseCardType
from modules.CleanPath import CleanPath
from modules.Debug import log
from modules.EpisodeInfo import EpisodeInfo
from modules.SeriesInfo import SeriesInfo

# Built-in BaseCardType classes
from modules.cards.AnimeTitleCard import AnimeTitleCard
from modules.cards.BannerTitleCard import BannerTitleCard
from modules.cards.CalligraphyTitleCard import CalligraphyTitleCard
from modules.cards.ComicBookTitleCard import ComicBookTitleCard
from modules.cards.CutoutTitleCard import CutoutTitleCard
from modules.cards.DividerTitleCard import DividerTitleCard
from modules.cards.FadeTitleCard import FadeTitleCard
from modules.cards.FormulaOneTitleCard import FormulaOneTitleCard
from modules.cards.FrameTitleCard import FrameTitleCard
from modules.cards.GraphTitleCard import GraphTitleCard
from modules.cards.InsetTitleCard import InsetTitleCard
from modules.cards.LandscapeTitleCard import LandscapeTitleCard
from modules.cards.LogoTitleCard import LogoTitleCard
from modules.cards.MarvelTitleCard import MarvelTitleCard
from modules.cards.MusicTitleCard import MusicTitleCard
from modules.cards.NotificationTitleCard import NotificationTitleCard
from modules.cards.OlivierTitleCard import OlivierTitleCard
from modules.cards.OverlineTitleCard import OverlineTitleCard
from modules.cards.PosterTitleCard import PosterTitleCard
from modules.cards.RomanNumeralTitleCard import RomanNumeralTitleCard
from modules.cards.ShapeTitleCard import ShapeTitleCard
from modules.cards.StandardTitleCard import StandardTitleCard
from modules.cards.StarWarsTitleCard import StarWarsTitleCard
from modules.cards.StripedTitleCard import StripedTitleCard
from modules.cards.TextlessTitleCard import TextlessTitleCard
from modules.cards.TintedFrameTitleCard import TintedFrameTitleCard
from modules.cards.TintedGlassTitleCard import TintedGlassTitleCard
from modules.cards.WhiteBorderTitleCard import WhiteBorderTitleCard


if TYPE_CHECKING:
    from modules.Episode import Episode, MultiEpisode
    from modules.ImageMagickInterface import ImageMagickInterface
    from modules.Profile import Profile


class TitleCard:
    """
    This class describes a title card. This class is responsible for
    applying a given profile to the Episode details and initializing a
    CardType with those attributes.

    It also contains the mapping of card type identifier strings to
    their respective CardType classes.
    """

    """Extension of the input source image"""
    INPUT_CARD_EXTENSION = '.jpg'

    """Default extension of the output title card"""
    DEFAULT_CARD_EXTENSION = '.jpg'

    """Default filename format for all title cards"""
    DEFAULT_FILENAME_FORMAT = '{full_name} - S{season:02}E{episode:02}'

    """Default card dimensions"""
    DEFAULT_WIDTH = BaseCardType.WIDTH
    DEFAULT_HEIGHT = BaseCardType.HEIGHT
    DEFAULT_CARD_DIMENSIONS = BaseCardType.TITLE_CARD_SIZE

    """Default card type identifier to utilize if unspecified"""
    DEFAULT_CARD_TYPE = 'standard'

    """Mapping of canonical card type identifiers to CardType classes"""
    BUILTIN_CARD_TYPES = {
        'anime': AnimeTitleCard,
        'banner': BannerTitleCard,
        'calligraphy': CalligraphyTitleCard,
        'comic book': ComicBookTitleCard,
        'cutout': CutoutTitleCard,
        'divider': DividerTitleCard,
        'fade': FadeTitleCard,
        'formula 1': FormulaOneTitleCard,
        'frame': FrameTitleCard,
        'graph': GraphTitleCard,
        'inset': InsetTitleCard,
        'landscape': LandscapeTitleCard,
        'logo': LogoTitleCard,
        'marvel': MarvelTitleCard,
        'music': MusicTitleCard,
        'notification': NotificationTitleCard,
        'olivier': OlivierTitleCard,
        'overline': OverlineTitleCard,
        'poster': PosterTitleCard,
        'roman numeral': RomanNumeralTitleCard,
        'shape': ShapeTitleCard,
        'standard': StandardTitleCard,
        'star wars': StarWarsTitleCard,
        'striped': StripedTitleCard,
        'textless': TextlessTitleCard,
        'tinted frame': TintedFrameTitleCard,
        'tinted glass': TintedGlassTitleCard,
        'white border': WhiteBorderTitleCard,
    }

    """Additional aliases that map to the canonical identifiers"""
    CARD_TYPE_ALIASES = {
        '4x3': 'fade',
        'blurred border': 'tinted frame',
        'generic': 'standard',
        'gundam': 'poster',
        'import': 'textless',
        'ishalioh': 'olivier',
        'musikmann': 'white border',
        'phendrena': 'cutout',
        'photo': 'frame',
        'polygon': 'striped',
        'polymath': 'standard',
        'reality tv': 'logo',
        'roman': 'roman numeral',
        'sherlock': 'tinted glass',
        'spotify': 'music',
    }

    """Mapping of card type identifiers to CardType classes"""
    CARD_TYPES = dict(BUILTIN_CARD_TYPES)
    for alias, target in CARD_TYPE_ALIASES.items():
        CARD_TYPES[alias] = BUILTIN_CARD_TYPES[target]

    __slots__ = ('episode', 'profile', 'converted_title', 'maker', 'file')

    _SIGNATURE_CACHE: dict[type, inspect.Signature] = {}


    _CANONICAL_TEXT_ALIASES: dict[str, tuple[str, ...]] = {
        'episode_title_text': ('title_text',),
        'episode_number_text': ('episode_text',),
        'episode_title_text_format': ('title_text_format',),
        'episode_number_text_format': ('episode_text_format',),
        'episode_number_text_case': ('episode_text_case',),
        'episode_number_text_font_file': ('episode_text_font',),
        'episode_number_text_font_size': ('episode_text_font_size',),
        'episode_number_text_size': ('episode_text_font_size',),
        'episode_number_text_vertical_shift': ('episode_text_vertical_shift',),
        'episode_number_text_stroke_color': (
            'episode_text_stroke_color',
            'episode_stroke_color',
        ),
        'episode_number_text_stroke_width': ('episode_text_stroke_width',),
        'episode_title_text_stroke_color': (
            'episode_title_stroke_color',
            'stroke_color',
        ),
        'episode_title_text_stroke_width': ('episode_title_stroke_width',),
        'episode_title_text_horizontal_offset': ('title_text_margin',),
        'episode_title_text_margin': ('title_text_line_end_offset',),
        'episode_title_text_font_file': ('font_file',),
        'episode_title_text_size': ('font_size',),
        'episode_title_text_color': ('font_color',),
        'episode_title_text_case': ('font_case',),
        'episode_title_text_vertical_shift': ('font_vertical_shift',),
        'episode_title_text_line_spacing': ('font_interline_spacing',),
        'episode_title_text_word_spacing': ('font_interword_spacing',),
        'episode_title_text_kerning': ('font_kerning',),
    }

    _LOGGED_ALIAS_WARNINGS: set[tuple[str, str, str]] = set()


    def __init__(self,
            episode: 'Episode',
            profile: 'Profile',
            title_characteristics: dict,
            image_magick: Optional['ImageMagickInterface'] = None,
            **extra_characteristics,
        ) -> None:
        """
        Constructs a new instance of this class.

        Args:
            episode: The episode whose TitleCard this corresponds to.
            profile: The profile to apply to the creation of this title
                card.
            title_characteristics: Dictionary of characteristics from
                the CardType class for this Episode to pass to
                Title.apply_profile().
            extra_characteristics: Any extra keyword arguments to pass
                directly to the creation of the CardType object.
        """

        # Store this card's associated episode and profile
        self.episode = episode
        self.profile = profile

        # Apply the given profile to the Title
        self.converted_title = episode.episode_info.title.apply_profile(
            profile, **title_characteristics
        )

        # Normalize canonical/legacy text option aliases
        extra_characteristics = self._normalize_text_option_aliases(extra_characteristics)

        # Apply any custom episode text casing if supplied
        episode_text_case = extra_characteristics.get('episode_text_case')

        # Apply any custom title text formatting if supplied
        if 'title_text_format' in extra_characteristics:
            try:
                self.converted_title = extra_characteristics['title_text_format'].format(
                    title_text=self.converted_title,
                    episode_title_text=self.converted_title,
                    **self.episode.episode_info.characteristics,
                    **extra_characteristics,
                )
            except Exception as exc:
                log.error(f'Invalid title text format - {exc}')

        # Initialize this episode's CardType instance
        kwargs = {
            'source_file': episode.source,
            'card_file': episode.destination,
            'title_text': self.converted_title,
            'season_text': profile.get_season_text(
                self.episode.episode_info,
                getattr(self.episode.card_class, 'SEASON_TEXT_FORMATTER', None),
            ),
            'episode_text': profile.get_episode_text(
                self.episode, episode_text_case=episode_text_case
            ),
            'hide_season_text': profile.hide_season_title,
            'blur': episode.blur,
            'grayscale': episode.grayscale,
            'watched': episode.watched,
            'font_replacements': profile.font.replacements,
        } | profile.font.attributes \
          | self.episode.episode_info.indices \
          | extra_characteristics

        if image_magick is not None:
            kwargs['image_magick'] = image_magick

        self._coerce_extra_types(kwargs)

        kwargs = self._filter_kwargs(kwargs)

        try:
            self.maker = self.episode.card_class(**kwargs)
        except Exception as e:
            log.exception(f'Cannot initialize Card for {self.episode} - {e}')
            self.maker = None

        # File associated with this card is the episode's destination
        self.file = episode.destination

    @classmethod
    def normalize_option_keys(cls,
            config_dict: dict[str, Any],
            *,
            scope: str = 'configuration',
        ) -> dict[str, Any]:
        """
        Normalize option aliases so canonical keys always exist.

        Canonical keys always win over legacy aliases. If only a legacy
        key exists, a canonical key is synthesized and a deprecation
        warning is logged once per alias+scope pair.
        """

        normalized = dict(config_dict)

        for canonical_key, legacy_keys in cls._CANONICAL_TEXT_ALIASES.items():
            present_legacy = [key for key in legacy_keys if key in normalized]
            if canonical_key in normalized:
                for legacy_key in present_legacy:
                    cache_key = ('both', scope, f'{legacy_key}->{canonical_key}')
                    if cache_key in cls._LOGGED_ALIAS_WARNINGS:
                        continue
                    cls._LOGGED_ALIAS_WARNINGS.add(cache_key)
                    log.warning(
                        'Both legacy "%s" and canonical "%s" were provided in %s; '
                        'using canonical key.',
                        legacy_key,
                        canonical_key,
                        scope,
                    )
                continue

            if not present_legacy:
                continue

            chosen_legacy = present_legacy[0]
            normalized[canonical_key] = normalized[chosen_legacy]

            cache_key = ('deprecated', scope, f'{chosen_legacy}->{canonical_key}')
            if cache_key in cls._LOGGED_ALIAS_WARNINGS:
                continue
            cls._LOGGED_ALIAS_WARNINGS.add(cache_key)
            log.warning(
                'Deprecated option key "%s" found in %s; use "%s" instead '
                '(migration: %s -> %s).',
                chosen_legacy,
                scope,
                canonical_key,
                chosen_legacy,
                canonical_key,
            )

        return normalized

    @classmethod
    def _normalize_text_option_aliases(cls, extras: dict[str, Any]) -> dict[str, Any]:
        """Map canonical text option names to current constructor argument names."""

        normalized = cls.normalize_option_keys(extras, scope='card extras')

        for key, legacy_keys in cls._CANONICAL_TEXT_ALIASES.items():
            for legacy_key in legacy_keys:
                if key in normalized and legacy_key not in normalized:
                    normalized[legacy_key] = normalized[key]

        for key, value in list(normalized.items()):
            if key.startswith('episode_number_text_') and key not in cls._CANONICAL_TEXT_ALIASES:
                suffix = key.removeprefix('episode_number_text_')
                legacy_key = f'episode_text_{suffix}'
                normalized.setdefault(legacy_key, value)
            elif key.startswith('episode_title_text_') and key not in cls._CANONICAL_TEXT_ALIASES:
                suffix = key.removeprefix('episode_title_text_')
                legacy_key = f'title_text_{suffix}'
                normalized.setdefault(legacy_key, value)

        return normalized

    @classmethod
    def rewrite_option_keys_for_persistence(cls,
            config_dict: dict[str, Any],
            *,
            scope: str = 'configuration',
        ) -> tuple[dict[str, Any], set[str]]:
        """
        Rewrite legacy option keys to canonical keys for persisted YAML.

        This preserves read-time backwards compatibility (legacy keys are still
        accepted), but returns output where canonical keys win and legacy keys
        are removed.

        Returns:
            Tuple of ``(rewritten_config, rewrites)``, where ``rewrites`` is a
            set of ``legacy->canonical`` mapping labels that were applied.
        """

        normalized = cls.normalize_option_keys(config_dict, scope=scope)
        rewritten = dict(normalized)
        rewrites: set[str] = set()

        for canonical_key, legacy_keys in cls._CANONICAL_TEXT_ALIASES.items():
            if canonical_key not in rewritten:
                continue

            for legacy_key in legacy_keys:
                if legacy_key in rewritten:
                    rewritten.pop(legacy_key, None)
                    rewrites.add(f'{legacy_key}->{canonical_key}')

        return rewritten, rewrites


    def _coerce_extra_types(self, kwargs: dict[str, Any]) -> None:
        """Convert extras to expected types based on the card constructor."""

        card_class = self.episode.card_class
        try:
            signature = self._SIGNATURE_CACHE[card_class]
        except KeyError:
            signature = inspect.signature(card_class.__init__)
            self._SIGNATURE_CACHE[card_class] = signature

        for name, param in signature.parameters.items():
            if name not in kwargs or name in ('self', 'preferences'):
                continue

            expected_type = self._expected_type(param)
            if expected_type is None:
                continue

            value = kwargs[name]
            if isinstance(value, expected_type):
                continue

            try:
                kwargs[name] = self._convert_value(value, expected_type)
            except (TypeError, ValueError) as exc:
                log.error(
                    'Invalid value for %s extra "%s": %r (expected %s) - %s',
                    self.episode.card_class.__name__,
                    name,
                    value,
                    expected_type.__name__,
                    exc,
                )
                if param.default is not inspect._empty:
                    kwargs[name] = param.default
                else:
                    kwargs.pop(name)

    @staticmethod
    def _expected_type(param: inspect.Parameter) -> type | None:
        """Determine whether a parameter expects a basic numeric or bool type."""

        if param.default is inspect._empty:
            return None

        candidates: set[type] = set()
        primitives = (int, float, bool)

        def literal_candidate(value: Any) -> type | None:
            if isinstance(value, bool):
                return bool
            if isinstance(value, int):
                return int
            if isinstance(value, float):
                return float
            return None

        def collect(annotation: Any) -> tuple[bool, bool]:
            """
            Collect coercible primitive types.

            Returns:
                Tuple of ``(safe, contributed)``, where ``safe`` indicates the
                annotation is unambiguously primitive-coercible, and
                ``contributed`` indicates at least one primitive type was found.
            """

            if annotation is inspect._empty:
                return True, False

            if annotation in primitives:
                candidates.add(annotation)
                return True, True

            origin = get_origin(annotation)
            if origin is None:
                return False, False

            if origin in (types.UnionType, Union):
                safe = True
                contributed = False
                for arg in get_args(annotation):
                    if arg is type(None):
                        continue
                    arg_safe, arg_contributed = collect(arg)
                    if arg_contributed:
                        contributed = True
                    if not arg_safe or not arg_contributed:
                        safe = False
                if not contributed:
                    return False, False
                return safe, True

            if origin is Literal:
                literal_types = set()
                for value in get_args(annotation):
                    candidate = literal_candidate(value)
                    if candidate is None:
                        return False, False
                    literal_types.add(candidate)
                if not literal_types:
                    return False, False
                candidates.update(literal_types)
                return True, True

            return False, False

        annotation = param.annotation
        safe_annotation, _ = collect(annotation)

        if not safe_annotation:
            return None

        if not candidates and annotation in (inspect._empty, Any) and isinstance(param.default, (int, float, bool)):
            candidates.add(type(param.default))

        if not candidates:
            return None

        if float in candidates:
            return float
        if int in candidates:
            return int
        if bool in candidates:
            return bool

        return None

    def _filter_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Remove extras not supported by the card constructor when needed."""

        signature = inspect.signature(self.episode.card_class.__init__)
        accepts_var_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        )

        if accepts_var_kwargs:
            return kwargs

        supported_keys = {name for name in signature.parameters.keys() if name != 'self'}
        unsupported = set(kwargs.keys()) - supported_keys
        for key in unsupported:
            kwargs.pop(key, None)

        return kwargs

    @staticmethod
    def _convert_value(value: Any, expected_type: type) -> Any:
        """Safely convert extras to the expected primitive type."""

        if expected_type is float:
            return float(value)

        if expected_type is int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return int(float(value))

        if expected_type is bool:
            if isinstance(value, bool):
                return value

            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ('true', '1', 'yes', 'y', 'on'):  # type: ignore[arg-type]
                    return True
                if lowered in ('false', '0', 'no', 'n', 'off'):
                    return False
                raise ValueError(f'Cannot interpret {value!r} as boolean')

            return bool(value)

        raise TypeError(f'Unsupported conversion to {expected_type!r}')


    @staticmethod
    def get_output_filename(
            format_string: str,
            series_info: SeriesInfo,
            episode_info: EpisodeInfo,
            media_directory: Path
        ) -> Path:
        """
        Get the output filename for a title card described by the given
        values.

        Args:
            format_string: Format string that specifies how to construct
                the filename.
            series_info: SeriesInfo for this entry.
            episode_info: EpisodeInfo to get filename of.
            media_directory: Top-level media directory.

        Returns:
            Path for the full title card destination.
        """

        # Get the season folder for this entry's season
        season_folder = global_objects.pp.get_season_folder(
            episode_info.season_number
        )

        # Get filename from the given format string, with illegals removed
        abs_number = episode_info.abs_number
        filename = CleanPath.sanitize_name(
            format_string.format(
                name=series_info.name,
                full_name=series_info.full_name,
                year=series_info.year,
                title=episode_info.title.full_title,
                season=episode_info.season_number,
                episode=episode_info.episode_number,
                abs_number=abs_number if abs_number is not None else 0,
            )
        )

        # Add card extension
        filename += global_objects.pp.card_extension

        return media_directory / season_folder / filename


    @staticmethod
    def get_multi_output_filename(
            format_string: str,
            series_info: SeriesInfo,
            multi_episode: 'MultiEpisode',
            media_directory: Path
        ) -> Path:
        """
        Get the output filename for a title card described by the given
        values, and that represents a range of Episodes (not just one).

        Args:
            format_string: Format string that specifies how to construct
                the filename.
            series_info: Series info for this entry.
            multi_episode: MultiEpisode object to get filename of.
            media_directory: Top-level media directory.

        Returns:
            Path to the full title card destination.
        """

        # If there is an episode key to modify, do so
        if '{episode' in format_string:
            # Replace existing episode number reference with start number
            mod_format_string=format_string.replace('{episode','{episode_start')

            # Episode number formatting with prefix
            episode_text = match(
                r'.*?(e?{episode_start.*?})', mod_format_string, IGNORECASE
            ).group(1)

            # Duplicate episode text format for end text format
            end_episode_text=episode_text.replace('episode_start','episode_end')

            # Range of episode numbers
            range_text = f'{episode_text}-{end_episode_text}'

            # Completely modified format string with keys for start/end episodes
            modified_format_string = sub(
                r'e?{episode_start.*?}', range_text, mod_format_string,
                flags=IGNORECASE
            )
        else:
            # No episode key to modify, format the original string
            modified_format_string = format_string

        # # Get the season folder for these episodes
        season_folder = global_objects.pp.get_season_folder(
            multi_episode.season_number
        )

        # Get filename from the modified format string
        abs_number = multi_episode.episode_info.abs_number
        filename = CleanPath.sanitize_name(
            modified_format_string.format(
                name=series_info.name,
                full_name=series_info.full_name,
                year=series_info.year,
                title=multi_episode.episode_info.title.full_title,
                season=multi_episode.season_number,
                episode_start=multi_episode.episode_start,
                episode_end=multi_episode.episode_end,
                abs_number=abs_number if abs_number is not None else 0,
            )
        )

        # Add card extension
        filename += global_objects.pp.card_extension

        return media_directory / season_folder / filename


    @staticmethod
    def validate_card_format_string(format_string: str) -> bool:
        """
        Return whether the given card filename format string is valid or
        not.

        Args:
            format_string:  Format string being validated.

        Returns:
            True if the given string can be formatted, False otherwise.
        """

        try:
            # Attempt to format using all the standard keys
            format_string.format(
                name='TestName', full_name='TestName (2000)', year=2000,
                season=1, episode=1, title='Episode Title', abs_number=1,
            )
            return True
        except Exception as e:
            # Invalid format string, log
            log.error(f'Card format string is invalid - "{e}"')
            return False


    def create(self, overwrite: bool = False) -> bool:
        """
        Create this title card. If the card already exists, a new one is
        not  created unless overwrite is True. Return whether a card was
        created.

        Returns:
            True if a title card was created, False otherwise.
        """

        # If card is invalid, exit
        if self.maker is None or not self.maker.valid:
            return False

        # If the card already exists, exit unless overwriting
        if self.file.exists():
            if not overwrite:
                return False
            try:
                self.file.unlink()
            except Exception as e:
                log.exception(f'Failed to overwrite card at '
                              f'"{self.file.resolve()}" - {e}')
                return False

        # Create parent folders if necessary for this card
        self.file.parent.mkdir(parents=True, exist_ok=True)

        # Create card
        try:
            self.maker.create()
        except Exception as e:
            log.exception(f'Error encountered while creating card for '
                          f'{self.episode} - {e}')

        # Return whether card creation was successful or not
        if self.file.exists():
            log.debug(f'Created card "{self.file.resolve()}"')
            return True

        # Card doesn't exist, log commands to debug
        log.debug(f'Could not create card "{self.file.resolve()}"')
        self.maker.image_magick.print_command_history()

        return False
