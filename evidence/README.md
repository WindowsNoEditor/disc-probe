# 实测证据

以下全部是 2026-11-03 在 HL-DT-ST GH70N（固件 NYA2）上、使用 Ritek F1 DVD-R（MID `RITEKF1`）得到的原始结果。JSON 里的本地绝对路径已换成文件名（`scrub_paths.py`）。图可以用 `python evidence/make_figures.py` 重新生成。

| 文件 | 内容 |
|---|---|
| `drive/info_blank_ritekf1.json` | 空白盘的 `info` 输出：INQUIRY、各项功能、DVD 物理格式、MID、读写速度表 |
| `drive/timing_4x_random_rings_summary.json` | 读速固定 4x、只读随机数据环的计时测试：转速、抖动、相位精度 |
| `geo/random_disc_*` | 随机数据盘上的全盘梯子测量：26 级，25.8–54.5 mm，残差 rms 0.15°，测量范围内 1σ 为 0.12° |
| `geo/rings_disc_*` | 纹理环盘上 3 个随机数据环的梯子测量：21 级，33.6–45.8 mm |
| `gridscan/grid1_*` | 按计时几何刻的网格盘，6 张扫描，逐半径的转角 φ(r) |
| `gridscan/grid2_*` | 加角度修正、另一张新盘，4 张扫描 |
| `gridscan/grid3_*` | 用复测得到的纯计时几何、不加修正刻的网格盘，8 张扫描；`grid3_eval.txt` 为预先登记判据的结果（通过：0.106° 峰峰值、rms 0.032°、U 形 0.003°） |
| `geo/remeasure_*` | 换参考点（LBA 262336）的预先登记复测：36 级，与"计时加扫描修正"相差 0.082°，0.73σ，强通过 |
| `angle_correction.json` | 由 grid1 拟合出的修正曲线 φ(r)（四次多项式） |
| `dis_preset_ritekf1.json` | 把计时结果加角度修正，拟合成 DiscImageStudio 的 DVD 预设（三次轨距），附转换残差：在 25.8–54.4 mm 内，与实测角度映射的最大差 0.011°、RMS 0.0036°。用精确弧长公式独立复核，最大差 0.011° |
| `check_export.py` | 不依赖 `disexport`，用精确弧长独立复核导出预设，也把社区预设与我们的结果对照（`python evidence/check_export.py`） |
| `ringscan/` | 纹理环盘扫描后各纹理的亮度等级（`--refs A5,B9`） |
| `figures/bending_before_after.png` | 三张网格盘的 φ(r)：grid1 0.31°、grid2 0.14°、grid3 0.11° 峰峰值 |
| `figures/ladder_residuals.png` | 两次梯子测量每一级的残差 |
| `figures/preset_comparison.png` | DiscImageStudio 社区预设 `ritek-dvd-r-e-series`（独立的拍照标定）与我们结果的角度差：不加修正 0.294°，加修正 0.083° 峰峰值 |
| `figures/grid1_scan_*` | grid1 扫描的高通处理图，以及字母 F 的局部放大 |
| `figures/grid_design.png` | 网格测试图的设计（从数据面看） |
| `figures/grid2_scan_highpass.jpg` | grid2（加修正、另一张新盘）扫描的高通处理图 |
| `figures/grid3_scan_highpass.jpg` | 网格盘 3（纯计时，第一次刻录）扫描的高通处理图 |
| `figures/rings_scan_unrolled.png` | 纹理环盘扫描按（半径，角度）展开 |

## CD-DA（DiscImageStudio 音频轨）读取计时：HP BU20N 等（WindowsNoEditor 贡献）

数据和工具在 [`contrib/dis-cd-timing/`](../contrib/dis-cd-timing/README.md)。READ CD 单扇区，读前先读远处挤掉缓存；命令走 IMAPI2 `IDiscRecorder2Ex`，不需要管理员权限。

| 路径 | 内容 |
|---|---|
| `contrib/dis-cd-timing/analysis/rungs_all_runs.csv` | 联想 Thinkplus CD-R 两张盘、4 次阶梯（一次 2 倍转速）的 99 个点；二次轨距 χ²/ν 1.72 |
| `contrib/dis-cd-timing/results/disc5_jog*` | 第 5 张盘 r ≈ 33.4 mm 处约 +0.2 mm 沿轨台阶的定点测量（照片见 `docs/jog_photo_annotated.png`） |
| `contrib/dis-cd-timing/out/newmodel*` | 新型号 CD-R（ATIP 97:27:18）一张探测盘：HP BU20N 两次测量和接缝定点测量，恒定轨距；同一扇区没有台阶 |
| `contrib/dis-cd-timing/out/plds_du8a5lh` | 同一张盘在另一台电脑的 PLDS DU-8A5LH 上（0x06E4，2032 rpm）：几何一致，沿轨常数 x ≈ −603 字节 |
| `contrib/dis-cd-timing/results/gating` | READ CD 完成时刻门控实验：完成由最后一个请求扇区决定，通道选择只加固定处理时间 |
