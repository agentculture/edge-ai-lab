# Orin NX 16GB — Qwen3.5-4B Q4_K_M cortex on the llama.cpp lane + hand

**Status: DECLARED, UNVALIDATED.** No Orin NX 16GB is owned by the lab (operator decision, 2026-08-29); this arm is authored so the profile exists the day one arrives. Nothing in this directory has
been booted or measured; every value is a declaration with its source named
beside it, per `docs/lab-conventions.md` §3. No throughput figure appears
here on purpose.

## What this arm is

A lobes **card profile** (`profile-override.toml`, to be installed as
`<deploy-dir>/profiles/orin-nx-16.toml`) for a Jetson Orin NX 16GB: a small
GGUF `cortex` served by the `llamacpp-primary` lane
(`../lobes-cli/lobes/templates/fleet/docker-compose.yml`, compose profile
`llamacpp`, activated because the catalog gear's engine is `llama.cpp` —
`../lobes-cli/lobes/profiles/render.py` `role_engine`), plus the `hand` lobe on
the vLLM hand lane; `senses` and the pooling gears off.

**Precondition on the lobes side:** `unsloth/Qwen3.5-4B-GGUF:Q4_K_M` is not in
`../lobes-cli/lobes/catalog.py`. lobes derives the engine from the catalog
entry, so rendering this profile fails until a `SupportedModel(...,
engine=ENGINE_LLAMA_CPP, status="configured")` entry exists — the existing
pattern is `unsloth/Qwen3.8-27B-GGUF:UD-Q4_K_M` (`catalog.py` ~line 1028).
The loader check below passes because the loader validates knobs, not catalog
membership. The catalog entry is part of the lobes-cli issue in Hand-off.

## Roles this board is declared to host

| role | declared | source of the declaration |
|---|---|---|
| cortex | `unsloth/Qwen3.5-4B-GGUF:Q4_K_M`, 32768 ctx, no `gpu_mem_util` | Q4_K_M file is 2.55 GiB on the HF tree listing (`api/models/unsloth/Qwen3.5-4B-GGUF/tree/main`, 2026-08-29); `gpu_mem_util` omitted because it renders a vLLM flag the llama.cpp lane does not consume; 32768 is a declared ceiling, not the file's native window |
| senses | `feasible = false` | the int4 W4A16 Gemma senses gear the 64GB card serves does not fit beside cortex + hand in 16 GB |
| hand | `LiquidAI/LFM2.5-1.2B-Instruct`, util 0.20, 8192 ctx, 2 seqs, `TRITON_ATTN` | ~2.4 GiB bf16 weights (`orin.toml` hand comment) / 16 GB ≈ 0.15 plus KV headroom — arithmetic, not a measurement |
| embedder / reranker | `feasible = false` | `orin.toml`'s 0.06 of ~61 GiB is ~3.7 GiB; 0.06 of 16 GB is below the 0.6B gears' ~1.2 GiB bf16 weights — declared off until measured |

`stt`/`tts` are fixed audio sidecars, not profile roles
(`../lobes-cli/lobes/profiles/shapes.py` `AUDIO_ROLES`); whether they run is
decided by the deployment shape a box applies — the `orin-small`-style shape
(`../lobes-cli/lobes/profiles/builtin_shapes/orin-small.toml`, itself
DECLARED, UNVALIDATED) is the nearest existing pattern.

## Why lobes cannot serve this board today

`../lobes-cli/lobes/machines/_strategy.py` (docstring around line 62) records
that the whole Orin family — 64GB / 32GB / NX / Nano — carries `orin` in the
device-tree model string, and that resolving a Nano to the 64GB card "would
hand it a senses budget (util 0.45 at a 256K window) it cannot possibly hold".
`../lobes-cli/tests/test_detect.py:334-344` pins the behaviour: a probe with
`device_tree="NVIDIA Jetson Orin Nano Developer Kit"` and `meminfo_gb=7.4`
resolves to `UNKNOWN`, i.e. the conservative `base` profile, **not** `orin`.
`base.toml` declares a `Qwen/Qwen3.5-4B` vLLM cortex at util 0.30 — untested on
any 8/16 GB board. So a new card is needed on the lobes side, not a tweak.

### CardStrategy sketch (for `../lobes-cli/lobes/machines/`)

`CardStrategy.matches()` (`_strategy.py`) accepts a name marker plus optional
`compute_capability` and `total_memory_gb` constraints, and the memory check is
a band of 0.80–1.25 × the declared figure. Registration order is precedence
(`_registry.py`), so the smaller variants must register **before** `orin`
(declared `total_memory_gb=64`, band 51.2–80 GB — a 7.4 GB or 15.x GB probe
already misses it, which is why they fall to UNKNOWN today):

| module | `name_markers` | `compute_capability` | `total_memory_gb` | band | device-tree string |
|---|---|---|---|---|---|
| `orin_nano.py` | `("orin nano",)` | `sm_87` | 8 | 6.4–10 GB | `NVIDIA Jetson Orin Nano Developer Kit` |
| `orin_nx.py` | `("orin nx",)` | `sm_87` | 16 | 12.8–20 GB | `NVIDIA Jetson Orin NX` (module; carrier boards vary) |

Open on the lobes side: the Orin NX also ships as an 8 GB module and the AGX
Orin as a 32 GB module — both would need their own rows (32 GB: band 25.6–40)
or the bands overlap; the name marker alone cannot separate them.

## Loader check

Both files were loaded read-only through lobes-cli's operator-profile loader
(`lobes.profiles.loader.discover_operator_profiles`) from a throwaway copy:

```bash
# throwaway copy: only lobes/, pyproject.toml, uv.lock copied out of ../lobes-cli (never edited)
cp -r ../lobes-cli/lobes ../lobes-cli/pyproject.toml ../lobes-cli/uv.lock "$SCRATCH/lobes-ro/"
mkdir -p "$SCRATCH/deploy-ro/profiles" && cp profile-override.toml "$SCRATCH/deploy-ro/profiles/orin-nx-16.toml"
cd "$SCRATCH/lobes-ro" && PYTHONPATH=. uv run --no-project python3 -c '
import sys; from lobes.profiles.loader import discover_operator_profiles
p = discover_operator_profiles(sys.argv[1])["orin-nx-16"]
print(p.summary); print({r: (rp.feasible, rp.model) for r, rp in p.roles.items()})' "$SCRATCH/deploy-ro"
```

Output on 2026-08-29 (lobes-cli 0.69.2):

```text
Jetson Orin NX 16GB (Ampere sm_87, 16 GB unified) — DECLARED, UNVALIDATED: small llama.cpp GGUF cortex + hand; no senses, no pooling gears
cortex: feasible=True model='unsloth/Qwen3.5-4B-GGUF:Q4_K_M' max_model_len=32768 | senses: feasible=False | hand: feasible=True model='LiquidAI/LFM2.5-1.2B-Instruct' gpu_mem_util=0.2 max_model_len=8192 attention_backend='TRITON_ATTN' max_num_seqs=2 | embedder: feasible=False | reranker: feasible=False
LOADED OK: orin-nx-16
```

The loader accepted every knob (an unknown knob is a load error per
`../lobes-cli/lobes/profiles/schema.py`), which is all this proves.

## Rollback

Declared arm: nothing is running, so rollback is removing the operator profile
from a lobes deploy dir and re-rendering. On the box, with `LOBES_DEPLOY_DIR`
set to the deploy dir (default `~/.lobes`):

```bash
rm -f "${LOBES_DEPLOY_DIR:-$HOME/.lobes}/profiles/orin-nx-16.toml"
lobes init            # re-render .env from the built-in card profile
lobes doctor --json   # expect no profile named orin-nx-16 in the output
```

Executed: not yet — there is no box to execute it on (see Status).

## Build footprint

- Build time: not built — declared arm (no image built)
- Disk delta: 0 B — no image pulled, no weights downloaded
- Retention: nothing to prune

## Pins

- `image_digest`: `sha256:f7c67c102b08252e963f9e5f92c3a36554c8f69305eb7ea257c6cd12e24c3191` — `ghcr.io/nvidia-ai-iot/llama_cpp`, build `38406d597`, CUDA 13, `CUDAARCHS=87;110`, **sm_87 exercised** (`../lobes-cli/docs/image-ledger.md`, "the llama.cpp lane" row; default of `LLAMACPP_IMAGE` in the fleet compose)
- `model_revision`: `e87f176479d0855a907a41277aca2f8ee7a09523` — `git ls-remote https://huggingface.co/unsloth/Qwen3.5-4B-GGUF HEAD`, 2026-08-29
- `sparkrun_version`: empty — Jetson arms do not use sparkrun (`docs/lab-conventions.md` §10)
- `jetson_containers_commit`: `3717f380fc9543090c7a2e07d00772d6e05907f8` — `git -C ../jetson-containers-nv rev-parse HEAD`, 2026-08-29
- `jetson_containers_packages`: `llama_cpp:b7368` — the jetson-containers default; the pinned ledger image is NVIDIA's own build, recorded so a rebuild can be compared (`../jetson-containers-nv/packages/llm/llama_cpp/config.py`)
- `model_gear_version`: `0.69.2` — `../lobes-cli/pyproject.toml`, 2026-08-29

## Hand-off

Proposed to lobes-cli as an issue (card profiles + CardStrategy sketch):
<https://github.com/agentculture/lobes-cli/issues/231> (filed 2026-08-29 via the `communicate` skill; nothing in `../lobes-cli` was edited).
