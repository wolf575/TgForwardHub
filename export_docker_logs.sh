#!/bin/bash
# Docker日志导出脚本
# 功能：将Docker容器日志导出到data/logs目录

set -e

# 配置
CONTAINER_NAME="save-restricted-bot"
LOGS_DIR="./data/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUTPUT_FILE="${LOGS_DIR}/docker_${TIMESTAMP}.log"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Docker日志导出工具${NC}"
echo -e "${GREEN}========================================${NC}"

# 确保logs目录存在
mkdir -p "${LOGS_DIR}"

# 检查容器是否存在
if ! docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}❌ 错误: 容器 ${CONTAINER_NAME} 不存在${NC}"
    echo -e "${YELLOW}提示: 请先启动Bot容器${NC}"
    exit 1
fi

# 检查容器是否运行
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${YELLOW}⚠️  警告: 容器 ${CONTAINER_NAME} 未运行${NC}"
fi

# 导出日志
echo -e "${GREEN}📝 正在导出日志...${NC}"
echo -e "   容器: ${CONTAINER_NAME}"
echo -e "   输出: ${OUTPUT_FILE}"

# 根据参数选择导出方式
case "${1:-all}" in
    all)
        echo -e "   模式: 导出所有日志"
        docker logs "${CONTAINER_NAME}" > "${OUTPUT_FILE}" 2>&1
        ;;
    tail)
        LINES="${2:-1000}"
        echo -e "   模式: 导出最近 ${LINES} 行"
        docker logs --tail "${LINES}" "${CONTAINER_NAME}" > "${OUTPUT_FILE}" 2>&1
        ;;
    since)
        TIME="${2:-1h}"
        echo -e "   模式: 导出最近 ${TIME} 的日志"
        docker logs --since "${TIME}" "${CONTAINER_NAME}" > "${OUTPUT_FILE}" 2>&1
        ;;
    error)
        echo -e "   模式: 只导出错误日志"
        docker logs "${CONTAINER_NAME}" 2>&1 | grep -iE "error|exception|traceback|failed" > "${OUTPUT_FILE}" || true
        ;;
    *)
        echo -e "${RED}❌ 未知模式: ${1}${NC}"
        echo -e "${YELLOW}用法:${NC}"
        echo -e "  $0 [all|tail|since|error] [参数]"
        echo -e ""
        echo -e "${YELLOW}示例:${NC}"
        echo -e "  $0              # 导出所有日志"
        echo -e "  $0 tail 500     # 导出最近500行"
        echo -e "  $0 since 30m    # 导出最近30分钟"
        echo -e "  $0 error        # 只导出错误日志"
        exit 1
        ;;
esac

# 检查导出结果
if [ -f "${OUTPUT_FILE}" ]; then
    FILE_SIZE=$(du -h "${OUTPUT_FILE}" | cut -f1)
    LINE_COUNT=$(wc -l < "${OUTPUT_FILE}")
    echo -e "${GREEN}✅ 导出成功!${NC}"
    echo -e "   文件大小: ${FILE_SIZE}"
    echo -e "   行数: ${LINE_COUNT}"
    echo -e "   路径: ${OUTPUT_FILE}"

    # 显示最后几行
    echo -e ""
    echo -e "${YELLOW}最后10行日志:${NC}"
    tail -10 "${OUTPUT_FILE}"
else
    echo -e "${RED}❌ 导出失败${NC}"
    exit 1
fi

echo -e ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}提示: 应用日志保存在 ${LOGS_DIR}/bot.log${NC}"
echo -e "${GREEN}========================================${NC}"
