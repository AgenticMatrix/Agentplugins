---
name: blender-viewer
description: 启动 Blender 实时渲染预览视图，返回预览/资产链接。Use when 需要可视化查看 Blender 场景的渲染结果、`.glb`/`.gltf` 模型或渲染 PNG 预览，尤其是建模流程完成后需要把成果展示到前端右侧预览面板时。
---

# Blender Viewer（实时渲染预览）

Blender 是单实例单场景，渲染预览走独立通道：harness 后端直接 TCP 连 addon
（`127.0.0.1:9876`）执行 bpy 渲染代码，产出 PNG / 读取 `.glb`，经 SSE 推送到前端。

## 组件位置

- 前端预览组件：`${CODERIX_PLUGIN_ROOT}/components/viewer/`（`index.html` / `app.js` / `style.css`）。
- 渲染预览图：`$BLENDER_PREVIEW_PATH`（默认 `~/.coderix/blender/preview.png`），所有会话共享。

## 职责边界

- 你只负责**产出文件**（`.blend` / `.glb` / 渲染 `.png`），不负责启动任何常驻 viewer / server 进程。
- 前端实时预览由 harness 统一管理：它会自动轮询渲染预览图，你无需生成或回传图片。
- 几何核对用 `get_objects_summary` / `get_object_detail_summary` 的文本输出，不要用 `Read` 读图片。

## 预览 / 交付产物

- 建模完成后保存 `.blend` 到工作目录，并导出同名 `.glb`（预览主用）。
- 需要静态渲染图时，用 `render_viewport_to_path` 渲染到文件，或让 harness 轮询预览图即可。
