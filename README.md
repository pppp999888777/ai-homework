# 智学闭环 · 自适应数学作业系统

## 两种运行方式

**1. 纯前端演示**：直接双击打开 `index.html`。批改结果为本地模拟，不需要网络 API。

**2. 真实 AI 批改**（阶段 2）：

```bash
# 首次安装（需要 Python 3.9+）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 启动
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

浏览器打开 http://localhost:8000 ，右上角显示"🤖 AI 批改"即为真实模式。
手机与电脑在同一 Wi-Fi 下时，可用 `http://<电脑局域网 IP>:8000` 直接拍照上传。

## 批改流程

1. 前端把照片压缩到长边 1800px 的 JPEG，连同题目清单、标准答案、当前掌握度一起 POST 到 `/api/grade`。
2. 后端调用 Claude（默认 `claude-opus-5-5`）识别手写过程、判断对错、归因、写引导提示，输出严格 JSON（structured outputs）。
3. **规则校验**：对数值题和比较大小题，后端用标准答案再判一次对错；与模型判断不一致时以规则为准，并在 `meta.rule_overrides` 中记录。
4. 后端按与前端一致的规则计算 `mastery_updates`，结果与照片存入 `data/`（SQLite + 原图）。

## 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | 必填 |
| `CLAUDE_MODEL` | `claude-opus-5-5` | 批改模型 |
| `CLAUDE_EFFORT` | `high` | `low` / `medium` / `high`，越低越快越省 |

请求启用了服务端 `fallbacks: "default"`：如果模型因安全策略拒绝处理，会自动换用推荐的备用模型重试。

## 接口

- `GET  /api/health` — 是否已配置 API Key
- `POST /api/grade` — 批改，返回 PRD 提示词 1 的 JSON 协议（额外字段：`recognized_work`、`error_step`、`meta`）
- `GET  /api/submissions/{student_id}` — 历史批改记录

## 说明

- 学生的知识状态（掌握度、复习调度）目前仍保存在浏览器 localStorage；后端只保存批改记录。
- `data/uploads/` 中保存的是学生作业照片，部署前请考虑访问控制和保留期限。
