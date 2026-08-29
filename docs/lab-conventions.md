# Lab conventions — the rulebook for experiment arms

This is the rulebook every arm in `edge-ai-lab` follows. It encodes the
confirmed claims of the spec
[`docs/specs/2026-08-29-edge-arms-across-nvidia-boxes.md`](specs/2026-08-29-edge-arms-across-nvidia-boxes.md)
(c6, h6, c13, c27, c31, c32, h28, c33, c8, h10, c10, h12, c11, h13, c24) and
is the contract that `lab arm validate` (planned, task t5) and `lab doctor`
(task t8) enforce. Every rule cites the sibling file it was taken from —
paths written `../lobes-cli/...` are relative to this repository's root in
the multi-project workspace. If a rule here and the cited source disagree,
the source wins and this file gets a PR.

Two sibling repositories set the bar:

- **`../lobes-cli`** — the runtime that consumes proven configurations. Its
  evidence discipline (issue #108, quoted in `../lobes-cli/CLAUDE.md`) is
  the contract this lab feeds.
- **sparkrun 0.3.6** — the DGX Spark recipe launcher used for Spark arms.
  It is consumed as a tool, never cloned (section 10).

## 1. Arm path scheme

An **arm** is one experiment: a hardware class, a model, and one
configuration of it. Every arm is a directory:

```text
setup/<device-class>/<model>/<configuration>/
```

The three path segments are the only way an arm is addressed. A newcomer
must be able to locate any arm from its device class, model and
configuration alone, and rebuild and relaunch it from the directory without
consulting chat history (spec h7).

**Device classes** (fixed vocabulary; add a class by editing this section):

| device class | board | arm format |
|---|---|---|
| `spark` | NVIDIA DGX Spark (GB10, sm_121, 128 GB unified) | sparkrun recipe |
| `thor` | NVIDIA Jetson AGX Thor (sm_110, 128 GB unified) | lobes override |
| `orin-agx-64` | NVIDIA Jetson AGX Orin 64GB (sm_87) | lobes override |
| `orin-agx-32-virtual` | the 64GB board budget-capped to 32GB — capacity only, see section 3 | lobes override |
| `orin-nx-16` | NVIDIA Jetson Orin NX 16GB (sm_87) | lobes override |
| `orin-nano-8` | NVIDIA Jetson Orin Nano 8GB (sm_87) | lobes override |

The compute-capability numbers come from
`../jetson-containers-nv/jetson_containers/l4t_version.py` (`get_cuda_arch`,
line 302): Orin on JetPack 6 builds for `[87]`, JetPack 7 tegra for
`[87, 110, 120, 121]`, and SBSA (Thor and Spark) for `[110, 121]`.

**What lives in the directory:**

| file | required | what it is |
|---|---|---|
| `arm.toml` | yes | the manifest (section 2) |
| `README.md` | yes | the arm's own page: what it is, why we wanted it, rollback (section 6), build footprint (section 7), pins (section 5), status marker (section 3) |
| `Dockerfile` | yes | the image the arm runs; its header records the build chain (section 5) |
| `recipe.yaml` | Spark arms | a sparkrun `recipe_version: "2"` recipe; `container:` names the lab-built image |
| `profile-override.toml` | Jetson arms | a lobes-cli card profile or shape override using only the twelve `RoleProfile` knobs listed in `../lobes-cli/lobes/profiles/schema.py` (`KNOB_NAMES`, line 81); an unknown knob is a load error there, not a warning |
| `results/` | after a run | the `sparkrun_benchmark` YAML (Spark) or exported measurements; the raw transcript itself lives under `docs/evidence/` (section 3) |

Keep the arm definition (recipe or override) next to its transcript so a
result is reproducible without re-deriving flags — the same rule
`../lobes-cli/docs/evidence/README-dspark-arms.md` applies to its
`arm-*.json` files.

## 2. The `arm.toml` manifest

The manifest is what `lab arm list` and `lab arm show` read. It is TOML so the
CLI can parse it with the standard library's `tomllib` — the runtime package
declares no third-party dependencies (`pyproject.toml`, `dependencies = []`),
and a YAML parser is not in the standard library. sparkrun recipes stay YAML
because sparkrun owns that format; the lab hands them to `uvx sparkrun`
unparsed (section 10).

Fields:

| field | values | notes |
|---|---|---|
| `device_class` | one of the classes in section 1 | must equal the first path segment |
| `model` | Hugging Face id, or GGUF `repo:QUANT` | must match the second path segment's slug |
| `configuration` | free slug | must equal the third path segment |
| `format` | `sparkrun-recipe` or `lobes-override` | which file drives the launch |
| `engine` | `vllm`, `llama.cpp`, `sglang` | lobes-cli's closed `ENGINES` tuple (`../lobes-cli/lobes/catalog.py`); anything else needs a lobes-cli issue first |
| `box` | `spark`, `thor`, `orin`, `nx`, `nano` | the evidence-name box suffix (section 3) |
| `status` | `measured`, `declared-unvalidated`, `virtual-32gb-capacity-only` | the honesty marker; see section 3 |
| `[pins]` | table | section 5 |
| `transcripts` | list of paths under `docs/evidence/` | empty means `status` cannot be `measured` |

A full example for a Spark arm:

```toml
device_class = "spark"
model = "Qwen/Qwen3.8-27B-FP8"
configuration = "vllm-mtp"
format = "sparkrun-recipe"
engine = "vllm"
box = "spark"
status = "declared-unvalidated"   # flips to "measured" when a transcript lands

[pins]
image_digest = "sha256:<64 hex>"           # never a tag
model_revision = "<40-hex commit sha>"     # HF repo commit
sparkrun_version = "0.3.6"
jetson_containers_commit = ""              # empty for an upstream-FROM Spark image
jetson_containers_packages = ""            # e.g. "vllm:0.13.0" on a Jetson arm
model_gear_version = ""                    # set when a lobes lane is involved

transcripts = []
```

A Jetson arm sets `format = "lobes-override"`, fills
`jetson_containers_commit` and `jetson_containers_packages`, and sets
`model_gear_version` to the `MODEL_GEAR_VERSION` the box's fleet ran during
the measurement.

## 3. Evidence: transcripts, experiments, and the UNVALIDATED rule

The lab adopts lobes-cli's evidence discipline unchanged, from day one.

**Transcript naming** — the pattern in `../lobes-cli/docs/evidence/`:

```text
docs/evidence/YYYY-MM-DD-<verb>-<subject>-<box>.txt
```

- `verb` is one of `accept`, `spike`, `measure`, `baseline`, `partial` — the
  five verbs in use in `../lobes-cli/docs/evidence/` as of 2026-08-29.
- `box` is one of `spark`, `thor`, `orin`, `nx`, `nano` (lobes-cli uses the
  first three; the last two are this lab's additions for the Orin NX and
  Orin Nano).

**What a transcript must record** — every rule below is from
`../lobes-cli/docs/model-switch-playbook.md` (rule numbers) or
`../lobes-cli/docs/measuring-lane-performance.md`:

- **Decode throughput from `usage.completion_tokens`, never from counting
  stream chunks.** Under speculative decoding a chunk carries several tokens;
  playbook rule 1 records a roughly two-fold under-report from the chunk
  trap.
- **Three generation shapes** — short, medium, long — because decode speed
  changes with generation length (lane-performance axis 5), plus **TTFT**
  (axis 3) and **prefill versus prompt depth** (axis 2). Both docs say axes 2
  and 5 are the ones normally skipped and where the surprises live.
- **Prompt size as the server's own `prompt_tokens`**, never the requested
  depth (`measuring-lane-performance.md`, "Recording the result").
- **Benchmark the incumbent first, on today's engine** (playbook rule 1) —
  that baseline is unrecoverable once the model is swapped.
- **Budgets are measured, never computed** (playbook rule 6): record the
  value that booted *and* any value that was refused.
- **Concurrency figures are ceilings** (playbook rule 8): quote the ceiling
  and the measured saturation together, or quote neither.
- **The conditions** (`measuring-lane-performance.md`, Rule 3 — "a number
  without its conditions is not reproducible"): power mode and clocks
  (`nvpmodel -q`; devfreq `cur_freq`/`min_freq`/`max_freq` with min pinned
  equal to max for the run — Rule 2 there records a false "clock has no
  effect" conclusion from an unpinned governor); the exact co-resident set
  (`docker ps` before and after) and any active downloads; free memory
  before; thermals before **and** after; the image digest; the model file or
  revision.
- Throughput measurements need a **quiet box**; a concurrent download or a
  resident model lane changes the number (`measuring-lane-performance.md`,
  "Which measurements need a quiet box").

**Experiments that are not adopted keep their record.**
`docs/experiments/<name>.md` answers the three questions
`../lobes-cli/docs/experiments/README.md` asks: *what it is, why we wanted
it, why it is not running.* An arm that graduates keeps its file. Cite, don't
delete.

**The UNVALIDATED rule** (issue #108, quoted throughout
`../lobes-cli/CLAUDE.md`; the image-ledger form is
`../lobes-cli/docs/image-ledger.md` line 34, "a row with no evidence link is
UNVALIDATED, and says so"):

- **No number appears in a lab README, table, or CLI output without a
  transcript path next to it.** A configuration with no transcript is
  `declared-unvalidated` in its manifest and carries the literal words
  `DECLARED, UNVALIDATED` in its README and in any lobes profile `summary`
  string it ships (lobes-cli puts the phrase in the summary itself, e.g.
  `../lobes-cli/lobes/profiles/builtin_shapes/orin-lobe.toml`).
- Never back-fill a value a run did not capture.
- **Virtual-32GB arms are capacity-only.** The `orin-agx-32-virtual` class
  runs on the 64GB board with the memory budget capped. It answers "does it
  fit"; it never answers "how fast" — NVIDIA's published AGX Orin
  specifications give the 32GB module fewer GPU cores than the 64GB module
  at the same memory bandwidth, so a throughput figure from the capped 64GB
  board is not a 32GB number. The manifest status is
  `virtual-32gb-capacity-only`, the README carries the literal
  `capacity-only`, and any throughput block in the transcript is labelled
  "measured on 64GB hardware — not a 32GB figure".

Observations, not benchmarks: on 2026-08-29 the Spark `spark-f8a9` had a
307 GB Hugging Face cache and 14 GB of memory available with the fleet up
(`du -sh ~/.cache/huggingface`, `free -g`). Those are the conditions the
first arm was planned against, not results.

## 4. The shared-box budget rule

The Spark (`spark-f8a9`), the Orin (`Host orin`) and the Thor (`Host thor`)
all serve the lobes fleet the mesh depends on — on 2026-08-29 the Spark was
running `model-gear-vllm-primary`, `model-gear-vllm-rerank` and the gateway
on `:8001`, which is the backend the `ask-colleague` skill calls. The lab
explores; it must never destabilise that fleet (spec c23, c24).

Every arm on a fleet box therefore:

1. **Declares a memory budget that fits beside the co-resident lanes**, or
   runs inside a **logged downtime window** with the lane stopped (playbook
   rule 7, "Sequence the downtime"). The window, its start and end, and the
   lane stopped are written into the transcript.
2. **Never uses sparkrun's unqualified defaults** — the recipe default
   `gpu_memory_utilization: 0.8` and the GB10 platform's 0.85 usable-memory
   cap (sparkrun 0.3.6, `RECIPES.md` and `platforms/dgx_spark.py`) assume the
   box is empty. A Spark arm sets `gpu_memory_utilization` from the memory
   actually free with the fleet up, and says so in the README.
3. **Binds a port other than 8000 and 8001** — those are the fleet's vLLM and
   gateway ports (`../lobes-cli/lobes/templates/fleet/docker-compose.yml`).
4. **Proves the fleet survived**: the gateway's `GET /capabilities` must
   answer after the arm exits, and the transcript records the reply. The
   `docker ps` before/after pair from section 3 is the other half of that
   proof.
5. **One arm per box at a time.** An arm run leaves a box-level marker (a
   lock file in the deploy directory plus a Docker label — `lab arm run`,
   task t6); a second run from any actor — another Claude session, the
   colleague resident, an operator — must detect it and refuse with a hint
   naming the running arm, and the marker is removed on every exit
   including abnormal ones. Two arms on one box would contaminate each
   other's numbers (the quiet-box rule in section 3).

## 5. Pins

An arm is reproducible only if every moving part is pinned. The `[pins]`
table in `arm.toml` (section 2) and the `Dockerfile` header carry:

| pin | why | source of the rule |
|---|---|---|
| `jetson_containers_commit` — the `../jetson-containers-nv` commit SHA the image was built from | package defaults move: `packages/llm/vllm/config.py` marks `0.13.0` as `default=True` today and will move it | `../jetson-containers-nv/packages/llm/vllm/config.py` |
| `jetson_containers_packages` — the package chain and versions (e.g. `vllm:0.13.0`) plus the build env `L4T_VERSION` / `CUDA_VERSION` / `CUDA_ARCH` | the same chain resolves differently per L4T and CUDA version; `get_cuda_arch` picks the compute capabilities from them | `../jetson-containers-nv/jetson_containers/l4t_version.py` |
| `image_digest` — `sha256:` digest, **never a tag** | tags move under a running fleet; the ledger's only unpinned image is its one known drift risk | `../lobes-cli/docs/image-ledger.md` (line 99) |
| `model_revision` / `hf_revision` — the Hugging Face commit SHA | lobes-cli pins every catalog checkpoint by `hf_revision`; sparkrun recipes carry `model_revision` for download, cache check and VRAM estimate | `../lobes-cli/lobes/catalog.py`; sparkrun 0.3.6 `RECIPES.md` |
| `sparkrun_version` — the exact version the wrapper invokes as `uvx sparkrun==<ver>` | section 10 | this file |
| `model_gear_version` — `MODEL_GEAR_VERSION` when a lobes lane is involved | transcripts that cite only a shape name under-describe what ran; the lock work in `../lobes-cli/docs/deployment-lock.md` exists because of that | `../lobes-cli/docs/deployment-lock.md` |

The `Dockerfile` header states either the jetson-containers chain and env it
was built with, or the upstream image digest it is `FROM`. Rebuilding an arm
from its README alone on a clean box must yield the same image digest, or the
README documents why it cannot (an upstream nightly, for instance) — spec h23.

## 6. Rollback before the first run

`../lobes-cli/docs/model-switch-playbook.md` rule 9: **write the rollback
recipe before you need it**, with the literal `.env` lines. In this lab the
rule is:

- The arm README carries a `## Rollback` section containing the **literal
  commands** that restore the fleet lane and its `.env` on that box — not a
  description of them.
- The section exists **before the first run**: it lands in the same commit as
  the arm (spec h29).
- It has been **executed at least once** on a fleet box, and the transcript
  records the commands and their result, including the `/capabilities` reply
  from section 4.

A rollback that has never been run is a hypothesis.

## 7. Build footprint and retention

Jetson builds through `../jetson-containers-nv` take hours, and the small
boards have small disks. Each arm README carries a `## Build footprint`
section with three **measured** lines (spec h27 — filled from a measurement,
not estimated, and no `TBD` placeholders):

- **Build time** — wall-clock, from the build log.
- **Disk delta** — `docker system df` before and after the build, plus the
  Hugging Face cache growth.
- **Retention** — what stays: images and cache entries promoted to a
  transcript-backed configuration are kept and referenced by digest;
  everything else is pruned once the transcript is committed.

## 8. Secrets and telemetry

**No secrets, tokens or private hostnames in any arm file.** Two properties
of sparkrun make this a hard rule rather than hygiene:

- sparkrun passes a recipe's `env:` map **literally** — `${HF_TOKEN}` reaches
  the container as that string, by design, because expansion was an
  exfiltration path (sparkrun 0.3.6 `RECIPES.md`, "Container environment
  variables"). Credentials go through a **cluster-level `env_file`** instead
  (`RECIPES.md`, same section).
- Spark Arena uploads publish the recipe text and the run logs.

`lab doctor` (task t8) scans `setup/` for token, password and private-host
patterns and fails on a hit.

**Telemetry — decision recorded here:** sparkrun sends anonymous usage
telemetry to `telemetry.sparkrun.dev` by default (sparkrun 0.3.6 `README.md`,
"Anonymous Telemetry"). **The lab disables it: every wrapper that invokes
sparkrun sets `SPARKRUN_NO_TELEMETRY=1`.** The upstream doc also offers
`sparkrun setup telemetry --disable` for a persistent opt-out; the
environment variable is preferred because it needs no per-box state.

**Hooks:** a recipe's `pre_exec` / `post_exec` / `post_commands` run
arbitrary commands. Recipes from any registry other than the lab's own run
only after the hook bodies have been read, and the README notes that
`--trust` was used and why (`RECIPES.md`, trust rules for untrusted sources).

## 9. Hand-off

A proven configuration becomes a change on the sibling that serves it —
never an edit made from this checkout.

- **To lobes-cli:** an issue or a PR on `lobes-cli`, filed with the
  `communicate` skill (`.claude/skills/communicate/`), which signs the post
  `- edge-ai-lab (Claude)` itself — do not sign the body by hand. The
  sibling pattern is fixed in `../lobes-cli/CLAUDE.md` ("Working with the
  mesh from here"): siblings *file issues on siblings but never edit them*.
  A PR on lobes-cli follows its own rules — bump the version on every PR,
  wait for every reviewer, reply to every thread, never merge with an
  unaddressed comment (`../lobes-cli/CLAUDE.md`, PR workflow). What lands
  there: a card profile or shape TOML, a `deployments/<variation-id>/`
  lock with a `VARIATION.md` that either cites a transcript or carries the
  exact line `No measured result.` (`../lobes-cli/deployments/VARIATION.template.md`),
  a catalog entry with `status="configured"` until lobes itself boots it,
  an image-ledger row, a `docs/<model>.md`. Remember playbook rule 2:
  swapping a served checkpoint id breaks every consumer that pins the raw id.
- **To jetson-arena:** the lab emits statistics in the agreed ingest shape
  (task t4 files the issue that agrees it). jetson-arena stores and
  publishes; **the lab never posts results itself.**

## 10. sparkrun via uvx only

sparkrun is a tool the lab runs, not code the lab owns:

- It is **never cloned or vendored** into this repository or the workspace.
  Every invocation is `uvx sparkrun==<pinned version>` with the version in
  the arm's `[pins]` (section 5). The current pin is 0.3.6, Apache-2.0,
  upstream `spark-arena/sparkrun`; `agentculture/sparkrun` is a fork at the
  same version.
- Recipes are opaque to the lab CLI: validation is `uvx sparkrun show
  <recipe>` and launch is `uvx sparkrun run <recipe>` — the lab does not
  parse YAML (section 2).
- **Any use on a non-GB10 host is UNVALIDATED.** sparkrun's platform
  detection puts every non-Spark NVIDIA host into its generic NVIDIA
  platform with x86-oriented default images and without the GB10 tuning
  (sparkrun 0.3.6, `docs/MULTIPLATFORM.md`). **Thor does not use sparkrun**
  (decision c34 in the spec): Thor arms are lobes overrides.
- Every wrapper sets `SPARKRUN_NO_TELEMETRY=1` (section 8).

## 11. The lab never serves

The lab is the experiments layer; lobes is the serving layer (spec c23).

- No compose file, systemd unit, or gateway in this repository serves models
  to the mesh. Anything long-running belongs to lobes-cli's fleet template
  (`../lobes-cli/lobes/templates/fleet/docker-compose.yml`). An arm binds
  its own port for the length of its run and then exits, leaving the box as
  it found it (sections 4 and 6).
- The vendored skills under `.claude/skills/` stay byte-verbatim to the
  upstreams recorded in [`docs/skill-sources.md`](skill-sources.md); the lab
  does not fork them to make an arm convenient.
