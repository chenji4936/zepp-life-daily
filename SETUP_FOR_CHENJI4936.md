# 为 chenji4936 部署私人 GitHub 仓库

**当前只准备好了文件，没有替你创建仓库或启用自动写入。** 你的私人仓库及 Secrets 只能由你在自己登录 GitHub 的浏览器里设置。此文档不含也不需要你在聊天中给出的账号密码。

## 1. 建一个空的私人仓库

打开 <https://github.com/new> 并确认你登录的是 **chenji4936**：

- **Owner**：`chenji4936`
- **Repository name**：`zepp-life-daily`
- **Visibility**：选 **Private**（不要选 Public）
- 初始化选项：**不要**勾选 Add a README、.gitignore、license（本包都有相应内容）
- 点 **Create repository**。目标地址应为 `https://github.com/chenji4936/zepp-life-daily`，创建成功前它不存在；私人仓库其他人无权查看。

## 2. 先建 Secrets，再上传工作流

建议先把此前发在聊天中的 Zepp 密码**修改为新密码**。在刚创建的私人仓库点 **Settings → Secrets and variables → Actions → Secrets → New repository secret**，依次创建：

1. 名称 `ZEPP_ACCOUNT`，值是在 Zepp Life 使用的登录邮箱/带区号手机号。
2. 名称 `ZEPP_PASSWORD`，值是你**修改后的** Zepp Life 密码。**只在 GitHub 页面输入，不要再发给我，也不要写入项目文件。**

GitHub 会自动提供 `GITHUB_TOKEN`，无需另外购买、创建或在聊天里发送访问令牌。请不要给其他人这个私人仓库的写权限。

## 3. 把本包内容上传到空仓库

解压 `zepp-github-actions.zip`，进入里面的 **`zepp-github`** 文件夹。需要上传的是**文件夹内部**的文件，不能把整个 ZIP 当成一个文件上传，尤其不能漏掉 `.github/workflows/zepp-daily.yml`。

**方式 A：Git 命令行**（在 `zepp-github` 文件夹打开 PowerShell 或 VS Code 终端）：

```powershell
git init
git add .github/workflows/zepp-daily.yml .gitignore github_daily.py zepp_client.py requirements.txt README.md SETUP_FOR_CHENJI4936.md THIRD_PARTY_NOTICES.md TEST_REPORT.md tests
git commit -m "Add private Zepp daily workflow"
git branch -M main
git remote add origin https://github.com/chenji4936/zepp-life-daily.git
git push -u origin main
```

如果 `git` 命令不存在，先安装 Git for Windows，或者用 GitHub Desktop：登录你的 GitHub → Clone 刚创建的空仓库 → 把解压文件夹**内部**的全部内容（含 `.github`）复制到克隆文件夹 → Commit to main → Push origin。登录 GitHub 的步骤只在 Git 官方程序/浏览器中完成；不要向我发送 GitHub 密码或令牌。

## 4. 检查，不手动上传

打开你新建的仓库 → **Actions → Zepp Daily (opt-in)**。应能看到 `.github/workflows/zepp-daily.yml`。手动点 **Run workflow** 只显示 `manual_dry_run`，不访问 Zepp，不修改步数；它只是检查工作流能被 GitHub 启动。

随后等待实际定时触发：北京时间/新加坡时间 **12:07、16:07、20:07、23:07** 是后备触发点，**不是每天写入四次**。当日第一个有效任务预先留存无凭据的预约标记；之后任务应跳过。GitHub 可能延迟或丢弃定时任务，不能保证每天准点或一定运行。查看 Actions 的 reserve/upload 日志以及微信运动的真实显示。**不要点 Re-run 来强制重试，更不要删除当天的预约 Artifact。**

**停用**：Actions 中选择工作流菜单 **Disable workflow**；再到 Settings 删除 `ZEPP_ACCOUNT`、`ZEPP_PASSWORD`。只删除本地文件不会停用 GitHub 上的任务。

若创建仓库、添加 Secrets 或 `git push` 卡住，发**不包含凭据/令牌**的截图和错误提示，我可以按你当前页面继续指导。
