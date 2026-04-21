# Generate-and-Send-Newsletter

**自动抓取 AI 新闻 → AI 总结翻译 → 生成精美邮件 → 定时发送**

[English](README.md)

---

## 简介

本项目是一个全自动的 AI 新闻简报生成与发送系统。通过 RSS 订阅源抓取最新的 AI 资讯，利用 Azure OpenAI 大模型进行内容总结与中文翻译，生成精美的 HTML 邮件，最后通过 SMTP 发送给订阅者。整个流程由 GitHub Actions 每日自动执行。

## 工作流程

```
RSS 源 → 解析内容 → AI 去广告 → AI 总结 → AI 翻译 → HTML 邮件 → SMTP 发送
```

## 项目结构

```
├── newsletter_git_action.py        # 主入口脚本
├── requirements.txt                # Python 依赖
├── function/
│   ├── AzureAIClient.py            # Azure OpenAI 客户端封装
│   ├── EmailSender.py              # SMTP 邮件发送器（含重试机制）
│   └── NewsCollector.py            # 新闻采集、总结、翻译核心逻辑
├── NewsTemplate/
│   └── AINewsTemplate.py           # HTML 邮件模板
└── .github/workflows/
    └── PLAYPRO-Generate-and-Send-Daily-AI-Newsletter.yaml  # GitHub Actions 定时任务
```

## 核心功能

- **RSS 新闻抓取** — 从指定 RSS 源获取最新 AI 资讯
- **AI 广告移除** — 使用大模型智能识别并移除推广内容
- **AI 内容总结** — 将长文压缩为易懂的要点摘要
- **AI 中文翻译** — 自动翻译为中文，保留 Markdown 格式和链接
- **精美 HTML 邮件** — 暗色主题响应式邮件模板
- **自动重试机制** — SMTP 发送失败时自动重试
- **GitHub Actions 定时运行** — 每日 UTC 8:00 自动执行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

创建 `.env` 文件（本地调试用）：

```env
# Azure OpenAI
AZURE_OPENAI_TOKEN=your_azure_openai_api_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/

# RSS 源
RSS_URL=https://your-rss-feed-url.com/rss.xml

# SMTP 邮件配置
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SENDER_USERNAME=your_email@example.com
SENDER_PASSWORD=your_email_password
TO_ADDRS=recipient1@example.com,recipient2@example.com
FROM_ALIAS=AI Newsletter
```

### 3. 本地运行

```bash
python newsletter_git_action.py
```

## GitHub Actions 部署

在仓库的 **Settings → Secrets and variables → Actions** 中添加以下 Secrets：

| Secret 名称 | 说明 |
|---|---|
| `AZURE_OPENAI_TOKEN` | Azure OpenAI API 密钥 |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI 端点 URL |
| `RSS_URL` | RSS 订阅源地址 |
| `SMTP_HOST` | SMTP 服务器地址 |
| `SMTP_PORT` | SMTP 端口（如 465） |
| `SENDER_USERNAME` | 发件人邮箱 |
| `SENDER_PASSWORD` | 发件人密码/授权码 |
| `TO_ADDRS` | 收件人（逗号分隔） |
| `FROM_ALIAS` | 发件人显示名称 |

配置完成后，workflow 将在每天 UTC 8:00 自动运行，也可在 Actions 页面手动触发。

## 技术栈

- **Python 3.11+**
- **Azure OpenAI** — GPT 大模型用于总结、翻译、去广告
- **html2text** — HTML 转 Markdown
- **markdown** — Markdown 转 HTML（邮件模板渲染）
- **GitHub Actions** — CI/CD 定时任务

## 许可证

详见 [LICENSE](LICENSE)。
