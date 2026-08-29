# edge-arms-across-nvidia-boxes

> edge-ai-lab builds and runs experiment arms — Dockerfiles, sparkrun recipes and lobes profiles/shapes — across DGX Spark, Jetson Thor, AGX Orin 64/32GB, Orin NX 16GB and Orin Nano 8GB, and hands proven configurations to lobes-cli with evidence transcripts
> instruction: Verify by listing setup/\*\*/ arms: each directory holds an arm definition + Dockerfile + either a docs/evidence transcript or an UNVALIDATED marker in its README

## Audience

- The edge-ai-lab agent and its operator running arms; lobes-cli (consumer of proven profiles/shapes/lock files); jetson-arena (consumer of statistics); any sparkrun user pulling @<lab-registry>/<recipe>

## Before → After

- Before: Today edge-ai-lab is an identity scaffold with no experiment noun, no Dockerfiles, no results store; lobes-cli has profiles only for spark/thor/orin-64GB, its deployments/ catalog is empty, sparkrun has no Jetson notion, and jetson-arena is a scaffold — every Orin NX/Nano/32GB configuration is UNVALIDATED by definition
- After: An arm is a path setup/<device-class>/<model>/<configuration>/ holding a Dockerfile, its recipe or profile override and its transcript; lab recipes resolve via a lab sparkrun registry with arena results uploaded; proven configurations reach lobes-cli as profile/shape/lock-file PRs or issues with an evidence transcript; Orin 64GB (and virtual-32GB) arms are measured here, Thor/Nano arms are declared and labelled UNVALIDATED

## Why it matters

- Serving decisions on the mesh are made on measured evidence (lobes #108); without a lab that owns the arms, the Dockerfiles and the transcripts, every new box or checkpoint is re-derived ad hoc, baselines are lost when models swap, and lobes' variation catalog stays empty
- Separate the experiments layer from the serving/production layer: the lab is where things are allowed to break, be re-flagged and re-measured; lobes is where only proven configurations run — keeping them apart means an experiment can never destabilise the fleet the mesh depends on, and a served config always has a traceable experiment behind it

## Requirements

- Lab output to lobes-cli is a card profile TOML (stem == name; only the 12 RoleProfile knobs in lobes/profiles/schema.py:79-141; unknown knob = load error; `gpu_access`="runtime" for CSV-mode Jetsons; \[\[`exclusive_roles`\]\]; \[`host_env`\]) plus optional shape TOML (name/summary/hosts/\[overrides.\*\] only), an image-ledger row (digest, arch exercised, evidence link), a catalog SupportedModel + docs/<model>.md (status="configured" until lobes boots it), and regenerated goldens
  - honesty: A lab-authored profile TOML loads through lobes-cli's loader without error (uv run lobes profile show <name> against an operator profiles/ dir) and tests/goldens/regen.py diff shows only the new card's keys
- Spark-class arms are sparkrun `recipe_version` 2 YAMLs (model, runtime, container, defaults, metadata VRAM inputs, benchmark, command, `executor_config`); container: is a free-form image ref so lab-built images plug in; arms run as sparkrun run ./arm.yaml or from a lab registry repo carrying .sparkrun/registry.yaml; sparkrun 0.3.6 runs here via uvx without a clone
  - honesty: sparkrun show ./arm.yaml and sparkrun run ./arm.yaml succeed on this Spark with a lab-built container: tag, and the recipe validates as `recipe_version` 2 without CLI overrides
- Image building rides jetson-containers-nv's package system (Dockerfile YAML header name/depends/requires, config.py `build_args` like `VLLM_VERSION`/`IS_SBSA`/`LLAMA_CPP_FLAGS`/`CUDA_ARCHITECTURES`; `get_cuda_arch`() gives Orin \[87\], JP7 tegra \[87,110,120,121\], SBSA \[110,121\]; base is ubuntu:`LSB_RELEASE` for JP6/JP7) — the lab targets arches by `L4T_VERSION`/`CUDA_VERSION`/`CUDA_ARCH` env, not hand-rolled base images
  - honesty: Each lab Dockerfile records the jetson-containers-nv package chain and env (`L4T_VERSION`/`CUDA_VERSION`/`CUDA_ARCH`) it was built with, and the resulting image's CUDA arch list matches the target board (`sm_87` for Orin, `sm_121` for Spark)
- Orin NX 16GB and Orin Nano 8GB need a new lobes CardStrategy + profile: tests/`test_detect.py`:334-344 deliberately refuses to resolve them to the 64GB orin card, and the 2026-07-13 spec says the profile must downshift cortex to a smaller model or declare it infeasible (a 27B NVFP4 cortex cannot run on Nano); AGX Orin 32GB likewise has no distinct profile
  - honesty: A Nano/NX profile is never silently produced by the 64GB orin card: the lab's profile names the box class explicitly and its cortex entry is either a model that fits the box's memory or feasible=false
- The lab's results store adopts lobes' evidence discipline from day one: docs/evidence/YYYY-MM-DD-<verb>-<subject>-<box>.txt transcripts (verbs accept/spike/measure/baseline/partial), docs/experiments/<name>.md for arms not adopted (what/why/why-not), `sparkrun_benchmark` v1 YAML for arena runs; decode from usage.`completion_tokens`, pinned clocks + recorded conditions (nvpmodel, devfreq, docker ps, thermals, image digest), incumbent baselined first; anything without a transcript is labelled UNVALIDATED
  - honesty: No number appears in a lab README, table or CLI output without a transcript path next to it; decode figures cite usage.`completion_tokens`; every transcript records clocks/power mode, co-resident containers and image digest
- Dockerfiles are checked into edge-ai-lab under a path scheme setup/<device-class>/<model>/<configuration>/ (Dockerfile + arm definition — sparkrun recipe or lobes profile/shape override — + transcript kept together) so any arm is findable by path and reproducible without re-deriving flags
  - honesty: A newcomer can locate any arm from its device class, model and configuration alone, and the directory contains everything needed to rebuild and relaunch it without consulting chat history
- The lab maintains a lab-owned sparkrun registry (.sparkrun/registry.yaml declaring recipes/, benchmarks/, tuning/ subpaths) and uploads arena results via sparkrun benchmark perf --arena, so Spark arms are consumable by any sparkrun user by @<registry>/<name>
  - honesty: sparkrun registry add <lab-repo-url> resolves the lab's recipes by @<name>/<recipe>, and an arena upload from a lab recipe is visible under the lab's arena account
- Results flow to jetson-arena for storage and publication: the lab emits statistics in a form jetson-arena can ingest (`sparkrun_benchmark` v1 YAML for Spark, lobes-style transcripts for Jetson), and jetson-arena — not the lab — owns posting them
  - honesty: jetson-arena's ingest format is agreed (as an issue on jetson-arena) before the lab commits to an export shape; the lab never posts statistics itself
- Arms on a box that also serves the lobes fleet declare a memory budget that fits beside the co-resident lanes (this Spark runs model-gear-vllm-primary/-rerank + gateway :8001, the backend ask-colleague uses) or run inside a declared downtime window with the lane stopped; sparkrun's default `gpu_memory_utilization` 0.8 and GB10 0.85 cap are never used unqualified on a shared box
  - honesty: Every transcript from a fleet box shows docker ps before and after and the gateway /capabilities answering after the arm exits, or a logged downtime window with the lane stopped
- A lab-captured lobes deployment lock must satisfy the variation-catalog contract enforced by lobes/`variation_catalog.py`: deployments/<variation-id>/VARIATION.md with either a cited docs/evidence transcript or the exact line 'No measured result.' (a blank section is a failure), and lobes doctor reporting no `lock_drift` on the captured box
  - honesty: The lab's lock directory passes lobes-cli's tests/`test_variation_catalog.py` validator when dropped under deployments/ and lobes doctor --json on the captured box reports `lock_drift` clean
- Every arm pins what it was built and run from: jetson-containers-nv commit SHA + package versions (vllm 0.13.0 is default=True today and moves), image digest not tag, `model_revision` / `hf_revision` commit SHA, sparkrun version, and the lobes `MODEL_GEAR_VERSION` where a lobes lane is involved
  - honesty: Rebuilding an arm from its README alone on a clean box yields the same image digest (or a documented reason it cannot, e.g. upstream nightly)
- The colleague resident is an actor that runs arms and never loads CLAUDE.md: the evidence discipline, the shared-box budget rule and the arm path scheme are written into AGENTS.colleague.md (11 lines today), not only CLAUDE.md
  - honesty: AGENTS.colleague.md names the arm path scheme, the transcript rule and the shared-box budget rule; lab doctor checks the file mentions them
- One arm at a time per box: an arm run leaves a box-level marker (e.g. a docker label or a lock file under the deploy dir) that a second run — from another Claude session, the colleague resident, or an operator — detects and refuses, and the transcript records any concurrent arm it found
  - honesty: Starting a second arm on a box with a live marker exits non-zero with a hint naming the running arm; the marker is removed on exit including abnormal exit
- Each arm README states its measured build time and disk footprint (docker system df before/after) and its retention: images and HF cache entries not promoted to a transcript-backed configuration are pruned, because Orin-class builds take hours and Nano-class disks are small (this Spark's HF cache alone is 307 GB)
  - honesty: Each arm README has build-time, disk-delta and retention lines filled from a measurement, not estimated
- Before an arm runs on a fleet box the arm README carries the rollback recipe as literal commands (lobes playbook rule 9): how to restore the fleet lane and its .env, checked by hitting the gateway /capabilities after the arm exits
  - honesty: The rollback section exists before the first run (git history shows it in the same commit as the arm) and has been executed at least once on a fleet box with the result in the transcript
- The Orin Nano 8GB arm targets the roles it can plausibly hold — hand and the audio sidecars (stt/tts) — and the lab may propose new lobes roles ('lobes') sized for the Nano, filed on lobes-cli as issues
  - honesty: The Nano arm's lobes profile declares cortex/senses feasible=false and hosts only hand + stt/tts (or lab-proposed roles filed as lobes-cli issues); no Nano artifact claims a role the 8GB board has not booted

## Honesty conditions

- Every hardware class named in the announcement has a defined arm format (sparkrun recipe for Spark; lobes profile/shape override for Jetson) and an explicit validation status (measured vs DECLARED/UNVALIDATED) — none is implied validated
- Every hand-off to lobes-cli in the lab's history is a PR or issue on lobes-cli filed via the communicate skill — no commit in ../lobes-cli originates from the edge-ai-lab checkout
- The lab's tooling invokes sparkrun only through uvx/pip with a pinned version recorded in the arm; no sparkrun source tree lives in this repo or the workspace, and every non-GB10 sparkrun run is marked UNVALIDATED in its transcript
- No compose file, systemd unit or gateway in this repo serves models to the mesh — anything long-running belongs to lobes; .claude/skills/ diffs against their upstreams stay byte-empty except the ledgered divergences in docs/skill-sources.md
- Each named audience has a concrete consumption path that exists: lobes-cli via profile/shape/lock PR or issue; jetson-arena via an agreed ingest format; sparkrun users via sparkrun registry add <lab-repo>
- The before-state is checkable against today's tree: git ls-files shows no setup/, docs/evidence/ or Dockerfile in edge-ai-lab; lobes-cli builtin/ holds exactly spark/thor/orin/base; lobes-cli deployments/ holds no variation
- At least one concrete loss is documented in the lab's README with a source — e.g. lobes' playbook rule 1 (the incumbent baseline is unrecoverable once the model is swapped) — rather than asserted generically
- Every element of the after-state maps to a checked-in artifact: a setup/ tree, a .sparkrun/registry.yaml, a docs/evidence/ transcript, and a lobes-cli issue/PR URL recorded in the arm's README; Thor/Nano arm READMEs carry DECLARED, UNVALIDATED
- The success signal is met only when both transcripts exist under docs/evidence/ with usage.`completion_tokens`-based figures and pinned-clock conditions, the Spark upload is visible on arena, and the lobes-cli issue/PR link resolves — a partial (one box only) is reported as partial
- No experiment ever runs against the production lobes fleet ports/compose on a box: lab arms bind their own ports or run while the fleet lane is down, the transcript names the co-resident containers (docker ps), and every served lobes configuration can be traced back to a lab arm path
- grep -r 'import yaml' `edge_ai_lab`/ is empty and pyproject dependencies stays \[\]; recipe validation is delegated to uvx sparkrun show
- Every virtual-32GB artifact labels itself capacity-only and quotes no tok/s figure as a 32GB-board number
- git grep over setup/ finds no token, password or private hostname; the telemetry decision is a recorded decision claim; no --trust use without a review note in the arm README

## Success signals

- At least one Spark arm and one AGX Orin 64GB arm exist end-to-end: Dockerfile builds, sparkrun/lobes launches it, a transcript under docs/evidence/ records usage.`completion_tokens`-based throughput with pinned clocks and conditions, the Spark result appears in the lab registry + arena upload, and a lobes-cli issue or PR carries the resulting profile/shape/lock file

## Scope / boundaries

- Hand-off is an issue or PR on lobes-cli (communicate skill, auto-signed), never an edit from this checkout — lobes-cli CLAUDE.md:958-971 fixes the sibling pattern as 'files issues on siblings but never edits them'; lobes-cli additionally requires every PR to bump version and reply to every review thread
- sparkrun is consumed as a PyPI/uvx tool (0.3.6, Apache-2.0, upstream spark-arena/sparkrun; agentculture/sparkrun is a same-version fork) — the lab does not clone or vendor its source, and any Thor/Orin use of it is unvalidated because a non-GB10 host falls into GenericNvidiaPlatform with x86-oriented default images and loses GB10 tuning
- The lab explores, it does not serve: it does not replace lobes' compose fleet (lobes/templates/fleet/docker-compose.yml) or model-gear's scaffold, and it never edits vendored skills under .claude/skills/ (cite verbatim, re-sync via docs/skill-sources.md)
- No secrets, tokens or hostnames in arm files: sparkrun passes env: literally and arena uploads publish the recipe text and logs, so HF/nvcr.io credentials go via cluster `env_file`; sparkrun telemetry (on by default to telemetry.sparkrun.dev) is an explicit decision recorded in the lab, and `pre_exec`/`post_exec` hooks from non-lab registries run only after review with --trust

## Non-goals

- Hailo 10H and Rockchip/RK-series NPUs are out of the first iteration: lobes-cli has a closed ENGINES tuple (vllm, llama.cpp, sglang) and an engine derived from the catalog with a vLLM-shaped compose lane per role; sparkrun's non-NVIDIA seams are stubs (AMD RCCL, Gaudi HCCL) with no Jetson mention; jetson-containers-nv has no hailo/rknn package — a fourth engine needs an issue on lobes-cli before anything can be built against it

## Assumptions

- lobes-cli 0.68.0's deployments/ variation catalog + deployment.lock.toml (lobes init --from-lock) ships with zero real variations because capture needs physical hardware — it is the intended landing zone for lab-captured configurations, alongside profile/shape TOML
- Thor-class and Orin-class arms are expressed as lobes profile/shape overrides (orin.toml uses `gpu_access`="runtime", llama.cpp engine via ghcr.io/nvidia-ai-iot/`llama_cpp` CUDAARCHS=87;110, `ASSOCIATE_IMAGE`=vllm/vllm-openai:v0.27.1 pinned for dspark), not sparkrun recipes — one arm format per hardware class, both kept next to their transcript
- The AGX Orin 32GB arm is emulated on the 64GB box by capping the memory budget (`gpu_mem_util` / container `memory_limit`) — results are labelled as virtual-32GB, never as measured on a 32GB board
- sparkrun recipes are YAML and the lab's runtime dependencies must stay empty (pyproject dependencies = \[\], teken rubric) while the stdlib has no YAML parser — so the lab CLI treats recipes as opaque files it hands to uvx sparkrun (show/run validate them) rather than parsing them; lobes profile/shape TOML is parsed with stdlib tomllib
- Virtual-32GB on the AGX Orin 64GB emulates memory capacity only: NVIDIA's published AGX Orin specs give the 32GB module fewer GPU cores (1792 CUDA / 56 tensor vs 2048 / 64) at the same 204.8 GB/s, so throughput measured on the capped 64GB box overstates a real 32GB board — virtual-32GB results answer 'does it fit', never 'how fast'

## Scope exploration

- `s1` — `lobes-cli lobes/profiles/schema.py + builtin/{spark,thor,orin,base}.toml`: lobes-cli 0.69.2 is a renderer, not a builder: profile x shape -> .env for a 2137-line compose template. RoleProfile is a closed 12-knob vocabulary (feasible, model, `gpu_mem_util`, `max_model_len`, quantization, `kv_cache_dtype`, `attention_backend`, `enforce_eager`, `max_num_seqs`, `hf_overrides`, `allow_long_max_model_len`, `speculative_config`); unknown knob is a load error; omitted knob = compose default; profile stem must equal name; override replaces wholesale; thor/orin overlay `SM_110` traits from lobes/machines at load time
  - seeds: `c2`, `c12`
- `s2` — `lobes-cli lobes/profiles/builtin_shapes/*.toml + shapes.py`: 9 shapes (machine-as-brain, spark-lobe, thor-lobe/muse/worker, orin-cortex/lobe/associate/small); Shape = name/summary/hosts/\[overrides.<role>\] only, no env mechanism; dropped role renders only <PREFIX>`_FEASIBLE`=false; machine-as-brain must render byte-identical to the bare card (goldens in tests/goldens, regen.py)
  - seeds: `c2`
- `s3` — `lobes-cli lobes/catalog.py SupportedModel + docs/image-ledger.md`: catalog entry needs id/`role_hint`/shape/context/`native_max_model_len`/`tool_parser`/quantization/status(load-tested|configured)/doc; ENGINES is a closed tuple vllm/llama.cpp/sglang and engine is derived from the catalog id, never a knob; sglang has no compose lane (declared-only); image ledger pins by digest with arch-exercised + evidence link, a row without evidence is UNVALIDATED; only unpinned image is nvcr.io/nvidia/vllm:26.04-py3
  - seeds: `c2`, `c9`
- `s4` — `lobes-cli docs/evidence, docs/experiments/README.md, docs/model-switch-playbook.md, docs/measuring-lane-performance.md, CLAUDE.md #108 rule`: 57 transcripts named YYYY-MM-DD-<accept|spike|measure|baseline|partial>-<subject>-<box>.txt (box = spark/thor/orin); experiments/ keeps non-adopted arms (one file exists); playbook: incumbent first, usage.`completion_tokens` not chunk counts, budgets measured never computed (record refused values), concurrency = ceiling + measured saturation or neither; lane-perf: prefill vs depth, pin clocks min=max, record nvpmodel/devfreq/docker ps/thermals/digest; #108: no doc or capabilities output claims validated without a transcript
  - seeds: `c6`
- `s5` — `lobes-cli docs/machine-profiles.md:657, docs/specs/2026-07-13-lobes-fits-the-machine..., tests/test_detect.py:334-344, tests/test_machines.py:283`: Orin Nano/NX have no built-in profile and are 'unvalidated at that scope'; detection explicitly refuses to resolve 'NVIDIA Jetson Orin Nano Developer Kit' to the 64GB orin card; spec requires the profile to pin a smaller cortex model or declare cortex infeasible; orin.toml assumes 61.34 GiB usable so AGX Orin 32GB is also uncovered
  - seeds: `c5`
- `s6` — `lobes-cli deployments/ + lobes/variation_catalog.py + docs/deployment-lock.md (0.68.0)`: published variation catalog with info-file honesty contract and validator, lobes init --from-lock; CHANGELOG says it ships with zero real variations because capture needs physical hardware
  - seeds: `c7`
- `s7` — `lobes-cli CLAUDE.md:946-971 (mesh handoff + PR workflow)`: siblings file issues, never edit; every PR bumps version, waits for Qodo/Copilot/human reviewers, replies to every thread; edge-ai-lab is not mentioned anywhere in lobes-cli yet; the retired names lepenseur/model-gear refer to this same lineage (model-gear checkout is the older scaffold-era lobes)
  - seeds: `c8`
- `s8` — `sparkrun 0.3.6 (PyPI sdist RECIPES.md, docs/MULTIPLATFORM.md, src/sparkrun/platforms, core/hosts.py, benchmarking/base.py; spark-arena registries)`: recipe v2 keys: model (HF id | GGUF repo:QUANT | absolute path), `model_revision`, runtime (vllm/vllm-ray/sglang/llama-cpp/trtllm/eugr-vllm/atlas/modular-max), container (free-form ref, default per platform x runtime), defaults (schema-less, -o overrides), env (literal), command ({key} template), `runtime_config`, metadata (VRAM inputs), benchmark (llama-benchy), `executor_config`, min/`max_nodes`, pre/`post_exec` hooks; --tp N = N hosts; clusters at ~/.config/sparkrun/clusters/<name>.yaml with `hosts_hardware` probe; registry = git repo with .sparkrun/registry.yaml (recipes/tuning/benchmarks/mods subpaths); results = `sparkrun_benchmark` v1 YAML with pseudonymised hosts; sparkrun show estimates VRAM from metadata or HF config; no Thor/Jetson mention, non-GB10 hosts fall into GenericNvidiaPlatform; official @official/qwen3.8-27b-fp8-mtp-vllm recipe exists
  - seeds: `c3`, `c10`
- `s9` — `jetson-containers-nv jetson_containers/l4t_version.py, packages.py, packages/llm/{vllm,llama_cpp,sglang,tensorrt_optimizer/tensorrt_llm}/config.py, docs/build.md`: package = Dockerfile with YAML header (name/alias/depends/requires/test/`build_args`) or config.py that emits version variants; requires gates on L4T ('>=r36') and CUDA ('<cu130'); `CUDA_ARCH` detected via nvidia-smi (nvgpu -> tegra-aarch64, else SBSA), overridable with `L4T_VERSION`/`CUDA_VERSION`/`LSB_RELEASE`/`PYTHON_VERSION`/`CUDA_ARCH` env; `get_cuda_arch`: Orin JP6 \[87\], JP7 tegra \[87,110,120,121\], SBSA \[110,121\], no `sm_101`; base is plain ubuntu:`LSB_RELEASE` for JP6/7; vllm 0.7.4-0.13.0 with -builder/-installer variants, `llama_cpp` b7368 with `LLAMA_CPP_FLAGS`, sglang, trtllm; no results store; no hailo/rknn/sparkrun/lobes mentions; jetson-containers-lab is the same tree plus docs/distributed-inference.md
  - seeds: `c4`
- `s10` — `model-gear (older lobes), dgx-spark-cli, jetson-arena, jetson-thor-cli, jetson-orin-cli, rtx-spark-cli, jetson-ai-lab-cli`: model-gear serves via prebuilt nvcr.io/nvidia/vllm:26.04-py3 compose scaffold with profiles spark/thor/blackwell/generic and lobes benchmark/assess; dgx-spark-cli has real GB10 telemetry (memory/gpu/containers/swap) but no build/launch; jetson-arena declares device x model-setup benchmarking with Docker recipes (Thor -> AGX Orin JP7.2 -> Orin Nano Super) but is scaffold-only; jetson-thor-cli / jetson-orin-cli / rtx-spark-cli are unmodified template scaffolds
  - seeds: `c11`
- `s11` — `edge-ai-lab itself (git ls-files, CLAUDE.md, CHANGELOG 0.7.1, culture.yaml, AGENTS.colleague.md)`: checked-in code is the teken-cited agent-first CLI (whoami/learn/explain/overview/doctor/cli overview) with no experiment noun, no results store, no Dockerfiles; runtime deps must stay empty; any new noun needs <noun> overview + explain catalog entries + tests; this box is a DGX Spark (GB10, hostname spark-f8a9); eidetic recall returned nothing for sparkrun/lobes/jetson experiment topics; culture.yaml still pins sakamakismile/Qwen3.6-27B-Text-NVFP4-MTP (a demoted candidate in lobes-cli)
  - seeds: `c11`
- `s12` — `user decisions q1-q4 (2026-08-29)`: boxes = Spark here + AGX Orin 64GB (doubles as virtual 32GB) + unconnected Nano, no Thor; Dockerfiles live here by setup/model/configuration; lab experiments, jetson-arena stores+posts statistics; lab-owned sparkrun registry + arena uploads
  - seeds: `c13`, `c14`, `c15`, `c16`, `c17` (rejected)
- `s13` — `challenge pass / adjacent-systems lens: docker ps + df on spark-f8a9, lobes-cli deployments/VARIATION.template.md + docs/deployment-lock.md, pyproject dependencies`: this Spark runs the production fleet (vllm-primary, rerank, gateway :8001); HF cache 307G of 3.7T; variation catalog contract requires transcript citation or the literal 'No measured result.'; empty runtime deps vs YAML recipes
  - seeds: `c24`, `c25`, `c26`
- `s14` — `challenge pass / overlooked-actors + concurrency lens: AGENTS.colleague.md, culture.yaml backend colleague, two-agent box sharing`: the mesh resident never reads CLAUDE.md; nothing prevents two agents launching arms on one box
  - seeds: `c29`, `c30`
- `s15` — `challenge pass / lifecycle lens: jetson-containers-nv packages/llm/vllm/config.py defaults, image tags vs digests, HF revisions`: upstream defaults move (vllm 0.13.0 default today); pin commit/digest/revision per arm; build-time and disk retention on Orin/Nano
  - seeds: `c27`, `c31`
- `s16` — `challenge pass / security + operations lens: sparkrun env literal passing, arena upload contents, telemetry default, pre_exec hooks and --trust`: recipe env and logs are published on upload; telemetry is opt-out; hooks execute arbitrary commands from registries
  - seeds: `c32`
- `s17` — `challenge pass / rollback + recovery lens: lobes docs/model-switch-playbook.md rule 9, measuring-lane-performance.md conditions`: rollback recipe before the run; Jetson unified-memory OOM containment is unmeasured (parked)
  - seeds: `c33`
- `s18` — `challenge pass / probes run (read-only, scratch): docker ps, df -h, du HF cache, ls ~/.config/sparkrun (absent — sparkrun never set up here), ls ~/.lobes, ssh config hosts`: no sparkrun state on this box yet (first arm needs uvx sparkrun setup); lobes deploy dir carries hand-edited overrides and .bak files, matching the deployment-lock motivating incident
- `s19` — `challenge pass / counter-evidence lens: ~/.ssh/config hosts, lobes-cli docs/evidence box suffix census (15 spark, 11 thor, 7 orin), lobes/machines/_strategy.py:62`: Thor and Orin hosts exist and have served the fleet; q1's 'no Thor' and the Orin-as-lab-box assumption both need a decision (raised as q5, q6); virtual-32GB capacity-vs-compute mismatch from published Orin specs
  - seeds: `c28`

## Decisions

- Thor is a supported lab box, measurable like Spark and Orin: Thor arms are lobes profile/shape overrides run on the Thor host; sparkrun is not used for Thor for now. Only the Orin Nano remains DECLARED, UNVALIDATED until it is connected.
- The AGX Orin 64GB is the production orin machine; Orin arms share the box with lobes' orin lanes and obey the shared-box budget and rollback rules

## Open parks

- [unknown_nonblocking] Whether Thor should run via sparkrun (GenericNvidiaPlatform, unvalidated, x86-oriented defaults) or exclusively via lobes profiles/shapes — decidable only after a Thor box runs one arm each way
- [unknown_nonblocking] How a fourth engine (Hailo / rknn runtimes) would get a compose lane, `ENGINE_`\* constant and activation env in lobes-cli — needs an issue on lobes-cli and hardware in hand
- [unknown_nonblocking] The AGX Orin 32GB memory budget — no profile, no transcript, no spec mention; unknown whether orin.toml's cortex/associate shapes downshift or are infeasible there
- [unknown_nonblocking] Which lobes lanes an Orin Nano 8GB can host at all: JetPack 6 / CUDA 12.6 / `sm_87` makes vLLM impractical, and lobes' only llama.cpp lane is llamacpp-primary (`PRIMARY_URL`) — hand/embedder/reranker have no llama.cpp lane today
- [unknown_nonblocking] Containment of unified-memory OOM on Jetson: an arm that overcommits can take down the host, not just its container; whether executor `memory_limit` + swap policy (dgx-spark-cli swap telemetry exists for Spark, nothing for Orin) is enough is unmeasured
- [unknown_nonblocking] jetson-arena's docs/scope.md is a sketch with 'where does the benchmark execute?' still open — if arena later drives boards itself, the lab-emits/arena-ingests split (c15/h9) may need renegotiation
