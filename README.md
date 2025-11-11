# Ocean & Climate Daily Digest (Auto JSON via GitHub Actions)

这个小项目会**每天自动生成 `latest.json`**（涵盖昨天的顶级海洋/气候论文），并发布到 GitHub Pages，供你的本地离线网页自动拉取。

## 快速上手（10 分钟）
1. 新建一个 GitHub 仓库（私有或公开均可），名字例如 `ocean-climate-digest`。
2. 在仓库里创建以下文件（见本压缩包）：
   - `.github/workflows/daily_digest.yml`
   - `scripts/build_digest.py`
   - `docs/` 目录（GitHub Pages 将从这里发布），先放一个占位的 `latest.json`。
3. 在仓库 **Settings → Pages** 选择 Source = `Deploy from a branch`，Branch = `main`，Folder = `/docs`。
4. 在仓库 **Settings → Secrets and variables → Actions → New repository secret** 添加：
   - `OPENAI_API_KEY`：你的 OpenAI API Key（可选；填写后将对每篇论文生成“关键结论/对比/未解问题”）。
   - （可选）`CONTACT_EMAIL`：用于 Crossref 的礼貌参数。
5. 打开 `docs/latest.json` 的公网地址，例如：`https://YOURNAME.github.io/REPO/latest.json`，复制这个 URL。
6. 打开我给你的**自动拉取版 HTML**，点击“设置”，把上一步的 URL 粘贴进去，并勾选“打开页面时自动拉取”。

> GitHub Actions 默认使用 **UTC**；当前工作流设定在 `00:30 UTC` 运行，即 **台北时间 08:30**。

## 生成逻辑
- 主数据源：**OpenAlex Works API**，按**发布日期**筛选“昨天”的**期刊论文**，并限定在**高水平期刊**白名单中；字段采用 `primary_location.source.id` 指定期刊，`type=journal-article`，`from_publication_date` 与 `to_publication_date` 设为昨天。
- 兼容性：如当天为空，可回退到 **Crossref REST API**（`from-pub-date` / `until-pub-date`）。
- 摘要生成：若提供 `OPENAI_API_KEY`，将基于摘要（可用时）自动生成 `summary / context / open_question`。

## 本地开发
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/build_digest.py
```

生成的 JSON 会写入 `docs/latest.json` 和 `docs/YYYY-MM-DD.json`。

## 注意
- OpenAlex 的 `from_created_date / from_updated_date` 可能是 **Premium** 功能，脚本默认使用 `from_publication_date`（免费）。
- 期刊白名单可在脚本顶部编辑。
