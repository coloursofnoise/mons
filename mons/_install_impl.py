import errno
import logging
import os
import typing as t

import dnfile

from mons import fs
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
OPCODE_LDSTR = 0x0072


def find_version_ctor(byte_iter, pe: dnfile.dnPE):
    """Parse a method body :param:`byte_iter` to find a version constructor."""

    def _parse_ldc_i4(byte_value):
        """Extract the LDC_I4 value from the given byte value."""
        ldc_i4 = None
        if byte_value in OPCODE_LDC_I4_N:
            ldc_i4 = byte_value - 0x0016
        elif byte_value == OPCODE_LDC_I4_S:
            # LDC_I4_S values are stored in the following byte
            (ldc_i4,) = next(byte_iter)
        return ldc_i4

    assert pe.net
    assert pe.net.mdtables.MemberRef
    try:
        version = None
        while True:
            (byte_value,) = next(byte_iter)
            if version:
                # Check if the instruction following four LDC_I4 instructions is a NEWOBJ.
                if byte_value == OPCODE_NEWOBJ:
                    ctor_loc = int.from_bytes(
                        [next(byte_iter)[0] for _ in range(3)], byteorder="little"
                    )
                    member_ref = pe.net.mdtables.MemberRef.rows[ctor_loc]
                    # lazy-load only the data we need
                    try:
                        member_ref._parse_struct_codedindexes([pe.net.mdtables.TypeRef], None)  # type: ignore
                    except AttributeError:
                        pass  # ignore
                    type_ref = member_ref.Class.row
                    assert isinstance(type_ref, dnfile.stream.mdtable.TypeRefRow)

                    if (
                        type_ref
                        and type_ref.TypeNamespace == "System"
                        and type_ref.TypeName == "Version"
                    ):
                        return Version(*version)
                version = None

            ldc_i4 = _parse_ldc_i4(byte_value)
            if ldc_i4 is not None:
                # We have found one LDC_I4 instruction, now check if there are three more.
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


def find_celeste_version(pe: dnfile.dnPE) -> Version:
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
    try:
        t_Celeste._parse_struct_lists([pe.net.mdtables.MethodDef], next_row)  # type: ignore
    except AttributeError:
        pass  # ignore
    for method_def in t_Celeste.MethodList:
        assert method_def.row
        # patched by Everest
        if method_def.row.Name == "orig_ctor_Celeste":
            ctor = method_def.row
            break
        if method_def.row.Name == ".ctor":
            ctor = method_def.row

    assert ctor, "Did not find '.ctor' or 'orig_ctor_Celeste' in 'Celeste.Celeste'."

    struct_data = struct.iter_unpack("<B", pe.get_data(ctor.Rva))
    return find_version_ctor(struct_data, pe)


def find_everest_version(pe: dnfile.dnPE) -> t.Optional[Version]:
    """Parse the Everest static cctor to find the version string."""
    import struct

    assert pe.net, "Assembly could not be loaded as a .NET PE file."
    typedef = pe.net.mdtables.TypeDef
    assert typedef, "Assembly does not have a TypeDef metadata table."

    t_Everest = next(
        (
            row
            for row in typedef.rows
            if row.TypeNamespace == "Celeste.Mod" and row.TypeName == "Everest"
        ),
        None,
    )
    if not t_Everest:
        return None  # assembly is not modded.

    # Pre-emptively load with only the data we care about to prevent
    # triggering a full data load.
    try:
        t_Everest._parse_struct_lists([pe.net.mdtables.MethodDef], None)  # type: ignore
    except AttributeError:
        pass  # ignore
    cctor = next(
        (
            method_def.row
            for method_def in t_Everest.MethodList
            if method_def.row and method_def.row.Name == ".cctor"
        ),
        None,
    )

    assert cctor, "Did not find valid '.cctor' in 'Celeste.Mod.Everest'."
    struct_data = struct.iter_unpack("<B", pe.get_data(cctor.Rva, cctor.row_size))

    assert pe.net.user_strings, "Assembly does not have a user string heap."

    try:
        while True:
            (byte_data,) = next(struct_data)
            # The first LDSTR instruction *should* always be the Everest version.
            if byte_data == OPCODE_LDSTR:
                offset = int.from_bytes(
                    reversed([next(struct_data)[0] for _ in range(3)])
                )
                # Lookup the offset in the user string table.
                us = pe.net.user_strings.get_us(offset)
                assert us, "Invalid string or offset in user string table."
                return Version.parse(us.value)
    except StopIteration:
        raise AssertionError(
            "Could not find instructions matching an expected Everest version."
        )


def find_framework(pe: dnfile.dnPE) -> str:
    """Find the name of the assembly containing the Microsoft.Xna.Framework namespace."""
    assert pe.net
    assert pe.net.mdtables.TypeRef
    for row in pe.net.mdtables.TypeRef.rows:
        if row.TypeNamespace.startswith("Microsoft.Xna.Framework"):
            # Pre-emptively load with only the data we care about to prevent
            # triggering a full data load.
            try:
                row._parse_struct_codedindexes([pe.net.mdtables.AssemblyRef], None)  # type: ignore
            except AttributeError:
                pass  # ignore
            framework: str = row.ResolutionScope.row.Name  # type: ignore
            logger.debug(
                f"Found TypeRef '{row.TypeNamespace}.{row.TypeName}' with resolution scope name '{framework}'."
            )
            return framework
    raise AssertionError(
        "Did not find 'Microsoft.Xna.Framework' reference in assembly."
    )


def parse_exe(path: fs.File):
    logger.info(f"Retrieving version information from '{path}'.")

    # Suppress warnings
    dnfile_stream_logger = logging.getLogger(dnfile.stream.__name__)
    dnfile_stream_logger.setLevel(logging.ERROR)

    try:
        pe = dnfile.dnPE(path, fast_load=True, clr_lazy_load=True)  # type: ignore
    except TypeError:
        logger.warning("Installed dnfile version does not support lazy loading.")
        pe = dnfile.dnPE(path, fast_load=True)
    pe.parse_data_directories()

    return find_celeste_version(pe), find_everest_version(pe), find_framework(pe)
