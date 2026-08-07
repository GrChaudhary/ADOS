"""
ADOS-authored, trusted runner for the raw_code onboarding track — staged
into the sandbox image at build time (never target-repo code, see
sandbox_runner.py's _build_raw_code_image). Given a target Python file and
one top-level function name, imports the module, resolves the function,
calls it with JSON-decoded arguments from stdin, and prints exactly one
JSON line to real stdout: {"result": ...} on success, {"error": ...} on
any failure — never anything else. Both module import and the function
call run with real stdout redirected to a buffer, so a stray print()
inside target code can never interleave with (and corrupt) this script's
own single line of output.

Usage: python raw_code_runner.py <entrypoint_path> <function_name>
       (a JSON object of call arguments piped via stdin)
"""

import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import sys

_MAX_RESULT_BYTES = 2_000_000


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _load_target_function(entrypoint_path: str, function_name: str):
    spec = importlib.util.spec_from_file_location("target_module", entrypoint_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {entrypoint_path!r}")
    module = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)

    fn = getattr(module, function_name, None)
    # Defense-in-depth: Turn 2's synthesize_session already constrains
    # function_name to one of the names inspector.py's AST scan found, but
    # this is the last point before real execution -- never trust a
    # single upstream call site alone for something this consequential.
    if not (inspect.isfunction(fn) and fn.__module__ == module.__name__) or fn.__name__.startswith("_"):
        raise RuntimeError(f"{function_name!r} is not an eligible top-level function in {entrypoint_path!r}")
    return fn


def main() -> None:
    if len(sys.argv) != 3:
        _emit({"error": f"usage: raw_code_runner.py <entrypoint_path> <function_name>, got argv={sys.argv[1:]!r}"})
        sys.exit(1)
    entrypoint_path, function_name = sys.argv[1], sys.argv[2]

    try:
        arguments = json.loads(sys.stdin.read() or "{}")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be a JSON object")
    except (json.JSONDecodeError, ValueError) as e:
        _emit({"error": f"invalid arguments on stdin: {e}"})
        sys.exit(1)

    try:
        fn = _load_target_function(entrypoint_path, function_name)
        with contextlib.redirect_stdout(io.StringIO()):
            result = fn(**arguments)
            if inspect.isawaitable(result):
                result = asyncio.run(result)
    except Exception as e:  # noqa: BLE001 -- any target-code failure becomes clean evidence, not a crash
        _emit({"error": f"{type(e).__name__}: {e}"})
        sys.exit(1)

    try:
        serialized = json.dumps(result)
    except TypeError as e:
        _emit({"error": f"function result is not JSON-serializable: {e}"})
        sys.exit(1)

    if len(serialized.encode()) > _MAX_RESULT_BYTES:
        _emit({"error": f"function result exceeds the {_MAX_RESULT_BYTES}-byte limit"})
        sys.exit(1)

    _emit({"result": result})


if __name__ == "__main__":
    main()
