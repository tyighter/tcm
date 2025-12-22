from argparse import ArgumentParser, ArgumentTypeError, SUPPRESS
from datetime import datetime
from pathlib import Path
from os import environ
from sys import exit as sys_exit
from re import match
from time import sleep

from modules.Version import Version
from modules import global_objects

try:
    from requests import get
    import schedule

    from modules.Debug import log, apply_no_color_formatter
    from modules.FontValidator import FontValidator
    from modules.PreferenceParser import PreferenceParser
    from modules.RemoteFile import RemoteFile
    from modules.global_objects import set_preference_parser, \
        set_font_validator, set_media_info_set, set_show_record_keeper
    from modules.Manager import Manager
    from modules.MediaInfoSet import MediaInfoSet
    from modules.ShowRecordKeeper import ShowRecordKeeper
except ImportError as e:
    print(f'Required Python packages are missing - execute "pipenv install"')
    print(f'  Specific Error: {e}')
    sys_exit(1)

# Version information
REPO_URL = ('https://api.github.com/repos/'
            'CollinHeist/TitleCardMaker/releases/latest')

# Environment variables
ENV_IS_DOCKER = 'TCM_IS_DOCKER'
ENV_PREFERENCE_FILE = 'TCM_PREFERENCES'
ENV_RUNTIME = 'TCM_RUNTIME'
ENV_FREQUENCY = 'TCM_FREQUENCY'
ENV_MISSING_FILE = 'TCM_MISSING'
ENV_LOG_LEVEL = 'TCM_LOG'

# Default values
DEFAULT_PREFERENCE_FILE = Path(__file__).parent / 'config' / 'preferences.yml'
DEFAULT_MISSING_FILE = Path(__file__).parent / 'missing.yml'
DEFAULT_FREQUENCY = '12h'

# Pseudo-type functions for argument runtime and frequency
def runtime(arg: str) -> dict:
    """Validate the given argument is a valid runtime (e.g. HH:MM)"""
    try:
        hour, minute = map(int, arg.split(':'))
        assert hour in range(0, 24) and minute in range(0, 60)
        return arg
    except Exception as exc:
        raise ArgumentTypeError(f'Invalid time, specify as HH:MM') from exc

def frequency(arg: str) -> dict:
    """Get the frequency dictionary of the given frequency string."""
    try:
        interval, unit = match(r'(\d+)(s|m|h|d|w)', arg).groups()
        interval, unit = int(interval), unit.lower()
        assert interval > 0 and unit in ('s', 'm', 'h', 'd', 'w')
        return {
            'interval': interval,
            'unit': {'s': 'seconds', 'm':'minutes', 'h':'hours', 'd':'days',
                     'w':'weeks'}[unit],
        }
    except Exception as exc:
        raise ArgumentTypeError(f'Invalid frequency, specify as FREQUENCY[unit]'
                                f', i.e. 12h -> 12 hours, 1d -> 1 day') from exc

# Set up argument parser
parser = ArgumentParser(description='Start the TitleCardMaker')
parser.add_argument(
    '-p', '--preferences', '--preference-file',
    type=Path,
    default=environ.get(ENV_PREFERENCE_FILE, DEFAULT_PREFERENCE_FILE),
    metavar='FILE',
    help=f'File to read global preferences from. Environment variable '
         f'{ENV_PREFERENCE_FILE}. Defaults to '
         f'"{DEFAULT_PREFERENCE_FILE.resolve()}"')
parser.add_argument(
    '-r', '--run',
    action='store_true',
    help='Run the TitleCardMaker')
parser.add_argument(
    '-s', '--sync', '--run-sync',
    action='store_true',
    help='Sync from Sonarr/Plex without running')
parser.add_argument(
    '-t', '--runtime', '--time', 
    type=runtime,
    default=environ.get(ENV_RUNTIME, SUPPRESS),
    metavar='HH:MM',
    help=f'When to first run the TitleCardMaker (in 24-hour time). Environment '
         f'variable {ENV_RUNTIME}')
parser.add_argument(
    '-f', '--frequency',
    type=frequency,
    default=environ.get(ENV_FREQUENCY, DEFAULT_FREQUENCY),
    metavar='FREQUENCY[unit]',
    help=f'How often to run the TitleCardMaker. Units can be s/m/h/d/w for '
         f'seconds/minutes/hours/days/weeks. Environment variable '
         f'{ENV_FREQUENCY}. Defaults to "{DEFAULT_FREQUENCY}"')
parser.add_argument(
    '-m', '--missing', '--missing-file',
    type=Path,
    default=environ.get(ENV_MISSING_FILE, DEFAULT_MISSING_FILE),
    metavar='FILE',
    help=f'File to write the list of missing assets to. Environment variable '
         f'{ENV_MISSING_FILE}. Defaults to "{DEFAULT_MISSING_FILE.resolve()}"')
parser.add_argument(
    '-l', '--log',
    choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
    default=environ.get(ENV_LOG_LEVEL, 'INFO'),
    help=f'Level of logging verbosity to use. Environment variable '
         f'{ENV_LOG_LEVEL}. Defaults to "INFO"')
parser.add_argument(
    '-nc', '--no-color',
    action='store_true',
    help='Omit color from all print messages')
# Parse given arguments
args = parser.parse_args()
is_docker = environ.get(ENV_IS_DOCKER, 'false').lower() == 'true'

# Set global log level and coloring
log.handlers[0].setLevel(args.log)
if args.no_color:
    apply_no_color_formatter()

# Log parsed arguments
log.debug('Runtime arguments  :')
max_width = max(map(len, vars(args).keys()))
for arg, value in vars(args).items():
    log.debug(f'{arg:>{max_width}} : {value}')

# Check if preference file exists
if not args.preferences.exists():
    log.critical(f'Preference file "{args.preferences.resolve()}" does not exist')
    sys_exit(1)

# Store objects in global namespace
if not (pp := PreferenceParser(args.preferences, is_docker)).valid:
    log.critical(f'Preference file is invalid')
    sys_exit(1)
set_preference_parser(pp)
set_font_validator(FontValidator())
set_media_info_set(MediaInfoSet())
set_show_record_keeper(ShowRecordKeeper(pp.database_directory))


def check_for_update():
    """Check for a new version of TCM."""

    # Make API call to get latest version
    try:
        response = get(REPO_URL, timeout=30)
        available_version = Version(response.json().get('name', '').strip())
        assert response.ok
    except Exception:
        log.debug(f'Failed to check for new version')
    else:
        if available_version > pp.version:
            log.info(f'New version of TitleCardMaker ({available_version}) '
                     f'available')
            if is_docker:
                log.info(f'Update your Docker container')
            else:
                log.info(f'Get the latest version with "git pull origin"')
        else:
            log.debug(f'Latest remote version is {available_version}')


def read_preferences():
    """
    Read the indicated Preferences file, and then update the global
    `PreferenceParser` object.
    """

    # Read the preference file, verify it is valid and exit if not
    if (pp := PreferenceParser(args.preferences, is_docker)).valid:
        set_preference_parser(pp)
    else:
        log.critical(f'Preference file is invalid, not updating preferences')


def run():
    """
    Create and run the Manager object's main loop - e.g.
    `Manager.run()`. This also checks for a new version of TCM.
    """

    # Check for new version
    check_for_update()

    # Re-read preferences
    read_preferences()

    # Reset previously loaded assets
    RemoteFile.reset_loaded_database()
    if global_objects.info_set is not None:
        global_objects.info_set.reset_episode_info()

    # Create Manager, run, and write missing report
    try:
        tcm = Manager()
        tcm.run()
        tcm.report_missing(args.missing)
    except PermissionError as error:
        log.critical(f'Invalid permissions - {error}')
        sys_exit(1)


def first_run() -> schedule.CancelJob:
    """
    First Manager run that schedules subsequent runs and then cancels
    itself.
    """

    run()
    interval, unit = args.frequency['interval'], args.frequency['unit']
    getattr(schedule.every(interval), unit).do(run)
    log.debug(f'Scheduled run() every {interval} {unit}')
    return schedule.CancelJob


# Run immediately if specified
if args.run:
    log.info(f'Starting TitleCardMaker ({pp.version})')
    run()

# Sync if specified
if args.sync:
    # Re-read preferences
    read_preferences()

    # Create Manager, run, and write missing report
    Manager().sync_series_files()

# Schedule first run, which then schedules subsequent runs
if hasattr(args, 'runtime'):
    # Schedule first run
    schedule.every().day.at(args.runtime).do(first_run)
    log.info(f'Starting first run in {schedule.idle_seconds():,.0f} seconds')

# Infinte loop if an infinite argument was indicated
if hasattr(args, 'runtime'):
    while True:
        # Run schedule, sleep until next run
        schedule.run_pending()
        next_run = schedule.next_run().strftime("%H:%M:%S %Y-%m-%d")
        log.info(f'Sleeping until {next_run}')
        sleep(max(0, (schedule.next_run()-datetime.today()).total_seconds()))
