# 报销助手（Star Invoice Helper）

学生社团报销材料齐套管理、启发式归类与 A4 拼版导出。

## 功能

1. **齐套管理**：创建报销条目，上传发票 PDF / 订单截图 / 支付记录，查看缺项
2. **自动排版**：齐套后一键导出 A4 纵向 PDF（上发票，下订单 | 支付等高并排）
3. **自动归组**：批量上传后用 PDF 文本 + RapidOCR 抽取金额/商家等，按金额归入拟建条目，审阅后入库（模型在 `vendor/ocr/`，可绿色拷贝）

## 环境说明（避免污染 base）

| 用途 | 环境 |
|------|------|
| 前端 Node / npm / Vue | conda 环境 **`star-invoice`**（见 `environment.yml`） |
| 后端 Python 依赖 | 项目内 **`.venv`**（不写入 conda base） |

若尚未创建 conda 环境：

```bat
conda env create -f environment.yml
```

或：

```bat
conda create -y -n star-invoice nodejs=22 -c conda-forge
```

## 开发启动

推荐双击或运行：

```bat
start-dev.bat
```

或 PowerShell：

```powershell
.\start-dev.ps1
```

脚本会：

1. 如无则创建 `.venv` 并 `pip install -r requirements.txt`
2. 用 `D:\Miniconda\envs\star-invoice\npm.cmd` 安装前端依赖
3. 启动 API：`http://127.0.0.1:8765`（**不用 8000**，避免和本机其他服务冲突；开发模式带 `--reload`，改 `backend/` 会自动热重启）
4. 健康检查确认 `service=star-invoice-helper`
5. 启动 Vite：`http://127.0.0.1:5180`（代理 `/api` → `8765`；不用 5173，避免和 PhotoProcesser 等冲突）

浏览器打开 **http://127.0.0.1:5180**。顶部应显示「API 已连接」。

若 **360 安全卫士** 在启动或批量入库时弹窗拦截：把本项目目录（或绿色包解压目录）加入 360 的「信任区 / 加白名单」。本软件只监听本机 `127.0.0.1`，不访问外网；第一次识别发票时会加载 OCR 模型，360 仍可能误报一次。

手动分步：

```bat
:: 后端（开发热重启）
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8765 --reload --reload-dir backend

:: 前端（另开终端，使用 conda 环境里的 npm）
cd frontend
D:\Miniconda\envs\star-invoice\npm.cmd install
D:\Miniconda\envs\star-invoice\npm.cmd run dev
```

## 日志

运行后日志写入：

- 控制台（uvicorn + 业务日志）
- `data/logs/app.log`（滚动文件，含请求耗时、创建条目、上传、归类、拼版等）

## 生产 / 单端口模式

```bat
start.bat
```

会构建 `frontend/dist`，由 FastAPI 静态托管，访问 **http://127.0.0.1:8765**。

## 目录结构

```
backend/app/          FastAPI、SQLite、拼版与归类
frontend/             Vue 3 + Vite
data/                 上传、导出、数据库（gitignore）
environment.yml       conda 前端工具链
requirements.txt      Python 依赖
```

## 绿色便携包（Windows）

在本机双击或运行：

```bat
build-green.bat
```

或：

```powershell
.\scripts\build-green.ps1
```

脚本会：构建前端、下载 embeddable Python、安装依赖、拷贝 `vendor/ocr`，输出到：

- `release/StarInvoiceHelper/`（解压即用，双击 `启动.bat` / `Start.bat`）
- `release/StarInvoiceHelper-green-*.zip`

目标机无需安装 Python / Node。数据写在包内 `data/`。
