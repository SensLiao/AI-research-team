# Worker runtime/provider usage observability audit

Date: 2026-07-31  
Status: `MINIMAL_UNOBSERVABLE_BOUNDARY_PROVEN / SIGNED_HOST_ADAPTER_REQUIRED / NO_USAGE_ESTIMATION`

## Outcome

The current `research_agent_teams` Python process cannot obtain a provider response for a real research worker. It therefore cannot truthfully produce per-call `resolved_model`, `service_tier`, `reasoning_effort`, `input_tokens`, `output_tokens`, or `elapsed_ms` evidence.

This is an architectural boundary, not a missing parser:

1. `operate/__init__.py` states that real workers are Codex-harness sub-agents that a Python `agent_fn` cannot spawn.
2. `operate/cli.py::_schedule_stage_worker` and `cmd_worker` return a scheduler-authorized worker specification. The CLI tells the outer orchestrator to spawn that sub-agent, then exits. No provider response object crosses back into the process.
3. The worker writes its scientific bundle directly to the authorized output path. A later, separate `run-dets`/commit invocation sees files, not the model call or its response metadata.
4. `operate/spine.py::commit_stage` and `orchestrator/engine.py::_drive` append stage-level observability after artifact validation. They have no author-call start/end handle and cannot distinguish model time from human/orchestrator delay.
5. `orchestrator/model_policy.py::codex_runtime_fields` reads optional deployment environment bindings. Those values describe a requested deployment binding, not the provider-resolved response. They contain no token usage.
6. `agent_run_log.schema.json` historically allowed a nullable aggregate `cost_tokens`, but current run logs contain no such values and the field cannot establish input/output parity.

The minimal unavailable object is therefore the provider/host completion callback. Without that callback, token counts cannot be recovered later from Markdown, character count, a tokenizer approximation, context-window limits, or a stage wall clock.

## Honesty hardening implemented

New observability rows explicitly record:

```text
runtime_observation_status = unobserved | not_applicable
runtime_binding_source = deployment_environment | none
runtime_observation_reason = <non-empty reason>
```

The schema intentionally does not admit `provider_attested`; there is no verifier for that state today. Worker dispatch specifications now carry a `runtime_observability` contract stating:

- provider receipt is unavailable;
- usage estimation is forbidden;
- the future adapter must supply `resolved_model`, `service_tier`, `reasoning_effort`, `input_tokens`, `output_tokens`, and `elapsed_ms`.

Optional `runtime_model`, `reasoning_effort`, and `service_tier` fields remain for backward compatibility, but their schema descriptions now identify them as deployment-request bindings rather than observed facts.

## Required adapter seam

The adapter must run in the host that actually invokes the provider, outside every reasoning worker. It cannot be implemented inside `operate` until the host exposes a completion callback. A sufficient interface is:

```text
dispatch_started(dispatch_envelope)
  -> host invokes provider
  -> provider/host returns completion metadata
  -> host signs invocation_receipt
  -> import_signed_invocation_receipt(receipt, trusted_public_key)
```

The pre-dispatch envelope must freeze:

- unique invocation/nonce and one-use replay identity;
- project/run/stage/worker identifiers;
- prompt and source-packet SHA-256;
- scheduler-contract and expected output-path SHA-256;
- requested capability profile, model policy, service tier, reasoning effort, context budget, and output budget.

The host-signed receipt must bind:

- the full pre-dispatch envelope hash;
- provider request ID and actual response/output hash;
- provider-reported resolved model and input/output/total tokens;
- service tier and reasoning effort together with a field-level source (`provider_response` or host-attested accepted request); missing confirmation is a hard failure;
- monotonic host start/end duration and UTC timestamps;
- signer key ID, Ed25519 signature, and receipt version.

The private signing key must stay in the non-LLM host. `research_agent_teams` receives only a trusted public-key reference, following the existing `execution_receipt_import.py` trust pattern. The importer must schema-validate, verify the signature, compare hashes in constant time, reject replayed invocation IDs, and refuse missing or non-observed usage. It must expose no production signing function.

## Forbidden substitutes

- token estimates from characters, words, or a local tokenizer;
- `cost_tokens` supplied by the worker or copied from a prompt budget;
- deployment environment model/service bindings relabelled as provider-resolved values;
- elapsed time between separate `worker` and `run-dets` CLI calls;
- unsigned JSON written by the author or orchestrator;
- retroactive reconstruction from the final artifact.

Until the host callback and signed importer both exist, the only admissible state is `RUNTIME_USAGE_EXPORT_BLOCKED`; strict A/B sealing must remain unavailable.
