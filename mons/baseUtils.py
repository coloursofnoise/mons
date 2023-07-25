import logging
import typing as t

from click import Abort

from mons.logging import ProgressBar

logger = logging.getLogger(__name__)


if t.TYPE_CHECKING:
    import _typeshed as _ts


T = t.TypeVar("T")


NestedIter = t.Union[t.Iterator["NestedIter"], T]


def flatten(iter: t.Iterator[NestedIter[T]]) -> t.Generator[T, None, None]:
    for item in iter:
        if isinstance(item, t.Iterator):
            yield from flatten(t.cast(t.Iterator[NestedIter[T]], item))
        else:
            yield item


def flatten_lines(iter: t.Iterator[NestedIter[T]]) -> t.Generator[str, None, None]:
    for item in flatten(iter):
        yield from str(item).splitlines(keepends=True)


@t.overload
def invert(b: None) -> None:
    ...


@t.overload
def invert(b: t.Literal[True]) -> t.Literal[False]:
    ...


@t.overload
def invert(b: t.Literal[False]) -> t.Literal[True]:
    ...


@t.overload
def invert(b: t.Optional[bool]) -> t.Optional[bool]:
    ...


def invert(b: t.Optional[bool]):
    """Invert a `bool`, ignoring `None` values."""
    if b is None:
        return None
    return not b


def partition(predicate: t.Callable[[T], bool], iterable: t.Iterable[T]):
    """Partition a list based on the results of a :param:`predicate`."""
    trues: t.List[T] = []
    falses: t.List[T] = []
    for item in iterable:
        if predicate(item):
            trues.append(item)
        else:
            falses.append(item)
    return trues, falses


def multi_partition(*predicates: t.Callable[[T], bool], iterable: t.Iterable[T]):
    """Partition a list based on a series of :param:`predicates`.

    Predicates are checked in the order they are passed."""
    results: t.List[t.List[T]] = [[] for _ in predicates]
    results.append([])

    for item in iterable:
        matched = False
        for i, pred in enumerate(predicates):
            if pred(item):
                results[i].append(item)
                matched = True
                break
        if not matched:
            results[-1].append(item)

    return tuple(results)


def chain_partition(predicate: t.Callable[[T], bool], *iterables: t.Iterable[T]):
    """Partition a series of lists based on a :param:`predicate`."""
    matches: t.List[T] = []
    non_matches: t.List[t.List[T]] = [[] for _ in iterables]

    for i, iterable in enumerate(iterables):
        for item in iterable:
            if predicate(item):
                matches.append(item)
            else:
                non_matches[i].append(item)
    return tuple((matches, *non_matches))


def find(iter: t.Iterable[T], matches: t.Iterable[T]):
    return next((match for match in iter if match in matches), None)


_download_interrupt = False


def read_with_progress(
    input: "_ts.SupportsRead[t.AnyStr]",
    output: "_ts.SupportsWrite[t.AnyStr]",
    size=0,
    blocksize=4096,
    label: t.Optional[str] = "",
    clear_progress=False,
):
    with ProgressBar(
        total=size,
        desc=label,
        leave=(not clear_progress),
        unit_scale=True,
        unit="b",
        delay=0.4,
    ) as bar:
        while True:
            if _download_interrupt:
                logger.debug("Download interrupted, aborting...")
                raise Abort

            buf = input.read(blocksize)
            if not buf:
                break
            output.write(buf)
            bar.update(len(buf))


class GeneratorWithLen(t.Generic[T]):
    def __init__(self, gen: t.Iterator[T], length: int):
        self.gen = gen
        self.length = length

    def __iter__(self):
        return self.gen

    def __next__(self):
        return next(self.gen)

    def __len__(self):
        return self.length
