# spark / model / cfg (fixture arm)

Test fixture arm used by `tests/test_arm_validate.py`. Carries the literal
marker DECLARED, UNVALIDATED until a transcript lands.

## Rollback

Restore the previous fleet lane on this box:

```bash
docker compose -f fleet/docker-compose.yml up -d model-gear-vllm-primary
curl -sf localhost:8001/capabilities
```

## Build footprint

Build time: 42m18s (build log 2026-08-01)
Disk delta: +6.2GB (docker system df before/after)
Retention: image kept, tagged by digest; HF cache pruned after transcript commit

## Pins

- `image_digest`: sha256:abc123 (never a tag)
- `model_revision`: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef
- `sparkrun_version`: 0.3.6
- `jetson_containers_commit`: empty — upstream-FROM Spark image, no jetson-containers build
- `jetson_containers_packages`: empty — no jetson-containers packages on this arm
- `model_gear_version`: empty — no lobes lane involved
