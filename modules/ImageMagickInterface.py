from os import environ, name as os_name
from pathlib import Path
from random import choices as random_choices
from re import findall
from shlex import split as command_split
from string import hexdigits
from subprocess import Popen, PIPE, TimeoutExpired
from time import monotonic, sleep
from typing import Iterable, Literal, NamedTuple, Optional, overload

try:
    from cairosvg import svg2png
except ModuleNotFoundError:
    svg2png = None
from imagesize import get as im_get

from modules.Debug import log


class Dimensions(NamedTuple): # pylint: disable=missing-class-docstring
    width: float
    height: float


class ImageMagickInterface:
    """
    This class describes an interface to ImageMagick. If initialized
    with a valid docker container (name or ID), then all given
    ImageMagick commands will be run through that docker container.

    If the `TCM_IM_PATH` environment variable is defined, then that is
    assumed to be a path to an ImageMagick executable, which is then
    used for command execution.

    Note: This class does not validate the provided container
    corresponds to a valid ImageMagick container. Commands are passed to
    docker so long as any container name/ID is provided.

    An example command

    >>> docker run --name="ImageMagick" --entrypoint="/bin/bash" \
        -dit -v "/mnt/user/":"/mnt/user/" 'dpokidov/imagemagick'
    """

    """How long to wait before terminating a command as timed out"""
    COMMAND_TIMEOUT_SECONDS = 60

    """Default quality for image creation"""
    DEFAULT_CARD_QUALITY = 95

    """Seconds to aggregate identical timeout log entries"""
    TIMEOUT_AGGREGATION_WINDOW_SECONDS = 45

    """Minimum duplicate count before escalating timeout summary to warning"""
    TIMEOUT_WARNING_THRESHOLD = 5

    """Directory for all temporary images created during image creation"""
    TEMP_DIR = Path(__file__).parent / '.objects'

    """Temporary file location for svg -> png conversion"""
    TEMPORARY_SVG_FILE = TEMP_DIR / 'temp_logo.svg'

    """Characters that must be escaped in commands"""
    __REQUIRED_ESCAPE_CHARACTERS = ('\\', '"', '`', '%')

    """Substrings that must be present in --version output"""
    __REQUIRED_VERSION_SUBSTRINGS = ('Version','Copyright','License','Features')

    __slots__ = (
        'executable', 'container', 'use_docker', 'prefix', 'timeout', '__history',
        '__timeout_count', '__timeout_warning_logged', '__timeout_events',
    )

    TEXT_LOG_PATH = Path('/config/text.log')
    __text_log_initialized = False


    def __init__(self,
            container: Optional[str] = None,
            use_magick_prefix: bool = False,
            timeout: int = COMMAND_TIMEOUT_SECONDS,
        ) -> None:
        """
        Construct a new instance of an interface to ImageMagick.

       Args:
            container: Optional Docker container name/ID to sending
                ImageMagick commands to.
            use_magick_prefix: Whether to use 'magick' command prefix.
            timeout: How many seconds to wait for a command to execute.
        """

        # Definitions of this interface, i.e. whether to use docker and how
        self.container = container
        self.use_docker = bool(container)
        self.executable = environ.get('TCM_IM_PATH', None)

        # Whether to prefix commands with "magick" or not
        self.prefix = 'magick ' if use_magick_prefix else ''

        # Store command timeout
        self.timeout = timeout

        # Command history for debug purposes
        self.__history: list[tuple[str, bytes, bytes]] = []
        self.__timeout_count = 0
        self.__timeout_warning_logged = False
        self.__timeout_events: dict[tuple[str, str], dict[str, float | int | str]] = {}

        self.__initialize_text_log()

    @classmethod
    def __initialize_text_log(cls) -> None:
        """Ensure the text dimension log exists without clearing previous entries."""

        if cls.__text_log_initialized:
            return

        try:
            cls.TEXT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            if not cls.TEXT_LOG_PATH.exists():
                cls.TEXT_LOG_PATH.touch()
        except OSError as error:
            log.debug(f'Unable to initialize text log - {error}')
        else:
            cls.__text_log_initialized = True

    @classmethod
    def __append_text_log(cls, message: str) -> None:
        """Append a single log entry to the text dimension log."""

        try:
            with cls.TEXT_LOG_PATH.open('a', encoding='utf-8') as log_file:
                log_file.write(f"{message}\n")
        except OSError as error:
            log.debug(f'Unable to write text log - {error}')


    def validate_interface(self) -> bool:
        """
        Verify this interface has a valid connection to ImageMagick.

        Returns:
            True if the connection is valid, False otherwise.
        """

        output = self.run_get_output('convert --version')

        return all(_ in output for _ in self.__REQUIRED_VERSION_SUBSTRINGS)


    @overload
    @staticmethod
    def escape_chars(string: Literal[None]) -> Literal[None]: ...
    @overload
    @staticmethod
    def escape_chars(string: str) -> str: ...

    @staticmethod
    def escape_chars(string: Optional[str]) -> Optional[str]:
        """
        Escape the necessary characters within the given string so that
        they can be sent to ImageMagick.

        Args:
            string: The string to escape.

        Returns:
            Input string with all necessary characters escaped. This
            assumes that text will be wrapped in "".
        """

        if string is None:
            return None

        for char in ImageMagickInterface.__REQUIRED_ESCAPE_CHARACTERS:
            string = string.replace(char, f'\{char}')

        return string


    def run(self,
            command: str,
            *,
            operation: Optional[str] = None,
            retries: int = 0,
            retry_backoff_seconds: float = 0.25,
            retry_on_timeout: bool = False,
        ) -> tuple[bytes, bytes]:
        """
        Wrapper for running a given command. This uses either the host
        machine (i.e. direct calls); or through the provided docker
        container (if preferences has been set; i.e. wrapped through
        "docker exec -t {id} {command}").

        Args:
            command: The command (as string) to execute.
            operation: Optional label that describes what operation this
                command belongs to.
            retries: Number of times to retry when a timeout occurs.
            retry_backoff_seconds: Seconds to wait between timeout
                retries.
            retry_on_timeout: Whether timeout retries are allowed for
                this command.

        Returns:
            Tuple of the STDOUT and STDERR of the executed command.
        """

        # Un-escape \( and \) into ( and )
        if os_name == 'nt':
            command = command.replace('\(', '(').replace('\)', ')')

        self.__flush_expired_timeout_events()

        # If a docker image ID is specified, execute the command in that
        # container otherwise, execute on the host machine (no docker wrapper)
        if self.use_docker:
            command = f'docker exec -t {self.container} {self.prefix}{command}'
        # If an executable was indicated, use as 
        elif self.executable:
            command = f'{self.executable} {command}'
        else:
            command = f'{self.prefix}{command}'

        # Split command into list of strings for Popen
        try:
            cmd = command_split(command)
        except ValueError:
            log.exception('Invalid ImageMagick command')
            log.debug(command)
            return b'', b''

        # Execute, capturing stdout and stderr
        stdout, stderr = b'', b''
        max_retries = max(0, retries)
        attempt = 1
        while True:
            try:
                with Popen(cmd, stdout=PIPE, stderr=PIPE) as process:
                    try:
                        stdout, stderr = process.communicate(timeout=self.timeout)
                        break
                    except TimeoutExpired:
                        process.kill()
                        stdout, stderr = process.communicate()
                        self.__timeout_count += 1
                        truncated_command = command if len(command) <= 200 \
                            else f'{command[:197]}...'
                        self.__log_timeout_event(
                            operation=operation or 'unspecified',
                            command_fingerprint=truncated_command,
                            attempt=attempt,
                            max_attempts=max_retries + 1,
                        )
                        log.debug(command)
                        if (self.__timeout_count >= 3
                                and not self.__timeout_warning_logged):
                            log.warning(
                                ('ImageMagick has timed out repeatedly in this run; '
                                 'consider increasing `imagemagick.timeout` in '
                                 'your user config.')
                            )
                            self.__timeout_warning_logged = True

                        can_retry = retry_on_timeout and attempt <= max_retries
                        if can_retry:
                            log.debug(
                                'Retrying ImageMagick command after timeout '
                                '(attempt %s/%s, operation=%s)',
                                attempt + 1,
                                max_retries + 1,
                                operation or 'unspecified',
                            )
                            if retry_backoff_seconds > 0:
                                sleep(retry_backoff_seconds)
                            attempt += 1
                            continue

                        log.error(
                            'ImageMagick timeout retries exhausted '
                            '(operation=%s attempts=%s)',
                            operation or 'unspecified',
                            attempt,
                        )
                        break
            except FileNotFoundError:
                log.exception('Command error')
                log.debug(command)
                break

        # Add command to history and return results
        self.__history.append((command, stdout, stderr))

        return stdout, stderr


    def __flush_expired_timeout_events(self, now: Optional[float] = None) -> None:
        """Emit summaries for timeout events whose aggregation window expired."""

        now = monotonic() if now is None else now
        expired_keys: list[tuple[str, str]] = []

        for key, timeout_event in self.__timeout_events.items():
            if now - float(timeout_event['last_seen']) < self.TIMEOUT_AGGREGATION_WINDOW_SECONDS:
                continue

            count = int(timeout_event['count'])
            if count > 1:
                self.__log_timeout_summary(
                    operation=str(timeout_event['operation']),
                    count=count,
                )
            expired_keys.append(key)

        for key in expired_keys:
            self.__timeout_events.pop(key, None)


    def __log_timeout_event(self,
            operation: str,
            command_fingerprint: str,
            attempt: int,
            max_attempts: int,
        ) -> None:
        """Log timeout details while suppressing duplicate timeout flood."""

        now = monotonic()
        key = (operation, command_fingerprint)
        timeout_event = self.__timeout_events.get(key)

        if timeout_event is None:
            self.__timeout_events[key] = {
                'operation': operation,
                'count': 1,
                'last_seen': now,
            }
            log.error(
                ('ImageMagick command timed out '
                 '(operation=%s timeout=%ss attempt=%s/%s command="%s")'),
                operation,
                self.timeout,
                attempt,
                max_attempts,
                command_fingerprint,
            )
            return

        timeout_event['count'] = int(timeout_event['count']) + 1
        timeout_event['last_seen'] = now


    def __log_timeout_summary(self, *, operation: str, count: int) -> None:
        """Log an aggregated timeout summary message."""

        recommendation = ''
        if count >= self.TIMEOUT_WARNING_THRESHOLD:
            recommendation = (
                ' Consider increasing `imagemagick.timeout` in your user config '
                'if this operation is expected to take longer.'
            )

        message = (
            f'ImageMagick timeouts: {count} occurrences for {operation} '
            f'within {self.TIMEOUT_AGGREGATION_WINDOW_SECONDS}s '
            f'(timeout={self.timeout}s).{recommendation}'
        )
        if count >= self.TIMEOUT_WARNING_THRESHOLD:
            log.warning(message)
        else:
            log.info(message)


    def run_get_output(self,
            command: str,
            *,
            operation: Optional[str] = None,
            retries: int = 0,
            retry_backoff_seconds: float = 0.25,
            retry_on_timeout: bool = False,
        ) -> str:
        """
        Wrapper for `run()`, but return the byte-decoded stdout.

        Args:
            command: The command (as string) being executed.
            operation: Optional label that describes what operation this
                command belongs to.
            retries: Number of times to retry when a timeout occurs.
            retry_backoff_seconds: Seconds to wait between timeout
                retries.
            retry_on_timeout: Whether timeout retries are allowed for
                this command.

        Returns:
            The decoded stdout output of the executed command.
        """

        output = self.run(
            command,
            operation=operation,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            retry_on_timeout=retry_on_timeout,
        )

        try:
            return b''.join(output).decode()
        except UnicodeDecodeError:
            return b''.join(output).decode('iso8859')


    def delete_intermediate_images(self, *paths: Path) -> None:
        """
        Delete all the provided intermediate files.

        Args:
            paths: Any number of files to delete.
        """

        # Delete (unlink) each image, don't raise FileNotFoundError if DNE
        for image in paths:
            image.unlink(missing_ok=True)


    def print_command_history(self) -> None:
        """Print the command history of this Interface."""

        for command, stdout, stderr in self.__history:
            log.debug(f'Command:\n{command}\n\n'
                      f'stdout:\n{stdout.decode()}\n\n'
                      f'stderr:\n{stderr.decode()}')


    def get_image_dimensions(self, image: Path) -> Dimensions:
        """
        Get the dimensions of the given image.

        Args:
            image: Path to the image to get the dimensions of.

        Returns:
            Namedtuple of dimensions.
        """

        # Return dimenions of zero if image DNE
        if not image.exists():
            return Dimensions(0, 0)

        return Dimensions(*im_get(image))


    def get_text_dimensions(self,
            text_command: list[str],
            *,
            density: Optional[int] = None,
            interline_spacing: int = 0,
            line_count: int = 1,
            width: Literal['sum', 'max'] = 'max',
            height: Literal['sum', 'max'] = 'sum',
        ) -> Dimensions:
        """
        Get the dimensions of the text produced by the given text
        command. For 'width' and 'height' arguments, if 'max' then the
        maximum value of the text is utilized, while 'sum' will add each
        value. For example, if the given text command produces text like:

            Top Line Text
            Bottom Text

        Specifying width='sum', will add the widths of the two lines
        (not very meaningful), width='max' will return the maximum width
        of the two lines. Specifying height='sum' will return the total
        height of the text, and height='max' will return the tallest
        single line of text.

        Args:
            text_command: ImageMagick commands that produce text(s) to
                measure.
            density: Density of the image.
            width: How to process the width of the produced text(s).
            height: How to process the height of the produced text(s).

        Returns:
            Dimensions namedtuple.
        """

        # No text
        if not text_command:
            return Dimensions(0, 0)

        command = ' '.join([
            f'convert',
            f'-debug annotate',
            f'-density {density}' if density else '',
            f'' if '-annotate ' in ' '.join(text_command) else f'xc: ',
            *text_command,
            f'null: 2>&1',
        ])
        command_contains_label = ' label:"' in command

        # Execute dimension command, parse output
        metrics = self.run_get_output(
            command,
            operation='text_metrics',
            retries=2,
            retry_on_timeout=True,
        )
        widths = list(map(int, findall(r'Metrics:.*width:\s+(\d+)', metrics)))
        heights = list(map(int, findall(r'Metrics:.*height:\s+(\d+)', metrics)))
        ascents = list(map(int, findall(r'Metrics:.*ascent:\s+(\d+)', metrics)))
        descents = list(map(int, findall(r'Metrics:.*descent:\s+-(\d+)', metrics)))

        try:
            # Label text produces duplicate Metrics
            def sum_(dims: Iterable[float]) -> int:
                return sum(dims) / (2 if command_contains_label else 1)

            # Process according to given methods
            height_adjustment = interline_spacing * (line_count - 1)
            dimensions = Dimensions(
                sum_(widths)  if width  == 'sum' else max(widths),
                (sum_(ascents) + sum_(descents)) + height_adjustment,
            )
            self.__append_text_log(
                '\n'.join([
                    '---',
                    f'COMMAND: {command}',
                    f'DENSITY: {density or "default"}',
                    f'WIDTH_MODE: {width}',
                    f'HEIGHT_MODE: {height}',
                    f'INTERLINE_SPACING: {interline_spacing}',
                    f'LINE_COUNT: {line_count}',
                    f'WIDTHS: {widths}',
                    f'ASCENTS: {ascents}',
                    f'DESCENTS: {descents}',
                    f'RESULT: {dimensions}',
                ])
            )
            return dimensions
        except ValueError as e:
            log.debug(f'Cannot identify text dimensions - {e}')
            log.debug(f'{widths=} {heights=}')
            self.__append_text_log(
                '\n'.join([
                    '---',
                    f'COMMAND: {command}',
                    'ERROR: Cannot identify text dimensions',
                    f'EXCEPTION: {e}',
                    f'WIDTHS: {widths}',
                    f'HEIGHTS: {heights}',
                ])
            )
            return Dimensions(0, 0)


    def resize_image(self,
            input_image: Path,
            output_image: Path,
            *,
            by: Literal['width', 'height'],
            width: Optional[int] = None,
            height: Optional[int] = None
        ) -> Path:
        """
        Resize the given input image by a given width or height.

        Args:
            input_image: Path to the image to resize.
            output_image: Path to write the resized image to.
            by: Whether to resize by width or height.
            width: Width dimension to resize toward (if indicated).
            height: Height dimension to resize toward (if indicated).

        Raises:
            ValueError if by is not "width" or "height".
            ValueError if the indicated dimension is not provided or
                less than 0.
        """

        if by not in ('width', 'height'):
            raise ValueError(f'Can only resize by "width" or "height"')

        if by == 'width' and width is not None and width > 0:
            resize_command = f'-resize {width}x'
        elif by == 'height' and height is not None and height > 0:
            resize_command = f'-resize x{height}'
        else:
            raise ValueError(f'Resized dimension must be greater than zero')

        command = ' '.join([
            f'convert "{input_image.resolve()}"',
            f'-sampling-factor 4:4:4',
            f'-set colorspace sRGB',
            f'+profile "*"',
            f'-background transparent',
            f'-gravity center',
            resize_command,
            f'"{output_image.resolve()}"',
        ])

        self.run(command, operation='resize_image')

        return output_image


    def convert_svg_to_png(self,
            image: Path,
            destination: Path,
            min_dimension: int = 2500
        ) -> Optional[Path]:
        """
        Convert the given SVG image to PNG format.

        Args:
            image: Path to the SVG image being converted.
            destination: Path to the output image.
            min_dimension: Minimum dimension of the converted image.

        Returns:
            Path to the converted file. None if the conversion failed.
        """

        # If the temp file doesn't exist, return
        if not image.exists():
            return None

        # Command to convert file to PNG
        command = ' '.join([
            f'convert',
            f'-density 512',
            f'-resize "{min_dimension}x{min_dimension}"',
            f'-background None',
            f'"{image.resolve()}"',
            f'"{destination.resolve()}"',
        ])
        self.run(
            command,
            operation='svg_convert',
            retries=2,
            retry_on_timeout=True,
        )

        # Print command history if conversion failed
        if destination.exists():
            return destination

        self.print_command_history()

        if svg2png is None:
            log.error('Unable to convert SVG without cairosvg installed')
            return None

        try:
            svg2png(
                url=image.as_posix(),
                write_to=destination.as_posix(),
                output_width=min_dimension,
            )
        except Exception:  # pylint: disable=broad-except
            log.exception('CairoSVG conversion failed for %s', image)
            return None

        if destination.exists():
            return destination

        return None


    def get_random_filename(self, base: Path, extension: str = 'webp') -> Path:
        """
        Get the path to a randomly named image.

        Args:
            base: Base image used for the randomized path.
            extension: Extension of randomized file to create.

        Returns:
            Path to the randomized file. This file LIKELY DOES NOT
            exist.
        """

        random_chars = ''.join(random_choices(hexdigits, k=8))

        return base.parent / f'{base.stem}.{random_chars}.{extension}'


    def round_image_corners(self,
            image: Path,
            commands: list[str],
            dimensions: Optional[Dimensions] = None,
            radius: int = 25,
        ) -> Path:
        """
        Round the corners of the given image, writing the resulting
        image to a new file.

        Args:
            image: Path to the image to modify.
            commands: List of ImageMagick commands which contains the
                image data to modify.
            dimensions: Dimensions of the image. If not provided, these
                are calculated.
            radius: Radius to utilize for the corner rounding.

        Returns:
            Path to the created file.
        """

        # Calculate dimensions if not provided
        if not dimensions:
            dimensions = self.get_image_dimensions(image)

        temp_image = self.get_random_filename(image)
        self.run(' '.join([
            f'convert',
            f'-background none',
            *commands,
            f'-matte',
            f'\( -size {dimensions.width}x{dimensions.height}',
            f'xc:none',
            f'-draw "roundrectangle',
            f'0,0 {dimensions.width:.0f},{dimensions.height:.0f}',
            f'{radius:.0f},{radius:.0f}"',
            f'\)',
            f'-compose DstIn',
            f'-composite',
            f'"{temp_image.resolve()}"',
        ]), operation='round_corners')

        return temp_image
