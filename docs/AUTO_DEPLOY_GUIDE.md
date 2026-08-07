# 自动部署配置指南

## 📋 **概述**

本项目已配置 **GitHub Actions 自动部署流程**，当代码合并到 `main` 分支时，会自动触发部署到生产 VPS。

---

## 🔧 **配置步骤**

### **1. 配置 GitHub Secrets**

需要在 GitHub 仓库中添加以下 Secrets：

#### **进入设置页面**
```
Repository Settings → Secrets and variables → Actions → New repository secret
```

#### **添加以下 Secrets**

| Secret 名称 | 值 | 说明 |
|------------|-----|------|
| `VPS_HOST` | `38.60.126.42` | VPS 服务器 IP 地址 |
| `VPS_USERNAME` | `ubuntu` | SSH 登录用户名 |
| `VPS_SSH_KEY` | (私钥内容) | SSH 私钥（完整的私钥文件内容） |

#### **获取 SSH 私钥**

```bash
# 在本地执行
cat ~/.ssh/id_ed25519  # 或者你使用的私钥文件
# 复制完整输出（包括 BEGIN 和 END 行）
```

---

## 🚀 **使用方式**

### **方式 1: 自动部署（推荐）**

1. 创建 PR 从 `develop` 到 `main`
2. Review 并合并 PR
3. GitHub Actions 自动触发部署
4. 在 Actions 页面查看部署进度

**流程图**：
```
develop → PR → main → GitHub Actions → 自动部署到 VPS
```

### **方式 2: 手动部署**

如果需要手动部署（例如紧急修复）：

```bash
# 在 VPS 上执行
cd /opt/quant-agent
git pull origin main
docker-compose -f docker-compose.master.yml build --no-cache quant_app
docker-compose -f docker-compose.master.yml up -d quant_app
docker logs -f quant_app --tail 50
```

---

## 📊 **查看部署状态**

### **GitHub Actions 页面**

1. 进入仓库主页
2. 点击 **Actions** 标签
3. 查看最新的 workflow 运行状态

### **部署日志**

每次部署会执行以下检查：
- ✅ 拉取最新代码
- ✅ 重新构建 Docker 镜像
- ✅ 重启容器
- ✅ 健康检查（`/api/v1/health`）
- ✅ 检查 tushare 安装状态
- ✅ 显示容器运行状态

---

## 🔍 **故障排查**

### **部署失败**

如果自动部署失败，检查：

1. **SSH 连接**
   ```bash
   # 测试 SSH 密钥是否正确
   ssh -i ~/.ssh/id_ed25519 ubuntu@38.60.126.42
   ```

2. **GitHub Secrets**
   - 确认所有 Secrets 都已正确配置
   - 确认 SSH 私钥格式正确（包含 BEGIN 和 END 行）

3. **VPS 权限**
   ```bash
   # 确认用户有 docker 权限
   groups ubuntu
   # 应该包含 docker 组
   ```

### **手动查看部署日志**

```bash
# 在 VPS 上执行
docker logs quant_app --tail 100
```

---

## 🛡️ **安全建议**

1. **定期轮换 SSH 密钥**
   - 每 3-6 个月更换一次
   - 更新 GitHub Secrets 中的私钥

2. **限制 SSH 访问**
   - 只允许特定 IP 访问 SSH 端口
   - 使用 fail2ban 防止暴力破解

3. **审计部署记录**
   - 定期检查 GitHub Actions 日志
   - 关注部署失败的原因

---

## 📝 **自定义部署脚本**

如果需要修改部署逻辑，编辑：

```
.github/workflows/auto-deploy.yml
```

常见修改：
- 添加更多健康检查
- 发送部署通知（Slack/Email）
- 部署前备份数据库
- 部署后运行测试

---

## 🎯 **最佳实践**

1. **小步快跑**
   - 频繁合并小 PR，而不是一次性合并大量更改
   - 降低部署风险

2. **充分测试**
   - 在 develop 分支充分测试后再合并到 main
   - 使用 PR review 确保代码质量

3. **回滚准备**
   - 保留最近的 Docker 镜像备份
   - 准备好回滚脚本

---

## 📚 **相关文档**

- [GitHub Actions 文档](https://docs.github.com/en/actions)
- [SSH Action 文档](https://github.com/appleboy/ssh-action)
- [Docker 部署最佳实践](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)

---

**最后更新**: 2026-08-04
**维护者**: Quant Agent Team
