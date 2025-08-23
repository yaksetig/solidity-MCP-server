# solidity-MCP-server

Server exposing [Model Context Protocol](https://github.com/modelcontextprotocol) tools for working with smart contracts and Circom circuits.

## Available tools

- `compile_solidity` – compile Solidity contracts using `solc`.
- `security_audit` – run [Slither](https://github.com/crytic/slither) static analysis on Solidity code.
- `compile_circom` – compile Circom circuits and return generated artifacts.
- `audit_circom` – audit Circom code with `circomspect`.
- `compile_and_audit` – compile Solidity code then run the security audit.

The Docker image also installs the `circom` compiler and the `circomspect` analyzer. These tools must be present on the system for the corresponding features to function.

## Installing Circom and Circomspect

The Circom compiler is distributed via npm:

```bash
npm install -g circom
```

Circomspect is published on crates.io and can be installed with Cargo:

```bash
cargo install circomspect
```

To build Circomspect from source, clone its repository and run `cargo build` in the project root. To install from source, use:

```bash
cargo install --path cli
```

Run a security analysis by pointing Circomspect at a circuit:

```bash
circomspect path/to/circuit
```

## Tamarin Prover

The Docker image installs the [Tamarin prover](https://tamarin-prover.github.io/) using Homebrew:

```bash
brew install tamarin-prover/tap/tamarin-prover
```

After installation, the `tamarin-prover` command is available inside the container for protocol verification tasks.

When building the prover from source using `stack`, make sure the system has the
`xz-utils` package installed. Stack downloads GHC archives compressed with XZ
and will fail with a missing `configure` script if the archive cannot be
extracted.

