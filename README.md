# chuangkou — 创口红外温差初筛与临床档案工作站

面向海康微影微型红外测温模组 **HM-TB421-3XF**（`160×120` 氧化钒非制冷探测器，Type-C / UVC）的低成本创口相对温差（`ΔT = T_创口 − T_对照`）初筛平台。已完整融合 `dsh-wound-clinic v0.7.2` 的 5 栏临床工作站体验、右侧“循证对话”医师助手、草稿/患者档案/HTML 报告流程，并在 `dsh-plugin/` 目录保留同步更新的可安装 DeepSeek Harness 原生插件。

> **免责声明**：本系统仅用于创口感染风险辅助筛查与实验验证，不替代医护人员结合创面表现、实验室及病原学检查作出的临床诊断。

---

## 核心特性

### 1. 双形态交付
- **独立浏览器工作站（`app/`）**：无需任何外部宿主，双击 [启动平台.bat](启动平台.bat) 或运行 `python -m app.server` 即可在浏览器中使用完整 5 栏临床工作站。
- **同步 DSH 插件目录（`dsh-plugin/`）**：完整保留 `dsh-wound-clinic v0.7.2` 的 DeepSeek Harness 插件外壳（`package.json / cordis.patch.yml / index.js / client.js / runtime/assistant.js`），且已同步最新多后端相机取流、窗口抓帧兜底、中文路径与 SQLite 句柄关闭修复，供已安装 DSH 的团队成员直接链接使用。

### 2. 医疗亮色 / 暗色实验室双主题 5 栏工作站 UI
- **视觉与主题**：默认采用清透医疗亮色卡片 + 医疗青绿（`#0f766e`）强调色 + 深海蓝黑（`#0e1b24`）高对比热像视口；顶栏支持**一键切换暗色实验室模式**（自动记忆偏好）。
- **左侧 5 个主视图**：
  1. **实时筛查**：4 格 KPI 指标条、交互式热像 ROI 画布（拖拽/四角缩放/点温固定）、4 视图（原图 / 去背景 / 前后对比 / 等温差线 ΔT）、分割模型切换、10 帧稳态锁帧、空间热扩散特征、一键编码探测，以及**示例 JSON / 自定义测量 JSON 导入**。
  2. **报告中心**：草稿列表 → 独立草稿详情页（编辑标题、补充创口结构化详情、查看补充记录、打开循证对话提取字段、质控通过后一键归档）。
  3. **患者档案**：自动编号伪匿名档案（`患者01 / PT-0001` 起递增）、检测记录历史表、可在线打开的 HTML 筛查报告（含 SHA-256 哈希与审计日志）。
  4. **趋势与验收**：纵向 ΔT 折线图、`.npy` 历史帧一键回载复盘、课程分组重复性极差（目标 `≤ 0.30 °C`）与 NTC 误差统计、Markdown 验收表复制与 CSV 下载。
  5. **医学知识库**：已审核 `E001–E004` 循证条目卡片与原始文献链接（实时判定卡片中的 `E00x` 标签可一键跳转高亮）。
- **右侧可折叠“循证对话”医师助手**（[app/assistant.py](app/assistant.py)）：
  - **离线默认可用**：未配置 API Key 时直接由本地规则引擎 + 循证库模板回答，并在草稿模式下自动启发式提取创口部位/病程/表现/处理字段供确认写入。
  - **可选大模型增强**：可在抽屉“模型”页或环境变量填入 DeepSeek / OpenAI 兼容 API（仅保存在本机 `data/assistant_config.json`，不提交 Git）；外发前自动脱敏，回答经服务端防确诊/防用药/防篡改等级校验，违规一律拦截并回退本地模板。
- **双阈值口径清晰分工**：实时热像画布与验收统计台沿用**课程三级**（`1.0 / 2.2 °C`），临床草稿、患者档案、HTML 报告与循证对话严格执行 **dsh 四级循证规则**（`-0.6 / 0.6 / 2.2 / 2.55 °C`，版本 `wound-delta-v1`）。

### 3. 多后端 / 多编码相机接入与 Windows 编码兼容
- **自适应取流链路**（[app/engine.py](app/engine.py)）：
  1. `FFmpeg DirectShow (-vcodec mjpeg)`：原生 MJPEG 直通，兼容海康 `0x70827773`（`STREAM_FARME_INFO_TEMP`）全屏温度帧解析；
  2. `FFmpeg DirectShow (自动解码)`：兼容 `YUYV / NV12 / RGB24` 等非 MJPEG 像素格式；
  3. `OpenCV (DSHOW / MSMF × MJPG / 默认)`：无 FFmpeg 时自动回退，支持 `uint16` 16-bit 候选温度帧识别；
  4. `WinRT MediaCapture`（[app/winrt_capture.py](app/winrt_capture.py)）：安装 `winrt-*` 依赖时作为可选后端（优先独占模式）；
  5. `Windows 相机窗口抓帧`（[app/window_capture.py](app/window_capture.py)）：零额外依赖 Win32 兜底源，自动裁去标题栏与黑边。
- **编码与中文路径修复**：[启动平台.bat](启动平台.bat) 启用 `chcp 65001` 与 `PYTHONUTF8=1`；子进程严格 `UTF-8 → GBK` 解码；中文目录 8.3 短路径兼容 OpenCV；ONNX 加载提供内存字节回退；全程规避 `cv2.imread`/`cv2.imwrite` 中文路径限制。

---

## 快速开始

### 1. 环境准备
- Python `3.10+`（Windows 10/11 推荐）
- 安装依赖：
  ```bash
  pip install opencv-python numpy onnxruntime
  ```
- 推荐安装 `FFmpeg` 并加入 `PATH`（未安装时自动回退 OpenCV）。

### 2. 启动独立浏览器工作站
- 双击根目录 [启动平台.bat](启动平台.bat)，或运行：
  ```bash
  python -m app.server
  ```
- 浏览器访问：`http://127.0.0.1:8765`（端口可通过环境变量 `CHUANGKOU_PORT` 修改）。

### 3. 连接摄像头或体验完整演示流程
- **连接真机**：关闭 Windows 系统“相机”或其他占流程序，插入 `HM-TB421-3XF`，点顶栏 **刷新 → 开始**；点击 **探测编码**（或运行 `python -m app.probe_camera`）查看格式与位深。若设备在特定电脑上被系统策略限制，可先打开系统“相机”并在来源中选择 **“抓拍 Windows 相机窗口（兜底）”**。
- **无硬件体验完整临床流程**：点击热像视口上方 **“示例 JSON”** 载入 [examples/measurement.json](examples/measurement.json)，即可完整走通 **保存草稿 → 报告中心补充详情 / 循证对话提取 → 归档为患者01 → 在线查看 HTML 报告**。

### 4. 实时筛查快捷键
| 按键 | 功能 |
|---|---|
| `A` | 切换自动热区追踪 / 手动框选 |
| `1` / `2` | 切换绘制创口框（橙） / 对照框（蓝） |
| `P` | 按手掌质心与主轴姿态对齐 ROI |
| `M` | 启动 / 解除 10 帧稳态采集锁定 |
| `S` | 归档实验帧（`.npy` + `.png` + CSV） |
| `Esc` | 关闭弹窗 / 收起循证对话 / 清除点温标记 |

---

## 目录结构

```text
chuangkou/
├── 启动平台.bat                      # Windows UTF-8 一键启动脚本
├── 初步方案.md                       # 硬件选型、300 mm 支架设计与验收方案
├── examples/
│   └── measurement.json             # 标准 wound-measurement/v1 演示数据
├── app/                             # 独立浏览器工作站
│   ├── server.py                    # HTTP 服务、MJPEG 推流与全量 API
│   ├── engine.py                    # 多后端采集、10 帧稳态平均、分割与实验归档
│   ├── protocol.py                  # 0x70827773 / Y16 解码、物理分割、热扩散与 OSD 反演
│   ├── foreground.py                # 热像伪彩分割与 U²-Net ONNX 防漂移门控
│   ├── clinic.py                    # SQLite 临床草稿、患者档案、质量门禁与 HTML 报告
│   ├── assistant.py                 # 医师角色循证对话、脱敏、详情提取与安全校验拦截
│   ├── probe_camera.py              # DirectShow / OpenCV 编码与 16-bit 位深探测
│   ├── winrt_capture.py             # 可选 WinRT MediaCapture 后端
│   ├── window_capture.py            # Windows 相机窗口抓帧兜底模块
│   ├── clinical_data/               # E001–E004 循证库与 physician_rules.json
│   ├── static/                      # 5 栏亮/暗双主题前端（index.html / app.css / app.js）
│   ├── weights/                     # U²-Net 权重（默认附带 u2netp.onnx）
│   └── test_*.py                    # 协议、引擎、临床与循证对话回归测试
├── dsh-plugin/                      # 同步更新的 DeepSeek Harness 原生插件（dsh-wound-clinic）
└── data/                            # 运行时数据（SQLite、HTML 报告、本机模型配置等，已忽略）
```

---

## 运行测试

```bash
# 独立工作站全套单元测试（协议、引擎、HTTP API、临床归档、循证安全校验）
python -m unittest discover -s app -p "test_*.py" -v
python -m app.test_protocol

# DSH 插件回归测试（Python 工作流与实时流 + Node 规则与客户端渲染）
python dsh-plugin/runtime/test_workflow.py
python dsh-plugin/runtime/test_live.py
node dsh-plugin/runtime/test_assistant.mjs
node dsh-plugin/runtime/test_client_render.cjs
```
