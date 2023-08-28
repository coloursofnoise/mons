import errno
import logging
import os
import re
import typing as t

import dnfile

from mons import fs
from mons.logging import ProgressBar
from mons.version import NOVERSION
from mons.version import Version

logger = logging.getLogger(__name__)


def find_celeste_asm(path: fs.Path):
    if fs.isfile(path):
        if os.path.basename(path) in ("Celeste.exe", "Celeste.dll"):
            return path

    elif fs.isdir(path):
        if os.path.basename(path) == "Celeste.app":
            path = fs.joindir(path, "Resources")

        if fs.isfile(os.path.join(path, "Celeste.dll")):
            return fs.joinfile(path, "Celeste.dll")

        if fs.isfile(os.path.join(path, "Celeste.exe")):
            return fs.joinfile(path, "Celeste.exe")

    raise FileNotFoundError(
        errno.ENOENT, "'Celeste.exe' or 'Celeste.dll' could not be found", path
    )


OPCODE_LDC_I4_N = list(range(0x0016, 0x0016 + 8))
OPCODE_LDC_I4_S = 0x001F
OPCODE_LDC_I4 = 0x0020
OPCODE_NEWOBJ = 0x0073


def find_version_ctor(byte_iter, pe: dnfile.dnPE):
    def _parse_ldc_i4(byte_value):
        ldc_i4 = None
        if byte_value in OPCODE_LDC_I4_N:
            ldc_i4 = byte_value
        elif byte_value == OPCODE_LDC_I4_S:
            (ldc_i4,) = next(byte_iter)
        return ldc_i4

    assert pe.net
    assert pe.net.mdtables.MemberRef
    try:
        version = None
        while True:
            (byte_value,) = next(byte_iter)
            if version:
                if byte_value == OPCODE_NEWOBJ:
                    ctor = bytes(reversed([next(byte_iter)[0] for _ in range(3)])).hex()
                    member_ref = pe.net.mdtables.MemberRef.rows[int(ctor, 16)]
                    member_ref._parse_struct_codedindexes([pe.net.mdtables.TypeRef], None)  # type: ignore
                    type_ref = member_ref.Class.row
                    if (
                        type_ref
                        and type_ref.TypeNamespace == "System"
                        and type_ref.TypeName == "Version"
                    ):
                        return Version(*map(lambda v: v - 0x0016, version))
                version = None

            ldc_i4 = _parse_ldc_i4(byte_value)
            if ldc_i4 is not None:
                version = [ldc_i4]
                for _ in range(3):
                    ldc_i4_n = _parse_ldc_i4(next(byte_iter)[0])
                    if ldc_i4_n is None:
                        break
                    version.append(ldc_i4_n)
                if len(version) != 4:
                    version = None
    except StopIteration:
        raise AssertionError(
            "Could not find instructions matching an expected Celeste version."
        )


def find_framework(pe: dnfile.dnPE) -> str:
    assert pe.net
    assert pe.net.mdtables.TypeRef
    for row in pe.net.mdtables.TypeRef.rows:
        if row.TypeNamespace.startswith("Microsoft.Xna.Framework"):
            # Pre-emptively load with only the data we care about to prevent
            # triggering a full data load.
            row._parse_struct_codedindexes([pe.net.mdtables.AssemblyRef], None)  # type: ignore
            framework: str = row.ResolutionScope.row.Name  # type: ignore
            logger.debug(
                f"Found TypeRef `{row.TypeName}` with resolution scope `{framework}`."
            )
            return framework
    raise AssertionError(
        "Did not find 'Microsoft.Xna.Framework' reference in assembly."
    )


def find_celeste_version(pe: dnfile.dnPE) -> t.Tuple[Version, bool]:
    import struct

    assert pe.net, "Assembly could not be loaded as a .NET PE file."
    typedef = pe.net.mdtables.TypeDef
    assert typedef, "Assembly does not have a TypeDef metadata table."

    row_iter = iter(typedef.rows)

    t_Celeste = next(
        (
            row
            for row in row_iter
            if row.TypeNamespace == "Celeste" and row.TypeName == "Celeste"
        ),
        None,
    )
    assert t_Celeste, "Did not find 'Celeste.Celeste' in assembly."

    # Used to know when to stop assigning MethodDefs to t_Celeste in _parse_struct_lists
    next_row = next(row_iter)

    ctor = None
    # Pre-emptively load with only the data we care about to prevent
    # triggering a full data load.
    t_Celeste._parse_struct_lists([pe.net.mdtables.MethodDef], next_row)  # type: ignore
    for method_def in t_Celeste.MethodList:
        assert method_def.row
        if method_def.row.Name == "orig_ctor_Celeste":
            logger.debug("Found 'orig_ctor_Celeste'")
            ctor = method_def.row
            break
        if method_def.row.Name == ".ctor":
            logger.debug("Found '.ctor'")
            ctor = method_def.row

    assert ctor, "Did not find '.ctor' or 'orig_ctor_Celeste' in 'Celeste.Celeste'."

    struct_data = struct.iter_unpack("<B", pe.get_data(ctor.Rva))
    return find_version_ctor(struct_data, pe), ctor.Name == ".ctor"


def find_everest_version(pe: dnfile.dnPE) -> t.Optional[Version]:
    import struct

    assert pe.net
    stringHeap: dnfile.stream.StringsHeap = pe.net.strings  # type: ignore
    userstir: dnfile.stream.UserStringHeap = pe.net.user_strings  # type: ignore

    everest_version = None
    matches: t.List[t.Tuple[Version, str]] = list()

    version_re = re.compile(r"\d+\.\d+\.\d+(-.+)?")

    ui = 0
    while ui < len(userstir.__data__):
        bytestr = userstir.get(ui)
        if bytestr is None:
            break
        string = bytestr.decode(encoding="utf-16")
        match = version_re.fullmatch(string)
        if match:
            try:
                matches.append(
                    (
                        Version.parse(match.string),
                        ui.to_bytes(
                            (max(ui.bit_length(), 1) + 7) // 8, byteorder="big"
                        ).hex(),
                    )
                )
            except ValueError as e:
                logger.error("Error processing possible version match: " + str(e))
        ui += max(len(bytestr), 1)

    # currently, this case will never be met because Everest also includes version strings for
    # stubbed Everest modules. As of 2023-07-25, unique version strings are: ("1.0.0", "1.0.2")
    if len(matches) == 1:
        everest_version = matches[0][0]
        logger.debug(
            f"Found likely everest version in user string heap: '{everest_version}'."
        )
        return everest_version

    if len(matches):
        typedef = pe.net.mdtables.TypeDef
        assert typedef, "Assembly does not have a TypeDef metadata table."

        OPCODE_LDSTR = 0x0072

        memberref = pe.net.mdtables.MemberRef
        assert memberref

        t_Everest = next(
            (
                row
                for row in typedef.rows
                if row.TypeNamespace == "Celeste" and row.TypeName == "Celeste"
            ),
            None,
        )
        assert (
            t_Everest
        ), "Did not find 'Celeste.Mod.Everest' in supposedly modded assembly."

        # Pre-emptively load with only the data we care about to prevent
        # triggering a full data load.
        t_Everest._parse_struct_lists([pe.net.mdtables.MethodDef], None)  # type: ignore
        cctor = next(
            (
                method_def
                for method_def in t_Everest.MethodList
                if method_def.row and method_def.row.Name == ".cctor"
            ),
            None,
        )

        assert cctor, "Did not find '.cctor' in 'Celeste.Mod.Everest'."
        assert cctor.row
        struct_data = struct.iter_unpack(
            "<B", pe.get_data(cctor.row.Rva, cctor.row.row_size)
        )
        while True:
            (byte_data,) = next(struct_data)
            if byte_data == OPCODE_LDSTR:
                # assert i == 12, "Offset to first ldstr instruction does not match expected."
                mdToken = bytes(
                    reversed([next(struct_data)[0] for _ in range(3)])
                ).hex()
                for match, offset in matches:
                    if mdToken == offset:
                        everest_version = match
                        logger.debug(
                            f"Found everest version in user string heap that matches expected offset '0x{mdToken}': '{everest_version}'."
                        )
                        return everest_version
                break

    build_number = None

    i = 0
    with ProgressBar(desc="Scanning string heap", leave=False) as bar:
        while i < len(stringHeap.__data__):
            string = stringHeap.get(i)
            if string is None:
                break

            string = str(string)
            if string.startswith("EverestBuild"):
                build_number = string[len("EverestBuild") :]
                break
            inc = max(len(string), 1)
            i += inc
            bar.update(inc)

    if build_number:
        logger.debug(
            f"Found EverestBuild in strings heap with suffix '{build_number}'."
        )
        everest_version = Version(1, int(build_number), 0)
    return everest_version


def parse_exe(path: fs.File):
    logger.info(f"Retrieving version information from '{path}'.")

    # Suppress warnings
    dnfile_stream_logger = logging.getLogger(dnfile.stream.__name__)
    dnfile_stream_logger.setLevel(logging.ERROR)

    try:
        pe = dnfile.dnPE(path, fast_load=True, clr_lazy_load=True)
    except TypeError:
        pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories()

    celeste_version, vanilla = find_celeste_version(pe)
    everest_version = None
    if not vanilla:
        everest_version = find_everest_version(pe) or NOVERSION()
    return celeste_version, everest_version, find_framework(pe)
