# S6.5.2 — PyO3 / maturin native build skeleton

S6.5.2 establishes the native build/import path for FeynMap's first Rust
accelerator. It deliberately implements **no routing behavior**.

The purpose of this checkpoint is to prove that:

1. Rust can compile inside the FeynMap repository;
2. PyO3 can expose a Rust module to Python;
3. maturin can package that module as a Python wheel;
4. the wheel can be imported through FeynMap's optional-native loader;
5. one Python 3.8 `abi3` wheel can also import on Python 3.12;
6. the pure-Python package remains usable when the native wheel is absent.

## Project layout

The native accelerator currently lives in:

```text
native/
└── routing_kernel/
    ├── Cargo.toml
    ├── pyproject.toml
    └── src/
        └── lib.rs
```

The main Python project remains setuptools-based.

This separation is intentional. Rust is still optional and experimental. A
native build failure must not prevent installation or use of the Python
reference implementation.

## Cargo

Cargo is Rust's package manager and build system.

For Python developers, it fills several roles normally spread across tools such
as `pip`, `pyproject.toml`, dependency resolution, and a compiler build
command.

The Rust package manifest is:

```text
native/routing_kernel/Cargo.toml
```

A Rust package is called a **crate**.

The crate is currently named:

```text
feynmap-native-routing
```

and is marked `publish = false`, because this is an internal FeynMap
accelerator rather than an independently published Rust library.

## The Rust library type

The Cargo manifest declares:

```toml
[lib]
name = "_feynmap_native_routing"
crate-type = ["cdylib"]
```

A `cdylib` is a compiled dynamic library designed to be loaded by another
language/runtime.

For this project:

```text
Rust source
   ↓ rustc
native shared library
   ↓ packaged by maturin
Python wheel
   ↓ installed with pip
import _feynmap_native_routing
```

Python never executes the Rust source directly. It loads compiled machine code.

## PyO3

PyO3 is the Rust library that understands Python's extension-module interface.

The skeleton currently exposes only:

```text
abi_version()     -> "1.0.0"
implementation()  -> "rust-pyo3"
```

These functions prove that Python has loaded the compiled Rust module and that
the module agrees with the internal routing ABI selected in S6.5.1.

There is intentionally no `NativeRegionIndex` yet. That belongs to S6.6.

## Why PyO3 0.28.3 is pinned

FeynMap currently supports Python 3.8.

The native crate pins:

```toml
pyo3 = { version = "=0.28.3", features = ["abi3-py38"] }
```

rather than moving directly to the newest PyO3 release line.

PyO3 0.28.3 documents support for older Python versions including the current
FeynMap 3.8 floor. The newer PyO3 line is evolving its supported Python floor,
so preserving FeynMap's declared compatibility is more important than using a
newer binding release during the first experiment.

This pin can be reconsidered when FeynMap intentionally raises its Python
minimum.

## abi3

Normal compiled Python extensions are often tied to the exact CPython minor
version they were built against.

For example, without a stable ABI a module built for Python 3.8 may require a
different binary for Python 3.12.

PyO3's `abi3-py38` feature targets Python's limited/stable ABI with Python 3.8
as the minimum.

The first CI build produced:

```text
feynmap_native_routing-0.1.0-cp38-abi3-manylinux_2_34_x86_64.whl
```

That same binary wheel was then imported successfully by:

- CPython 3.8;
- CPython 3.12.

This reduces future wheel count across Python minor versions. Wheels are still
platform/architecture specific, so Linux, macOS, Windows, x86-64, ARM, etc.
remain separate build targets.

## maturin

maturin connects Cargo/PyO3 to Python packaging.

The native subproject has its own `pyproject.toml` with maturin as the build
backend.

The current build tool is pinned to:

```text
maturin 1.15.0
```

The CI build command is essentially:

```bash
cd native/routing_kernel
maturin build --release --interpreter python --out ../../native-dist
```

maturin:

1. invokes Cargo/rustc;
2. detects the PyO3 binding model;
3. creates a correctly tagged Python wheel;
4. makes the resulting native extension installable with `pip`.

## Release build

The build uses Cargo's `--release` mode.

Rust normally has two common build styles:

- **debug** — faster compilation, extra checks/debug information, slower runtime;
- **release** — compiler optimizations enabled, intended for real performance.

Because this work exists specifically to measure native performance, CI tests
the release build.

## Rust version

The crate declares:

```toml
rust-version = "1.83"
```

This is the minimum Rust version expected by the pinned PyO3 line.

The first GitHub Actions build actually used:

```text
rustc 1.98.1
cargo 1.98.1
```

The declaration prevents accidentally writing Rust code that requires a newer
compiler than the supported native project floor.

## Optional loader

Python-side discovery lives in:

```text
feynmap/native_routing.py
```

The normal FeynMap package does not import Rust unconditionally.

When the native wheel is absent:

```python
native_routing_available() == False
```

and the Python implementation continues normally.

When the extension is installed, FeynMap verifies that:

```text
native ABI == feynmap.native_region_routing / 1.0.0
```

before reporting it available.

This is the first layer of the eventual safe fallback design.

## Why the Rust extension is a companion wheel for now

The main FeynMap package currently uses setuptools and remains dependency-free
at its core.

S6.5.2 does **not** replace the root build backend with maturin.

Instead there are temporarily two packages:

```text
feynmap                    pure Python reference package
feynmap-native-routing     optional compiled companion wheel
```

This minimizes risk while Rust is experimental.

If S6.8 demonstrates enough performance value, S6.9 can decide whether release
packaging should:

- keep the accelerator as an optional companion wheel;
- bundle it into FeynMap platform wheels;
- or adopt a mixed Rust/Python root package.

Packaging is therefore downstream of performance evidence rather than assumed
up front.

## CI proof

The `rust-native-build` workflow performs two jobs.

### Build under Python 3.8

It:

1. installs Rust stable;
2. installs maturin;
3. builds the release `abi3` wheel;
4. installs the wheel;
5. imports `_feynmap_native_routing`;
6. validates ABI/implementation metadata through both the direct module and
   `feynmap.native_routing`.

The first successful run used:

```text
Python 3.8.18
rustc 1.98.1
cargo 1.98.1
maturin 1.15.0
```

### Reuse the wheel under Python 3.12

CI uploads the exact wheel built by the Python 3.8 job.

A second job downloads that wheel under Python 3.12, installs it without
recompiling Rust, and imports it successfully.

This proves the intended `abi3` compatibility path rather than merely building
two separate binaries.

## What is deliberately missing

S6.5.2 does not include:

- native region arrays;
- `NativeRegionIndex`;
- the route scoring algorithm;
- Python/Rust output comparison;
- GIL release;
- native fast-path integration;
- production packaging decisions.

Those belong to subsequent checkpoints.

## Next checkpoint

S6.6 should implement the first real Rust class:

```text
NativeRegionIndex
```

It should:

1. accept the static numeric arrays defined in S6.5.1;
2. validate/copy them into Rust-owned `Vec<T>` storage;
3. initially expose the constructor and data validation;
4. then implement the native deterministic route kernel;
5. avoid changing the existing Python production route path.

S6.7 remains responsible for full differential Python/Rust conformance before
the native route can be trusted.
