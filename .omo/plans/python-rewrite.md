# Plan: Rewrite virtuoso-cli in Python

## Objective

Replace the Rust implementation of `vcli`, `vtui`, and `virtuoso-daemon` with
Python while preserving the current user-visible behavior, state files, bridge
protocol, and Rocky Linux 8 compatibility.

## Confirmed Constraints

- Runtime compatibility: Python 3.10 and newer.
- Development environment: Conda `venv312`, currently Python 3.12.13.
- Deployment OS: Rocky Linux 8 / RHEL 8.
- Compatibility: preserve command names, arguments, global-option placement,
  help/error behavior, JSON and table output, exit codes, environment variables,
  state files, history files, and wire protocol.
- Installation: users prepare Python 3 and install from `requirements.txt`.
- Product scope: CLI and TUI now; public SDK later.
- Architecture must make the later SDK a packaging/export task rather than a
  redesign.
- Live Virtuoso validation is available, including two simultaneous sessions.
- The daemon must retain the callback-file workaround required by IC23.1/RHEL8.

## Selected Compatibility Baseline

The migration baseline is `v0.4.0-alpha.9` at
`60a861b2c147c5241fd733f80b125d43f6212530`.

This tag is 48 commits and roughly 17,000 added lines ahead of the former
`main` checkout. It includes
CLI-visible transaction, RPC, MCP, profile, SKILL Finder, snapshot, auth,
capability, plugin, heartbeat, and streaming functionality.

## Architecture

```text
src/virtuoso_cli/
  __init__.py
  __main__.py
  cli/
    main.py
    parser.py
    dispatch.py
    compatibility.py
    commands/
  application/
    services/
  domain/
    errors.py
    models.py
    identifiers.py
  config/
    settings.py
    dotenv.py
  bridge/
    client.py
    protocol.py
    routing.py
    escaping.py
    sexp.py
    blocking.py
    ops/
  storage/
    paths.py
    sessions.py
    tunnel_state.py
    jobs.py
    history.py
    command_log.py
  transport/
    process.py
    ssh.py
    tunnel.py
  spectre/
    runner.py
    parsers.py
    jobs.py
  ocean/
    builders.py
    corner.py
  tui/
    app.py
    screens/
    widgets/
  daemon/
    main.py
    callbacks.py
    stats.py
  auth/                 # when v0.4 baseline is selected
  capability/           # when v0.4 baseline is selected
  plugins/              # when v0.4 baseline is selected
  rpc/                  # when v0.4 baseline is selected
  mcp/                  # when v0.4 baseline is selected
  transaction/          # when v0.4 baseline is selected
  skill_finder/         # when v0.4 baseline is selected
  streaming/            # when v0.4 baseline is selected
  resources/
    ramic_bridge.il
```

The CLI imports application services, never command implementation details.
Application services depend on domain protocols. Infrastructure modules
implement those protocols. A later SDK will export the domain models, service
interfaces, and concrete client adapters.

## Tooling And Dependencies

Runtime dependencies in `requirements.txt`:

- `pydantic>=2.7,<3`
- `python-dotenv>=1.0,<2`
- `rich>=13.7,<15`
- `textual>=1.0,<2`
- `platformdirs>=4.2,<5`

Development dependencies in `requirements-dev.txt`:

- `pytest>=8,<10`
- `pytest-cov>=5,<8`
- `hypothesis>=6.100,<7`
- `ruff>=0.11,<1`
- `basedpyright>=1.29,<2`

`pyproject.toml` defines the package and entry points. Requirements files are
generated/maintained as installation interfaces for user-managed environments.
Users install dependencies and entry points with `python -m pip install .`;
`requirements.txt` alone is not treated as an application installer.
All code uses Python 3.10-compatible syntax. The daemon is standard-library
only and can be copied independently of the package environment.

## Compatibility Oracle

The selected Rust source commit remains frozen during migration.
A current Rust build is retained as a test oracle until cutover. The stale
checked-in `resources/daemons/virtuoso-daemon-x86_64` is not used.

Known defects are not blindly preserved. Before recording fixtures, create
`tests/contract/exceptions.toml` listing approved compatibility exceptions.
At minimum, the obsolete stdin-framed remote Python daemon selection and the
hardcoded `_RBAutoStart` daemon path must be fixed in the oracle or recorded as
intentional Python corrections.

Differential tests compare:

- exit code;
- stdout and stderr independently;
- parsed JSON with no shape coercion;
- exact table/help/error text where deterministic;
- generated SKILL and SSH argument sequences;
- filesystem changes and serialized schemas.

Only timestamps, elapsed durations, UUIDs, PIDs, and temporary absolute paths
may be normalized.

## TODOs

- [x] Port Python `skill exec`, `skill eval`, `skill load`, and `skill broadcast`.
- [x] Port Python `skill info`.
- [ ] Port Python local `skill find`.
- [ ] Port Python `skill cache` and `skill sync` compatibility surfaces.
- [ ] Port Python `cell` command group.
- [ ] Port Python `schematic` command group.
- [ ] Port Python `maestro` command group.
- [ ] Port Python `window` command group.
- [ ] Port Python Ocean-backed synchronous `sim` commands.
- [ ] Port Python `profile`, `schema`, `tx`, `rpc`, and `mcp` surfaces.
- [ ] Port Python SSH/tunnel, remote deployment, Spectre jobs, and PSF parsing.
- [ ] Rebuild `vtui` with Textual.
- [ ] Run live Virtuoso compatibility wave and final release gate.

## Tasks

### 1. Select And Establish The Frozen Rust Oracle

Pin either `v0.4.0-alpha.9` or current `main`, create a complete feature and
command inventory from that commit, and record approved oracle defects.

Acceptance:

- The chosen commit is recorded in the plan, oracle manifest, and contract
  fixtures.
- Every CLI leaf and non-CLI product surface is listed.
- Features excluded by the baseline choice are explicitly documented.
- Oracle defects are either stabilized in Rust or listed as Python exceptions.

### 2. Create The Python Project Skeleton

Create `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, the
`src/virtuoso_cli` package, and test configuration. Configure console scripts:

- `vcli = virtuoso_cli.cli.main:main`
- `vtui = virtuoso_cli.tui.app:main`
- `virtuoso-daemon = virtuoso_cli.daemon.main:main`

Build the selected Rust commit with a locally installed Rust toolchain and copy
the three binaries into an ignored `.migration/oracle/` directory. Record their
SHA-256 hashes and source commit in `.migration/oracle/manifest.json`.

Acceptance:

- `conda run -n venv312 python --version` reports 3.12.x.
- Python package imports without creating cache/log files.
- Oracle `vcli --version`, `vtui`, and `virtuoso-daemon --version` execute.
- CI installs and tests on Python 3.10 and 3.12.
- A Rocky Linux 8 or UBI 8 job installs the wheel and runs CLI/daemon smoke
  tests without Rust installed.

### 3. Capture Black-Box Compatibility Fixtures

Add `tests/contract/` with a subprocess harness that isolates `HOME`,
`XDG_CACHE_HOME`, cwd, PATH, and environment. Add PTY execution for TTY/table
tests and pipe execution for JSON tests.

Capture every leaf and parent command in the selected baseline:

- `--help`, `--version`;
- missing/invalid arguments;
- global flags before and after nested subcommands;
- offline success and failure behavior;
- stdout/stderr split and exit code;
- deterministic state-file effects.

Add fake TCP, SSH, and Spectre executables so bridge commands can be captured
without Virtuoso.

Acceptance:

- Each CLI leaf has at least one parse/help contract.
- Every semantic exit code `0,1,2,3,5,10` has a fixture.
- Fixture normalization is limited to the documented dynamic fields.
- The harness detects an intentional output, exit-code, or channel mismatch.

### 4. Port Domain Models, Errors, Configuration, And Storage

Implement typed IDs, immutable models, the two-layer `VirtuosoResult` success
contract, typed error variants, and exact exit-code/error-envelope mapping.

Port:

- upward `.env` discovery;
- profile-suffixed environment lookup;
- session auto-selection;
- cache/runtime paths;
- session, tunnel, job, daemon-stat, history, and command-log schemas;
- atomic job writes and liveness checks.

Acceptance:

- `skill_ok` is false for transport success with output `nil`.
- Existing Rust JSON files round-trip without field or type changes.
- Session cleanup retains ports backed by real listeners.
- Config defaults and invalid-input behavior match the Rust oracle.
- Unit and property tests pass on Python 3.10 and 3.12.

### 5. Port SKILL Parsing, Escaping, Builders, And Version Logic

Port S-expression parsing, SKILL string escaping, blocking-expression checks,
Virtuoso version detection, and every Ocean/layout/schematic/Maestro/window
builder.

Keep builders pure and outside CLI modules. Every user-controlled string must
pass through the centralized escape function.

Acceptance:

- Generated SKILL matches oracle fixtures byte-for-byte.
- Strings containing quotes, slashes, newlines, and Unicode are covered.
- The parser covers nested lists, strings, atoms, `nil`, and `t`.
- Security tests prove no command bypasses escaping.

### 6. Port The TCP Client Against The Rust Daemon

Implement the compact JSON request, connect/read timeouts, write half-close,
100 MB response limit, STX/NAK handling, nonstandard-marker warning, stale
`sync_N` drain limit, logging, and session history.

Use synchronous sockets. Implement broadcast with a bounded
`ThreadPoolExecutor`, one client connection per session.

Acceptance:

- Fake-daemon tests cover STX value, STX `nil`, NAK, timeout, empty response,
  oversized response, unknown marker, and ten stale responses.
- Python client passes the same fake-server cases as the Rust oracle.
- Live Rust-daemon smoke test returns `2` for `1+1`.
- Broadcast preserves session association and existing aggregate failure rules.

### 7. Implement The Standard-Library Python Daemon

Port current `src/daemon/main.rs`, not the historical Python relay.

Required behavior:

- CLI `virtuoso-daemon <host> <port>` and `--version`;
- bind port `0` and report the actual port;
- emit `VERSION:` before `PORT:` on stderr;
- accept one request at a time;
- parse request JSON and write raw SKILL to stdout;
- remove stale callback files;
- poll `/tmp/.ramic_cb_<actual_port+1>` and `.done`;
- strip trailing RS;
- return NAK plus `TimeoutError` on deadline;
- write `/tmp/.ramic_stats_<actual_port>`;
- enforce request and response size limits;
- clean temporary files on success, timeout, malformed input, and shutdown;
- use no third-party imports.

Acceptance:

- Protocol tests run identically against Rust and Python daemons.
- Two daemon processes bind distinct OS-assigned ports.
- Invalid arguments and malformed/oversized JSON fail deterministically.
- Timeout recovery allows a subsequent command to succeed.

### 8. Port CLI Parsing, Dispatch, Output, And Offline Commands

Implement a custom `argparse` compatibility layer that:

- accepts global flags at any command depth;
- preserves Clap-style command spelling and defaults;
- reproduces current help, usage errors, and exit code 2;
- dispatches through application services;
- records command history at the same boundary as Rust.

Port `init`, `schema`, session commands, design lookup commands, and job
inspection before bridge-dependent commands.

Acceptance:

- Black-box fixtures match for arguments, help, output channels, and exits.
- Auto format remains table on TTY and JSON on a pipe.
- Specialized table renderers match existing output.
- `schema` retains existing behavior, including known legacy quirks, until a
  separately approved compatibility break.

### 9. Port Bridge-Dependent Command Groups

Port command groups in this order:

1. `skill`;
2. `cell`;
3. `schematic`;
4. `maestro`;
5. `window`;
6. Ocean-backed synchronous `sim`;
7. `process` and `design`.

When the v0.4 baseline is selected, also port `tx`, `rpc`, `mcp`, `profile`,
skill finder, Maestro snapshot, schematic polish-label, heartbeat, auth,
capability, plugin, and streaming surfaces.

Each command returns a typed result model; JSON assembly occurs in one output
adapter. Every SKILL result check uses `skill_ok` where `nil` signals failure.

Acceptance:

- Each command group passes its Rust differential suite before the next group.
- Exact JSON keys, nullability, list ordering, and exit behavior are preserved.
- Generated SKILL sequences match fake-server captures.
- No CLI module contains SKILL construction.

### 10. Port SSH, Tunnel, Remote Deployment, And Async Spectre Jobs

Use OpenSSH executables with argument arrays. Preserve jump hosts, custom SSH
config/key/port, login-shell behavior, ControlMaster fallback, profile-aware
state, uploads/downloads, remote discovery, and dry-run semantics.

Port Spectre runner, PSF ASCII parser, async job registry, remote `nohup`
execution, refresh, cancellation, cleanup, and atomic state writes.

Acceptance:

- Fake executables verify argv without shell interpolation.
- ControlMaster failure retries without multiplexing.
- Local and remote job lifecycle fixtures match Rust state and output.
- PSF fixtures match Rust numeric data, including sweep layouts and errors.
- Rocky 8 smoke tests cover direct SSH and configured jump-host behavior when
  available.

Update the SKILL resource and remote deployment to launch Python through
`/usr/bin/env -u LD_LIBRARY_PATH -u LD_PRELOAD`, preserving dynamic sessions,
the ready banner, callback workaround, and UID-scoped stop behavior.

Acceptance:

- Protocol tests run identically against Rust and Python daemons.
- Two daemon processes bind distinct OS-assigned ports.
- Session files use the selected actual ports.
- IC23.1/RHEL8 handles at least 100 sequential commands without the historical
  second-command failure.
- Timeout recovery allows a subsequent command to succeed.

### 11. Rebuild `vtui` With Textual

Implement sessions, jobs, tunnel/config views, overlays, keyboard navigation,
refresh, log display, confirmation, and config editing using the shared
application services.

Blocking operations run through Textual threaded workers. TUI code does not
own storage, SSH, bridge, or Spectre logic.

Acceptance:

- Textual Pilot tests cover navigation, refresh, selection, overlays, config
  save, cancellation, and error display.
- `NO_COLOR` and non-color behavior are preserved.
- Manual Rocky 8 terminal QA verifies resize, keyboard input, and clean exit.

### 12. Live Virtuoso Compatibility Wave

Install the package into a Python 3.10+ user environment. Generate a setup IL
file containing absolute paths to the standard-library daemon and bridge
resource.

Run:

- bridge startup and `1+1`;
- SKILL non-`nil`, `nil`, and error cases;
- 100 sequential requests;
- timeout then recovery;
- Unicode and large response handling;
- reload, stop, and restart;
- session list/current/history/cleanup;
- two simultaneous Virtuoso sessions and broadcast;
- a PDK-neutral cell open/info/save/close flow;
- a PDK-neutral schematic read-only flow;
- Maestro discovery when available;
- TUI refresh against live session/job data.

Record Virtuoso version, OS, Python executable, daemon version, and sanitized
outputs in `tests/live/reports/`.

Acceptance:

- No callback deadlock or second-request failure.
- Exact CLI compatibility tests remain green.
- No test requires credentials, license paths, PDK model data, or proprietary
  design content in the repository.

### 13. Cutover, Packaging, And Rust Removal

Publish one transition release where Python entry points are primary and Rust
oracle binaries remain CI-only. Update README, AGENTS.md, CI, release workflow,
installation instructions, and attribution for reused MIT code.

After one successful transition release and the live compatibility wave:

- remove Rust source and Cargo workflows;
- remove stale daemon artifacts;
- retain golden compatibility fixtures;
- expose a documented internal service API without promising public SDK
  stability yet.

Acceptance:

- Fresh Rocky 8 user environment installs from `requirements.txt` and the
  project package.
- `vcli`, `vtui`, and `virtuoso-daemon` resolve to Python entry points.
- Full tests, Ruff, basedpyright, packaging build, and live smoke report pass.
- Repository contains no credentials, fab data, PDK models, or license paths.

## Verification Commands

```bash
conda run -n venv312 python -m pip install -r requirements-dev.txt
conda run -n venv312 ruff format --check .
conda run -n venv312 ruff check .
conda run -n venv312 basedpyright
conda run -n venv312 pytest
conda run -n venv312 python -m build
```

CI additionally runs the same suite under Python 3.10.

## Live Daemon Startup Procedure

During migration, do not use
`resources/daemons/virtuoso-daemon-x86_64`; it is stale.

For an immediate protocol-compatible live smoke test without Cargo, stage the
newer tagged bridge assets:

```bash
cd /home/cloud/Github_opensource/virtuoso-cli
mkdir -p "$HOME/.local/share/vcli-bridge-test" "$HOME/.cargo/bin"
git archive v0.4.0-alpha.9 \
  resources/ramic_bridge.il \
  resources/daemons/virtuoso-daemon-x86_64 |
  tar -x -C "$HOME/.local/share/vcli-bridge-test"
install -m 755 \
  "$HOME/.local/share/vcli-bridge-test/resources/daemons/virtuoso-daemon-x86_64" \
  "$HOME/.cargo/bin/virtuoso-daemon"
```

In Virtuoso CIW:

```skill
load("/home/cloud/.local/share/vcli-bridge-test/resources/ramic_bridge.il")
```

Wait for the Ready banner. This tagged binary implements the callback protocol
and is sufficient for connectivity testing, although it reports daemon version
`0.4.0-alpha.7`.

For the exact selected Rust oracle:

```bash
source "$HOME/.cargo/env"
cd /home/cloud/Github_opensource/virtuoso-cli
cargo build --release --features daemon
install -D -m 755 target/release/virtuoso-daemon \
  "$HOME/.cargo/bin/virtuoso-daemon"
install -D -m 755 target/release/vcli "$HOME/.cargo/bin/vcli"
```

Then start Virtuoso from the same user account. In CIW:

```skill
load("/home/cloud/Github_opensource/virtuoso-cli/resources/ramic_bridge.il")
```

The file auto-starts the daemon. Wait for a banner containing a nonzero
`Session` and `Port`. In a terminal:

```bash
vcli session list
vcli skill exec '1+1'
```

If the banner does not appear, run in CIW:

```skill
RBStop()
load("/home/cloud/Github_opensource/virtuoso-cli/resources/ramic_bridge.il")
```

If a stale daemon remains:

```skill
RBStopAll()
load("/home/cloud/Github_opensource/virtuoso-cli/resources/ramic_bridge.il")
```

After task 7, the generated Python setup IL replaces this temporary Rust
procedure and points directly at the standard-library Python daemon.

## Final Release Gate

- Python 3.10 and 3.12 test matrices pass.
- Ruff and basedpyright are clean.
- All Rust/Python differential contracts pass.
- Rocky 8 install and TUI manual QA pass.
- Live Virtuoso single-session, sequential-request, timeout-recovery, and
  two-session tests pass.
- Rust is removed only after the transition release satisfies every gate.
