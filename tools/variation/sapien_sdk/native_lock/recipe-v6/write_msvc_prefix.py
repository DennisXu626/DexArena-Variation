"""Write a UTF-8 CMake /showIncludes prefix from captured compiler bytes.

Run after loading the locked MSVC environment:
    python -B write_msvc_prefix.py --compiler C:/VS/bin/cl.exe \
        --work-dir C:/sdk/private-work --output C:/sdk/private-work/msvc-prefix.cmake

Only one small CPU compile is launched, synchronously. No SDK, renderer or GPU
module is imported. CMake input must be UTF-8. Raw CP936 in a .cmake bracket
argument can silently prevent rules.ninja from being written. Report the raw
bytes, UTF-8 input, and ACP candidate separately: the generated Ninja prefix
must be checked against real compiler output and dependency tracking.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


FIELDS = (b"CMAKE_CL_SHOWINCLUDES_PREFIX", b"CMAKE_C_CL_SHOWINCLUDES_PREFIX",
          b"CMAKE_CXX_CL_SHOWINCLUDES_PREFIX")


def detect_prefix(stdout: bytes, stderr: bytes = b"") -> bytes:
    """Find the first absolute-header include line without any text conversion."""
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        raise TypeError("Compiler output must be captured as bytes")
    for stream in (stdout, stderr):
        for line in stream.splitlines():
            match = re.match(rb"^(.*?)[A-Za-z]:[\\/].*\.h[ \t]*$", line)
            if match:
                prefix = match.group(1)
                if prefix and not any(char in prefix for char in (b"\0", b"\r", b"\n")):
                    return prefix
    raise ValueError("MSVC /showIncludes output contained no localized absolute-header line")


def windows_ansi_code_page() -> int:
    """Read CP_ACP directly; Python UTF-8 mode and console code pages are irrelevant."""
    if os.name != "nt":
        raise RuntimeError("The MSVC prefix helper requires Windows GetACP")
    function = ctypes.WinDLL("kernel32", use_last_error=True).GetACP
    function.argtypes, function.restype = [], ctypes.c_uint
    return int(function())


def decode_prefix(prefix: bytes, code_page: int) -> tuple[str, str]:
    try:
        return prefix.decode("utf-8", errors="strict"), "utf-8"
    except UnicodeDecodeError:
        encoding = f"cp{code_page}"
        return prefix.decode(encoding, errors="strict"), encoding


def cmake_bytes(prefix: str) -> bytes:
    # Bracket arguments preserve the Unicode value, including '$' and quotes.
    # CMake source is always UTF-8; Ninja output encoding is CMake's responsibility.
    equals = "="
    while "]" + equals + "]" in prefix:
        equals += "="
    opening, closing = "[" + equals + "[", "]" + equals + "]"
    text = ("# UTF-8 CMake input; validate generated Ninja prefix against compiler bytes.\nif(MSVC)\n"
            + "".join("  set(" + field.decode("ascii") + " " + opening + prefix + closing + ")\n"
                      for field in FIELDS)
            + "endif()\n")
    return text.encode("utf-8")


def write_prefix(compiler: Path, work: Path, output: Path) -> dict:
    compiler, work, output = compiler.resolve(strict=True), work.resolve(), output.resolve()
    if not output.is_relative_to(work):
        raise ValueError("--output must be inside the explicitly supplied work directory")
    work.mkdir(parents=True, exist_ok=True)
    probe, obj = work / "include_probe.cpp", work / "include_probe.obj"
    if output in (probe, obj, compiler):
        raise ValueError("Prefix output must not replace compiler/probe inputs")
    probe.write_bytes(b"#include <stddef.h>\nint dexarena_include_probe;\n")
    result = subprocess.run([str(compiler), "/nologo", "/showIncludes", "/c", str(probe),
                             "/Fo" + str(obj)], cwd=work, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"MSVC include-prefix CPU probe failed with exit code {result.returncode}")
    if not obj.is_file():
        raise RuntimeError("MSVC include-prefix probe did not produce its object file")
    prefix = detect_prefix(result.stdout, result.stderr)
    code_page = windows_ansi_code_page()
    unicode_prefix, decoded_as = decode_prefix(prefix, code_page)
    prefix_utf8 = unicode_prefix.encode("utf-8")
    expected_ninja_acp = unicode_prefix.encode(f"cp{code_page}", errors="strict")
    payload = cmake_bytes(unicode_prefix)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    return {"output": str(output), "sha256": hashlib.sha256(payload).hexdigest(),
            "prefix_bytes_hex": prefix.hex(), "prefix_bytes_count": len(prefix),
            "raw_prefix_hex": prefix.hex(), "prefix_decoded_as": decoded_as,
            "windows_ansi_code_page": code_page, "cmake_input_encoding": "utf-8",
            "utf8_prefix_hex": prefix_utf8.hex(),
            "expected_ninja_acp_prefix_hex": expected_ninja_acp.hex(),
            "expected_ninja_acp_matches_raw": expected_ninja_acp == prefix,
            "ninja_acp_candidate_only": True,
            "ninja_validation_required": "generated rules prefix must match compiler bytes; real compile must record header dependencies",
            "probe_source_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
            "cpu_compile_count": 1, "capture_mode": "raw_bytes_then_strict_unicode_decode",
            "scope": "compiler-prefix detection only; not a full build or runtime acceptance"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(write_prefix(args.compiler, args.work_dir, args.output), ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, LookupError) as exc:
        parser.exit(2, f"MSVC byte-prefix detection failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
