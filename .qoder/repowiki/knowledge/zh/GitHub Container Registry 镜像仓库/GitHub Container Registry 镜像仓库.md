---
kind: external_dependency
name: GitHub Container Registry 镜像仓库
slug: ghcr
category: external_dependency
scope:
    - '**'
---

主服务与 worker 镜像拉取自 `ghcr.io/songlinhe5-lab/quant_agent:latest`，配合本地 registry（SEC-17）在国内节点经 Tailscale 内网加速拉取。