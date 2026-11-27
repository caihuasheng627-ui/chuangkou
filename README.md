# chuangkou — 创口红外温差初筛与临床档案工作站

面向海康微影微型红外测温模组 **HM-TB421-3XF**（`160×120` 氧化钒非制冷探测器，Type-C / UVC）的低成本创口相对温差（`ΔT = T_创口 − T_对照`）初筛平台。已整合 `dsh-wound-clinic v0.7.2` 的质量门禁、临床草稿、自动编号患者档案、可追溯 HTML 筛查报告与循证依据库，可作为独立浏览器工作站运行。

> **免责声明**：本系统仅用于创口感染风险辅助筛查与实验验证，不替代医护人员结合创面表现、实验室及病原学检查作出的临床诊断。

---

## 核心特性

### 1. 多后端 / 多编码相机接入与探测
- **自适应取流链路**（[app/engine.py](app/engine.py)）：
  1. `FFmpeg DirectShow (-vcodec mjpeg)`：原生 MJPEG 直通，同时兼容海康 `0x70827773`（`STREAM_FARME_INFO_TEMP`）全屏温度帧解析；
  2. `FFmpeg DirectShow (自动解码)`：兼容 `YUYV / NV12 / RGB24` 等非 MJPEG 像素格式；
  3. `OpenCV (DSHOW / MSMF × MJPG / 默认)`：无 FFmpeg 环境自动回退，支持 `uint16` 16-bit 候选温度帧解码；
  4. `WinRT MediaCapture`（[app/winrt_capture.py](app/winrt_capture.py)）：安装 `winrt-*` 依赖时作为可选后端（优先独占模式）；
  5. `Windows 相机窗口抓帧`（[app/window_capture.py](app/window_capture.py)）：零额外依赖的 Win32 兜底输入源，自动裁切标题栏与黑边。
- **一键编码与位深探测**（[app/probe_camera.py](app/probe_camera.py)）：界面点击 **“探测编码”** 或运行 `python -m app.probe_camera`，输出 DirectShow 支持格式、OpenCV 实际 `FOURCC / dtype` 与 16-bit 温度候选判定。
- **Windows 中文路径与编码兼容**：统一 `UTF-8 / GBK` 子进程解码、中文目录 8.3 短路径兼容、[启动平台.bat](启动平台.bat) 启用 `chcp 65001` 与 `PYTHONUTF8=1`。

### 2. 红外测温分析、分割与物理可视化
- **10 帧稳态采集与防抖**：监测皮肤区域帧间跳变与 10 帧极差（阈值 `≤ 0.3 °C`），避开快门校正和手部晃动。
- **三级温差分级**（[app/protocol.py](app/protocol.py)）：
  - `< 1.0 °C`：未见明显局部温升（档 0）
  - `1.0 ~ 2.2 °C`：局部偏热，建议观察（档 1）
  - `≥ 2.2 °C`：温升明显，建议进一步检查（档 2）
- **四视图切换**：`原图`、`去背景`、`前后对比`、`等温差线 ΔT`（叠加 `+1.0 °C` 黄线与 `+2.2 °C` 红线）。
- **前景分割**（[app/foreground.py](app/foreground.py)）：默认零域偏移热像伪彩分割，可选 `U²-Net 小 (u2netp.onnx)`、`U²-Net 标准`、`人体分割`（均带热像暖区防漂移纠偏）。
- **空间热扩散与手姿对齐**：输出半高宽热斑面积（mm²）、等效直径、0–24 mm 径向温度衰减斜率、热晕比、形态长宽比，以及手掌质心-主轴姿态跨次对齐。
- **伪彩半定量提示**：模组仅输出带 OSD 的 8-bit 伪彩流时，支持红/绿十字双锚点半定量反演用于定位与演示（质量门禁会自动标明非真实温度矩阵，禁止正式临床归档）。

### 3. 临床草稿、患者档案与验收统计
- **临床档案工作流**（[app/clinic.py](app/clinic.py)）：
  - `实时筛查 → 存为草稿 → 质量门禁与规则判定 → 补充结构化创口详情（自动剥离直接身份字段） → 归档为患者01 (PT-0001) → 生成带 SHA-256 哈希与审计日志的 HTML 报告`。
  - 内置 `E001–E004` 审核循证条目（[app/clinical_data/evidence.json](app/clinical_data/evidence.json)）与医师助手安全边界规则（[app/clinical_data/physician_rules.json](app/clinical_data/physician_rules.json)）。
- **课程/实验验收台**：支持分组统计重复性极差（目标 `≤ 0.30 °C`）与 NTC 实测平均误差，支持 `.npy` 原始温度矩阵回载复盘、CSV 下载与 Markdown 验收表一键复制。

---

## 快速开始

### 1. 环境准备
- Python `3.10+`（Windows 10/11 推荐）
- 安装 Python 依赖：
  ```bash
  pip install opencv-python numpy onnxruntime
  ```
- 推荐安装 `FFmpeg`（加入系统 `PATH`），以启用 DirectShow 原生 MJPEG 直通与全屏测温流解析；未安装时会自动回退到 OpenCV 采集。

### 2. 启动工作站
- **Windows 一键启动**：双击根目录 [启动平台.bat](启动平台.bat)
- **命令行启动**：
  ```bash
  python -m app.server
  ```
- 浏览器访问：`http://127.0.0.1:8765`（可通过环境变量 `CHUANGKOU_PORT` 自定义端口）。

### 3. 连接摄像头与实测
1. 关闭 Windows 系统“相机”或其他占用摄像头的软件，插入 `HM-TB421-3XF`。
2. 启动服务后会自动尝试连接名称包含 `UVC / HIK / THERMAL` 的热像模组；如中途插拔，点击顶部 **刷新 → 开始**。
3. 点击右侧 **“探测编码”**（或命令行运行 `python -m app.probe_camera`）查看实际格式与位深。
4. 若某些受策略管控的电脑拦截了桌面进程访问摄像头，可先打开 Windows 系统“相机”保持不最小化，再在来源下拉框中选择 **“抓拍 Windows 相机窗口（兜底）”**。

### 4. 快捷键
| 按键 | 功能 |
|---|---|
| `A` | 切换自动热区追踪 / 手动框选 |
| `1` / `2` | 切换绘制创口框（橙） / 对照框（蓝） |
| `P` | 按当前手掌姿态对齐框选位置 |
| `M` | 启动 / 解除 10 帧稳态采集锁定 |
| `S` | 归档当前稳定温度帧（`.npy` + `.png` + CSV） |
| `Esc` | 清除画布上固定的点温标记 |

---

## 目录结构

```text
chuangkou/
├── 启动平台.bat                      # Windows UTF-8 一键启动脚本
├── 初步方案.md                       # 硬件选型、300 mm 支架设计与验收方案
├── app/
│   ├── server.py                    # 本地 HTTP 服务、MJPEG 推流与全部 API 路由
│   ├── engine.py                    # 多后端采集、10 帧稳态平均、分割与归档引擎
│   ├── protocol.py                  # 0x70827773 / Y16 解码、物理分割、热扩散与 OSD 反演
│   ├── foreground.py                # 热像伪彩分割与 U²-Net ONNX 防漂移门控
│   ├── clinic.py                    # SQLite 临床草稿、患者档案、质量门禁与 HTML 报告
│   ├── probe_camera.py              # DirectShow / OpenCV 编码与 16-bit 位深探测工具
│   ├── winrt_capture.py             # 可选 WinRT MediaCapture 后端
│   ├── window_capture.py            # Windows 相机窗口抓帧兜底模块
│   ├── clinical_data/
│   │   ├── evidence.json            # E001–E004 审核医学循证库
│   │   └── physician_rules.json     # 医师助手安全口径与校验规则
│   ├── static/                      # 独立前端界面（index.html / app.js / app.css）
│   ├── weights/                     # U²-Net 权重（默认附带 u2netp.onnx）
│   ├── test_protocol.py             # 协议、算法与实拍样本回归测试
│   ├── test_engine.py               # 引擎状态机与 HTTP API 端到端测试
│   └── test_clinic.py               # 编码兼容、采集回退与临床归档全链路测试
└── data/                            # 运行时数据（数据库、报告、抓拍归档已加入 .gitignore）
```

---

## 主要 API 接口

| 方法与路径 | 说明 |
|---|---|
| `GET /stream.mjpg` | 实时 MJPEG 视频流 |
| `GET /api/devices` | 枚举已连接摄像头与可用分割模型 |
| `GET /api/probe` | 探测摄像头 DirectShow 格式、视频编码与 16-bit 候选帧 |
| `GET /api/state` | 获取实时温度、ROI、分级、手姿、热扩散特征与采集后端状态 |
| `POST /api/start` / `/api/stop` | 启停信号源（`cam:N`、`window:camera`、`file`、`synthetic[:strong\|mild\|baseline]`） |
| `POST /api/measure` / `/api/unlock` | 启动 10 帧稳态锁帧 / 恢复实时流 |
| `POST /api/save` & `GET /api/records(.csv)` | 保存实验帧与导出验收 CSV |
| `GET /api/clinic/summary` | 获取临床草稿、患者档案、HTML 报告与循证依据列表 |
| `POST /api/clinic/draft/create\|update\|archive` | 创建草稿、补充结构化详情、质控通过后归档为患者档案 |
| `GET /api/clinic/report/<report_id>` | 在线浏览已生成的 HTML 筛查报告 |

---

## 运行测试

```bash
# 引擎、HTTP 接口、编码安全与临床归档全套测试
python -m unittest discover -s app -p "test_*.py" -v

# 温度协议、物理皮肤分割与实拍样本回归
python -m app.test_protocol
```

---

## 常见问题排查

1. **只有 Windows 系统“相机”能出图，桌面程序返回 0 帧或灰屏**：
   - 检查 `Windows 设置 → 隐私和安全性 → 相机 → 允许桌面应用访问你的相机` 是否开启；
   - 关闭 360 / 火绒 / OEM 管家的“摄像头保护”或放行 Python/FFmpeg；
   - 确认没有其他程序（包括后台系统相机）占用摄像头，必要时重启 `Windows Camera Frame Server` 服务；
   - 临时应急可直接切换下拉框中的 **“抓拍 Windows 相机窗口（兜底）”**。
2. **有画面但提示“无真实温度矩阵 / 门禁阻断归档”**：
   - `HM-TB421-3XF` 默认 UVC 流为 `240×320` 带 OSD 的 8-bit 伪彩预览，不含每像元温度矩阵；
   - 如需真实 `160×120` 辐射温度矩阵，需通过海康微影官方上位机/UVC 扩展单元（XU）切至全屏测温流，或对接官方 SDK（`HCUSBSDK / IThermal SDK`）。
