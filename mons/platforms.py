import os
import platform
import sys
import typing as t

import typing_extensions as te


if t.TYPE_CHECKING:
    if os.name == "nt":
        CURRENT_PLATFORM = te.Literal["Windows"]
        OTHER_PLATFORMS = t.Union[te.Literal["Darwin"], te.Literal["Linux"]]

    elif sys.platform == "darwin":
        CURRENT_PLATFORM = te.Literal["Darwin"]
        OTHER_PLATFORMS = t.Union[te.Literal["Windows"], te.Literal["Linux"]]

    else:
        CURRENT_PLATFORM = te.Literal["Linux"]
        OTHER_PLATFORMS = t.Union[te.Literal["Windows"], te.Literal["Darwin"]]

    @t.overload
    def assert_platform(target: CURRENT_PLATFORM) -> bool:
        ...

    @t.overload
    def assert_platform(target: OTHER_PLATFORMS) -> t.NoReturn:
        ...

    @t.overload
    def is_platform(target: CURRENT_PLATFORM) -> te.Literal[True]:
        ...

    @t.overload
    def is_platform(target: OTHER_PLATFORMS) -> te.Literal[False]:
        ...


def assert_platform(
    target: t.Union[te.Literal["Windows"], te.Literal["Darwin"], te.Literal["Linux"]]
):
    """Provides a way to indicate to the type-checker what platform
    is requested, allowing it to mark platform-specific code unreachable as
    appropriate, without compromising on detection realiability at runtime.

    Simply defining a function that returns a literal boolean doesn't seem to be
    adequate, but the `Never`/`NoReturn` (equivalent) types can be used to define
    a function that will never return on some platforms.

    In practice, these can be used as follows:
    ```
    if is_platform("Windows"):
        # Windows-specific code..

    if is_platform("Windows") and assert_platform("Windows"):
        # Windows-specific code...
    ```

    Note that these two functions cannot be combined, as using `assert_platform` on
    its own will cause *all* following code to be marked unreachable, and
    wrapping them in another function will result in the type-checker treating it
    as a `Union[Literal[{bool}], NoReturn]` return type.

    https://github.com/microsoft/pylance-release/issues/470#issuecomment-1203154386
    https://docs.python.org/3/library/platform.html
    https://peps.python.org/pep-0484/#version-and-platform-checking
    """
    return is_platform(target)  # no-op, for type-checker only


def is_platform(
    target: t.Union[te.Literal["Windows"], te.Literal["Darwin"], te.Literal["Linux"]]
):
    return platform.system() == target


def is_os_64bit():
    """Determines whether the current OS is 64bit, regardless of installed
    Python architecture.
    """
    return platform.machine().endswith("64")
