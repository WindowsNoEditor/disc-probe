# DiscImageStudio CD-DA 读取计时标定（HP BU20N，参考实现）

[English](README.en.md)

这是一个独立原型，用来标定 DiscImageStudio（DIS）刻的 **CD-DA 音轨**盘的螺旋几何。原理和 disc-probe 相同：恒定转速（CAV）下交替读参考扇区和目标扇区，读完时刻对一圈的周期取余数就是扇区在盘上的角度，用"阶梯"推出整圈数，再拟合螺旋。它和 disc-probe 互补：

| | disc-probe | 本目录 |
|---|---|---|
| 盘 | 随机数据盘（Mode 1 / DVD），READ(12) + FUA | DIS 刻的 CD-DA 音轨盘，READ CD 单扇区，每次先读远处挤掉缓存 |
| 命令通道 | SPTI | IMAPI2 `IDiscRecorder2Ex`（普通用户即可） |
| 拟合 | u/v 恒定轨距 + `geo_polyfit.py` 多项式修正 | DIS 测试版的轨距模型（恒定、二次、三次），F 检验 + 留一预测自动选模型；每次测量一个自由常数 κ；可选刻录接缝台阶项 |
| 输出 | DIS 预设（`disexport`） | DIS 工程里的 5 个参数（内半径、外半径、c1/c2/c3）和扇区数 |

许可：GPL-3.0-or-later（与 DIS 相同，与 disc-probe 的 GPL-3.0 兼容）。

## 结果

### 联想 Thinkplus CD-R 80 min（359845 扇区）

- 两张盘、4 次阶梯（一次 2 倍转速），99 个点，25.6–57.6 mm：`analysis/rungs_all_runs.csv`。
- 恒定轨距不够（χ²/ν 14.7），二次够（1.72）：残差是峰峰约 1.8° 的平滑 S 形。2 倍转速下 S 形的幅度比为 0.87 ± 0.11（若是计时假象应为 2），说明是盘的几何。
- 二次参数：内半径 24.921551846562572、外半径 57.838950219991993、c1 −3.8950535120452173e−05、c2 1.5748336087855265e−05、c3 0。
- 第 5 张盘用这组参数刻验证图案，实线辐条是直的。
- 第 5 张盘在 r ≈ 33.4 mm 有一处约 0.2 mm 的沿轨台阶，照片和计时都看得到，读回的数据是连续的：见 `docs/seam_disc5_zh.md`、`docs/jog_photo_annotated.png`、`results/disc5_jog*`。
  - 位置在扇区 65 600 附近：最可能在 65 556–65 636 之间，65 440–66 540 都不能排除。
  - 大小 g = +0.20 ± 0.05 mm。
  - 下面的新型号盘在同一扇区没有台阶，所以它不是这台光驱在固定扇区的固定行为。

### 新型号 CD-R（ATIP 导入起点 97:27:18，359849 扇区），一张探测盘

- 程序自动选出恒定轨距：内半径 24.911761984709965、外半径 57.93170828230436，三个系数都是 0（`out/newmodel_fit_final.json`）。
- 同一张盘在 HP BU20N 上测了两次（`out/newmodel`、`out/newmodel_portable`），两次分别拟合，半径只差约 1 nm。
- 扇区 65 500 两侧的定点测量没有台阶：g = −0.01 ± 0.04 mm（`out/newmodel_seam`）。
- 这种盘和联想盒差得很远：平均轨距大约 0.4 %。拿联想盒的参数刻它，直线会扭成约 22 圈的螺旋。

### 换一台光驱测同一张盘

- 另一台电脑，PLDS DVD±RW DU-8A5LH（`out/plds_du8a5lh`）。
- `autocal` 发现它在 0x0583 下不是恒定转速：41.5 mm 处周期 108 ms，内外圈 29.5 ms。于是自动改用 0x06E4，内中外三处都是 29.53 ms（2032 rpm），见 `autocal_speeds.csv`。
- 36 级、9.3 分钟，同样自动选出恒定轨距（`out/plds_fit.json`）。
- 除沿轨常数 x 以外都一致：两台都按 x = 0 换算时直尺读数 B 差 8.2 mm，即这台读盘光驱的 x ≈ −603 字节；代入后两台的半径只差几 nm（`out/plds_vs_hp_pred.*`）。
- 两台的读偏移 s 也不同（−144 对 −532 字节），但 x 不能从 s 推出，只能用实刻的直线核对一次。

## 沿轨常数 x

计时测不出图案沿轨道整体错开的常数 x：它在数学上等价于内外半径一起变一点。x 属于"谁刻 + 谁读"这一对光驱，每对用一张带直线的盘量一次。本机（BU20N 自己刻、自己读）x ≈ 0（直尺估计 −45 字节，68 % 区间 −152…+64）。DIS 的交织补偿把图案放在编码器帧网格的 +111 帧（`CddaInterleaveTable`），读完成点相对扇区末尾的常数各光驱不同，所以 x 要逐对核对。

## 目录

| 路径 | 内容 |
|---|---|
| `src/` | C# 探测程序（.NET 10，`dotnet build src/Probe.csproj -c Release -o bin`）：`inventory`、`autocal`（自动找恒定转速的读速）、`calibrate`（阶梯，写 `summary.json`）、`head`（读写偏移 s）、`laddersim`/`simsuite`（离线模拟）。命令白名单只放行查询、读取和 SET CD SPEED |
| `src_extra/` | 另一个探测程序版本里的阶段：`localsteps`（参考扇区 + 若干目标扇区的相位差，用来找台阶）、`linkscan`（C2 和子码扫描）、`writespeeds`。它们依赖那个版本的 `Program.cs`，没有并入 `src/` |
| `analysis/calibrate_pitch.py` | 恒定、二次、三次轨距联合拟合和模型选择；`--link 扇区[=G]` 拟合刻录接缝台阶，`--localsteps CSV` 把定点测量一起拟合；`test_calibrate_pitch_link.py` 是它的测试（`--only bce`；回归测试 a 的基线没有收录） |
| `analysis/pitchfit/` | 与 DIS 测试版 `DvdTrackGeometry` 一致的螺旋模型（精确弧长）和加权 Gauss-Newton 拟合 |
| `analysis/make_probe_project.py`、`make_probe_pattern.py`、`predict_disc.py` | 换新型号：按扇区数写探测盘工程和探测图案，按"刻录值对真值"预测盘上图案的样子 |
| `analysis/step_scan.py`、`link_locate.py`、`jog_estimate.py` | 在阶梯或定点测量里找单个沿轨台阶 |
| `analysis/prewarp.py` | 预变形设计图（恒定轨距下的 S 形弯，`--link` 预补偿接缝） |
| `analysis/calibrate.py` | 早期的恒定轨距拟合（也能打印读写偏移 s） |
| `docs/CD_TIMING_CALIBRATION_SPEC.md` | 完整技术规格（英文）。其中引用的部分核查脚本没有收录 |
| `results/` | 联想盒：`disc1`、`disc2`、`disc3`、`disc3_2x`、`disc5_cubic_r3`（阶梯），`disc5_link*`、`disc5_jog*`（接缝定点测量，28–38 mm 的 C2/子码扫描），`gating`（READ CD 完成时刻门控实验），`writespeeds` |
| `out/` | 新型号：两次 HP 测量、接缝定点测量、PLDS 测量和拟合结果 |
| `templates/cd_cubic_template.discproj` | `make_probe_project.py` 照抄字段用的 DIS 测试版工程 |

## 数据格式

- `ladder_raw.csv`：每次读一行，`completion_ms` 是 READ CD 返回的时刻（QueryPerformanceCounter），`role` 是 R（参考）或 X（目标）。
- `ladder_rungs.csv`、`analysis/rungs_all_runs.csv`：每级一行。`y_rad` 是目标减参考的展开相位（弧度，含整圈），`sigma_rad` 是它的误差。LBA k 对应弧长 16·(k + 1) mm（1200 mm/s，每扇区 16 mm）。
- `localsteps_<参考扇区>.csv`：`target, radius_mm, bytes_per_deg, measured_minus_prior_deg, sigma_deg, used`。先验是联想盒的恒定轨距：24.9216305 / 57.8390244 mm、359845 扇区，面积公式。
- `summary.json`：光驱、容量、ATIP、转速周期、参考扇区、先验和阶梯拟合。

## 复现

```bash
cd contrib/dis-cd-timing/analysis
python calibrate_pitch.py --sectors 359845 ../results/disc1 ../results/disc2 ../results/disc3 ../results/disc3_2x
python calibrate_pitch.py --sectors 359849 ../out/newmodel ../out/newmodel_portable
python calibrate_pitch.py --sectors 359845 --link 65600 --localsteps ../results/disc5_jog/localsteps_60067.csv --localsteps ../results/disc5_jog2/localsteps_60067.csv ../results/disc5_cubic_r3
python step_scan.py ../results
python test_calibrate_pitch_link.py --only bce
```

只需要 Python 标准库。
