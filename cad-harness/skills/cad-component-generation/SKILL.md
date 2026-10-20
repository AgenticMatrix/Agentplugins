---
name: cad-component-generation
description: cad: Component Generation — Create a single industrial-grade mechanical part from a natural-language spec using build123d, by FIRST decomposing the part into a numbered feature plan (Sketch / Extrude NEW|ADD|REMOVE|ADD UP_TO_SURFACE / Revolve FULL / Sweep / Loft / Shell / Pattern / Helix / Mirror ADD / Fillet / Chamfer) with exact coordinates, radii, and construction geometry, then implementing each feature 1:1 in build123d. A functional component (motor, link, bracket, phalanx, frame tube) must be decomposed into real engineering sub-features, not one monolithic block — see references/technique-cases.md. For purchased/standard parts (motors, bearings, screws, servos), search step.parts and import the real STEP instead of modeling it. Use for ONE part only (bracket, link, rocker, mount, housing, flange, boss, ribbed plate, actuator, frame tube, etc.). Do NOT use for assemblies, multi-body parts, STEP import-only inspection, or secondary STL/3MF/GLB export — those belong to the $cad skill.
---

# cad: Component Generation — 单零件参数化建模（build123d / STEP）

本 skill 由总流程 `CLAUDE_cad.md`（harness 注入）编排：总流程负责「调研 → 部件清单 → 装配汇总 → 递归细化」，本 skill 只负责其中「单个零件」的特征级构建。它专门做一件事：**从自然语言规格创建「一个」零件**。它与通用 `$cad` skill 分工——`$cad` 覆盖装配、STEP 导入、二次导出等完整工作流；本 skill 只负责把单个零件按**特征设计史（design history）**一步步建出来。

## 使用时机

▲ **先判定零件归属：外购件/标准件 vs 自制结构件**（在动笔建模之前就判定，不是建完再想）：

- **外购件 / 标准件**（关节电机、谐波减速器、轴承、螺钉、螺母、舵机、连接器、标准电子件……）——**不要自建模**。先走 `step-parts` skill，用 `scripts/download_step_part.py` 搜 `https://api.step.parts` 拿**真实供应商 STEP**（`--id <part> --download`，自动校验 `sha256`），再 `import`。真实外购件的精细度靠「导入真实几何」，不靠重画。
- **自制结构件**（支架、壳体、连杆、支座、法兰、凸台、筋板、轴……）——才用本 skill 按特征清单自建。

**判断标准**：这个零件有型号/标准号、能买到现成的吗？能 → 走 `step-parts` 导入；必须按本装配定制加工、买不到 → 自建。拿不准就先 `download_step_part.py "关键词" --limit 5` 搜一下目录，别急着造一个假体素。

- 用户要画一个零件：支架、连杆、摇臂、安装座、外壳、法兰、凸台、筋、带孔板、旋钮等。
- 规格能用「草图 + 拉伸/旋转/镜像/圆角」这类**特征序列**表达。
- 产物是单一封闭正体积实体（STEP 为最终交付物）。

**不要**在本 skill 里处理：装配 / 多体（用 `$cad`）、直接导入 STEP 做测量或导出（用 `$cad`）、STL/3MF/GLB 二次导出（用 `$cad` + `supported-exports.md`）、纯渲染概念图。

## 工具环境

harness 已注入 CAD 工具链路径，一律用环境变量取用（与 `$cad` 共用同一套脚本，脚本在 `$CAD_SKILL_DIR` 下）：

```bash
$CAD_PYTHON $CAD_SKILL_DIR/scripts/gen       ...
$CAD_PYTHON $CAD_SKILL_DIR/scripts/inspect   ...
$CAD_PYTHON $CAD_SKILL_DIR/scripts/snapshot  ...
```

`$CAD_SKILL_DIR` 指向通用 cad skill 目录；`scripts/gen|inspect|snapshot|export` 都在其下。用 `--help` 查看完整接口。

## 强制工作流（核心）

**构建任何零件之前，必须先产出一份「特征步骤清单」，再逐条映射成 build123d 代码。** 不允许跳过清单直接写代码。

▲ **工业级硬要求（先读 `references/industrial-design.md` 再写清单）**：每个零件都必须是**真实零部件的工业级设计**，禁止 toy 体素——不允许用裸 `Box`/`Cylinder`/`Sphere`（长方体/圆柱/球体）直接当零件交付。倒角、圆角、加强筋、安装凸台、沉头孔、退刀槽、密封槽、减重、拔模、配合面等工程细节，必须在**产特征清单阶段**就规划进去（不是建完再补）。按该文件第 3 章「产特征清单时的强制顺序」走，并按第 0 章 toy 判定表自检。

### 1. 读规格 → 提取参数与接口契约

从用户 query 提取：尺寸、单位（默认 mm）、坐标约定、基准平面、特征意图。默认 XY 为基平面、+Z 为拉伸/向上轴，输出封闭正体积实体。

**先明确这个零件的「接口契约」**（它要和整体里的哪些零件对接，来自总装 `bom.md`）：

- **对接面 / 安装孔位 / 配合尺寸 / 运动轴线**各是多少、在什么位置——这些是**硬约束**，必须严格按契约来，不能随意改。▲ 配合尺寸要带**装配间隙**（轴-孔是间隙配合，不是零间隙），外形不侵占相邻零件包络，避免装配干涉（见 `references/industrial-design.md` 1.11）。
- 其余**自由几何**（外形 / 减重 / 美观）才可自由发挥。

**规划材质与颜色**（产特征清单前就定，别建完再补——速查表见 `$CAD_SKILL_DIR/references/materials.md`）：

- **材质** = 物理材料名 + 表面处理（如「铝合金 6061-T6，本色」「ABS，黑色」「45# 钢」）。材质决定壁厚 / 圆角 / 拔模等设计决策，也决定颜色。
- **颜色** = 一个主色 hex，从速查表取；`import` 外购件/标准件保持库内自带色，不重新上色。
- 复杂功能件额外规划**子特征区分色**（结构件灰 / 执行器蓝 / 轴承银 / 传感绿……），让渲染图一眼看清结构层次。

再定**局部原点（origin）**作为建模基准（对称件取几何中心，板件取底板中心，轴类取旋转轴心，安装件取主安装基准面），把接口尺寸相对这个 origin 定位。零件几何建在自身局部原点，不依赖装配时的世界坐标。

### 2. 用固定词汇写特征步骤清单

把零件拆成编号步骤，**只允许使用以下特征词汇**。清单中所有坐标都相对于第 1 步声明的**零件局部 origin**（不是世界坐标）。

▲ **复杂外形必须用曲线构建，禁止直线+圆硬拼**：零件的外形轮廓若是流线型、有机形、或需要光滑过渡的复杂形状（摇臂、曲柄、叶轮叶片、外壳曲面、流道轮廓、把手等），**不要用直线 + 圆去硬凑**——用样条 `Spline`、贝塞尔 `Bezier`、切线弧 `TangentArc`、三点弧 `ThreePointArc`、椭圆 `Ellipse` 等曲线实体拟合外形。直线 `Line`/`Polyline` 和圆 `Circle` 只用于真正的直线边、圆孔和圆凸台。判断标准：外形自然描述里一旦出现「顺滑」「流线」「过渡」「弧面」「曲面」「圆润」等词，就必须上曲线。

▲ **功能件必须拆解成工程子特征，禁止一个几何块代表一个功能部件**：即便是一个「零件」，只要它承载功能（关节电机、轴承座、结构连杆、手指指骨、减震器、把手……），就要把它拆成**真实内部子特征**逐条建模，而不是一整块。判据来自真实件解剖——一个「关节电机」不是一根圆柱，而是 **编码器后盖 + 编码器盘 + 电机壳体 + 谐波减速器 + 交叉滚子轴承 + 带螺栓孔环的输出法兰** 沿轴线堆叠；一根「结构连杆」不是实心方管，而是 **两端 U 形叉耳 + 中段减重空心梁 + 端部螺栓孔环法兰 + 双侧轴承座 + 侧走线槽**。每个子特征在清单里占一条 `Sketch/Extrude/...` 步骤，颜色/标签/尺寸各自独立（具体拆法见 `references/technique-cases.md`）。

▲ **真实参考尺寸**：尺寸不能拍脑袋。紧固件/轴承/标准件按标准（M3 通孔 Ø3.4、沉头 Ø6.3×90°、608ZZ 轴承 8×22×7、螺纹牙深 ≈ 0.8×螺距）；外购功能件（关节电机、减速器、轴承）按供应商 datasheet 的体径/长度/法兰/螺栓孔环比例。拿不准就查标准/目录，别用「大概 10mm」糊过去。

| 特征 | 含义 |
|---|---|
| `Sketch` | 在指定平面/面上画草图（含实体 + 构造元素，以「Solve the sketch.」收尾） |
| `Extrude NEW` | 首次拉伸，创建初始实体 |
| `Extrude ADD` | 增加材料（正向拉伸） |
| `Extrude REMOVE` | 切除材料（反向拉伸） |
| `Extrude ADD UP_TO_SURFACE` | 拉伸直到与指定面相交（up-to-face） |
| `Revolve FULL` | 绕轴旋转 360° 生成实体 |
| `Sweep NEW/ADD` | 沿一条路径（`Spline` 样条 / `Helix` 螺旋 / 折线）扫掠一个截面，生成/合并管状或弯曲实体（车架管、把手、排气歧管、弹簧、密封圈） |
| `Loft NEW` | 在两个/多个截面之间放样，生成平滑渐变的有机实体（指骨、叶片、空气动力学外壳、锥形件） |
| `Shell` | 抽壳（外体 − 内体布尔），生成等壁厚空心件（结构连杆、壳体、箱体） |
| `Pattern` | 阵列：`PolarLocations`（螺栓孔环 / 齿轮齿均布）、线性阵列（等距孔/筋） |
| `Helix` | 螺旋线路径（螺纹、压缩/拉伸弹簧） |
| `Mirror ADD` | 关于指定平面镜像并合并 |
| `Fillet` | 对指定边倒圆角（可带 tangent propagation） |
| `Chamfer` | 对外棱倒角（`C0.3–C1`，全件统一 C 值） |

**每个 `Sketch` 步骤必须写明**：
- 草图所在平面/面（Front/Top/侧平面/某特征的面……，并**显式声明**其 build123d 平面映射，见下）；
- 每个实体：圆心坐标 + 半径（圆），或端点/控制点（线、矩形、圆弧）；
- 复杂外形：优先用曲线实体（`Spline` 插值点、`Bezier` 控制多边形、`ThreePointArc`/`TangentArc` 弧、`Ellipse`），并写明每个曲线实体的控制点/关键点坐标；**不要用密集的 `Line`/`Polyline` 折线去逼近曲线**；
- 每个构造元素：同样给出精确坐标（构造线、构造圆、过若干点的构造弧）；
- 以 `Solve the sketch.` 结束。

**每个 `Extrude / Revolve / Sweep / Loft / Shell / Pattern / Helix / Mirror / Fillet / Chamfer` 步骤必须写明**：模式（NEW/ADD/REMOVE/UP_TO_SURFACE/FULL/ADD）、方向、深度/角度/半径、以及消费哪个草图/区域/边。`Sweep` 写明路径控制点、`Loft` 写明各截面轮廓、`Pattern` 写明阵列数量与分布圆/间距、`Shell` 写明壁厚。

### 3. 平面命名映射

把命名平面显式映射到 build123d 平面，并在清单开头声明：

| 命名平面 | build123d |
|---|---|
| Top（顶） | `Plane.XY` |
| Front（前） | `Plane.XZ` |
| Right/Side（右/侧） | `Plane.YZ` |

若规格里的「Front 平面」实际使用 (X, Y) 坐标，则把它当主基平面 `Plane.XY` 处理，并在清单里注明你采用的约定，全程保持一致。

### 4. 逐条映射成 build123d

清单写完后，把每一步 1:1 翻译成 build123d 代码（见下节映射表）。用命名参数、`label` 标注、`BuildPart()`/`BuildSketch()` 构造。源文件名必须以 `.step.py` 结尾（`gen` 只认它作为可构建入口）。

▲ **上色**：每个**叶子** shape 赋 `color = srgb("#hex")`（`from cadgen.color import srgb`），或经 `AssemblyHelper.feature(..., color=...)` 传色。颜色只能挂在叶子 shape 上，`Compound` 分组上的颜色进不了渲染包（见 `$CAD_SKILL_DIR/references/materials.md` 上色机制）；子特征区分色在对应子特征上单独赋。材质本身不进 STEP——材质通过「物理材料名写在清单/注释 + 对应 hex 上色」落地。

## 特征词汇 → build123d 映射

| 清单词汇 | build123d 做法 |
|---|---|
| `Sketch`（实体） | `with BuildSketch(plane) as sk:` 内画 `Circle(center, radius)`、`Rectangle`、`Line`、`ThreePointArc`、`TangentArc`、`Ellipse`、`Spline(*pts)`、`Bezier(*pts)` 等；复杂外形用 `Spline`/`Bezier`/弧拟合，不用直线+圆硬拼；退出上下文即「Solve」 |
| `Sketch`（构造元素） | 用 `Mode.PRIVATE` 标记构造几何（构造线/圆/弧不参与实体轮廓） |
| `Extrude NEW` | 首次 `extrude(amount=...)` 生成初始 `Solid` |
| `Extrude ADD` | `extrude(amount=..., mode=Mode.ADD)` |
| `Extrude REMOVE` | `extrude(amount=..., mode=Mode.SUBTRACT)`（沿拉伸反向切） |
| `Extrude ADD UP_TO_SURFACE` | `extrude(until=..., up_to_face=<目标面>, mode=Mode.ADD)`；具体 `Until`/face 选择器以 `scripts/gen --help` 与 `$CAD_SKILL_DIR/references/build123d-modeling.md` 为准 |
| `Revolve FULL` | `revolve(axis=Axis.Z, revolution_arc=360, mode=Mode.ADD)` |
| `Sweep NEW/ADD` | `sweep(<截面 Circle/Rectangle/Sketch face>, path=<Wire(Spline/Helix/折线)>, mode=Mode.ADD)`；截面放在路径起点、法向对齐路径切向；空心管 = 外截面扫掠 − 内截面扫掠（见 `references/technique-cases.md` 案例 5） |
| `Loft NEW` | `loft([sec1, sec2, ...])`；截面按点序一一对应，点序方向要一致（见 `build123d-modeling.md`「Multi-section lofts match sections BY INDEX」） |
| `Shell` | 代数布尔 `outer − inner`（inner = outer 同轴缩小壁厚后的实体），不要用不稳定的 `offset`；空心管 = 外圆柱 − 内圆柱 |
| `Pattern` | 螺栓孔环 `with PolarLocations(pcd/2, n): Hole(...)`；齿轮齿/均布凸台用 `PolarLocations` 循环布尔 |
| `Helix` | 螺纹/弹簧：`Helix(pitch, height, radius)` 转 `Wire` 后 `sweep` 圆形截面 |
| `Mirror ADD` | `mirror(about=<平面>, mode=Mode.ADD)` |
| `Fillet` | `fillet(<edges>, radius=..., tangent_propagation=True)`；圆角放最后（最易失败，且每次布尔都会使边选择器失效） |
| `Chamfer` | `chamfer(<edges>, length=0.3..1.0)`；全件同一 C 值，放圆角之前或之后均可，但要统一 |

（build123d 精确 API 签名以 `$CAD_SKILL_DIR/references/build123d-modeling.md` 和 `scripts/gen --help` 为准。）

## 完整范例（21 步特征清单）

下面是「三圆 + 三段弧」摇臂类零件的**标准格式范例**，仅用于展示特征步骤清单的写法。真实零件每次都要按自己的规格重新产出清单，坐标/半径以用户规格为准。

```text
Step 1 - Sketch
Create a sketch on the Front plane. Draw three circles: one centered at (0 mm, 0 mm)
with radius 25.4 mm, a second centered at (0 mm, 69.85 mm) with radius 15.88 mm, and a
third centered at (69.85 mm, 40.33 mm) with radius 19.05 mm. Add three construction
elements: a line from (0 mm, 0 mm) to (69.85 mm, 40.33 mm), a horizontal line from
(0 mm, 0 mm) to (74.27 mm, 0 mm), and three arcs passing through the points
(-20.58 mm, 14.89 mm) -> (-11.30 mm, 38.61 mm) -> (-14.70 mm, 63.85 mm),
(74.60 mm, 21.88 mm) -> (44.37 mm, 8.20 mm) -> (20.56 mm, -14.91 mm), and
(10.64 mm, 81.63 mm) -> (38.02 mm, 64.93 mm) -> (69.60 mm, 59.38 mm). Solve the sketch.

Step 2 - Extrude NEW
Extrude the combined sketch profile (the three circles together with the three arcs) a
distance of 8.9 mm in the positive normal direction, creating solid bodies.

Step 3 - Extrude ADD
Add material by extruding the region bounded by the circle centered at (0 mm, 69.85 mm)
(radius 15.88 mm) together with the first arc defined in Step 1, extending 13.97 mm
outward.

Step 4 - Extrude ADD
Add material by extruding the region bounded by the circle centered at (69.85 mm, 40.33 mm)
(radius 19.05 mm) together with the second arc defined in Step 1, extending 19.05 mm
outward.

Step 5 - Extrude ADD
Add material by extruding the region bounded by the circle centered at (0 mm, 0 mm)
(radius 25.4 mm) together with the first arc defined in Step 1, extending 25.4 mm outward.

Step 6 - Sketch
Create a sketch on the top (cap) face of the solid produced in Step 2. Draw three
circles centered at (0 mm, 69.85 mm) with radius 20.96 mm, at (69.85 mm, 40.33 mm) with
radius 24.13 mm, and at (0 mm, 0 mm) with radius 30.48 mm. Add three arcs that follow
the same point sequences used for the arcs in Step 1, scaled to the new radii. Solve
the sketch.

Step 7 - Extrude REMOVE
Cut material opposite the extrusion direction by 5.08 mm from the region defined by the
intersection of the circle centered at (0 mm, 69.85 mm) radius 20.96 mm and the second
arc defined in Step 6.

Step 8 - Sketch
Create a sketch on the top face of the solid added in Step 5 (the cap face of that
extrusion). Draw a solid circle centered at (0 mm, 0 mm) with radius 15.88 mm, a
construction circle at (0 mm, 69.85 mm) radius 15.88 mm, a construction circle at
(69.85 mm, 40.33 mm) radius 19.05 mm, a solid circle at (0 mm, 69.85 mm) radius
9.53 mm, and a solid circle at (69.85 mm, 40.33 mm) radius 12.70 mm. Solve.

Step 9 - Extrude REMOVE
Remove material opposite the extrusion direction, stopping at the top face created in
Step 2, from three circular regions on the sketch of Step 8: the circle at the origin
radius 15.88 mm, the circle at (0 mm, 69.85 mm) radius 9.53 mm, and the circle at
(69.85 mm, 40.33 mm) radius 12.70 mm. Use a depth of 25.4 mm.

Step 10 - Sketch
Create a sketch on the face that results from the cut performed in Step 7 (the cap face
of that removed region). Sketch a single circle centered at (0 mm, 69.85 mm) with radius
9.53 mm. Solve.

Step 11 - Extrude ADD UP_TO_SURFACE
Extrude the circle from Step 10 upward until it meets the top face of the added material
created in Step 3, a depth of 25.4 mm.

Step 12 - Extrude ADD UP_TO_SURFACE
Extrude the same circle from Step 10 upward until it meets the top face of the added
material created in Step 4, a depth of 25.4 mm.

Step 13 - Sketch
Create a sketch on the opposite copy of the cap face generated in Step 7. Sketch two
concentric circles centered at the origin with radii 4.45 mm and 15.88 mm. Solve.

Step 14 - Extrude ADD UP_TO_SURFACE
Extrude the inner 4.45 mm circle upward until it meets the top face of the added material
created in Step 5, a depth of 25.4 mm.

Step 15 - Sketch
Create a sketch on the Top plane. Draw a closed rectangular profile using the points
(-90.8 mm, 0 mm), (-90.8 mm, -25.4 mm), (-83.19 mm, -25.4 mm), (-83.19 mm, -22.23 mm),
(-85.10 mm, -22.23 mm), (-85.73 mm, -21.60 mm), (-85.73 mm, 0 mm), and back to
(-90.8 mm, 0 mm). Also draw a horizontal line from (24.13 mm, -25.4 mm) to
(-24.13 mm, -25.4 mm) and a construction vertical line at X = -95.25 mm from
Y = -25.4 mm to Y = 0 mm. Solve.

Step 16 - Revolve FULL
Revolve the closed rectangular profile from Step 15 a full 360° about the vertical
construction line at X = -95.25 mm, creating a solid of revolution.

Step 17 - Mirror ADD
Mirror the revolved solid across the planar face that contains the horizontal edge at
Y = 0 mm between X = -85.73 mm and X = -90.8 mm, adding the mirrored copy.

Step 18 - Sketch
Create a sketch on the top face of the solid added in Step 5 (the cap face of that
extrusion). Draw a circle centered at (-95.25 mm, 0 mm) with radius 12.07 mm, an arc
passing through (-96.74 mm, 11.97 mm) -> (-107.31 mm, -0.03 mm) -> (-96.70 mm, -11.98 mm),
a concentric circle radius 4.45 mm, a large circle centered at the origin with radius
25.40 mm, a second arc passing through (-6.92 mm, -24.44 mm) -> (25.34 mm, -1.72 mm) ->
(-3.56 mm, 25.15 mm), another concentric circle radius 4.45 mm at the origin, and four
line segments connecting the arc endpoints to the outer circle points as shown. Solve.

Step 19 - Extrude ADD
Extrude the six faces defined in Step 18 (the large 25.40 mm circular region, the two
circles of radii 12.07 mm and 4.45 mm, the region bounded by the first arc, and the two
line-segment regions) a distance of 6.35 mm, creating a complex protrusion.

Step 20 - Fillet
Apply a 5.08 mm radius fillet with tangent propagation to all edges of the protrusion
created in Step 19. Edge overflow is disabled.

Step 21 - Mirror ADD
Mirror the protrusion from Step 19 across the Front plane (the YZ plane at X = 0),
adding the mirrored copy and completing the model.
```

## 生成 / 校验 / 快照（沿用 harness 基线）

1. **生成 STEP**（必须显式写 STEP）：
   ```bash
   $CAD_PYTHON $CAD_SKILL_DIR/scripts/gen <name>.step.py --write
   ```
   同目录产出 `<name>.step`（以及渲染 GLB 侧车）。

2. **几何校验**（基线，必跑）：
   ```bash
   $CAD_PYTHON $CAD_SKILL_DIR/scripts/inspect refs <name>.step --facts
   $CAD_PYTHON $CAD_SKILL_DIR/scripts/inspect validate <name>.step
   ```
   `validate` 输出 `ok` 与 `failureCount`；`ok=true` 且无 failure 才算有效实体（水密、闭合、正体积、无自交）。`refs --facts` 给出实体数与包围盒。

3. **快照复核**（视觉确认，必跑）：
   ```bash
   $CAD_PYTHON $CAD_SKILL_DIR/scripts/snapshot <name>.step
   ```
   查看输出的 PNG，确认形状符合 spec，并与特征清单逐条对照。

4. **修复重跑**：任何一步失败，只改最小范围的源文件代码，重新 `gen --write` → `inspect validate`，直到通过。

## 交付要求

- 最终产物 `<name>.step` 必须存在于工作目录。
- 用 spec 里的尺寸和特征做显式校验：孔数、整体长宽高、特征位置，并与特征清单逐条对照。
- ▲ **工业级自查**：对照 `references/industrial-design.md` 第 0 章 toy 判定表逐条核对，确认不是 toy 体素、工程细节齐全；在交付说明里写明该零件加了哪些工业级特征（倒角/圆角/加强筋/凸台/沉头孔/退刀槽/密封槽/减重/拔模）。
- ▲ **材质颜色**：清单开头已声明材质 + 主色，代码里每个叶子 shape 已用 `srgb` 上色；交付说明里写明该零件的材质与颜色 hex。
- 生成器失败时，直接给出报错信息里指向你自己的 `<name>.step.py` 哪一行，据此修复。

## 禁止

- 不要用 `git status`/`git diff` 或文件大小变化作为 CAD 校验依据；用 `inspect` 摘要、`snapshot` 截图、或生成的拓扑输出做对比。
- 不要把 spec 里没有的特征/尺寸加进去。
- **禁止对能买到的外购件/标准件自建模**：关节电机、谐波减速器、轴承、螺钉、螺母、舵机、连接器、标准电子件等有型号/标准号、能买现成的，一律走 `step-parts` 拿真实 STEP 导入，禁止自建一个假体素替代。
- **禁止 toy 体素**：禁止用裸圆柱/球体/长方体/圆环直接作为零件交付；禁止「一个几何块代表一个功能部件」。每个零件都必须有工业级工程细节。
- **禁止**让零件源文件接收「绝对装配位置」参数（如 `part(base=Pos(x,y,z))` 或 `part(asm, prefix, base, ...)`）。零件只建在自身局部原点，定位由总装层负责——把位置塞进零件函数是「乱组装」的头号根因。
- **禁止启动任何常驻 viewer / server 进程**（如 cad-viewer 的 `start_viewer`、任何 `serve_forever`/监听端口的服务）。渲染由 harness 统一管理，你只负责产出文件。可视化只用 `snapshot` 出一张 PNG 即可，不要起交互式服务。

## 工业级参考

- `references/industrial-design.md` —— 工业级零件设计标准：toy 判定表、通用工业特征清单（倒角/圆角/加强筋/凸台/沉头孔/退刀槽/密封槽/减重/拔模/配合面）、常见零件类型的工业级设计模式、产特征清单的强制顺序。**产特征清单前必读。**
- `references/technique-cases.md` —— **真实高精度零件的参考案例**：从已验收的「人形机器人 / 灵巧手 / 摩托车 / 自行车」工程里提炼的 5 个单零件拆解范式（关节电机分解、空心结构连杆、U 形叉耳支座、放样有机指骨、样条扫掠弯管）。**拆功能件前必读，照着这些范式拆，不要自己发明粗糙做法。**
- `$CAD_SKILL_DIR/references/materials.md` —— **材质 → 颜色速查表** + `srgb()` 上色规则（只挂叶子、linear 通道）。规划材质颜色前必读。
- `$CAD_SKILL_DIR/references/build123d-modeling.md` —— build123d 精确 API 与 sweep/loft/helix/shell 陷阱（多截面放样按点序、扫掠截面法向、抽壳布尔）。用到 `Sweep`/`Loft`/`Shell`/`Helix` 时必读。
