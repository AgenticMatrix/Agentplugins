# 高精度单零件参考案例（拆功能件范式）

本文件是 `cad-component-generation` 的**拆解范式**。它回答一个问题：**一个「功能件」（关节电机、结构连杆、支座、指骨、车架管……）怎么拆成工程子特征，才能达到真实零部件（如谐波关节 DM-J4340）的精细度？**

这些案例不是凭空写的规范，是从已验收的「人形机器人 / 灵巧手 / 摩托车 / 自行车」工程里提炼的**真实做法**。产特征清单前对照下面的范式，把你要建的零件「套」进最接近的一类，逐条拆解。

> 代码片段是**示意**（简化自真实源），变量名和数值保留真实工程的量级；精确 API 签名以 `$CAD_SKILL_DIR/references/build123d-modeling.md` 和 `scripts/gen --help` 为准。

---

## 0. 核心心法：功能件 = 子特征沿功能轴堆叠/组合

「精细」不是多加圆角，而是**把一个功能件拆成它在真实世界里由哪些子部件组成**。判断标准：

- 一个「关节电机」拆开，真实是：编码器后盖 → 编码器盘 → 电机壳体 → 谐波减速器 → 交叉滚子轴承 → 带螺栓孔的输出法兰。
- 一根「结构连杆」拆开，真实是：近端 U 形叉耳 → 减重空心梁 → 远端 U 形叉耳 → 端部螺栓孔法兰 → 轴承座。
- 一个「手指指骨」拆开，真实是：渐缩骨体 → 近端双耳 → 远端单耳 → 球形指尖帽 → 背侧加强筋。

**先拆，再建模。** 一个子特征 = 清单里一条 `Sketch`/`Extrude`/`Sweep`/`Loft` 步骤 + 一个 label + 一个 color。

---

## 1. 关节电机（旋转执行器）—— 沿旋转轴堆叠子段

对应真实准直驱关节（达妙 DM-J4340 一类）：一个「电机」其实是**无框力矩电机 + 谐波减速器 + 交叉滚子轴承 + 编码器 + 输出法兰** 的轴向堆叠。这直接决定了「关节精细、不是一根圆柱」的观感。

```python
# 尺寸分级（真实量级，来自 datasheet 比例）：L=髋/肩, M=膝/肘, S=踝/腕/颈
ACT_SIZES = {
    "L": {"body_r": 48.0, "out_r": 55.0, "length": 120.0, "bolts": 8},
    "M": {"body_r": 40.0, "out_r": 45.0, "length": 100.0, "bolts": 6},
    "S": {"body_r": 28.0, "out_r": 32.0, "length": 78.0,  "bolts": 6},
}

def _flange(radius, thickness, bolts):
    """旋转输出法兰：圆盘 + 一圈螺栓孔（PCD 均布）。"""
    with BuildPart() as fp:
        Cylinder(radius=radius, height=thickness)
        with PolarLocations(radius * 0.72, bolts):
            Hole(radius=max(1.6, radius * 0.09))
    return fp.part

def actuator(asm, prefix, base, size="M"):
    p = ACT_SIZES[size]
    br, orr, length, n = p["body_r"], p["out_r"], p["length"], p["bolts"]
    z = -length / 2
    # 沿局部 Z 从后盖 → 输出法兰逐段堆叠，每段一个子特征
    def stack(h, radius, name, color, builder=None):
        nonlocal z
        shape = builder(radius, h, n) if builder else Cylinder(radius=radius, height=h)
        asm.feature(base * Pos(0, 0, z + h / 2) * shape, name, color=color)
        z += h
    stack(0.14 * length, br * 0.62, prefix + "_encoder_cap",    C_ACT_DK)
    stack(0.04 * length, br * 0.50, prefix + "_encoder_disc",   C_SENSE)
    stack(0.42 * length, br,         prefix + "_motor_housing", C_ACT)
    stack(0.24 * length, br * 0.92,  prefix + "_harmonic_reducer", C_ACT_LT)
    stack(0.10 * length, orr,        prefix + "_crossroller_bearing", C_BEARING)
    stack(0.06 * length, orr,        prefix + "_output_flange", C_FLANGE, builder=_flange)
```

**要点**：子段比例固定（后盖 0.14×长、壳体 0.42×长、减速器 0.24×长…），不是随手摆；输出法兰带螺栓孔环；每段独立 color/label（结构件灰、执行器蓝、轴承银、传感绿）。

---

## 2. 空心结构连杆 —— 抽壳 + 加强筋 + 减重窗 + 端部法兰

对应人形机器人「大腿 / 小腿壳」：真实连杆不是实心方管，是**薄壁空心 + 内部矢状筋 + 减重窗 + 端部螺栓孔法兰 + 轴承座**。

```python
def make_leg_link_shell(length=280.0, width=84.0, thick=84.0, flange_pcd=40.0, ear_bore=22.0):
    # 1) 外体：圆角方棒（外棱 R8 圆角，不是直角）
    outer = fillet(Box(width, thick, length).edges(), 8.0).moved(Location((0, 0, length/2)))
    # 2) 内体：同轴缩小一个壁厚，做空心（Shell = 外体 − 内体，不是 offset）
    inner = Box(width - 2*SHELL_T, thick - 2*SHELL_T, length - 6.0).moved(Location((0, 0, length/2)))
    shell = outer - inner
    # 3) 矢状加强筋 + 三处减重窗
    shell += Box(SHELL_T, thick - 2*SHELL_T, length).moved(Location((0, 0, length/2)))
    for frac in (0.30, 0.52, 0.74):
        shell -= Box(thick + 8.0, width*0.50, thick*1.1).moved(Location((0, 0, length*frac)))
    # 4) 端部法兰：4×M3 通孔在 PCD 上均布（M3 通孔 = M3/2 + 0.2 间隙）
    flange = fillet(Box(width+6.0, thick+6.0, 10.0).edges(), 3.0).moved(Location((0, 0, length-5.0)))
    for i in range(4):
        a = radians(90.0*i + 45.0)
        flange -= Cylinder(M3/2.0 + 0.2, 16.0).moved(
            Location((flange_pcd/2*cos(a), flange_pcd/2*sin(a), length-5.0)))
    shell += flange
    # 5) 双侧轴承座（耳塔 + 精配合孔）
    for t in (-thick/2 + 6.0, thick/2 - 6.0):
        tower = Cylinder(ear_bore/2 + 4.0, 12.0, rotation=(90, 0, 0)).moved(Location((0, t, ear_bore/2+4.0)))
        bore  = Cylinder(ear_bore/2, 26.0, rotation=(90, 0, 0)).moved(Location((0, t, ear_bore/2+4.0)))
        shell = shell + tower - bore
    # 6) 侧走线槽
    shell -= Box(width - 16.0, SHELL_T, length*0.70).moved(Location((0, 0, length*0.48)))
    return shell
```

**要点**：空心用 `外体 − 内体`（内体 = 外体同轴缩一个壁厚），不要用不稳定的 `offset`；筋厚 ≈ 主壁厚；减重窗避开螺栓孔与力线；轴承座 = 耳塔圆柱 + 精配合孔；螺栓孔带间隙（M3 通孔 Ø3.4）。

---

## 3. U 形叉耳支座 —— 座凸台 + 叉板 + 轴承耳塔 + PCD 螺栓孔

对应髋/肩/踝连接座（把电机输出轴与连杆铰接起来的转接件）。核心是「一个座 + 一个叉 + 一个耳 + 一圈孔」。

```python
def make_joint_bracket(side=1.0, seat_dia=57.0, boom_len=46.0, ear_bore=22.0, pcd=40.0, screws=4):
    main = fillet(Box(width, y_span, boom_len).edges(), 6.0)          # 主体，外棱 R6
    seat = Cylinder(seat_dia/2, 5.0).moved(Location((0, -side*(y_span/2+2.5), 0)))  # 座凸台
    clevis_plate = Box(width+18.0, 6.0, boom_len+2.0).moved(Location((0, side*(y_span/2-3.0), 0)))  # 叉板
    ear = Cylinder(ear_out_dia/2, 12.0).moved(Location((0, side*(y_span/2-6.0), 0)))   # 轴承耳塔
    bore = Cylinder(ear_bore/2, 18.0).moved(Location((0, side*(y_span/2-6.0), 0)))     # 耳孔
    body = main + seat + clevis_plate + ear - bore
    for i in range(screws):                                          # PCD 螺栓孔环
        a = radians(360.0/screws*i + 45.0)
        body -= Cylinder(M3/2 + 0.2, 6.0).moved(Location((pcd/2*cos(a), -side*y_span/2, pcd/2*sin(a))))
    return body
```

**要点**：座凸台、叉板、耳塔是**三个可分辨的子特征**，不是一块挖出来的方块；耳孔与耳塔同轴；螺栓孔在 PCD 上均布、带间隙。

---

## 4. 放样有机指骨 —— 截断椭圆截面 loft + 球形指尖帽 + 桶形铰耳

对应灵巧手「末节/中节/近节指骨」：真实指骨是**背侧圆润、腹侧扁平**的渐缩体，两端是**桶形铰耳**，指尖是**球面圆弧**。这是「机械手接近真实、不是粗糙方块」的关键——用 `loft` 而非 `Box`。

```python
def clipped_section_face(rx, ry, y_cut, n=40):
    """XY 平面的截断椭圆截面：椭圆上部 + 腹侧平边（背圆腹平）。"""
    ratio = max(-0.99, min(0.99, y_cut / ry))
    phi0 = asin(ratio)
    pts = [(rx*cos(phi0 + (pi - 2*phi0)*i/n), ry*sin(phi0 + (pi - 2*phi0)*i/n)) for i in range(n+1)]
    arc = Spline(pts)                       # 椭圆上部用样条拟合
    chord = Line(pts[-1], pts[0])           # 腹侧平边
    return make_face(Wire([arc, chord]))

def phalanx(length, r_prox, w_prox, w_tip, ...):
    # 近端截面 → 远端截面，截面参数随长度线性过渡（渐缩）
    sec1 = clipped_section_face(w_prox/2, r_prox*0.80, -r_prox*0.80*0.55).moved(Location((0, 0, 0)))
    sec2 = clipped_section_face(w_tip/2,   3.4,          -3.4*0.55).moved(Location((0, 0, length)))
    body = loft([sec1, sec2])               # 放样 = 光滑渐缩骨体
    for sx in (-1, 1):                       # 近端双耳（桶形铰耳）+ 背侧筋
        lug = Cylinder(r_prox, 2.0, rotation=(90,0,0)).moved(Location((sx*4.0, 0, 0)))
        web = Box(2.0, 3.0, r_prox+1.0).moved(Location((sx*4.0, r_prox*0.30, r_prox*0.5)))
        body = body + lug + web
    body -= Cylinder(1.6, 16.0, rotation=(90,0,0)).moved(Location((0, 0, 0)))  # 铰孔
    tip = Sphere(radius=w_tip/2).moved(Location((0, 0, length)))   # 指尖球面帽
    tip = tip - Box(20, 20, 20).moved(Location((0, -11.75, length)))  # 腹侧削平（指尖垫安装面）
    return body + tip
```

**要点**：`loft` 的截面点序方向要一致（都是逆时针、从同一起点），否则表面扭曲——见 `build123d-modeling.md`「Multi-section lofts match sections BY INDEX」；铰耳是**桶形**（轴沿 X 的圆柱），近端双耳 / 远端单耳交替；腹侧削平留出腱通道。

---

## 5. 样条扫掠弯管 —— 圆形截面沿 `Spline` 路径 sweep

对应摩托车车架主梁、自行车弯把、排气歧管：真实车架管是**沿三维样条路径扫掠的空心管**，不是「直线管段 + 硬折角拼接」。

```python
def sweep_tube(od, pts, bore=0.0):
    """圆管沿过 pts 的样条扫掠（bore>0 为空心管）。"""
    path = Wire(Spline(*[Vector(*p) for p in pts]))           # 3D 样条路径
    t0 = (V(*pts[1]) - V(*pts[0])).normalized()               # 起点切向
    prof = Circle(od/2).located(Location(Plane(origin=V(*pts[0]), z_dir=t0)))  # 截面法向对齐切向
    outer = sweep(prof, path=path)
    if bore <= 0.0:
        return outer
    inner = sweep(Circle(bore/2).located(Location(Plane(origin=V(*pts[0]), z_dir=t0))), path=path)
    return outer - inner

# 用法：车架主梁 = 一根沿 SPAR_PATH（一串 3D 坐标）的空心弯管
body = sweep_tube(P.SPAR_OD, P.SPAR_PATH, bore=P.SPAR_OD - 2*3.0)  # 壁厚 3mm
```

**要点**：路径点越密、过渡越顺滑；截面放在路径起点、法向对齐起点切向；空心管 = 外截面扫掠 − 内截面扫掠。折点多、弯急的管（排气歧管）用「逐段圆柱 + 转角球」`poly_tube`，或实心扫掠后再端部镗孔（见 `build123d-modeling.md` 的扫掠陷阱）。

---

## 6. 把这些范式落到特征清单

每个案例都能翻译成 `SKILL.md` 里的特征词汇。以「关节电机」为例，清单长这样（节选）：

```text
Step 1 - Revolve NEW    后盖：绕 Z 轴旋转生成后盖盘（半径 0.62×体径，厚 0.14×总长）
Step 2 - Extrude ADD    编码器盘：后盖前叠加薄盘（半径 0.50×体径，厚 0.04×总长）
Step 3 - Extrude ADD    电机壳体：主壳体段（半径 = 体径，长 0.42×总长）
Step 4 - Extrude ADD    谐波减速器：略缩颈段（半径 0.92×体径，长 0.24×总长）
Step 5 - Extrude ADD    交叉滚子轴承：外径段（半径 = 外径，长 0.10×总长）
Step 6 - Extrude ADD    输出法兰：圆盘 + 8×螺栓孔在 PCD 上均布（Pattern）
Step 7 - Chamfer       外棱倒角 C0.5（全件统一）
```

**自检**：对照 `industrial-design.md` 第 0 章 toy 判定表，逐条确认「功能分解 / 空心结构 / 曲线轮廓 / 螺栓孔环 / 尺寸来源」都过了，才是高精度零部件。
