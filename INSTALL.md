# OpenPilot 环境配置指南

本文档说明如何配置 OpenPilot 的开发和运行环境。

## 方式 1：使用 Conda（推荐）

### 创建新环境

```bash
# 使用 environment.yml 创建环境
conda env create -f environment.yml

# 激活环境
conda activate openpilot

# 安装 OpenPilot
cd Code
pip install -e .
```

### 更新现有环境

```bash
# 更新环境
conda env update -f environment.yml --prune

# 或者手动安装依赖
conda activate openpilot
pip install -r requirements.txt
```

### 删除环境

```bash
conda deactivate
conda env remove -n openpilot
```

## 方式 2：使用 pip + venv

### 创建虚拟环境

```bash
# 创建虚拟环境
python3.11 -m venv venv

# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt

# 安装 OpenPilot
cd Code
pip install -e .
```

## 方式 3：直接使用 pip（不推荐）

```bash
# 全局安装（不推荐，可能污染系统环境）
pip install -r requirements.txt
cd Code
pip install -e .
```

## 验证安装

```bash
# 检查 Python 版本
python --version  # 应该是 3.11+

# 检查依赖
pip list | grep -E "openai|pydantic|rich|prompt-toolkit"

# 检查 OpenPilot 命令
openpilot --help

# 检查配置
openpilot run
> /config
```

## 依赖说明

### 核心依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| openai | >=1.0.0 | OpenAI API 客户端 |
| pydantic | >=2.7.0 | 数据验证和模型 |
| pydantic-settings | >=2.2.0 | 配置管理 |
| python-dotenv | >=1.0.0 | 环境变量加载 |
| rich | >=13.7.0 | 终端 UI 渲染 |
| prompt-toolkit | >=3.0.0 | 命令行交互和补全 |

### 开发依赖

| 包名 | 版本 | 用途 |
|------|------|------|
| pytest | >=8.0.0 | 单元测试框架 |

## 常见问题

### Q: 为什么推荐使用 Conda？

A: Conda 可以更好地管理 Python 版本和依赖隔离，避免与系统 Python 冲突。

### Q: 如何导出当前环境？

```bash
# 导出 conda 环境
conda env export > environment.yml

# 导出 pip 依赖
pip freeze > requirements-freeze.txt
```

### Q: 如何在不同机器上复现环境？

```bash
# 方式 1：使用 environment.yml
conda env create -f environment.yml

# 方式 2：使用 requirements.txt
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Q: 依赖冲突怎么办？

```bash
# 清理并重新安装
conda deactivate
conda env remove -n openpilot
conda env create -f environment.yml
```

## 最低系统要求

- **Python**: 3.11 或更高
- **操作系统**: Linux, macOS, Windows (WSL2)
- **内存**: 至少 2GB 可用内存
- **磁盘**: 至少 500MB 可用空间

## 推荐配置

- **Python**: 3.11
- **操作系统**: Ubuntu 22.04+ / macOS 13+ / Windows 11 + WSL2
- **内存**: 4GB+ 可用内存
- **终端**: Windows Terminal / iTerm2 / GNOME Terminal

## 下一步

配置完成后，请参考：
- [README.md](Code/README.md) - 使用指南
- [测试指南.md](Plan/测试指南.md) - 功能测试
- [产品方案任务流程.md](Plan/产品方案任务流程.md) - 架构说明
