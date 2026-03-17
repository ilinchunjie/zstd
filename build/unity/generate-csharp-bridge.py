#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = ROOT / "lib"
HEADER_PATHS = [
    LIB_DIR / "zstd.h",
    LIB_DIR / "zstd_errors.h",
    LIB_DIR / "zdict.h",
]

PUBLIC_SECTION_END_MARKERS = {
    "zstd.h": "#if defined(ZSTD_STATIC_LINKING_ONLY) && !defined(ZSTD_H_ZSTD_STATIC_LINKING_ONLY)",
    "zdict.h": "#if defined(ZDICT_STATIC_LINKING_ONLY) && !defined(ZSTD_ZDICT_H_STATIC)",
}

API_MACROS = ("ZSTDLIB_API", "ZSTDERRORLIB_API", "ZDICTLIB_API")
EXCLUDED_FUNCTION_NAMES = {
    # Static-linking-only / experimental / callback-only helpers are intentionally excluded.
}

MANUAL_CONSTANTS = {
    "ZSTD_CLEVEL_DEFAULT": "3",
    "ZSTD_MAGICNUMBER": "0xFD2FB528u",
    "ZSTD_MAGIC_DICTIONARY": "0xEC30A437u",
    "ZSTD_MAGIC_SKIPPABLE_START": "0x184D2A50u",
    "ZSTD_MAGIC_SKIPPABLE_MASK": "0xFFFFFFF0u",
    "ZSTD_BLOCKSIZELOG_MAX": "17",
    "ZSTD_BLOCKSIZE_MAX": "(1 << ZSTD_BLOCKSIZELOG_MAX)",
    "ZSTD_VERSION_MAJOR": "1",
    "ZSTD_VERSION_MINOR": "5",
    "ZSTD_VERSION_RELEASE": "7",
    "ZSTD_VERSION_NUMBER": "(ZSTD_VERSION_MAJOR * 100 * 100 + ZSTD_VERSION_MINOR * 100 + ZSTD_VERSION_RELEASE)",
    "ZSTD_CONTENTSIZE_UNKNOWN": "unchecked((ulong)~0UL)",
    "ZSTD_CONTENTSIZE_ERROR": "unchecked((ulong)~1UL)",
    "ZSTD_MAX_INPUT_SIZE_32": "0xFF00FF00u",
    "ZSTD_MAX_INPUT_SIZE_64": "0xFF00FF00FF00FF00UL",
    "ZDICT_DICTSIZE_MIN": "256",
    "ZDICT_CONTENTSIZE_MIN": "128",
}

KEYWORD_REPLACEMENTS = {
    "params": "parameters",
    "event": "eventValue",
    "string": "stringValue",
    "base": "baseValue",
    "ref": "reference",
    "fixed": "fixedValue",
    "internal": "internalValue",
    "delegate": "delegateValue",
    "object": "objectValue",
    "in": "inValue",
    "out": "outValue",
}


@dataclass
class CParameter:
    ctype: str
    name: str


@dataclass
class CFunction:
    return_type: str
    name: str
    parameters: list[CParameter]
    header: str
    declaration: str


@dataclass
class CStruct:
    name: str
    fields: list[CParameter]


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def public_header_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = PUBLIC_SECTION_END_MARKERS.get(path.name)
    if marker and marker in text:
        text = text.rsplit(marker, 1)[0]
    return text


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_params(param_text: str) -> list[str]:
    param_text = param_text.strip()
    if not param_text or param_text == "void":
        return []
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in param_text:
        if ch == ',' and depth == 0:
            piece = ''.join(current).strip()
            if piece:
                parts.append(piece)
            current = []
            continue
        current.append(ch)
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
    tail = ''.join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def parse_param(param: str) -> CParameter:
    param = normalize_ws(param)
    if param == '...':
        raise ValueError('Variadic parameters are not supported')
    fnptr_match = re.match(r'(.+?)\(\s*\*\s*(\w+)\s*\)\s*\((.*)\)$', param)
    if fnptr_match:
        raise ValueError('Function pointer parameters are not supported in shared API generation')

    match = re.match(r'(.+?)([A-Za-z_]\w*)$', param)
    if not match:
        raise ValueError(f'Unable to parse parameter: {param}')
    ctype = normalize_ws(match.group(1))
    name = match.group(2)
    return CParameter(ctype=ctype, name=name)


def parse_exported_functions(header_name: str, text: str) -> list[CFunction]:
    cleaned = strip_comments(text)
    functions: list[CFunction] = []
    statement: list[str] = []

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        if line.startswith('ZSTD_DEPRECATED'):
            continue
        statement.append(line)
        if ';' not in line:
            continue

        joined = normalize_ws(' '.join(statement))
        statement = []
        if not any(macro in joined for macro in API_MACROS):
            continue
        if 'typedef ' in joined:
            continue

        macro_match = re.search(r'\b(?:' + '|'.join(API_MACROS) + r')\b', joined)
        if not macro_match:
            continue
        signature = joined[macro_match.end():].strip()
        fn_match = re.match(r'(.+?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*;', signature)
        if not fn_match:
            continue

        return_type = normalize_ws(fn_match.group(1))
        name = fn_match.group(2)
        if name in EXCLUDED_FUNCTION_NAMES:
            continue
        params_blob = fn_match.group(3)
        params = [parse_param(piece) for piece in split_params(params_blob)]
        functions.append(CFunction(return_type=return_type, name=name, parameters=params, header=header_name, declaration=joined))

    return functions


def parse_opaque_structs(text: str) -> list[str]:
    cleaned = strip_comments(text)
    return sorted(set(re.findall(r'typedef\s+struct\s+[A-Za-z_][A-Za-z0-9_]*\s+((?:ZSTD|ZDICT)_[A-Za-z0-9_]+)\s*;', cleaned)))


def parse_structs(text: str) -> list[CStruct]:
    cleaned = strip_comments(text)
    structs: list[CStruct] = []
    for match in re.finditer(r'typedef\s+struct(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\{(.*?)\}\s*((?:ZSTD|ZDICT)_[A-Za-z0-9_]+)\s*;', cleaned, flags=re.S):
        body = match.group(1)
        name = match.group(2)
        fields: list[CParameter] = []
        for piece in body.split(';'):
            piece = normalize_ws(piece)
            if not piece:
                continue
            fields.append(parse_param(piece))
        structs.append(CStruct(name=name, fields=fields))
    return structs


def parse_enum_members(body: str) -> list[tuple[str, str | None]]:
    body = strip_comments(body)
    members: list[tuple[str, str | None]] = []
    current_value: str | None = None
    for piece in body.split(','):
        item = normalize_ws(piece)
        if not item:
            continue
        if '=' in item:
            name, value = item.split('=', 1)
            current_value = normalize_ws(value)
            members.append((normalize_ws(name), current_value))
        else:
            members.append((item, None))
    return members


def parse_enums(text: str) -> dict[str, list[tuple[str, str | None]]]:
    cleaned = strip_comments(text)
    enums: dict[str, list[tuple[str, str | None]]] = {}
    for match in re.finditer(r'typedef\s+enum(?:\s+[A-Za-z_][A-Za-z0-9_]*)?\s*\{(.*?)\}\s*(ZSTD_[A-Za-z0-9_]+)\s*;', cleaned, flags=re.S):
        enums[match.group(2)] = parse_enum_members(match.group(1))
    return enums


def convert_constant_expr(expr: str) -> str:
    expr = expr.strip()
    replacements = {
        '0ULL': '0UL',
        '0U': '0u',
        '0xFD2FB528': '0xFD2FB528u',
        '0xEC30A437': '0xEC30A437u',
        '0x184D2A50': '0x184D2A50u',
        '0xFFFFFFF0': '0xFFFFFFF0u',
    }
    return replacements.get(expr, expr)


def sanitize_identifier(name: str) -> str:
    return KEYWORD_REPLACEMENTS.get(name, name)


def cs_type(ctype: str, known_structs: set[str], known_enums: set[str], opaque_types: set[str]) -> str:
    ctype = normalize_ws(ctype)
    ctype = ctype.replace('const ', '').strip()
    pointer_depth = ctype.count('*')
    base = normalize_ws(ctype.replace('*', ''))

    if pointer_depth > 0:
        if base == 'char':
            return 'IntPtr'
        if base in {'void'}:
            return 'IntPtr'
        if base in opaque_types:
            return 'IntPtr'
        if base in known_structs:
            return 'ref ' + base if pointer_depth == 1 else 'IntPtr'
        return 'IntPtr'

    mapping = {
        'void': 'void',
        'int': 'int',
        'unsigned': 'uint',
        'unsigned int': 'uint',
        'unsigned long long': 'ulong',
        'long long': 'long',
        'size_t': 'UIntPtr',
        'double': 'double',
        'float': 'float',
        'char': 'byte',
    }
    if base in mapping:
        return mapping[base]
    if base in known_enums or base in known_structs:
        return base
    if base in opaque_types:
        return 'IntPtr'
    raise ValueError(f'Unsupported C type: {ctype}')


def emit_enum(name: str, members: list[tuple[str, str | None]]) -> str:
    lines = [f'    public enum {name}', '    {']
    for member, value in members:
        if value is None:
            lines.append(f'        {member},')
        else:
            lines.append(f'        {member} = {convert_constant_expr(value)},')
    lines.append('    }')
    return '\n'.join(lines)


def emit_struct(struct: CStruct, known_structs: set[str], known_enums: set[str], opaque_types: set[str]) -> str:
    lines = ['    [StructLayout(LayoutKind.Sequential)]', f'    public struct {struct.name}', '    {']
    for field in struct.fields:
        field_type = cs_type(field.ctype, known_structs, known_enums, opaque_types)
        lines.append(f'        public {field_type} {sanitize_identifier(field.name)};')
    lines.append('    }')
    return '\n'.join(lines)


def emit_function(function: CFunction, known_structs: set[str], known_enums: set[str], opaque_types: set[str]) -> str:
    return_type = cs_type(function.return_type, known_structs, known_enums, opaque_types)
    parameters: list[str] = []
    for param in function.parameters:
        param_type = cs_type(param.ctype, known_structs, known_enums, opaque_types)
        parameters.append(f'{param_type} {sanitize_identifier(param.name)}')
    param_blob = ', '.join(parameters)
    lines = [
        '        [DllImport(NativeLibraryName, CallingConvention = CallingConvention.Cdecl)]',
        f'        internal static extern {return_type} {function.name}({param_blob});',
    ]
    return '\n'.join(lines)


def emit_constants() -> str:
    lines = ['    public static class ZstdConstants', '    {']
    for name, expr in MANUAL_CONSTANTS.items():
        cs_type_name = 'int'
        if name.startswith('ZSTD_MAGIC') or name == 'ZSTD_MAX_INPUT_SIZE_32':
            cs_type_name = 'uint'
        elif name in {'ZSTD_CONTENTSIZE_UNKNOWN', 'ZSTD_CONTENTSIZE_ERROR', 'ZSTD_MAX_INPUT_SIZE_64'}:
            cs_type_name = 'ulong'
        lines.append(f'        public const {cs_type_name} {name} = {expr};')
    lines.extend([
        '',
        '        public static readonly UIntPtr ZSTD_MAX_INPUT_SIZE = IntPtr.Size == 8',
        '            ? new UIntPtr(ZSTD_MAX_INPUT_SIZE_64)',
        '            : new UIntPtr(ZSTD_MAX_INPUT_SIZE_32);',
    ])
    lines.append('    }')
    return '\n'.join(lines)


def emit_native_library_block() -> str:
    return '\n'.join([
        '    public static class ZstdNativeLibrary',
        '    {',
        '#if UNITY_IOS && !UNITY_EDITOR',
        '        public const string Name = "__Internal";',
        '#elif UNITY_STANDALONE_OSX || UNITY_EDITOR_OSX',
        '        public const string Name = "libzstd.dylib";',
        '#elif UNITY_ANDROID',
        '        public const string Name = "zstd";',
        '#elif UNITY_STANDALONE_WIN || UNITY_EDITOR_WIN',
        '        public const string Name = "zstd";',
        '#elif UNITY_STANDALONE_LINUX || UNITY_EDITOR_LINUX',
        '        public const string Name = "libzstd.so";',
        '#else',
        '        public const string Name = "zstd";',
        '#endif',
        '    }',
    ])


def emit_helpers(functions: Iterable[CFunction]) -> str:
    fn_names = {f.name for f in functions}
    lines: list[str] = []

    lines.extend([
        '    public static class ZstdInterop',
        '    {',
    ])
    if 'ZSTD_isError' in fn_names:
        lines.append('        public static bool IsError(UIntPtr code) => NativeMethods.ZSTD_isError(code) != 0;')
    if 'ZSTD_getErrorName' in fn_names:
        lines.append('        public static string GetErrorName(UIntPtr code) => PtrToAnsiString(NativeMethods.ZSTD_getErrorName(code));')
    if 'ZSTD_getErrorString' in fn_names:
        lines.append('        public static string GetErrorString(ZSTD_ErrorCode code) => PtrToAnsiString(NativeMethods.ZSTD_getErrorString(code));')
    if 'ZSTD_versionString' in fn_names:
        lines.append('        public static string GetVersionString() => PtrToAnsiString(NativeMethods.ZSTD_versionString());')
    if 'ZSTD_versionNumber' in fn_names:
        lines.append('        public static uint GetVersionNumber() => NativeMethods.ZSTD_versionNumber();')
    if 'ZSTD_compressBound' in fn_names:
        lines.append('        public static UIntPtr GetCompressBound(UIntPtr srcSize) => NativeMethods.ZSTD_compressBound(srcSize);')
    if 'ZSTD_minCLevel' in fn_names:
        lines.append('        public static int GetMinCompressionLevel() => NativeMethods.ZSTD_minCLevel();')
    if 'ZSTD_maxCLevel' in fn_names:
        lines.append('        public static int GetMaxCompressionLevel() => NativeMethods.ZSTD_maxCLevel();')
    if 'ZSTD_defaultCLevel' in fn_names:
        lines.append('        public static int GetDefaultCompressionLevel() => NativeMethods.ZSTD_defaultCLevel();')
    lines.extend([
        '',
        '        public static void ThrowIfError(UIntPtr code)',
        '        {',
        '            if (IsError(code))',
        '                throw new InvalidOperationException(GetErrorName(code));',
        '        }',
        '',
        '        internal static UIntPtr ToUIntPtr(int value) => checked((UIntPtr)(uint)value);',
        '        internal static string PtrToAnsiString(IntPtr ptr) => ptr == IntPtr.Zero ? string.Empty : Marshal.PtrToStringAnsi(ptr) ?? string.Empty;',
        '        internal static void EnsureNotNull(Array value, string paramName)',
        '        {',
        '            if (value == null) throw new ArgumentNullException(paramName);',
        '        }',
        '    }',
        '',
        '    public static unsafe class ZstdUnsafe',
        '    {',
        '        public static UIntPtr Compress(byte* source, int sourceLength, byte* destination, int destinationLength, int compressionLevel)',
        '        {',
        '            return NativeMethods.ZSTD_compress((IntPtr)destination, ZstdInterop.ToUIntPtr(destinationLength), (IntPtr)source, ZstdInterop.ToUIntPtr(sourceLength), compressionLevel);',
        '        }',
        '',
        '        public static UIntPtr Decompress(byte* source, int sourceLength, byte* destination, int destinationLength)',
        '        {',
        '            return NativeMethods.ZSTD_decompress((IntPtr)destination, ZstdInterop.ToUIntPtr(destinationLength), (IntPtr)source, ZstdInterop.ToUIntPtr(sourceLength));',
        '        }',
        '',
        '        public static ulong GetFrameContentSize(byte* compressedData, int compressedLength)',
        '        {',
        '            return NativeMethods.ZSTD_getFrameContentSize((IntPtr)compressedData, ZstdInterop.ToUIntPtr(compressedLength));',
        '        }',
        '',
        '        public static ZSTD_inBuffer CreateInBuffer(byte* source, int length, int position = 0)',
        '        {',
        '            return new ZSTD_inBuffer',
        '            {',
        '                src = (IntPtr)source,',
        '                size = ZstdInterop.ToUIntPtr(length),',
        '                pos = ZstdInterop.ToUIntPtr(position),',
        '            };',
        '        }',
        '',
        '        public static ZSTD_outBuffer CreateOutBuffer(byte* destination, int length, int position = 0)',
        '        {',
        '            return new ZSTD_outBuffer',
        '            {',
        '                dst = (IntPtr)destination,',
        '                size = ZstdInterop.ToUIntPtr(length),',
        '                pos = ZstdInterop.ToUIntPtr(position),',
        '            };',
        '        }',
        '    }',
        '',
        '    public static unsafe class ZstdStreamUnsafe',
        '    {',
        '        public static UIntPtr CompressStream(IntPtr stream, ref ZSTD_outBuffer output, ref ZSTD_inBuffer input)',
        '            => NativeMethods.ZSTD_compressStream(stream, ref output, ref input);',
        '',
        '        public static UIntPtr CompressStream2(IntPtr stream, ref ZSTD_outBuffer output, ref ZSTD_inBuffer input, ZSTD_EndDirective endDirective)',
        '            => NativeMethods.ZSTD_compressStream2(stream, ref output, ref input, endDirective);',
        '',
        '        public static UIntPtr FlushStream(IntPtr stream, ref ZSTD_outBuffer output)',
        '            => NativeMethods.ZSTD_flushStream(stream, ref output);',
        '',
        '        public static UIntPtr EndStream(IntPtr stream, ref ZSTD_outBuffer output)',
        '            => NativeMethods.ZSTD_endStream(stream, ref output);',
        '',
        '        public static UIntPtr DecompressStream(IntPtr stream, ref ZSTD_outBuffer output, ref ZSTD_inBuffer input)',
        '            => NativeMethods.ZSTD_decompressStream(stream, ref output, ref input);',
        '    }',
        '',
        '    public static unsafe class ZstdArrays',
        '    {',
        '        public static UIntPtr Compress(byte[] source, byte[] destination, int compressionLevel)',
        '        {',
        '            ZstdInterop.EnsureNotNull(source, nameof(source));',
        '            ZstdInterop.EnsureNotNull(destination, nameof(destination));',
        '            ulong srcHandle = 0;',
        '            ulong dstHandle = 0;',
        '            try',
        '            {',
        '                var srcPtr = (byte*)UnsafeUtility.PinGCArrayAndGetDataAddress(source, out srcHandle);',
        '                var dstPtr = (byte*)UnsafeUtility.PinGCArrayAndGetDataAddress(destination, out dstHandle);',
        '                return ZstdUnsafe.Compress(srcPtr, source.Length, dstPtr, destination.Length, compressionLevel);',
        '            }',
        '            finally',
        '            {',
        '                if (dstHandle != 0) UnsafeUtility.ReleaseGCObject(dstHandle);',
        '                if (srcHandle != 0) UnsafeUtility.ReleaseGCObject(srcHandle);',
        '            }',
        '        }',
        '',
        '        public static byte[] Compress(byte[] source, int compressionLevel)',
        '        {',
        '            ZstdInterop.EnsureNotNull(source, nameof(source));',
        '            var bound = checked((int)NativeMethods.ZSTD_compressBound(ZstdInterop.ToUIntPtr(source.Length)).ToUInt64());',
        '            var destination = new byte[bound];',
        '            var written = Compress(source, destination, compressionLevel);',
        '            ZstdInterop.ThrowIfError(written);',
        '            Array.Resize(ref destination, checked((int)written.ToUInt64()));',
        '            return destination;',
        '        }',
        '',
        '        public static UIntPtr Decompress(byte[] source, byte[] destination)',
        '        {',
        '            ZstdInterop.EnsureNotNull(source, nameof(source));',
        '            ZstdInterop.EnsureNotNull(destination, nameof(destination));',
        '            ulong srcHandle = 0;',
        '            ulong dstHandle = 0;',
        '            try',
        '            {',
        '                var srcPtr = (byte*)UnsafeUtility.PinGCArrayAndGetDataAddress(source, out srcHandle);',
        '                var dstPtr = (byte*)UnsafeUtility.PinGCArrayAndGetDataAddress(destination, out dstHandle);',
        '                return ZstdUnsafe.Decompress(srcPtr, source.Length, dstPtr, destination.Length);',
        '            }',
        '            finally',
        '            {',
        '                if (dstHandle != 0) UnsafeUtility.ReleaseGCObject(dstHandle);',
        '                if (srcHandle != 0) UnsafeUtility.ReleaseGCObject(srcHandle);',
        '            }',
        '        }',
        '',
        '        public static byte[] Decompress(byte[] source)',
        '        {',
        '            ZstdInterop.EnsureNotNull(source, nameof(source));',
        '            var frameSize = GetFrameContentSize(source);',
        '            if (frameSize == ZstdConstants.ZSTD_CONTENTSIZE_UNKNOWN || frameSize == ZstdConstants.ZSTD_CONTENTSIZE_ERROR)',
        '                throw new InvalidOperationException("Unable to determine decompressed size from frame header.");',
        '            var destination = new byte[checked((int)frameSize)];',
        '            var written = Decompress(source, destination);',
        '            ZstdInterop.ThrowIfError(written);',
        '            if ((ulong)written.ToUInt64() != frameSize)',
        '                Array.Resize(ref destination, checked((int)written.ToUInt64()));',
        '            return destination;',
        '        }',
        '',
        '        public static ulong GetFrameContentSize(byte[] compressedData)',
        '        {',
        '            ZstdInterop.EnsureNotNull(compressedData, nameof(compressedData));',
        '            ulong handle = 0;',
        '            try',
        '            {',
        '                var ptr = (byte*)UnsafeUtility.PinGCArrayAndGetDataAddress(compressedData, out handle);',
        '                return ZstdUnsafe.GetFrameContentSize(ptr, compressedData.Length);',
        '            }',
        '            finally',
        '            {',
        '                if (handle != 0) UnsafeUtility.ReleaseGCObject(handle);',
        '            }',
        '        }',
        '    }',
        '',
        '    public static unsafe class ZstdNativeArrays',
        '    {',
        '        public static UIntPtr Compress(NativeArray<byte> source, NativeArray<byte> destination, int compressionLevel)',
        '        {',
        '            var srcPtr = (byte*)NativeArrayUnsafeUtility.GetUnsafeReadOnlyPtr(source);',
        '            var dstPtr = (byte*)NativeArrayUnsafeUtility.GetUnsafePtr(destination);',
        '            return ZstdUnsafe.Compress(srcPtr, source.Length, dstPtr, destination.Length, compressionLevel);',
        '        }',
        '',
        '        public static UIntPtr Decompress(NativeArray<byte> source, NativeArray<byte> destination)',
        '        {',
        '            var srcPtr = (byte*)NativeArrayUnsafeUtility.GetUnsafeReadOnlyPtr(source);',
        '            var dstPtr = (byte*)NativeArrayUnsafeUtility.GetUnsafePtr(destination);',
        '            return ZstdUnsafe.Decompress(srcPtr, source.Length, dstPtr, destination.Length);',
        '        }',
        '',
        '        public static ulong GetFrameContentSize(NativeArray<byte> compressedData)',
        '        {',
        '            var ptr = (byte*)NativeArrayUnsafeUtility.GetUnsafeReadOnlyPtr(compressedData);',
        '            return ZstdUnsafe.GetFrameContentSize(ptr, compressedData.Length);',
        '        }',
        '',
        '        public static ZSTD_inBuffer CreateInBuffer(NativeArray<byte> source, int position = 0)',
        '        {',
        '            var ptr = (byte*)NativeArrayUnsafeUtility.GetUnsafeReadOnlyPtr(source);',
        '            return ZstdUnsafe.CreateInBuffer(ptr, source.Length, position);',
        '        }',
        '',
        '        public static ZSTD_outBuffer CreateOutBuffer(NativeArray<byte> destination, int position = 0)',
        '        {',
        '            var ptr = (byte*)NativeArrayUnsafeUtility.GetUnsafePtr(destination);',
        '            return ZstdUnsafe.CreateOutBuffer(ptr, destination.Length, position);',
        '        }',
        '    }',
    ])
    return '\n'.join(lines)


def generate(output_path: Path) -> None:
    header_texts = {path.name: public_header_text(path) for path in HEADER_PATHS}

    functions: list[CFunction] = []
    enums: dict[str, list[tuple[str, str | None]]] = {}
    structs: list[CStruct] = []
    opaque_types: set[str] = set()

    for header_name, text in header_texts.items():
        functions.extend(parse_exported_functions(header_name, text))
        enums.update(parse_enums(text))
        structs.extend(parse_structs(text))
        opaque_types.update(parse_opaque_structs(text))

    functions.sort(key=lambda fn: fn.name)
    structs.sort(key=lambda item: item.name)

    known_structs = {item.name for item in structs}
    known_enums = set(enums.keys())

    parts = [
        '// <auto-generated>',
        '// Generated by build/unity/generate-csharp-bridge.py from lib/zstd.h, lib/zstd_errors.h, and lib/zdict.h.',
        '// This file intentionally covers the shared-library public API surface only.',
        '// </auto-generated>',
        '',
        'using System;',
        'using System.Runtime.InteropServices;',
        'using Unity.Collections;',
        'using Unity.Collections.LowLevel.Unsafe;',
        '',
        'namespace Zstd.Unity',
        '{',
        emit_native_library_block(),
        '',
        emit_constants(),
        '',
    ]

    for enum_name in sorted(enums.keys()):
        parts.extend([emit_enum(enum_name, enums[enum_name]), ''])

    for struct in structs:
        parts.extend([emit_struct(struct, known_structs, known_enums, opaque_types), ''])

    parts.extend([
        '    internal static class NativeMethods',
        '    {',
        '        private const string NativeLibraryName = ZstdNativeLibrary.Name;',
        '',
    ])

    for function in functions:
        parts.extend([emit_function(function, known_structs, known_enums, opaque_types), ''])

    parts.extend([
        '    }',
        '',
        emit_helpers(functions),
        '}',
        '',
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text('\n'.join(parts), encoding='utf-8', newline='\n')

    print(f'Generated {output_path}')
    print(f'Functions: {len(functions)}')
    print(f'Enums: {len(enums)}')
    print(f'Structs: {len(structs)}')
    print(f'Opaque handles: {len(opaque_types)}')


def main() -> None:
    parser = argparse.ArgumentParser(description='Generate Unity C# bindings for zstd public shared-library APIs.')
    parser.add_argument(
        '--output',
        default=str(ROOT / 'build' / 'unity' / 'generated' / 'ZstdNative.cs'),
        help='Path to the generated C# file.',
    )
    args = parser.parse_args()
    generate(Path(args.output).resolve())


if __name__ == '__main__':
    main()
