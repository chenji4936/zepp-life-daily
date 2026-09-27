# Step Studio · GitHub Actions 定时版

**无需你的 Windows 电脑开机。** 此独立项目借助 GitHub Actions 在云端定时启动临时 Linux 机器，复用本仓库 `zepp_client.py`，但**不提供本地网页登录界面，也不使用 Windows DPAPI**。GitHub 版不是西安交通大学签到脚本；借鉴的只有定时工作流机制，Zepp 登录与步数协议来自本项目已有的独立实现，详见 `THIRD_PARTY_NOTICES.md`。

> **启用前务必阅读：**你曾在聊天中提供 Zepp 密码。建议先更改密码，然后**只在自己 GitHub 仓库的 Secrets 页面输入新密码**。本下载包不含任何真实账号、密码或令牌。不要把密码填进代码、README、提交记录、Issues 或 GitHub Actions 运行参数。启用云端后，GitHub 及你授予仓库写权限的人可能通过修改工作流获取 Secrets；推荐**只有你自己可写的私人仓库**。不要与旧 Windows 自动任务同时启用。

## 运行策略

- 每天在 **UTC+8 12:07、16:07、20:07、23:07** 安排四次 GitHub 触发，分别对应 UTC `04:07、08:07、12:07、15:07`：`cron: '7 4,8,12,15 * * *'`。这些是**后备触发点，并非每日上传四次**。GitHub 可能延迟、取消或丢弃计划任务，不能保证恰好在 12:00 或当日执行。程序二次检查 UTC+8 **12:00–23:59**，窗外绝不登录、上传。延迟到次日会被拒绝。
- 第一条当日有效触发先经 GitHub API 查找名为 `zepp-daily-reserved-YYYY-MM-DD` 的现有 Artifact。若已存在，则跳过。不存在时用加密安全随机数抽取 **8,000–13,000**（包含两个端点）的当天**目标总步数**，把仅含日期和目标的“已保留”标记上传为 Artifact；**标记上传成功之前不运行 Zepp 任务**。标记留存 7 天。后续三个触发、手动重跑和失败后重跑不会再次写入；首次在登录前或回读前失败也保守地占用当天机会。不要删除当天的标记来强迫重跑。
- GitHub 两个任务串行并核对同一 GitHub run ID 的已上传标记。只有上传任务会获得 Zepp Secrets；先登录和回读当天云端步数。已有步数高于或等于随机目标时跳过；读取失败时停止而不写入。否则提交**一次**合成计步记录，再回读目标。上传超时不自动重试，不能因为看见接受码就声称微信已同步；请自己在微信确认。
- Actions 页面手动点击 **Run workflow** 是**纯检查**：不读 Zepp Secrets、不生成每日标记、不访问 Zepp、不上传步数。脚本拒绝 GitHub 的 Re-run attempt 执行实际写入。

## 在你的 GitHub 上部署（不能替你远程配置）

**针对你提供的 GitHub 用户名 `chenji4936`，请优先按 [SETUP_FOR_CHENJI4936.md](SETUP_FOR_CHENJI4936.md) 操作。** 先建私人仓库、再在 GitHub 页面设置 Secrets、最后上传工作流，避免工作流抢在 Secrets 配好之前运行。下面是通用版步骤。

1. 在自己的 GitHub 账号创建一个**私人仓库**，建议只允许自己拥有写权限。确认仓库默认分支为 `main`（其他默认分支也能工作，但必须把工作流文件放在默认分支）。不要公开自己的 Secrets 或修改工作流来打印环境变量。**别直接 fork 别人的运动仓库来放 Zepp 密码。**
2. 先到仓库 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，创建这两个 Secrets：

   | Secret 名称 | 值 |
   | --- | --- |
   | `ZEPP_ACCOUNT` | 你自己的 Zepp Life 账号邮箱或带国家码手机号；不要填写微信密码 |
   | `ZEPP_PASSWORD` | 你刚修改过的 Zepp Life 密码（只在 GitHub Secrets 页面填写） |

   不需要另建 GitHub Personal Access Token，也不需要把 `GITHUB_TOKEN` 手工存为 Secret。GitHub 自动提供临时仓库令牌；本工作流限制它为读取仓库与读取 Actions Artifact。授权 Secrets 会让这套工作流**自动代表你发送真实步数写入请求**，请确认仓库和代码由你控制。
3. 下载并解压 `zepp-github-actions.zip`。把压缩包里 `zepp-github/` **内部**的内容上传到你的私人仓库根目录：`.github/workflows/zepp-daily.yml`、`github_daily.py`、`zepp_client.py`、`requirements.txt` 等。注意隐藏的 `.github` 目录必须一起上传；不要只上传 ZIP 文件。你选择的新仓库地址是 `https://github.com/chenji4936/zepp-life-daily.git`（仅在你创建仓库后存在）。在解压出的 `zepp-github/` 文件夹内运行：

   ```bash
   git init
   git add .github/workflows/zepp-daily.yml .gitignore github_daily.py zepp_client.py requirements.txt README.md SETUP_FOR_CHENJI4936.md THIRD_PARTY_NOTICES.md TEST_REPORT.md tests
   git commit -m "Configure Zepp daily job"
   git branch -M main
   git remote add origin https://github.com/chenji4936/zepp-life-daily.git
   git push -u origin main
   ```

   不会使用 Git 可参见 [SETUP_FOR_CHENJI4936.md](SETUP_FOR_CHENJI4936.md) 中的 GitHub Desktop 方案；务必确认 `.github/workflows/zepp-daily.yml` 位于仓库默认分支。**绝不要将密码作为 `git remote` 地址或终端参数。**
4. 打开仓库 **Actions → Zepp Daily (opt-in)**，确认工作流可见且已启用。可以先点 **Run workflow** 做不访问 Zepp 的手动检查；查看日志中的 `manual_dry_run` 和 `windowOpen`。手动运行**不会测试真实登录/上传**。
5. 等第一个计划时段，打开 Actions 查看 `reserve` 与 `upload` 两个任务和脱敏结果，并查看微信运动。`cloud_matched_wechat_unverified` 只表示云端回读包含目标；`accepted_readback_unverified` 仅表示接口接受、但回读未确认；`skipped_existing_not_lower` 表示现有云端步数已达目标；`stopped` 或红色工作流表示本次未得到已确认结果，**不要通过手动重跑绕开标记**。

## 安全、费用及故障

- **不是“永久在线的服务器”**：每次 GitHub Job 是新的临时运行环境；本地状态文件、DPAPI 凭据、Windows 计划任务都不能直接搬上来。每天的 Artifact 标记是本版跨运行防重机制。如果 GitHub Artifact API、标记上传或本次标记验证失败，就停止；宁可当天不写也不误写两次。不要在一个私人仓库内安装两个相同的自动任务或分享给其他人写入权限。GitHub 有权限的维护者可能通过修改工作流提取 Secrets；即使日志自动遮蔽也不是绝对防护。
- **没有安排就不会自动写**：GitHub 的计划调度可能延迟或丢失；不要依赖它完成任何必须准点的活动。公开仓库如果 60 天没有仓库活动，定时工作流可能被停用；推荐私人仓库也不代表服务永远不会中断。
- **私人仓库有 Actions 免费额度，超出额度的费用视 GitHub 账号计划而定**。此工作流每次首先运行短暂的保留任务；已经保留当天则不安装 Requests、也不登录。留意仓库的 Actions 分钟/存储与计费设置。
- **未进行额外真实写入测试**。使用该用户明确授权的手动单账号测试曾以 12,000 步验证过协议，但本次云端版只做虚构账号 + 模拟 GitHub API/Zepp 上游的离线测试。GitHub 托管机器出口 IP/风控、凭据是否仍有效、计划是否运行及微信显示，均须你在自己账号上验证。程序不绕过验证码、封号、区域限制或上游限流，不伪造心率/睡眠等健康数据。
- 停用：仓库 Actions 中选择工作流右上角 **Disable workflow**，然后删除 `ZEPP_ACCOUNT`、`ZEPP_PASSWORD` Secrets；也可删除整个私有仓库。只删本机下载包**不会**停用 GitHub 上的任务。若已启用 Windows 版，另需在 Windows 上运行旧包中的 `Remove-Daily-Windows.cmd`；用户目前说明尚未安装 Windows 自动版。

## 开发验证

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

`tests` 使用虚构凭据和模拟上游/Artifact API，不接触真实 Zepp、GitHub Secrets 或上传接口。测试与文件校验结果见 `TEST_REPORT.md`。项目不提供“健康数据实际真实”的保证；这只是经你授权修改你自己的账户记录。

## 外部资料

- [GitHub Actions 定时事件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [创建 GitHub Actions Secrets](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions)
- [GitHub Actions Artifact API](https://docs.github.com/en/rest/actions/artifacts#list-artifacts-for-a-repository)
- [GitHub Actions 计费与额度](https://docs.github.com/en/actions/concepts/billing-and-usage)
