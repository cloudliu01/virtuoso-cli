# virtuoso-cli — Agent Guide

CLI tool for controlling Cadence Virtuoso from the command line. Three binaries:
`vcli` (main CLI), `vtui` (TUI), `virtuoso-daemon` (background bridge relay, requires `--features daemon`).

## Build & Test

```bash
cargo build                          # debug build
cargo build --release
cargo build --features daemon        # required to build virtuoso-daemon
cargo test                           # 91 unit tests, no live Virtuoso needed
cargo clippy -- -D warnings
cargo fmt --check
```

All CI checks must pass. Run `cargo test && cargo clippy -- -D warnings && cargo fmt --check` before finishing any task.

## Source Layout

```
src/
  main.rs            # clap entry point, command dispatch
  vtui.rs            # TUI binary entry point
  lib.rs             # shared library root
  error.rs           # VirtuosoError enum + exit code mapping
  config.rs          # Config::from_env() — all env vars here
  models.rs          # SessionInfo, JobInfo, shared structs
  history.rs         # per-session SKILL log + global cmd.jsonl
  output.rs          # JSON output helpers
  commands/          # one file per subcommand (session, maestro, skill, ...)
  client/
    bridge.rs        # TCP bridge: VirtuosoClient, STX/NAK protocol, escape_skill_string()
    maestro_ops.rs   # SKILL string builders for Maestro
    window_ops.rs    # SKILL string builders for window management
    skill_sexp.rs    # S-expression parser for SKILL return values
  daemon/            # virtuoso-daemon binary (feature-gated)
  transport/         # SSH tunnel and ControlMaster management
  spectre/           # standalone Spectre netlist / PSF parsing (no bridge needed)
  ocean/             # Ocean expression evaluator
  tui/               # TUI widgets and layout
```

## Critical Invariants

### `VirtuosoResult` has two layers — always use `skill_ok()`

```rust
r.ok()        // transport layer only (STX frame received vs NAK)
r.skill_ok()  // transport + SKILL returned non-nil  ← use this for all SKILL checks
```

SKILL failures return `nil` over a successful STX frame — `ok()` returns `true` for a SKILL
failure. Always check `r.skill_ok()` and propagate `Err(VirtuosoError::Execution(...))`.

### Error propagation — `VirtuosoError`, not `anyhow`

`src/error.rs` defines all error variants and their exit codes. Do not add `anyhow` as a
dependency. Only validate at system boundaries (user input, file I/O, external commands);
trust types internally.

Variants: `Connection`, `Execution`, `Ssh`, `Io`, `Json`, `Timeout`, `Config`, `NotFound`, `Conflict`.

### Security

- All user input entering a SKILL string **must** go through `bridge::escape_skill_string()`
- External commands use `Command::new()` + separate arguments — no shell string concatenation
- Do not commit credentials, license paths, fab process data, or PDK model files

## Adding a New Command

1. Define the JSON output shape first.
2. Add `src/commands/xxx.rs` → `pub fn do_thing(...) -> Result<Value>`.
3. Register in `src/commands/mod.rs` and add a clap variant + dispatch branch in `src/main.rs`.
4. If Virtuoso access is needed: `let client = VirtuosoClient::from_env()?;` and check `skill_ok()`.
5. Put SKILL string construction in `src/client/<domain>_ops.rs`; keep the command layer focused on argument parsing and JSON assembly.

## Binary vs Script boundary

- **Binary**: operations with a fixed success/fail semantic, security boundaries, state that persists across calls (job UUIDs, session files), performance-sensitive sweeps.
- **Script** (`.claude/skills/<name>/scripts/*.py`): multi-step workflows, PDK-specific logic, design methodology — anything that changes with process technology or IP.

## Session Files

Sessions are stored as JSON in `~/.cache/virtuoso_bridge/sessions/<id>.json`.
`SessionInfo::list()` returns all files; `list_alive()` filters to ports that are currently bound.
Test helpers must bind a real `TcpListener` for sessions that should survive concurrent `cleanup()` calls.

## Live Virtuoso Testing

When a task requires starting a live Virtuoso session, always start it as Unix user
`cloud_no_ex_network`. No exceptions. Do not start Virtuoso under any other user.

## Environment Variables

All configuration via env vars — see `src/config.rs` `Config::from_env()`.
Key vars: `VB_HOST`, `VB_PORT`, `VB_SESSION`, `VB_TIMEOUT` (default 30 s; set to 120 for busy servers).
