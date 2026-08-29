# Orin Nano 8GB — LFM2.5-1.2B hand + audio sidecars (vLLM hand lane)

**Status: DECLARED, UNVALIDATED.** The Orin Nano 8GB exists but is not connected to the lab yet (operator decision, 2026-08-29). Nothing in this directory has
been booted or measured; every value is a declaration with its source named
beside it, per `docs/lab-conventions.md` §3. No throughput figure appears
here on purpose.

## What this arm is

A lobes **card profile** (`profile-override.toml`, to be installed as
`<deploy-dir>/profiles/orin-nano-8.toml`) for a Jetson Orin Nano 8GB: `cortex`
and `senses` declared `feasible = false`, the `hand` lobe
(`LiquidAI/LFM2.5-1.2B-Instruct`) hosted, pooling gears off. The
configuration is named `vllm-hand-audio`, **not** `llamacpp-…`: lobes' only
llama.cpp lane is `llamacpp-primary`, which serves `cortex` alone
(`../lobes-cli/lobes/profiles/render.py` `LLAMA_CPP_ACTIVATION_ENV` maps only
`cortex`; `../lobes-cli/lobes/templates/fleet/docker-compose.yml` has no
llama.cpp hand lane). So `hand` on this board can only run through the vLLM
`vllm-hand` lane, exactly as the 64GB Orin card declares it
(`../lobes-cli/lobes/profiles/builtin/orin.toml` `[roles.hand]`).

## Roles this board is declared to host

| role | declared | source of the declaration |
|---|---|---|
| cortex | `feasible = false` | no 8 GB-class cortex in `../lobes-cli/lobes/catalog.py`; NVFP4 primaries need Blackwell (`../lobes-cli/lobes/machines/orin.py`) |
| senses | `feasible = false` | the 12B senses gear cannot fit beside hand in 8 GB |
| hand | `LiquidAI/LFM2.5-1.2B-Instruct`, util 0.40, 8192 ctx, 2 seqs, `TRITON_ATTN` | ~2.4 GiB bf16 weights (`orin.toml` hand comment); 7.4 GB usable is the Nano fixture in `../lobes-cli/tests/test_detect.py`; `TRITON_ATTN` copied from `orin.toml` (sm_87); the 0.40 is arithmetic, not a measurement — `orin.toml` records the 64GB card refuting its own declared hand budget twice |
| embedder / reranker | `feasible = false` | fit by weight (~1.2 GiB bf16 each) but not beside hand + stt + tts on 8 GB; re-declare after a measured hand boot |

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

## The Nano-sized role question (for lobes-cli)

A box that hosts only `hand` + audio is a shape lobes does not have: the
nearest, `orin-small`, also hosts `minor`, `embedder` and `reranker`. Whether
the right seam is a new small role, a new shape (`nano-hand-audio`), or simply
this card profile plus `[[exclusive_roles]]`, is asked in the lobes-cli issue
below — not decided here.

## Loader check

Both files were loaded read-only through lobes-cli's operator-profile loader
(`lobes.profiles.loader.discover_operator_profiles`) from a throwaway copy:

```bash
# throwaway copy: only lobes/, pyproject.toml, uv.lock copied out of ../lobes-cli (never edited)
cp -r ../lobes-cli/lobes ../lobes-cli/pyproject.toml ../lobes-cli/uv.lock "$SCRATCH/lobes-ro/"
mkdir -p "$SCRATCH/deploy-ro/profiles" && cp profile-override.toml "$SCRATCH/deploy-ro/profiles/orin-nano-8.toml"
cd "$SCRATCH/lobes-ro" && PYTHONPATH=. uv run --no-project python3 -c '
import sys; from lobes.profiles.loader import discover_operator_profiles
p = discover_operator_profiles(sys.argv[1])["orin-nano-8"]
print(p.summary); print({r: (rp.feasible, rp.model) for r, rp in p.roles.items()})' "$SCRATCH/deploy-ro"
```

Output on 2026-08-29 (lobes-cli 0.69.2):

```text
Jetson Orin Nano 8GB (Ampere sm_87, 8 GB unified) — DECLARED, UNVALIDATED: hand + audio sidecars only; no cortex/senses/pooling gears
cortex: feasible=False | senses: feasible=False | hand: feasible=True model='LiquidAI/LFM2.5-1.2B-Instruct' gpu_mem_util=0.4 max_model_len=8192 attention_backend='TRITON_ATTN' max_num_seqs=2 | embedder: feasible=False | reranker: feasible=False
LOADED OK: orin-nano-8
```

The loader accepted every knob (an unknown knob is a load error per
`../lobes-cli/lobes/profiles/schema.py`), which is all this proves.

## Rollback

Declared arm: nothing is running, so rollback is removing the operator profile
from a lobes deploy dir and re-rendering. On the box, with `LOBES_DEPLOY_DIR`
set to the deploy dir (default `~/.lobes`):

```bash
rm -f "${LOBES_DEPLOY_DIR:-$HOME/.lobes}/profiles/orin-nano-8.toml"
lobes init            # re-render .env from the built-in card profile
lobes doctor --json   # expect no profile named orin-nano-8 in the output
```

Executed: not yet — there is no box to execute it on (see Status).

## Build footprint

- Build time: not built — declared arm (no image built)
- Disk delta: 0 B — no image pulled, no weights downloaded
- Retention: nothing to prune

## Pins

- `image_digest`: empty — no sm_87 **vLLM** image is pinned by digest anywhere in lobes-cli (`../lobes-cli/docs/image-ledger.md` records the arm64 nightly as exercised on sm_121/sm_110 only; `orin.toml` names `vllm/vllm-openai:v0.27.1` by tag, for `associate`). Pin on first boot with `docker image inspect --format '{{index .RepoDigests 0}}'`.
- `model_revision`: `0f604ada3f766f9f257460c4c9f0b5d6f69d431b` — `git ls-remote https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct HEAD`, 2026-08-29
- `sparkrun_version`: empty — Jetson arms do not use sparkrun (`docs/lab-conventions.md` §10)
- `jetson_containers_commit`: `3717f380fc9543090c7a2e07d00772d6e05907f8` — `git -C ../jetson-containers-nv rev-parse HEAD`, 2026-08-29
- `jetson_containers_packages`: `llama_cpp:b7368` — recorded for the image family, this arm builds nothing (`../jetson-containers-nv/packages/llm/llama_cpp/config.py`)
- `model_gear_version`: `0.69.2` — `../lobes-cli/pyproject.toml`, 2026-08-29

## Hand-off

Proposed to lobes-cli as an issue (card profiles + CardStrategy sketch):
<https://github.com/agentculture/lobes-cli/issues/231> (filed 2026-08-29 via the `communicate` skill; nothing in `../lobes-cli` was edited).
