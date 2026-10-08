#!/usr/bin/env bash
# Create the project-local opam switch (./_opam) with Rocq + coq-lsp.
# Run inside `nix develop ./nix` so gmp/pkg-config are visible to opam.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${OCAML_VERSION:=4.14.2}"
: "${ROCQ_VERSION:=9.1.1}"
export OPAMASSUMEDEPEXTS=1

if ! opam switch list -s 2>/dev/null | grep -Fxq "$PWD"; then
  echo "[rlb] creating local switch with OCaml $OCAML_VERSION"
  opam switch create . "ocaml-base-compiler.$OCAML_VERSION" --no-install -y --no-switch
fi
eval "$(opam env --switch=. --set-switch)"

if ! opam repo list -s | grep -Fxq coq-released; then
  opam repo add --this-switch coq-released https://rocq-prover.org/opam/released
fi

# `coq.X` is the compatibility metapackage: rocq-prover + rocq-stdlib plus the
# coqc/coqtop names that LLMs know. coq-lsp brings petanque for future harnesses.
opam install -y "coq.$ROCQ_VERSION" "coq-lsp"
echo "[rlb] done: $(coqc --version | head -1)"
