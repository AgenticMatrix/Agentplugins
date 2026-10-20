---
name: blender
description: 用自然语言操控 Blender 建模、渲染与导出。Use when 用户要建 3D 模型、场景、材质、灯光、相机、渲染图，或做 .blend/.glb/.gltf/.obj/.stl/.fbx/.png 等 3D 资产的生成、修改、核对与导出。核心是经 `blender` MCP 工具向正在运行的 Blender 实例发 bpy Python 代码。
---

# Blender 建模（官方 Blender MCP）

通过 `blender` MCP 工具操控正在运行的 Blender 实例（官方 Blender MCP，TCP 端口默认 `9876`），
执行 bpy 代码完成「自然语言 → 3D 模型」的建模链路。

## 运行前提

- Blender **5.1.0+** 已安装并保持 GUI 运行，且已启用 MCP addon（`addon/blender_mcp_addon/`）。
- addon 的 Auto Start 默认开启，Blender 启动后监听 `127.0.0.1:9876`。
  - 若 Auto Start 静默失败：开 **Edit → Preferences → System → Online Access**，或启动 Blender 时加 `--online-mode`。
- `blender` MCP server（`mcp/blender/`，entry point `blender-mcp`）已由 harness 经 stdio 拉起。

## 核心工具

| 工具 | 作用 |
|---|---|
| `execute_blender_code` | 在**正在运行**的 Blender 里执行任意 bpy 代码（**最常用**：建模/材质/灯光/相机/导出全靠它） |
| `execute_blender_code_for_cli` | 在**后台** Blender 进程里执行 bpy 代码 |
| `get_objects_summary` / `get_object_detail_summary` | 读场景集合层级 / 单个对象结构摘要，做几何核对 |
| `render_viewport_to_path` / `render_thumbnail_to_path` | 渲染当前场景到文件 |
| `get_screenshot_of_area_as_image` | 截取单个编辑器区域（返回 PNG，供视觉核对） |
| `jump_to_view3d_object_by_name` | 把 3D 视口聚焦到指定对象 |
| `get_python_api_docs` / `search_api_docs` / `search_manual_docs` | 查询 bpy API / 用户手册（自带 RST 文档） |

## `execute_blender_code` 返回值约定

在代码里把要返回的数据放进 `result` 变量；`result` 必须是 **dict 且 JSON 可序列化**：

```python
import bpy
# ...建模代码...
result = {"objects": len(bpy.data.objects), "names": [o.name for o in bpy.data.objects]}
```

非 JSON 可序列化的值（bpy 对象、numpy 数组等）不要塞进 `result`，只放纯 Python 数据类型。

## 建模工作流

1. **分小步构建**：每次 `execute_blender_code` 只做一个逻辑步骤（建一个物体 / 加一个修改器 /
   设一段材质 / 打一盏灯），避免单段超长代码超时。
2. **步骤间核对**：用 `get_objects_summary` / `get_object_detail_summary` 核对结构、尺寸、包围盒、
   面数，确认上一步对了再往下走。
3. **bpy 属性名先探针**：不确定 Principled BSDF 输入名 / 修改器参数名时，先跑一小段探针
   （如 `[i.name for i in bsdf.inputs]`）查清楚，再写正式代码。
4. **删除默认物体**：新场景里通常有默认 Cube / Light / Camera，按需清理。
5. **单位与坐标**：Blender 默认单位是米，建模前先按需求统一单位（`bpy.context.scene.unit_settings`）
   与坐标约定，避免尺寸错一个数量级。

## 保存 / 导出

完成后把 `.blend` 保存到工作目录（cwd），再导出同名 `.glb` 供预览：

```python
import bpy
bpy.ops.wm.save_as_mainfile(filepath="/abs/path/workspace/<name>.blend")
bpy.ops.export_scene.gltf(filepath="/abs/path/workspace/<name>.glb")
result = {"blend": ".../<name>.blend", "glb": ".../<name>.glb"}
```

- 预览 / 交付需要 `.glb`（或 `.gltf`）；按需另导出 `.obj` / `.stl` / `.fbx` / 渲染 `.png`。
- 渲染预览用 EEVEE + 较低分辨率（`resolution_percentage`），Cycles 慢、慎用高频渲染。

## 真实建模示例（车身）

```python
import bpy

# 删除默认 Cube
for name in ["Cube"]:
    obj = bpy.data.objects.get(name)
    if obj:
        bpy.data.objects.remove(obj, do_unlink=True)

# 金属车漆材质
paint = bpy.data.materials.new("Car_Paint")
paint.use_nodes = True
bsdf = paint.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.72, 0.05, 0.05, 1.0)
bsdf.inputs["Metallic"].default_value = 1.0
bsdf.inputs["Roughness"].default_value = 0.28

# 车身主体
bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.9))
body = bpy.context.active_object
body.name = "Car_Body"
body.scale = (4.4, 1.8, 1.1)
body.data.materials.append(paint)

# 倒角
bevel = body.modifiers.new("Bevel", 'BEVEL')
bevel.width = 0.05

result = {"objects": len(bpy.data.objects)}
```

## 踩坑清单

- **Online Access 未开** → addon auto-start 静默失败，MCP 工具连不上。
- **Blender 版本过低**（< 5.1.0）→ addon manifest 硬性要求。
- **Blender 必须保持 GUI 运行**且 addon server 已启动——截图/渲染依赖视口与场景。
- **返回值必须写进 `result` dict** 且 JSON 可序列化。
- **高精度生物/雕刻模型**：不建议纯几何体硬搭，先用 Tripo / Rodin 等专用 AI 3D 生成器出模型，再导入 Blender 做后续处理。
