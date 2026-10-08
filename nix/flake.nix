{
  description = "rocq_llm_bench: system deps for the Rocq opam switch and the Python meta-harness. Rocq comes from opam (./_opam), Python from uv.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/64c08a7ca051951c8eae34e3e3cb1e202fe36786";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      devShells.${system}.default = pkgs.mkShell {
        # Only what opam/uv cannot provide themselves. opam, uv, jq, git and the
        # agent CLIs (claude, codex, pi) are installed systemwide on this machine.
        packages = with pkgs; [
          gnumake m4 unzip patch pkg-config perl which rsync
          gmp        # zarith (Rocq's bignums)
          zlib
          curl cacert
          python3    # for the agents: numeric sanity checks, scripting. Before the sandbox they
                     # got the rlb venv's python by accident (`uv run` prepends .venv/bin to PATH);
                     # the sandbox hides the repo, so the benchmark environment provides one explicitly.
          bubblewrap # opam's build sandbox, and the harness sandbox (rlb/sandbox.py)
          passt      # `pasta`: per-attempt network namespace + packet capture (rlb/net.py)
          nftables   # egress allowlist inside that namespace (rlb/sandbox.py)
          mitmproxy  # TLS-terminating proxy inside it: strips server-side tools, exact API timing (rlb/proxy.py)
          openssl    # the proxy CA, generated once per run (rlb/sandbox.py ensure_ca)
        ];

        shellHook = ''
          export SSL_CERT_FILE="${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt"
          export NIX_SSL_CERT_FILE="$SSL_CERT_FILE"
          # gmp etc. come from this shell; stop opam from trying to install depexts.
          export OPAMASSUMEDEPEXTS=1
          export RLB_ROOT="$PWD"  # `nix develop ./nix` is run from the repo root
          if [ -d "$PWD/_opam" ]; then
            eval "$(opam env --switch=. --set-switch)"
          else
            echo "[rlb] no ./_opam switch yet; run scripts/setup-rocq.sh (builds Rocq, ~15 min)" >&2
          fi
        '';
      };
    };
}
