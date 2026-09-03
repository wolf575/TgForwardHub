#!/bin/bash
# 运行所有测试套件
# 用于验证代码优化和bug修复

set -e

echo "=========================================="
echo "   完整测试套件 - 代码优化和Bug修复"
echo "=========================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试计数器
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# 运行单个测试
run_test() {
    local test_name="$1"
    local test_file="$2"
    
    echo "----------------------------------------"
    echo "📋 运行: $test_name"
    echo "----------------------------------------"
    
    if python3 "$test_file" > /tmp/test_output.txt 2>&1; then
        # 提取测试统计
        local test_count=$(grep -oP '运行测试: \K\d+' /tmp/test_output.txt | tail -1)
        local success_count=$(grep -oP '成功: \K\d+' /tmp/test_output.txt | tail -1)
        
        if [ -n "$test_count" ]; then
            TOTAL_TESTS=$((TOTAL_TESTS + test_count))
            PASSED_TESTS=$((PASSED_TESTS + success_count))
        fi
        
        echo -e "${GREEN}✅ $test_name 通过${NC}"
        echo ""
        return 0
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}❌ $test_name 失败${NC}"
        echo "错误详情:"
        tail -20 /tmp/test_output.txt
        echo ""
        return 1
    fi
}

# 测试1: 代码优化功能测试
echo ""
run_test "代码优化功能测试" "test_optimization.py" || true

# 测试2: Bug修复验证测试
echo ""
run_test "Bug修复验证测试" "test_bug_fixes_optimization.py" || true

# 测试3: 语法和导入测试
echo ""
run_test "语法和导入测试" "test_main_syntax.py" || true

# 测试4: 性能对比测试
echo ""
echo "----------------------------------------"
echo "📊 性能对比测试"
echo "----------------------------------------"
python3 performance_comparison.py > /tmp/perf_output.txt 2>&1
echo -e "${GREEN}✅ 性能对比完成${NC}"
echo ""

# 测试5: 编译检查
echo "----------------------------------------"
echo "🔍 编译检查"
echo "----------------------------------------"
if python3 -m py_compile constants.py database.py bot/utils/dedup.py bot/workers/message_worker.py main.py main_old.py 2>&1; then
    echo -e "${GREEN}✅ 所有Python文件编译成功${NC}"
else
    echo -e "${RED}❌ 编译失败${NC}"
    FAILED_TESTS=$((FAILED_TESTS + 1))
fi
echo ""

# 测试总结
echo "=========================================="
echo "   测试总结"
echo "=========================================="
echo ""
echo "📊 统计:"
echo "   总测试数: $TOTAL_TESTS"
echo "   通过: $PASSED_TESTS"
echo "   失败: $FAILED_TESTS"
echo ""

if [ $FAILED_TESTS -eq 0 ]; then
    echo -e "${GREEN}🎉 所有测试通过！代码可以安全部署。${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}❌ 有 $FAILED_TESTS 个测试失败，请检查错误。${NC}"
    echo ""
    exit 1
fi
