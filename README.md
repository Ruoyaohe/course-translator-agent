# Course Translator Agent

一个面向课堂场景的课程翻译 Agent：电脑麦克风录音、多语言识别、中文实时字幕、AI 课程纪要、DDL 提取、脑图生成，并在人工确认后发布到本地 Obsidian Vault。

> 当前版本是个人可运行的 MVP。录音与实时转写可以留在本机；生成结构化课程纪要需要用户自己的阿里云百炼千问 API Key，并按阿里云实际用量付费。

## 功能

- 使用电脑内置或蓝牙麦克风录音，音频分块写入 IndexedDB，支持断网缓存与恢复上传。
- 支持自动语言识别，也可指定英语、中文、法语、德语、西班牙语、意大利语、葡萄牙语、日语、韩语、阿拉伯语或印地语；字幕统一翻译为中文。
- 学校或机构名称为可选属性，未勾选时不会写入笔记。
- 使用 `qwen3.7-flash` 生成摘要、重点、时间线、日程、DDL、待确认事项和 Mermaid 脑图。
- 调用 AI 前显示预计 Token、阶梯单价、预计费用和处理时间。
- 所有课程笔记先进入 `REVIEW_DRAFT`，由用户审核后才能写入 Obsidian。
- 发布前核对路径、文件名和 frontmatter，按课程录制当天的本地日期命名。
- 提供 Streamable HTTP MCP Server 和配套 Codex skill。

## 费用与外部服务

### 千问模型 API

AI 整理不是免费的。你需要自行开通阿里云百炼、创建 API Key，并承担模型调用费用。

- [阿里云百炼控制台](https://bailian.console.aliyun.com/)
- [Qwen3.7-Flash 模型说明](https://help.aliyun.com/zh/model-studio/qwen3-7-flash)
- [官方模型价格](https://help.aliyun.com/zh/model-studio/model-pricing)
- [API Key 获取与配置](https://help.aliyun.com/zh/model-studio/get-api-key)

推荐模型：

```dotenv
QWEN_TEXT_MODEL=qwen3.7-flash
QWEN_REGION=singapore
```

`qwen3.7-flash` 支持结构化输出，价格较低，适合课程摘要和任务提取。项目中的费用弹窗只提供调用前估算，最终费用以阿里云账单为准。

API Key 只应写入服务端 `.env`。不要把 Key 放入浏览器代码、提交到 Git，或发送到公开聊天和 Issue。

### Obsidian

课程笔记写入用户指定的本地 Obsidian Vault，不需要 Obsidian Sync。你需要先安装 Obsidian，并创建或选择一个本地 Vault。

- [下载 Obsidian](https://obsidian.md/download)
- [Obsidian 官方安装说明](https://obsidian.md/help/install)

默认笔记结构：

```text
Note/课程记录/
├── 课程/
│   └── 课程名称/
│       └── YYYY-MM-DD—课程名称—课堂标题.md
├── 课程日程.md
└── 作业与DDL.md
```

应用不会另外保存“完整原文.md”。机器转写用于生成纪要和证据时间戳，发布时只输出审核后的单篇课程笔记及汇总条目。

## 本地运行

### 环境要求

- macOS、Linux 或 Windows
- Python 3.11
- Node.js 20 或更新版本
- npm
- 麦克风权限
- 可选：本地 Whisper/翻译模型目录
- 可选：阿里云百炼千问 API Key
- 可选：Obsidian

### 1. 克隆与安装

```bash
git clone https://github.com/Ruoyaohe/course-translator-agent.git
cd course-translator-agent

python3.11 -m venv .venv311
source .venv311/bin/activate
pip install -r services/api/requirements.txt

cd apps/web
npm install
cd ../..
```

Windows PowerShell 激活虚拟环境：

```powershell
.venv311\Scripts\Activate.ps1
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```dotenv
APP_ENV=development
PUBLIC_BASE_URL=http://127.0.0.1:3890
API_BASE_URL=http://127.0.0.1:8890

# 用户自行申请并付费；不要提交到 Git
DASHSCOPE_API_KEY=your_api_key_here
QWEN_REGION=singapore
QWEN_TEXT_MODEL=qwen3.7-flash

# mock：无需模型，使用演示数据
# local：本地语音识别 + 千问课程整理
COURSE_PROVIDER=local
LOCAL_MODEL_ROOT=/absolute/path/to/your/local-asr-models

# 你的本地 Obsidian Vault 绝对路径
OBSIDIAN_REPO_PATH=/absolute/path/to/your/obsidian-vault
OBSIDIAN_NOTES_ROOT=Note/课程记录
```

`.env`、录音、数据库、模型文件和课程隐私数据已在 `.gitignore` 中排除。

### 3. 启动服务

启动 API：

```bash
source .venv311/bin/activate
uvicorn services.api.app.main:app --host 127.0.0.1 --port 8890
```

另开一个终端启动 PWA：

```bash
cd apps/web
NEXT_PUBLIC_API_URL=http://127.0.0.1:8890 npm run dev -- --hostname 127.0.0.1 --port 3890
```

打开 <http://127.0.0.1:3890/>。

如果只想查看界面和完整流程，可以先设置：

```dotenv
COURSE_PROVIDER=mock
```

Mock 模式不会调用千问，也不会产生模型费用。

## 使用流程

1. 输入课程名、课堂标题和专业术语。
2. 点击“开始录音”，允许浏览器使用麦克风。
3. 课堂中查看英文原文和中文实时字幕。
4. 停止录音，等待转写和结构化整理。
5. 点击“AI 重新整理”时检查 Token 与费用预估。
6. 在 `REVIEW_DRAFT` 中审核摘要、重点、DDL 和待确认事项。
7. 点击“确认并发布”，将 Markdown 写入本地 Obsidian Vault。

## 数据与隐私

- 长期 API Key 仅保存在服务端环境变量中。
- 浏览器先把录音块保存在 IndexedDB，再上传到用户自己的服务端。
- 日志不应记录 API Key、完整转写或原始音频。
- 生产配置计划在处理完成七天后删除原始录音。
- 未审核的草稿不会写入 Obsidian。
- 请在录音前取得课堂参与者许可，并遵守所在地和学校的录音规定。

## 项目结构

```text
apps/web                   Next.js 手机 PWA
services/api               FastAPI、音频上传与课程工作流
services/worker            清理与后台任务入口
services/mcp               课程 MCP Server
packages/contracts         JSON Schema 和共享契约
skills/course-interpreter  Codex 课程整理 skill
infra                      Docker 与部署基础文件
```

## 开发与测试

```bash
source .venv311/bin/activate
pytest -q

cd apps/web
npm run build
```

## 当前限制

- 第一版是单用户产品。
- iPhone PWA 在锁屏或切换到其他 App 后不保证继续录音。
- 本地语音识别准确率受设备性能、收音距离、噪声和说话人口音影响。
- 发布目标必须是运行 API 服务的机器可以访问的本地目录。
- GitHub OAuth、阿里云部署、Qwen ASR 课后二次校准和 Obsidian Git 自动同步仍在继续完善。

## 安全报告

请不要在公开 Issue 中提交 API Key、录音、课堂原文或个人信息。发现安全问题时，请先撤销相关密钥，再通过仓库维护者提供的私密渠道联系。
