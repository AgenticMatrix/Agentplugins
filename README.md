# blender_plugins —— 自包含 Blender 建模插件

参照 `cad-harness` 的自包含插件范式，把 Blender 建模所需的全部内容收进本目录，
不再散落在 `blender-harness` / `blender-mcp` / `blender_skill.md` 各处。

## 目录结构

```
blender_plugins/
├── plugin.json              # 插件清单（blender-harness 身份，mcp=blender，display=blender-viewer）
├── prompt.md                # agent system prompt（Blender 建模工作流）
├── .env                     # 运行配置（uv 路径、addon TCP 端点）
├── components/
│   └── viewer/              # 前端实时渲染预览组件（web：index.html / app.js / style.css）
├── mcp/
│   └── blender/             # 官方 blender-mcp stdio server（自包含，含 blmcp + RST API/手册文档）
├── addon/
│   └── blender_mcp_addon/   # Blender addon（装进 Blender，监听 127.0.0.1:9876 执行 bpy）
└── skills/
    ├── blender/             # SKILL.md —— 自然语言 → bpy 建模流程
    └── blender-viewer/      # SKILL.md —— 实时渲染预览视图交接
```

## 与 cad-harness 的对应

| cad-harness | blender_plugins |
|---|---|
| `plugin.json`（name=cad-harness，display=cad-viewer） | `plugin.json`（name=blender-harness，display=blender-viewer） |
| `prompt.md`（STEP-first 五阶段流水线） | `prompt.md`（逐步构建 → 校验 → 保存/导出） |
| `mcp/cad-control/server.py`（自写 stdio server） | `mcp/blender/`（官方 blender-mcp stdio server，`uv run blender-mcp`） |
| `skills/cad-viewer/scripts/viewer/`（Three.js viewer） | `components/viewer/`（实时渲染预览 web） |
| `skills/cad` 等 | `skills/blender` / `skills/blender-viewer` |

## 运行前提

- Blender **5.1.0+**，且已安装本仓库 `addon/blender_mcp_addon/` 作为 addon 并启用。
- addon 需 `Online Access`（**Edit → Preferences → System → Online Access**）或启动 Blender 加 `--online-mode`，
  否则 Auto Start 静默失败。
- `uv` 可用（`.env` 里 `BLENDER_UV` 指向 `~/.local/bin/uv`）。

## 注册进 coderix（可选）

`plugin.json` 的 `mcp.blender.command` / `args` 使用 `${CODERIX_PLUGIN_ROOT}` 与
`${ENV:*}` 占位符，由 coderix 的 `installRegisteredPlugins()` 解析。把本目录加进注册表即可：

```json
// ~/.coderix/plugin-registry.json
{
  "plugins": [
    { "name": "blender-harness", "path": "/Users/wangguoqiang/Documents/apps/blender_plugins" }
  ]
}
```

> 注意：coderix 桌面端当前另有一路 blender 集成（`src/main/blender-mcp.ts`），它把
> `blender` MCP 注册为指向 `~/Documents/apps/blender-mcp/mcp` 的外部 server，并往
> `~/.coderix/plugins/blender-harness/` 播种一个轻量 manifest。二者都声明 `blender`
> MCP 与 `blender-harness` 身份，并存时需避免重复注册 `blender` server——迁移到本
> 自包含插件时应关掉那一路，或让注册表条目覆盖它。
