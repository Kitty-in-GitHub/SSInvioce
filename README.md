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

## 文档

- [开发计划与进度](docs/开发计划与进度.md)：工程方向、已完成、待办、已知限制、变更记录
- [材料上传与识别流程](docs/材料上传与识别流程.md)：上传 / 收件箱 / 聚类 / 判重 / 回收站的实现细节

## 自检

发票上的红色监制章在电子发票 PDF 里是 `/Stamp` 注释，拼版时必须先展平才能保留。改动拼版逻辑后可用脚本核对（只读发票 PDF，对比件写在内存/临时目录）：

```bat
.venv\Scripts\python scripts\check_invoice_seal.py
```

默认扫描 `data/uploads` 下的所有发票 PDF，也可传入具体文件。加 `--legacy` 会关闭「注释展平」以模拟修复前行为，此时应当全部失败——用来确认检查脚本本身有效。

批量上传/收件箱流程也可以跑隔离环境自检（数据目录指向系统临时目录，不碰项目 `data/`）：

```bat
.venv\Scripts\python scripts\check_inbox_staging.py
```

覆盖：上传直接进收件箱、关窗重开后仍能继续整理、改类型持久化、确认入库、丢弃进回收站并恢复、查重。

## 生产 / 单端口模式

```bat
start.bat
```

会构建 `frontend/dist`，由 FastAPI 静态托管，访问 **http://127.0.0.1:8765**。

## 目录结构

```
backend/app/          FastAPI、SQLite、拼版与归类
frontend/             Vue 3 + Vite
docs/                 开发计划与流程文档
data/                 上传、导出、回收站、数据库（gitignore）
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

### 发布到 GitHub Release

把 `release/StarInvoiceHelper-green-*.zip` 作为 Release 附件即可。建议在 Release 说明里写上 zip 的 **SHA256**（PowerShell：`Get-FileHash .\release\StarInvoiceHelper-green-*.zip -Algorithm SHA256`），并注明：本机工具、只监听 `127.0.0.1`、源码在本仓库、可用 `build-green.bat` 复现。

Windows SmartScreen、360 等可能把**未签名**且自带 `python.exe` 的压缩包标成风险，多半是误报。不要用加壳等方式规避扫描。正确做法：

1. 仓库公开，Release 说明写清用途与校验和
2. 解压后把目录加入 360「信任区 / 加白名单」
3. 若 Defender 误杀，到 [Microsoft 安全情报](https://www.microsoft.com/wdsi/filesubmission) 提交误报

发布包不要带用户 `data/`（脚本生成的是空数据目录）。界面主题在浏览器本地，不包含在备份/绿色包里。
