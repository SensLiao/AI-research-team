---
type: readme
updated: 2026-05-01
---

# 08-artifact-manifests/ — pointers to large artifacts

> Markdown manifests that **point to** datasets, model weights, container images, env locks, and result packages. Large binaries live elsewhere (DVC, git-annex, S3, university cluster).

## Subdirectories

| Path | Manifests for |
|---|---|
| `datasets/` | DVC / git-annex hashes for each dataset version used |
| `containers/` | Container image digests (sha256:...) used by experiments |
| `env-locks/` | `conda-lock` / `uv.lock` files committed here so any past run is restorable |
| `result-packages/` | RO-Crate-style packages: dataset + code + result + provenance, bundled |
| `ro-crate/` | Full RO-Crate metadata documents for each major output (paper supplementary, dataset release) |

## Rules

1. **No raw binaries** in this folder. Only manifests pointing at where binaries live.
2. Each manifest is a small markdown file with a frontmatter pointing at the artifact location, version/hash, license, and the wiki pages that depend on it.
3. Manifests are referenced from `wiki/runs/<run-slug>.md` via `data-version`, `env-lock`, `container-digest` fields.

## Recommended manifest schema

```yaml
---
type: manifest
updated: YYYY-MM-DD
artifact-type: dataset | container | env-lock | result-package | ro-crate
name: ""
version: ""
hash: ""                # sha256: ... or dvc hash
location: ""            # URL / cluster path / DVC remote
license: ""
used-by:                # wiki pages that depend on this artifact
  - '[[run-slug]]'
  - '[[experiment-slug]]'
---

# {Artifact Name}

<one-paragraph description + how to retrieve>
```

## Why this directory exists

Without a manifest layer, your `wiki/runs/<slug>.md` page just says `data-version: <some-hash>` and there's nothing in the vault explaining what that hash points at. Six months later the cluster is reorganized, the URL rots, and you can't reproduce. The manifest is what survives those changes.
