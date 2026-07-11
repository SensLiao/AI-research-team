---
name: "source-command-resource-bind"
description: "Bind a pool resource (capabilities/stages/skills) to a project under default-deny. Stores no secret — the credential stays a .env reference on the resource."
---

# source-command-resource-bind

Use this skill when the user asks to run the migrated source command `resource-bind`.

## Command Template

# /resource-bind — 绑定资源到项目 (Bind a Resource, default-deny)

> 把资源池里的某个 resource 授权给一个项目用：限定它能用哪些 capabilities、在哪些 stages / skills 里。
> resource_id 来自 `research_agent_teams/resources/resource_registry.yaml`，例如：
> `api.semantic_scholar`（paper_search / citation_existence）、`server.honor.gpu`（query_status / pull_logs / submit_job）。

1. 先看可绑的资源 + 它各自的 capabilities：
   ```powershell
   python -m research_agent_teams.operate resources --project <slug>
   ```
2. 绑定（`--capabilities` 必须是该资源 capabilities 的子集；逗号分隔）：
   ```powershell
   python -m research_agent_teams.operate resource-bind --project <slug> --alias paper_api `
     --resource api.semantic_scholar --capabilities paper_search,citation_existence
   ```
   可选收窄：`--stages DISCOVER` / `--skills literature_pull`；
   `--requires-approval` 标记此 binding 在 lease 时需人工批准（如 GPU 的 submit_job）。
3. 读回 JSON 的 `binding`：note 会确认「global default-deny 仍在其上叠加，且 binding 里不存任何 secret
   （凭据始终是资源上的 .env 引用）」。
   边界：绑定只授权「能 LEASE 哪个资源 + 哪些 capability」，不写入任何 secret 值。
