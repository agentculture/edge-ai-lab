# Build Plan — edge-arms-across-nvidia-boxes

slug: `edge-arms-across-nvidia-boxes` · status: `exported` · from frame: `edge-arms-across-nvidia-boxes`

> edge-ai-lab builds and runs experiment arms — Dockerfiles, sparkrun recipes and lobes profiles/shapes — across DGX Spark, Jetson Thor, AGX Orin 64/32GB, Orin NX 16GB and Orin Nano 8GB, and hands proven configurations to lobes-cli with evidence transcripts

## Tasks

### t1 — Write docs/lab-conventions.md — the lab's rulebook: arm path scheme setup/<device-class>/<model>/<configuration>/, arm manifest fields, evidence naming YYYY-MM-DD-<verb>-<subject>-<box>.txt, docs/experiments/ for non-adopted arms, shared-box budget rule, pin manifest (jetson-containers commit, package versions, image digest, `model_revision`, sparkrun version, `MODEL_GEAR_VERSION`), rollback section, build-footprint/retention lines, secrets rule, sparkrun telemetry decision (disabled via `SPARKRUN_NO_TELEMETRY`=1), hand-off = issue/PR on lobes-cli, sparkrun via uvx only, lab never serves

- covers: c6, h6, c13, c27, c31, c32, h28, c33, c8, h10, c10, h12, c11, h13, c24
- acceptance:
  - docs/lab-conventions.md exists, passes markdownlint-cli2, and has a numbered section for each of: path scheme, manifest, evidence naming, shared-box budget, pins, rollback, footprint/retention, secrets+telemetry, hand-off, sparkrun-via-uvx, lab-never-serves
  - Every rule cites its source (lobes-cli file path or sparkrun doc) inline; no number appears without a transcript path

### t2 — Update AGENTS.colleague.md (resident prompt) and README.md: the resident learns the arm path scheme, the transcript rule and the shared-box budget rule; README gains Why it matters (cites lobes playbook rule 1: incumbent baseline unrecoverable after swap), the experiments-vs-serving separation, the audiences and their consumption paths, and an honest before-state; CLAUDE.md moves the planned surface under Roadmap with the built parts marked

- depends on: t1
- covers: c29, c19, h15, c20, h16, c23, c18, h14
- acceptance:
  - AGENTS.colleague.md contains the literal phrases 'setup/<device-class>/<model>/<configuration>', 'docs/evidence/' and 'shared-box budget'
  - README.md cites ../lobes-cli/docs/model-switch-playbook.md rule 1 by path and names lobes-cli, jetson-arena and sparkrun users as audiences with one consumption path each; markdownlint passes

### t3 — Add the arm noun to the CLI: arm overview, arm list (walk setup/\*\*/arm.toml), arm show <path> (`device_class`, model, configuration, format = sparkrun-recipe|lobes-override, engine, box, status = measured|declared-unvalidated|virtual-32gb-capacity-only, pins table, transcript paths); arm.toml parsed with tomllib; explain catalog entries for every new path

- depends on: t1
- covers: c13, h7, c1, h1, c21, h17, c27
- acceptance:
  - tests/`test_arm.py`: arm list on a tmp setup/ tree with two manifests returns both in text and --json; arm show on a manifest missing a required field raises CliError with a remediation naming the field; `test_every_catalog_path_resolves` passes
  - grep -r 'import yaml' `edge_ai_lab`/ is empty; pyproject dependencies stays \[\]
  - The arm group lives in `edge_ai_lab`/cli/`_commands`/arm.py and its catalog entries in explain/catalog.py; later verbs (validate, run, export) are added as `arm_`<verb>.py modules that arm.py imports by name, so each later task edits its own module plus one import line

### t4 — jetson-arena ingest contract: file an issue on jetson-arena (communicate skill) proposing the export shape — `sparkrun_benchmark` v1 YAML for Spark arms, lobes-style transcript + arm.toml for Jetson arms — and add arm export <path> --format arena that emits that shape only after the issue records agreement

- depends on: t1, t3
- covers: c15, h9
- acceptance:
  - The jetson-arena issue URL is recorded in docs/lab-conventions.md and the export code lands in a commit that references the agreed comment
  - tests/`test_arm_export.py`: export of a fixture arm emits a document whose fields match the agreed shape; the lab never posts results itself (no arena/site write path in the code)
  - Export code lives in `edge_ai_lab`/cli/`_commands`/`arm_export.py` + tests/`test_arm_export.py`

### t5 — Add arm validate <path>: README has sections Rollback (before first run), Build footprint (build time, disk delta, retention — values not placeholders), Pins (every manifest pin present), Status marker (DECLARED, UNVALIDATED unless a docs/evidence transcript path in the manifest exists on disk; virtual-32GB arms carry 'capacity-only'); Dockerfile header records the jetson-containers-nv chain and env (`L4T_VERSION`/`CUDA_VERSION`/`CUDA_ARCH`) or the upstream digest it is FROM; no secrets

- depends on: t3
- covers: h23, h27, h29, c4, h4, c31, c33, c32
- acceptance:
  - tests/`test_arm_validate.py`: a fixture arm with all sections passes; removing any one section, leaving a placeholder like 'TBD', or citing a nonexistent transcript fails with a CliError naming the section
  - A fixture Dockerfile without a pinned digest or jetson-containers env header fails validation
  - All validate code lives in `edge_ai_lab`/cli/`_commands`/`arm_validate.py` + tests/`test_arm_validate.py`; only one import line and the catalog entry touch shared files

### t6 — Add arm run <path> — the box-side wrapper (stdlib only, shells out): acquires a box marker (lock file in the deploy dir + docker label) and refuses with a hint naming the live arm if one exists, removes it on any exit; captures before/after: docker ps, docker system df, df -h, nvpmodel -q / devfreq freqs where present, free memory, thermals; probes the fleet gateway /capabilities after the arm exits; launches via 'uvx sparkrun==<pinned> run <recipe>' or the lobes override commands the manifest names; writes a transcript skeleton under docs/evidence/ with the conventions' name

- depends on: t3, t5
- covers: c30, h26, c24, h20, h19, c6, c10, h12
- acceptance:
  - tests/`test_arm_run.py` with a fake docker/uvx on PATH: second arm run while a marker exists exits 1 with 'hint:' naming the running arm; marker is gone after a simulated SIGTERM; transcript file is created with before/after blocks and the gateway probe result
  - arm run never writes to ~/.lobes compose files or the fleet .env (test asserts the fake fleet dir is byte-identical after a run)
  - All run code lives in `edge_ai_lab`/cli/`_commands`/`arm_run.py` + tests/`test_arm_run.py`; only one import line and the catalog entry touch shared files

### t7 — Declared profiles for Orin Nano 8GB and Orin NX 16GB: setup/orin-nano-8/ and setup/orin-nx-16/ lobes profile TOMLs with cortex/senses feasible=false, hand + stt/tts hosted (Nano), a proposed CardStrategy sketch, summary strings carrying 'DECLARED, UNVALIDATED', and a lobes-cli issue (communicate skill) proposing the Nano/NX cards and any new Nano-sized role

- depends on: t6
- covers: c5, h5, c35, h30
- acceptance:
  - Both TOMLs load through ../lobes-cli's loader read-only without error; each summary contains 'DECLARED, UNVALIDATED'; arm validate marks them declared-unvalidated because no transcript path exists
  - A lobes-cli issue URL is recorded in each arm README, posted via .claude/skills/communicate (auto-signed), proposing the card + profile and naming the roles the board can host

### t8 — Extend lab doctor with three checks: resident-rules-present (AGENTS.colleague.md names the three rules), no-secrets-in-arms (scan setup/ for token/password/private-host patterns), stdlib-only (pyproject dependencies == \[\] and no 'import yaml' under `edge_ai_lab`/)

- depends on: t2
- covers: h25, h28, c11, h13
- acceptance:
  - tests/`test_cli_introspection.py` asserts each new check id appears in lab doctor --json and flips to fail on a fixture that violates it (`tmp_path` AGENTS file missing a rule; a setup/ file containing '`hf_xxx`'; a stub module importing yaml)
  - uv run teken cli doctor . --strict still passes

### t9 — First Spark arm: setup/spark/qwen3.8-27b-fp8/vllm-mtp/ — Dockerfile FROM the pinned digest of ghcr.io/spark-arena/dgx-vllm-eugr-nightly building lab tag edge-ai-lab/vllm-spark:<sha>, recipe.yaml (`recipe_version` 2, based on @official/qwen3.8-27b-fp8-mtp-vllm, `gpu_memory_utilization` sized to fit beside model-gear-vllm-primary/-rerank on spark-f8a9, port not 8000/8001), arm.toml, README with rollback + footprint + pins; run via arm run; transcript with usage.`completion_tokens` decode at short/medium/long shapes, TTFT, pinned conditions

- depends on: t5, t6
- covers: c3, h3, c22, h18, c24, h20, c33, h29
- acceptance:
  - uvx sparkrun show setup/spark/qwen3.8-27b-fp8/vllm-mtp/recipe.yaml reports fits with the chosen budget; sparkrun run succeeds with the lab-built container tag and /v1/models answers
  - docs/evidence/<date>-spike-qwen38-fp8-mtp-spark.txt exists, cites usage.`completion_tokens`, docker ps before/after, and the gateway :8001 /capabilities answering after exit; arm validate passes on the directory

### t10 — Lab sparkrun registry + arena upload: .sparkrun/registry.yaml (name edge-ai-lab, recipes: setup, benchmarks: benchmarks, tuning: tuning), benchmarks/edge-ai-lab-v1.yaml profile, telemetry disabled in the wrapper (`SPARKRUN_NO_TELEMETRY`=1), sparkrun arena login documented, first upload of the Spark arm result; results YAML committed next to the arm

- depends on: t9
- covers: c14, h8
- acceptance:
  - sparkrun registry add <this repo url> then sparkrun search resolves @edge-ai-lab/vllm-mtp (or the disambiguated path form) on a clean ~/.config/sparkrun
  - sparkrun benchmark perf --arena on the Spark recipe produces a `sparkrun_benchmark` v1 YAML committed under the arm directory and the upload is visible under the lab's arena account (transcript records the submission id)

### t11 — First AGX Orin 64GB arm: setup/orin-agx-64/<model>/<configuration>/ — image built with jetson-containers-nv (L4T 36.x, `CUDA_ARCH` tegra, `sm_87`; header records commit + env), a lobes profile/shape override TOML using only the 12 knobs, run on Host orin beside or around the orin lanes per the shared-box rule with rollback executed once; transcript with pinned clocks (nvpmodel, devfreq min=max), prefill-vs-depth and decode-vs-length, usage.`completion_tokens`

- depends on: t5, t6
- covers: c4, h4, c2, h2, c22, h18, c24, h20, c33, h29
- acceptance:
  - The override TOML loads through ../lobes-cli's loader read-only (uv run --project ../lobes-cli lobes profile show against a temp profiles dir) with no error and tests/goldens/regen.py in a throwaway copy diffs only the new card's keys
  - docs/evidence/<date>-spike-<model>-orin.txt exists with before/after docker ps, nvpmodel -q, devfreq cur/min/max, thermals, image digest, and the rollback commands executed with their result; arm validate passes

### t12 — Virtual-32GB arm on the Orin 64GB box: setup/orin-agx-32-virtual/<model>/<configuration>/ — same image as the Orin arm, budget capped to a 32GB board's usable memory via `gpu_mem_util` and executor `memory_limit`, README and manifest status 'virtual-32gb-capacity-only', transcript answers fit/no-fit only and quotes no tok/s as a 32GB number

- depends on: t11
- acceptance:
  - arm validate requires and finds the literal 'capacity-only' in README and manifest; the transcript has a fit verdict and its throughput block is labelled 'measured on 64GB hardware — not a 32GB figure'

### t13 — First Thor arm: setup/thor/<model>/<configuration>/ — lobes profile/shape override on Host thor (`sm_110`; sparkrun not used), image pinned by digest from the lobes image ledger or built via jetson-containers-nv JP7 path; shared-box rule applies (Thor served the fleet on 2026-08-25); transcript

- depends on: t5, t6
- covers: c1, h1
- acceptance:
  - docs/evidence/<date>-spike-<model>-thor.txt exists with the same condition blocks as the Orin arm and the gateway probe; arm.toml format = lobes-override and no recipe.yaml is present

### t14 — Hand-off of the Orin arm to lobes-cli: capture the deployment lock on Host orin (lobes lock capture), write deployments/<variation-id>/VARIATION.md per the template citing the Orin transcript, validate with lobes-cli's tests/`test_variation_catalog.py` in a throwaway copy, then open a PR on lobes-cli (cicd/communicate; version bump; reply to every thread) or an issue if the change is a proposal

- depends on: t11
- covers: c26, h22, c2, h2, c8, h10, c21, h17
- acceptance:
  - The variation directory passes `test_variation_catalog.py` unmodified and lobes doctor --json on Host orin reports no `lock_drift` at capture time
  - A lobes-cli PR or issue URL is recorded in the arm README; git log in ../lobes-cli shows no commit authored from this checkout

## Risks

- [unknown_nonblocking] jetson-arena's ingest format may not be agreed quickly (arena is a scaffold with its own open execution-locus question); t4's export code waits on that agreement (task t4)
- [unknown_nonblocking] Building a lab-owned vLLM image for Spark (h3 requires a lab-built container) may mean a multi-hour SBSA jetson-containers build or a thin layer over the eugr nightly digest — t9 chooses the thin layer first; if that fails to satisfy 'lab-built', escalate (task t9)
- [unknown_nonblocking] Thor and Orin both serve the production fleet; a downtime window or budget beside the lanes must be agreed with the operator before t11/t13 run (no agreed window yet) (task t11)
- [unknown_nonblocking] Jetson unified-memory OOM can take the host down; containment via executor `memory_limit` + swap policy is unmeasured until t11's first run (task t11)
- [unknown_nonblocking] The Orin Nano is not connected; t7 stays declared-only and no Nano number may appear anywhere until it is (task t7)
