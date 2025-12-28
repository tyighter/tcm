from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import requests
from tinydb import Query, where

from modules import global_objects
from modules.Debug import log
from modules.PersistentDatabase import PersistentDatabase
from modules.SeriesInfo import SeriesInfo
from modules.EpisodeInfo import EpisodeInfo
from modules.WebInterface import WebInterface


class TVDbInterface(WebInterface):
    """
    This class defines an interface to TheTVDB. Once initialized with a
    valid API key, this class can gather episode and series artwork to
    use as source images or backdrops.
    """

    API_URL = 'https://api4.thetvdb.com/v4'
    BLACKLIST_THRESHOLD = 5
    __BLACKLIST_DB = 'tvdb_blacklist.json'

    ARTWORK_PRIORITIES: tuple[str, ...] = (
        'fanart',
        'background',
        'series',
        'season',
        'poster',
        'banner',
        'keyart',
    )

    def __init__(
            self,
            api_key: str,
            language: Optional[str] = None,
            *,
            skip_localized_images: bool = False,
        ) -> None:
        """
        Construct a new instance of an interface to TVDb.

        Args:
            api_key: The API key to communicate with TVDb.
            language: Preferred language for localized images.
            skip_localized_images: Whether to skip localized images and
                prefer originals.
        """

        super().__init__('TVDb', cache=False)
        self.preferences = global_objects.pp
        self.info_set = global_objects.info_set

        self.api_key = api_key
        self.language = language
        self.skip_localized_images = skip_localized_images

        self.__token: Optional[str] = None
        self.__blacklist = PersistentDatabase(self.__BLACKLIST_DB)

        self.__authenticate()

    def __repr__(self) -> str:
        """Returns an unambiguous string representation of the object."""

        return f'<TVDbInterface {self.api_key}>'

    def __authenticate(self) -> None:
        """Authenticate with the TVDb API and set the session token."""

        try:
            response = self.session.post(
                url=f'{self.API_URL}/login',
                json={'apikey': self.api_key},
                timeout=self.REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            token = response.json().get('data', {}).get('token')
            if not token:
                raise ValueError('No token returned from TVDb login')
            self.__token = token
            self.session.headers.update({'Authorization': f'Bearer {token}'})
        except Exception:  # pylint: disable=broad-except
            log.critical('Failed to authenticate with TVDb')
            log.exception('TVDb authentication failure')
            raise

    def __language_priority(self, skip_localized_images: bool) -> list[Optional[str]]:
        """Return languages to attempt in priority order."""

        priority: list[Optional[str]] = []
        if not skip_localized_images and self.language:
            priority.append(self.language)
        priority.append('eng')
        priority.append(None)
        seen: set[Optional[str]] = set()
        ordered: list[Optional[str]] = []
        for lang in priority:
            if lang not in seen:
                seen.add(lang)
                ordered.append(lang)
        return ordered

    def __update_blacklist(
            self,
            series_info: SeriesInfo,
            episode_info: Optional[EpisodeInfo],
            type_: str,
        ) -> None:
        """
        Adds the given request to the blacklist; indicating that this
        request (series, episode, type) has failed.
        """

        next_check = datetime.now() + timedelta(days=1)
        episode_key = episode_info.index if episode_info else None

        condition = (
            (Query().series == series_info.full_name)
            & (where('episode') == episode_key)
            & (where('type') == type_)
        )

        entry = self.__blacklist.get(condition)
        failures = entry['failures'] + 1 if entry else 1
        self.__blacklist.upsert({
            'series': series_info.full_name,
            'episode': episode_key,
            'type': type_,
            'failures': failures,
            'next_check': next_check.timestamp(),
        }, condition)

    def __is_blacklisted(
            self,
            series_info: SeriesInfo,
            episode_info: Optional[EpisodeInfo],
            type_: str,
        ) -> bool:
        """Return whether the given request is temporarily or fully blacklisted."""

        entry = self.__blacklist.get(
            (Query().series == series_info.full_name)
            & (where('episode') == (episode_info.index if episode_info else None))
            & (where('type') == type_)
        )

        if not entry:
            return False
        if entry['failures'] > self.preferences.tvdb_retry_count:
            return True
        return datetime.now().timestamp() < entry['next_check']

    def is_permanently_blacklisted(
            self,
            series_info: SeriesInfo,
            episode_info: Optional[EpisodeInfo],
        ) -> bool:
        """Return whether the given entry is permanently blacklisted."""

        entry = self.__blacklist.get(
            (Query().series == series_info.full_name)
            & (where('episode') == (episode_info.index if episode_info else None))
        )

        if not entry:
            return False
        return entry['failures'] > self.preferences.tvdb_retry_count

    def __request(
            self,
            path: str,
            *,
            language: Optional[str] = None,
            params: Optional[dict[str, Any]] = None,
        ) -> dict[str, Any]:
        """Make an authenticated GET request to the TVDb API."""

        headers = {}
        if language:
            headers['Accept-Language'] = language

        try:
            response = self.session.get(
                f'{self.API_URL}{path}',
                headers=headers,
                params=params,
                timeout=self.REQUEST_TIMEOUT,
            )
            if response.status_code == requests.codes.unauthorized:
                self.__authenticate()
                response = self.session.get(
                    f'{self.API_URL}{path}',
                    headers=headers,
                    params=params,
                    timeout=self.REQUEST_TIMEOUT,
                )
            response.raise_for_status()
            return response.json()
        except Exception:  # pylint: disable=broad-except
            log.exception('TVDb request failed for %s', path)
            raise

    @staticmethod
    def __extract_image(data: dict[str, Any]) -> Optional[str]:
        """Extract an image URL from a data object."""

        if not data:
            return None

        for key in ('image', 'image_url', 'filename', 'fileName', 'thumbnail'):
            if image := data.get(key):
                return image
        if (artwork := data.get('artwork')) and isinstance(artwork, Iterable):
            for entry in artwork:
                if isinstance(entry, dict):
                    for key in ('image', 'image_url', 'filename', 'fileName'):
                        if image := entry.get(key):
                            return image
        return None

    def __get_episode_data(
            self,
            episode_id: Optional[int],
            *,
            language: Optional[str],
        ) -> Optional[dict[str, Any]]:
        """Get episode metadata for the given episode ID."""

        if episode_id is None:
            return None

        try:
            return self.__request(
                f'/episodes/{episode_id}',
                language=language,
            ).get('data')
        except Exception:
            return None

    def __get_series_artwork(
            self,
            series_id: Optional[int],
            *,
            language: Optional[str],
        ) -> list[dict[str, Any]]:
        """Get all artworks for the given series."""

        if series_id is None:
            return []

        try:
            response = self.__request(
                f'/series/{series_id}/artworks',
                language=language,
            )
            return response.get('data', [])
        except Exception:
            return []

    def __select_artwork(self, artworks: Iterable[dict[str, Any]]) -> Optional[str]:
        """Select the preferred artwork from the provided list."""

        for priority in self.ARTWORK_PRIORITIES:
            for art in artworks:
                if not isinstance(art, dict):
                    continue
                if art.get('type') == priority:
                    image = self.__extract_image(art)
                    if image:
                        return image
        return None

    def get_series_backdrop(
            self,
            series_info: SeriesInfo,
            *,
            skip_localized_images: bool = False,
        ) -> Optional[str]:
        """
        Get a backdrop for the requested series.
        """

        if series_info.tvdb_id is None:
            return None

        if self.__is_blacklisted(series_info, None, 'backdrop'):
            return None

        for language in self.__language_priority(skip_localized_images):
            artworks = self.__get_series_artwork(series_info.tvdb_id, language=language)
            image = self.__select_artwork(artworks)
            if image:
                return image

        self.__update_blacklist(series_info, None, 'backdrop')
        return None

    def get_source_image(
            self,
            series_info: SeriesInfo,
            episode_info: EpisodeInfo,
            *,
            skip_localized_images: bool = False,
        ) -> Optional[str]:
        """
        Get the best source image for the requested episode.
        """

        if self.__is_blacklisted(series_info, episode_info, 'image'):
            return None

        if episode_info.tvdb_id is None:
            return None

        for language in self.__language_priority(skip_localized_images):
            episode_data = self.__get_episode_data(
                episode_info.tvdb_id,
                language=language,
            )
            image = self.__extract_image(episode_data or {})
            if image:
                return image

        self.__update_blacklist(series_info, episode_info, 'image')
        return None
