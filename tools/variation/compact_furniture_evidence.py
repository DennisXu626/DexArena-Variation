"""Losslessly deduplicate furniture capture records without running simulation.

Material and mesh profiles are stored once. Explicit part rows reference them;
expand restores the original JSON and its exact capture-time bytes.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

FORMAT = "furniture-evidence-compact-v1"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pretty(value, level=0, key=""):
    """Keep arrays and audit rows together, with readable section boundaries."""
    inline = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if not isinstance(value, (dict, list)) or not value:
        return inline
    if (isinstance(value, list) and all(not isinstance(x, (dict, list)) for x in value)
            or key.startswith("material_") or key in ("$ref",)
            or len(inline) <= 140):
        return inline
    indent, child = "  " * level, "  " * (level + 1)
    if isinstance(value, list):
        rows = [json.dumps(x, ensure_ascii=False, allow_nan=False)
                if key in ("parts", "shapes") else pretty(x, level + 1) for x in value]
        return "[\n" + ",\n".join(child + row for row in rows) + "\n" + indent + "]"
    rows = [json.dumps(k, ensure_ascii=False) + ": " + pretty(v, level + 1, k)
            for k, v in value.items()]
    return "{\n" + ",\n".join(child + row for row in rows) + "\n" + indent + "}"


def expand(document):
    if document.get("format") != FORMAT:
        raise ValueError("Unknown compact evidence format")

    def visit(value):
        if isinstance(value, list):
            return [visit(x) for x in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise ValueError("A profile reference must contain only $ref")
            table, name = value["$ref"].split("/", 1)
            if table not in ("materials", "meshes"):
                raise ValueError("Unknown profile table")
            return deepcopy(document[table][name])
        return {k: visit(v) for k, v in value.items()}

    return visit(document["data"])


def original_bytes(document):
    raw = (json.dumps(expand(document), ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if document["capture"]["newline"] == "CRLF":
        raw = raw.replace(b"\n", b"\r\n")
    elif document["capture"]["newline"] != "LF":
        raise ValueError("Unknown capture line endings")
    if sha(raw) != document["capture"]["file_sha256"]:
        raise ValueError("Expanded capture does not match its original SHA-256")
    return raw


def compact(raw):
    source = json.loads(raw)
    canonical = (json.dumps(source, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    newline = "LF" if raw == canonical else "CRLF"
    if raw != canonical and raw != canonical.replace(b"\n", b"\r\n"):
        raise ValueError("Input must be an original indent=2 UTF-8 capture")
    pools = {"materials": {}, "meshes": {}}
    indices = {table: {} for table in pools}

    def visit(value):
        if isinstance(value, list):
            return [visit(x) for x in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            raise ValueError("Input already contains a reserved $ref")
        table = ("materials" if {"base_color", "roughness", "metallic"} <= value.keys()
                 else "meshes" if {"vertices", "triangles", "vertex_normal", "vertex_uv"} <= value.keys()
                 else None)
        if table:
            # Preserve key order too, so expansion recovers exact original bytes.
            identity = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            if identity not in indices[table]:
                name = ("material_" if table == "materials" else "mesh_") + str(len(pools[table]))
                indices[table][identity] = name
                pools[table][name] = value
            return {"$ref": table + "/" + indices[table][identity]}
        return {k: visit(v) for k, v in value.items()}

    data = visit(source)
    result = dict(format=FORMAT, capture={"file_sha256": sha(raw), "bytes": len(raw),
                                        "newline": newline, "serialization": "UTF-8, indent=2, trailing newline"},
                  **pools, data=data)
    if original_bytes(result) != raw:
        raise ValueError("Compaction must preserve every capture byte")
    return result


def archive_manifest(raw, evidence_bytes):
    """Update the evidence reference while preserving the capture identity."""
    manifest = json.loads(raw)
    evidence = json.loads(evidence_bytes)
    original_bytes(evidence)
    if manifest["evidence"]["sha256"] != evidence["capture"]["file_sha256"]:
        raise ValueError("Manifest does not refer to this original capture")
    manifest["evidence"]["capture_sha256"] = manifest["evidence"]["sha256"]
    manifest["evidence"]["sha256"] = sha(evidence_bytes)
    manifest["archive"] = {
        "format": FORMAT, "capture_manifest_sha256": sha(raw),
        "capture_manifest_newline": "CRLF" if b"\r\n" in raw else "LF",
        "conversion_tool": "tools/variation/compact_furniture_evidence.py",
        "conversion_tool_sha256": sha(Path(__file__).read_bytes()),
    }
    verify_manifest(manifest, evidence_bytes)
    return manifest


def verify_manifest(manifest, evidence_bytes):
    if manifest["archive"]["format"] != FORMAT:
        raise ValueError("Unknown manifest archive format")
    if sha(evidence_bytes) != manifest["evidence"]["sha256"]:
        raise ValueError("Archived evidence SHA-256 mismatch")
    raw = original_bytes(json.loads(evidence_bytes))
    if sha(raw) != manifest["evidence"]["capture_sha256"]:
        raise ValueError("Original evidence SHA-256 mismatch")
    original = deepcopy(manifest)
    archive = original.pop("archive")
    original["evidence"]["sha256"] = original["evidence"].pop("capture_sha256")
    encoded = (json.dumps(original, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if archive["capture_manifest_newline"] == "CRLF":
        encoded = encoded.replace(b"\n", b"\r\n")
    if sha(encoded) != archive["capture_manifest_sha256"]:
        raise ValueError("Original manifest SHA-256 mismatch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("compact", "expand", "verify"))
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.operation != "verify" and args.output is None:
        parser.error("--output is required")
    if args.output is not None and args.output.resolve() == args.input.resolve():
        parser.error("Use a different output path; the source capture is preserved")
    if args.output is not None:
        if args.output.exists():
            parser.error("Output already exists; choose a new path")
        args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.operation == "compact":
        result = compact(args.input.read_bytes())
        args.output.write_bytes((pretty(result) + "\n").encode("utf-8"))
    else:
        result = json.loads(args.input.read_bytes())
        if args.operation == "verify" and "archive" in result:
            verify_manifest(result, (args.input.parent / result["evidence"]["file"]).read_bytes())
        else:
            raw = original_bytes(result)
            if args.operation == "expand":
                args.output.write_bytes(raw)
    print(json.dumps({"status": "passed", "file": str(args.input)}))


if __name__ == "__main__":
    main()
