# AI Learning Partner Agent

本项目是一个本地命令行学习 Agent。  
现在支持两种模式：

- `LLM 模式`：调用大模型 API 生成学习路线、章节内容、测验与反馈。
- `本地兜底模式`：未配置 API 时，使用本地模板与规则继续运行。

## 是否需要配置 API

如果你要“真正的 Agent 智能生成”，需要配置 API。  
如果只想先跑通流程，可以不配 API（会走本地兜底）。

### API 配置方式

1. 在项目根目录复制 `.env.example` 为 `.env`
2. 填写以下变量：

```env
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=90
```

说明：

- `LLM_BASE_URL` 使用 OpenAI 兼容接口地址（形如 `.../v1`）。
- 代码会调用 `POST {LLM_BASE_URL}/chat/completions`。
- 程序会自动读取根目录 `.env`，也支持你手动设置系统环境变量。

## 快速开始（conda 环境 `pytorch1`）

```powershell
cd ai-learning-partner-agent
$env:PYTHONPATH='src'
& python -m learning_partner.cli --help
```

初始化学习项目：

```powershell
$env:PYTHONPATH='src'
& python -m learning_partner.cli init `
  --topic "React Hooks" `
  --level "前端初级" `
  --goal "掌握常见 Hooks 设计与应用" `
  --depth "标准" `
  --code-practice yes `
  --workspace "./learning-workspace"
```

常用命令：

```powershell
$env:PYTHONPATH='src'
& python -m learning_partner.cli next --workspace "./learning-workspace"
& python -m learning_partner.cli status --workspace "./learning-workspace"
& python -m learning_partner.cli answer --workspace "./learning-workspace" --answers-file "./my-answers.txt"
```

## 命令说明

- `init`：初始化学习工程，生成目录结构、`learning-plan.md`、`progress.json`。
- `next`：读取最新学习路线和进度，按顺序生成下一章内容。
- `answer`：提交章节测验回答，自动评分、写入反馈、更新进度。
- `status`：查看主题、完成度、当前章节、LLM 状态和下一步建议。

## 项目声明

本项目的作者及单位

```
项目名称：AI Learning Partner Agent
项目作者：Shengrui Gao,Hong Deng, Chang Ding, Jianhui Qiu,  Zhiquan Liu
作者单位：暨南大学网络空间安全学院
```
