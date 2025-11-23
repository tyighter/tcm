from json import dumps
import time
from pathlib import Path
from sys import exit as sys_exit
from typing import Any, Iterable, Optional

from modules.Debug import log
from modules.WebInterface import WebInterface


class TautulliInterface(WebInterface):
    """
    This class describes an interface to Tautulli. This interface can
    configure notification agents within Tautulli to enable fast card
    updating/creation.
    """

    """Default configurations for the notification agent(s)"""
    DEFAULT_AGENT_NAME = 'Update TitleCardMaker'
    DEFAULT_SCRIPT_TIMEOUT = 30

    """Agent ID for a custom Script"""
    AGENT_ID = 15


    def __init__(self,
            url: str,
            api_key: str,
            verify_ssl: bool,
            update_script: Path,
            agent_name: str = DEFAULT_AGENT_NAME,
            script_timeout: int = DEFAULT_SCRIPT_TIMEOUT,
            username: Optional[str] = None
        ) -> None:
        """
        Construct a new instance of an interface to Sonarr.

        Args:
            url: The API url communicating with Tautulli.
            api_key: The API key for API requests.
            verify_ssl: Whether to verify SSL requests.

        Raises:
            SystemExit: Invalid Sonarr URL/API key provided.
        """

        # Initialize parent WebInterface
        super().__init__('Tautulli', verify_ssl, cache=False)

        # Get correct URL
        url = url if url.endswith('/') else f'{url}/'
        if url.endswith('/api/v2/'):
            self.url = url
        elif (re_match := self._URL_REGEX.match(url)) is None:
            log.critical(f'Invalid Tautulli URL "{url}"')
            sys_exit(1)
        else:
            self.url = f'{re_match.group(1)}/api/v2/'

        # Base parameters for sending requests to Sonarr
        self.__params = {'apikey': api_key}

        # Query system status to verify connection to Tautulli
        try:
            status = self.get(self.url, self.__params | {'cmd': 'status'})
            if status.get('response', {}).get('result') != 'success':
                log.critical(f'Cannot get Tautulli status - invalid URL/API key')
                sys_exit(1)
        except Exception as e:
            log.critical(f'Cannot connect to Tautulli - returned error: "{e}"')
            sys_exit(1)

        # Store attributes
        self.update_script = update_script
        self.agent_name = agent_name
        self.script_timeout = script_timeout
        self.username = username

        # Warn if invalid timeout was provided
        if self.script_timeout < 0:
            log.error(f'Script timeout must be >= 0 (seconds) - using 0')
            self.script_timeout = 0


    def get_recent_activity(
        self,
        series_names: set[str],
        limit: int = 10,
        days: int = 7,
        username: Optional[str] = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return recent watched and added items filtered to configured series.

        Args:
            series_names: Names of the series present in tv.yml.
            limit: Maximum number of results per category to return.
            days: Restrict results to activity that occurred within this many days.

        Returns:
            Dictionary containing "watched" and "recently_added" lists with
            normalized episode metadata.
        """

        limit = max(0, limit)
        if limit == 0:
            return {"watched": [], "recently_added": []}

        cutoff = max(0, int(time.time() - max(0, days) * 24 * 60 * 60))
        filter_username = (username or self.username or "").casefold()

        def _matches_username(entry: dict[str, Any]) -> bool:
            if not filter_username:
                return True

            for key in ("username", "friendly_name", "user"):
                value = entry.get(key)
                if value is None:
                    continue
                try:
                    if str(value).casefold() == filter_username:
                        return True
                except Exception:
                    continue
            return False

        def _timestamp(entry: dict, fields: Iterable[str]) -> int:
            for field in fields:
                value = entry.get(field)
                if value is None:
                    continue
                try:
                    return int(value)
                except (TypeError, ValueError):
                    continue
            return 0

        def _season_label(entry: dict) -> str:
            if (season := entry.get('season')):
                return f'Season {season}'
            return entry.get('parent_title', '') or ''

        def _episode_title(entry: dict) -> str:
            return entry.get('title') or entry.get('episode_title') or entry.get('full_title') or ''

        def _normalize(
            entries: list[dict],
            timestamp_fields: Iterable[str],
            apply_user_filter: bool = True,
        ) -> list[dict[str, Any]]:
            series_lookup = {name.casefold() for name in series_names if name}
            results: list[dict[str, Any]] = []
            for entry in entries:
                if apply_user_filter and not _matches_username(entry):
                    continue

                series = (
                    entry.get('grandparent_title')
                    or entry.get('parent_title')
                    or entry.get('title')
                    or ''
                )
                if not series or series.casefold() not in series_lookup:
                    continue

                timestamp = _timestamp(entry, timestamp_fields)
                if timestamp < cutoff:
                    continue

                results.append(
                    {
                        'series': series,
                        'episode': _episode_title(entry),
                        'season': _season_label(entry),
                        'timestamp': timestamp,
                    }
                )

            results.sort(key=lambda entry: entry.get('timestamp', 0), reverse=True)
            return results[:limit]

        history_params = self.__params | {
            'cmd': 'get_history',
            'media_type': 'episode',
            'order_dir': 'desc',
            'order_column': 'date',
            'length': limit * 10,
        }
        history_response = self.get(self.url, history_params)
        history_entries = history_response.get('response', {}).get('data', {}).get('data', [])
        if not isinstance(history_entries, list):
            history_entries = []

        recently_added_params = self.__params | {
            'cmd': 'get_recently_added',
            'media_type': 'episode',
            'order_dir': 'desc',
            'length': limit * 10,
        }
        recently_added_response = self.get(self.url, recently_added_params)
        recently_added_entries = recently_added_response.get('response', {}).get('data', {})
        if isinstance(recently_added_entries, dict):
            recently_added_entries = recently_added_entries.get('recently_added', [])
        if not isinstance(recently_added_entries, list):
            recently_added_entries = []

        return {
            'watched': _normalize(
                history_entries,
                ('watched_at', 'date', 'started', 'last_played'),
                apply_user_filter=True,
            ),
            'recently_added': _normalize(
                recently_added_entries,
                ('added_at', 'date', 'added'),
                apply_user_filter=False,
            ),
        }


    def get_users(self) -> list[dict[str, Any]]:
        """Return a list of Plex users configured in Tautulli."""

        response = self.get(self.url, self.__params | {'cmd': 'get_users'})
        data = response.get('response', {}).get('data', [])

        raw_entries = []
        if isinstance(data, list):
            raw_entries = data
        elif isinstance(data, dict):
            if isinstance(data.get('users'), list):
                raw_entries = data.get('users', [])
            elif isinstance(data.get('data'), list):
                raw_entries = data.get('data', [])

        users: list[dict[str, Any]] = []
        for entry in raw_entries:
            if not isinstance(entry, dict):
                continue

            username = entry.get('username') or entry.get('user') or entry.get('friendly_name')
            if username is None:
                continue

            users.append(
                {
                    'id': entry.get('user_id') or entry.get('id'),
                    'username': str(username),
                    'friendly_name': entry.get('friendly_name') or str(username),
                }
            )

        return users


    def is_integrated(self) -> tuple[bool, bool]:
        """
        Check if this interface's Tautulli instance already has
        integration set up.

        Returns:
            Tuple of booleans. First value is True if the watched agent
            is already integrated (False otherwise); second value is
            True if the newly added agent is already integrated (False
            otherwise).
        """

        # Get all notifiers
        response = self.get(self.url, self.__params | {'cmd': 'get_notifiers'})
        notifiers = response['response']['data']

        # Check each agent's name
        watched_integrated, created_integrated = False, False
        for agent in notifiers:
            # Exit loop if both agents found
            if watched_integrated and created_integrated:
                break

            # If agent is a Script with the right name..
            if (agent['agent_label'] == 'Script'
                and agent['friendly_name'].startswith(self.agent_name)):
                # Get the config of this agent, check action flags
                params = self.__params | {'cmd': 'get_notifier_config',
                                          'notifier_id': agent['id']}
                response = self.get(self.url, params)['response']['data']
                if response['actions']['on_watched'] == 1:
                    watched_integrated = True
                if response['actions']['on_created'] == 1:
                    created_integrated = True

        return watched_integrated, created_integrated


    def __create_agent(self) -> Optional[int]:
        """
        Create a new Notification Agent.

        Returns:
            Notifier ID of created agent, None if agent was not created.
        """

        # Get all existing notifier ID's
        response = self.get(self.url, self.__params | {'cmd': 'get_notifiers'})
        existing_ids = {agent['id'] for agent in response['response']['data']}

        # Create new notifier
        params = {'cmd': 'add_notifier_config', 'agent_id': self.AGENT_ID}
        self.get(self.url,  self.__params | params)

        # Get notifier ID's after adding new one
        response = self.get(self.url, self.__params | {'cmd': 'get_notifiers'})
        new_ids = {agent['id'] for agent in response['response']['data']}

        # If no new ID's are returned
        if len(new_ids - existing_ids) == 0:
            log.error(f'Failed to create new notification agent on Tautulli')
            return None

        # Get ID of created notifier
        return list(new_ids - existing_ids)[0]


    def integrate(self) -> None:
        """
        Integrate this interface's instance of Tautulli with TCM. This
        configures a new notification agent if a valid one does not
        exist or cannot be identified.
        """

        # If already integrated, skip
        watched_integrated, created_integrated = self.is_integrated()
        if watched_integrated and created_integrated:
            log.debug('Tautulli integrated detected')
            return None

        # Integrate watched agent if required
        if (not watched_integrated
            and (watched_id := self.__create_agent()) is not None):
            # Conditions for watched agent
            # Always add condition for the episode
            conditions = [{
                'parameter': 'media_type',
                'operator':  'is',
                'value':     ['episode'],
                'type':      'str',
            }]
            # If provided, add condition for username
            if self.username is not None:
                conditions.append({
                    'parameter': 'username',
                    'operator':  'is',
                    'value':     [self.username],
                    'type':      'str',
                })

            # Configure this agent
            friendly_name = f'{self.agent_name} - Watched'
            params = self.__params | {
                # API arguments
                'cmd': 'set_notifier_config',
                'notifier_id': watched_id,
                'agent_id': self.AGENT_ID,
                # Configuration
                'friendly_name': friendly_name,
                'scripts_script_folder': str(self.update_script.parent.resolve()),
                'scripts_script': str(self.update_script.resolve()),
                'scripts_timeout': self.script_timeout,
                # Triggers
                'on_watched': 1,
                # Conditions
                'custom_conditions': dumps(conditions),
                # Arguments
                'on_watched_subject': '{rating_key}',
            }
            self.get(self.url, params)
            log.info(f'Creatd and configured Tautulli notification agent '
                     f'{watched_id} ("{friendly_name}")')

        # Integrate created agent if required
        if (not created_integrated
            and (created_id := self.__create_agent()) is not None):
            # Conditions for new content is just a show/season/episode
            conditions = [{
                'parameter': 'media_type',
                'operator':  'is',
                'value':     ['show', 'season', 'episode'],
                'type':      'str',
            }]

            # Configure this agent
            friendly_name = f'{self.agent_name} - Recently Added'
            params = self.__params | {
                # API arguments
                'cmd': 'set_notifier_config',
                'notifier_id': created_id,
                'agent_id': self.AGENT_ID,
                # Configuration
                'friendly_name': friendly_name,
                'scripts_script_folder': str(self.update_script.parent.resolve()),
                'scripts_script': str(self.update_script.resolve()),
                'scripts_timeout': self.script_timeout,
                # Triggers
                'on_created': 1,
                # Conditions
                'custom_conditions': dumps(conditions),
                # Arguments
                'on_created_subject': '{rating_key}',
            }
            self.get(self.url, params)
            log.info(f'Created and configured Tautulli notification agent '
                     f'{created_id} ("{friendly_name}")')

        return None
