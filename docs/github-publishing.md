# GitHub 上传说明

本发布包仅包含代码、配置、测试与文档，不包含 data、原件、密钥、备份或虚拟环境。此文提供上传操作，不表示远端已经完成推送。

## 准备仓库

在自己的 GitHub 账户新建空仓库，建议名称 Shiji。首次可设为 Private，审阅后再改 Public。创建时不自动添加 README、.gitignore 或 License，避免与本地第一次提交冲突。

示例目标为 https://github.com/mastercoyote99/Shiji.git；只有实际创建了该仓库才使用此地址。如采用其他名称，应替换对应 URL。

## 在 D 盘本地项目执行

将发布包中的 README.md、CHANGELOG.md、docs/ 和 .gitignore 放到项目根目录。其他源码与 v0.4.1 一致；已做额外修改时先备份再比较，不要盲目覆盖。

```powershell
Set-Location 'D:\Projects\Shiji'
git init -b main
git status --short
git ls-files -- data backups .env .streamlit/secrets.toml
```

最后一条预期无输出。如果已经追踪私人文件，先停止上传，处理当前索引和历史后再继续；.gitignore 不会自动清理历史。

仅加入明确公开的文件：

```powershell
git add -- .gitignore .streamlit/config.toml app.py ai_features.py storage.py ui.py requirements.txt tests/test_storage.py README.md CHANGELOG.md docs/
git --no-pager diff --cached --check
git --no-pager diff --cached --stat
git --no-pager diff --cached
git grep --cached -l -I -E 'sk-or-v1-[A-Za-z0-9_-]{10,}' -- .
```

检查未包含真实密钥、私人截图、笔记和个人路径记录。密钥匹配检查只是补充，不能代替人工检查。

```powershell
git commit -m "Document Shiji v0.4.1 product flows, improvements and validation"
git remote -v
```

若无 origin，执行：

```powershell
git remote add origin https://github.com/mastercoyote99/Shiji.git
git push -u origin HEAD:main
```

若已有 origin，不重复 add；核对是否为你本次要上传的拾集仓库。不要使用 InsightFlow 的远端，也不要 force push。

## 上传后

在 GitHub 确认 README 能显示、docs 链接可打开、data 未出现。可设置仓库 About：

Personal knowledge and inspiration library with local collection, source-grounded Q&A and daily learning cards.

Release/tag 尚未创建，可在完成真实 Windows 验收后再发布 v0.4.1 Release。截图应使用合成测试资料，避免公开个人收藏或密钥。

## 每次改进如何记

1. development-log.md：用户问题、诊断、决策、实际结果。
2. CHANGELOG.md：版本新增、修改和修复。
3. page-flows.md：页面行为改变时更新。
4. testing-and-evaluation.md：增加实际证据与尚未验证项。
5. README.md：只保留当前已实现能力和使用入口。
