import typing as t
from io import IOBase

from click import Abort
from tqdm import tqdm


T = t.TypeVar("T")


def flip(b: t.Optional[T]) -> t.Optional[T]:
    if b is None:
        return None
    return t.cast(t.Optional[T], not b)


def partition(pred: t.Callable[[T], bool], iterable: t.Iterable[T]):
    trues: t.List[T] = []
    falses: t.List[T] = []
    for item in iterable:
        if pred(item):
            trues.append(item)
        else:
            falses.append(item)
    return trues, falses


def multi_partition(*predicates: t.Callable[[T], bool], iterable: t.Iterable[T]):
    results: t.List[t.List[T]] = [[] for _ in predicates]
    results.append([])

    for item in iterable:
        i = 0
        matched = False
        for pred in predicates:
            if pred(item):
                results[i].append(item)
                matched = True
                break
            i += 1
        if not matched:
            results[-1].append(item)

    return tuple(results)


def tryExec(func: t.Callable[..., t.Any], *params: t.Any):
    try:
        func(*params)
    except:
        pass


def find(iter: t.Iterable[T], matches: t.Iterable[T]):
    return next((match for match in iter if match in matches), None)


_download_interrupt = False


def read_with_progress(
    input: IOBase,
    output: IOBase,
    size=0,
    blocksize=4096,
    label: t.Optional[str] = "",
    clear_progress=False,
):
    with tqdm(
        total=size,
        desc=label,
        leave=(not clear_progress),
        unit_scale=True,
        unit="b",
        delay=0.4,
        disable=False,
    ) as bar:
        while True:
            if _download_interrupt:
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
