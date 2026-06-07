# Draft: Python Rewrite

## Requirements (confirmed)
- Reimplement the Rust project in Python.
- Preserve the features added beyond `virtuoso-bridge-lite`.
- Use the `conda` environment `venv312` for build and test when useful.
- Support Python 3.10 and newer; use Python 3.12 for development and CI validation.
- Target Rocky Linux 8 / RHEL 8.
- Preserve the existing CLI contract exactly.
- Assume each user can provide a Python 3 environment and install dependencies from `requirements.txt`.
- Deliver CLI and TUI first, while keeping the core library clean enough to expose as a public SDK later.
- Validate against live Virtuoso, including multi-session behavior, with user assistance.

## Technical Decisions
- Treat the current Rust CLI as the behavioral reference, not as code to translate line by line.
- Preserve command names, arguments, JSON output shapes, exit codes, environment variables, and state-file formats unless explicitly approved otherwise.
- Migrate incrementally behind contract tests so Rust and Python implementations can be compared during the transition.
- Keep SKILL input escaping and the distinction between transport success and non-`nil` SKILL success as hard compatibility requirements.
- Keep the main Python API synchronous. Use bounded threads for broadcast and the TUI framework's worker mechanism for blocking calls.
- Keep OpenSSH subprocess integration rather than introducing an SSH protocol library, preserving SSH config, jump-host, and ControlMaster behavior.
- Port the daemon from the current Rust callback-file protocol; do not restore the upstream stdin-framed daemon.
- Keep the Rust CLI and daemon available until the corresponding Python surfaces pass differential and live Virtuoso tests.
- Use Python 3.10-compatible syntax and dependencies even though development runs under Python 3.12.
- Publish a normal `pyproject.toml` package and also maintain `requirements.txt` for user-managed environments.
- Separate CLI adapters from application services and domain models so a later SDK is an export/compatibility task, not a rewrite.
- Use a standard-library-only Python daemon so Virtuoso startup does not depend on the CLI/TUI virtual environment.

## Research Findings
- The current product has three surfaces: `vcli`, `vtui`, and `virtuoso-daemon`.
- The implementation spans CLI dispatch, TCP framing, session discovery/history, SSH tunnels, Spectre jobs/parsers, Ocean/SKILL builders, and a TUI.
- The repository already contains Python 3 and Python 2.7 relay daemons used as remote fallbacks.
- The original `virtuoso-bridge-lite` project is still active and now contains Python implementations of several domains, so reuse must be based on license and behavioral comparison rather than the historical baseline alone.
- Existing Rust tests provide substantial pure-function coverage but need CLI-level golden tests to become a migration safety net.
- The Conda environment named `venv312` now runs Python 3.12.13. It is fresh and currently lacks all project dependencies and development tools.
- `cargo` is not currently available on `PATH`, so the Rust compatibility oracle cannot yet be executed in this shell.
- The current Rust daemon and SKILL resource use callback files to avoid an IC23.1/RHEL8 `ipcWriteProcess` failure after the first request. The upstream Python daemon still uses the older stdin-framing design.
- The bundled Python daemon fallbacks in this repository have drifted from the current SKILL resource and are not drop-in replacements.
- The bundled native daemon binary is stale: it predates the current callback-file protocol and does not implement current `--version` behavior.
- The development host is Rocky Linux 8.10 with kernel 4.18, matching the target OS family.

## Proposed Migration
1. Restore a runnable Rust baseline and capture subprocess-level golden contracts.
2. Add a Python package beside the Rust implementation with `vcli`, `vtui`, and `virtuoso-daemon` entry points.
3. Port pure models, typed errors, configuration, storage formats, S-expression parsing, escaping, and SKILL builders.
4. Port the TCP client while continuing to use the Rust daemon.
5. Port command groups incrementally and compare Python versus Rust outputs and side effects.
6. Port SSH/tunnel behavior, Spectre execution, PSF parsing, and persistent job handling.
7. Rebuild `vtui` using Textual on the shared service layer.
8. Port the Rust daemon's dynamic-port, callback-file, timeout, version-banner, and statistics behavior to a standard-library-only Python daemon.
9. Ship one transition release with both implementations, perform live Virtuoso smoke tests, then remove Rust.

## User Assistance Needed
- Provide or run a PDK-neutral live smoke suite on an IC23.1/RHEL8 host and, if applicable, an IC25 host.
- Permit two simultaneous Virtuoso sessions during validation of dynamic ports and session discovery.
- Provide sanitized netlist, PSF, Maestro, and SKILL-return fixtures when a workflow cannot be reproduced without local data.
- Start the bridge in Virtuoso from the generated setup script when instructed, then report the CIW banner and session ID.

## Open Questions
- Which installed Virtuoso releases must be included in live validation beyond the known IC23.1/RHEL8 compatibility target?
- Which Rust baseline defines "all new features": current `main` at `6b74ed6`, or the recommended `v0.4.0-alpha.9` at `60a861b`? The alpha tag adds transaction, RPC, MCP, profile, SKILL Finder, snapshots, auth/capabilities, plugins, heartbeat, and streaming.

## Scope Boundaries
- INCLUDE: all current user-visible CLI features, session/state compatibility, bridge protocol, SSH/tunnel behavior, simulation workflows, TUI, packaging, and tests.
- EXCLUDE: PDK files, credentials, live-fab data, and behavioral changes unrelated to the language migration.
