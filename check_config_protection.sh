#!/bin/bash

# 配置文件保护状态检查脚本
# Configuration Protection Status Check Script

echo "=================================="
echo "配置文件保护状态检查"
echo "Config Protection Status Check"
echo "=================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查1: 查看配置文件是否被Git跟踪
echo "📋 检查 1: 配置文件Git跟踪状态"
echo "Check 1: Git tracking status of config files"
echo "---"

TRACKED_CONFIGS=$(git ls-files | grep -E "^(config\.json|watch_config\.json)$")

if [ -z "$TRACKED_CONFIGS" ]; then
    echo -e "${GREEN}✅ 通过: 配置文件未被Git跟踪${NC}"
    echo -e "${GREEN}✅ PASS: Config files are not tracked by Git${NC}"
else
    echo -e "${RED}❌ 失败: 以下配置文件仍被Git跟踪:${NC}"
    echo -e "${RED}❌ FAIL: Following config files are still tracked:${NC}"
    echo "$TRACKED_CONFIGS"
    echo ""
    echo -e "${YELLOW}修复方法 / Fix:${NC}"
    echo "  git rm --cached config.json"
    echo "  git rm --cached watch_config.json"
fi

echo ""

# 检查2: 查看本地配置文件是否存在
echo "📋 检查 2: 本地配置文件存在性"
echo "Check 2: Local config files existence"
echo "---"

if [ -f "config.json" ]; then
    echo -e "${GREEN}✅ config.json 存在${NC}"
else
    echo -e "${YELLOW}⚠️  config.json 不存在 (首次使用请从 config.json.example 复制)${NC}"
    echo -e "${YELLOW}⚠️  config.json not found (copy from config.json.example for first use)${NC}"
fi

if [ -f "watch_config.json" ]; then
    echo -e "${GREEN}✅ watch_config.json 存在${NC}"
else
    echo -e "${YELLOW}⚠️  watch_config.json 不存在 (首次使用会自动创建)${NC}"
    echo -e "${YELLOW}⚠️  watch_config.json not found (will be created automatically)${NC}"
fi

echo ""

# 检查3: 查看.gitignore配置
echo "📋 检查 3: .gitignore 配置"
echo "Check 3: .gitignore configuration"
echo "---"

GITIGNORE_CHECK=0

if grep -q "^config\.json$" .gitignore; then
    echo -e "${GREEN}✅ config.json 在 .gitignore 中${NC}"
else
    echo -e "${RED}❌ config.json 不在 .gitignore 中${NC}"
    GITIGNORE_CHECK=1
fi

if grep -q "^watch_config\.json$" .gitignore; then
    echo -e "${GREEN}✅ watch_config.json 在 .gitignore 中${NC}"
else
    echo -e "${RED}❌ watch_config.json 不在 .gitignore 中${NC}"
    GITIGNORE_CHECK=1
fi

if grep -q "^data/$" .gitignore; then
    echo -e "${GREEN}✅ data/ 在 .gitignore 中${NC}"
else
    echo -e "${RED}❌ data/ 不在 .gitignore 中${NC}"
    GITIGNORE_CHECK=1
fi

if [ $GITIGNORE_CHECK -eq 1 ]; then
    echo ""
    echo -e "${YELLOW}修复方法: 检查并更新 .gitignore 文件${NC}"
    echo -e "${YELLOW}Fix: Check and update .gitignore file${NC}"
fi

echo ""

# 检查4: 查看data目录
echo "📋 检查 4: data 目录状态"
echo "Check 4: data directory status"
echo "---"

if [ -d "data" ]; then
    echo -e "${GREEN}✅ data/ 目录存在${NC}"
    if [ -f "data/notes.db" ]; then
        DB_SIZE=$(du -h "data/notes.db" | cut -f1)
        echo -e "${GREEN}  ✅ notes.db 存在 (大小: $DB_SIZE)${NC}"
    else
        echo -e "${YELLOW}  ⚠️  notes.db 不存在 (如果使用了 record mode 会自动创建)${NC}"
    fi
    
    if [ -d "data/media" ]; then
        MEDIA_COUNT=$(find data/media -type f 2>/dev/null | wc -l)
        echo -e "${GREEN}  ✅ media/ 目录存在 (文件数: $MEDIA_COUNT)${NC}"
    else
        echo -e "${YELLOW}  ⚠️  media/ 目录不存在 (有媒体文件时会自动创建)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  data/ 目录不存在 (使用 record mode 时会自动创建)${NC}"
    echo -e "${YELLOW}⚠️  data/ directory not found (will be created when using record mode)${NC}"
fi

echo ""

# 检查5: 查看git status中的配置文件
echo "📋 检查 5: Git 工作区状态"
echo "Check 5: Git working directory status"
echo "---"

GIT_STATUS_CONFIGS=$(git status --short | grep -E "(config\.json|watch_config\.json)")

if [ -z "$GIT_STATUS_CONFIGS" ]; then
    echo -e "${GREEN}✅ 通过: 配置文件不在 git status 中${NC}"
    echo -e "${GREEN}✅ PASS: Config files not in git status${NC}"
else
    echo -e "${YELLOW}⚠️  警告: 配置文件出现在 git status 中:${NC}"
    echo -e "${YELLOW}⚠️  WARNING: Config files appear in git status:${NC}"
    echo "$GIT_STATUS_CONFIGS"
    echo ""
    echo -e "${YELLOW}这是正常的，如果它们显示为未跟踪文件 (??)${NC}"
    echo -e "${YELLOW}This is normal if they show as untracked (??)${NC}"
fi

echo ""

# 总结
echo "=================================="
echo "✨ 检查完成 / Check Complete"
echo "=================================="
echo ""

if [ -z "$TRACKED_CONFIGS" ] && [ $GITIGNORE_CHECK -eq 0 ]; then
    echo -e "${GREEN}🎉 所有检查通过！配置文件已正确保护。${NC}"
    echo -e "${GREEN}🎉 All checks passed! Config files are properly protected.${NC}"
    echo ""
    echo -e "${GREEN}你可以安全地运行: git pull${NC}"
    echo -e "${GREEN}You can safely run: git pull${NC}"
else
    echo -e "${YELLOW}⚠️  发现一些问题，请按照上面的提示修复。${NC}"
    echo -e "${YELLOW}⚠️  Some issues found, please fix according to hints above.${NC}"
fi

echo ""
echo "📖 详细文档: DATA_PROTECTION.md"
echo "📖 Detailed docs: DATA_PROTECTION.md"
