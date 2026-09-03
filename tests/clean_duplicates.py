#!/usr/bin/env python3
"""
Clean duplicate note records from media groups
清理媒体组的重复笔记记录
"""

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# 设置中国时区
CHINA_TZ = ZoneInfo("Asia/Shanghai")

# 数据目录
DEFAULT_DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data'))
DATA_DIR = os.environ.get('DATA_DIR', DEFAULT_DATA_DIR)
DATABASE_FILE = os.path.join(DATA_DIR, 'notes.db')

def clean_duplicates():
    """清理重复的笔记记录"""
    
    print("\n" + "="*60)
    print("🧹 开始清理重复笔记记录")
    print("="*60)
    
    if not os.path.exists(DATABASE_FILE):
        print(f"❌ 数据库文件不存在: {DATABASE_FILE}")
        return
    
    print(f"📁 数据库路径: {DATABASE_FILE}")
    
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    
    # 备份提示
    print("\n⚠️  建议在继续前备份数据库:")
    print(f"   cp {DATABASE_FILE} {DATABASE_FILE}.bak.{datetime.now(CHINA_TZ).strftime('%Y%m%d_%H%M%S')}")
    
    try:
        # 获取当前总记录数
        cursor.execute("SELECT COUNT(*) FROM notes")
        total_before = cursor.fetchone()[0]
        print(f"\n📊 清理前总记录数: {total_before}")
        
        deleted_count = 0
        
        # 方法1: 清理基于文本和时间窗口的重复（5秒内相同消息文本）
        print("\n🔍 检测方法1: 查找5秒内的重复消息（相同文本）...")
        
        cursor.execute("""
            SELECT user_id, source_chat_id, message_text, COUNT(*) as count
            FROM notes
            WHERE message_text IS NOT NULL AND message_text != ''
            GROUP BY user_id, source_chat_id, message_text
            HAVING count > 1
        """)
        
        text_duplicates = cursor.fetchall()
        print(f"   发现 {len(text_duplicates)} 组可能的文本重复")
        
        for user_id, source_chat_id, message_text, count in text_duplicates:
            # 获取这组重复的所有记录，按时间排序
            cursor.execute("""
                SELECT id, timestamp FROM notes
                WHERE user_id=? AND source_chat_id=? AND message_text=?
                ORDER BY timestamp ASC
            """, (user_id, source_chat_id, message_text))
            
            records = cursor.fetchall()
            if len(records) <= 1:
                continue
            
            # 保留第一条，删除5秒内的重复
            keep_id = records[0][0]
            keep_timestamp = datetime.strptime(records[0][1], '%Y-%m-%d %H:%M:%S')
            
            for record_id, timestamp_str in records[1:]:
                record_timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                time_diff = (record_timestamp - keep_timestamp).total_seconds()
                
                if time_diff <= 5:
                    cursor.execute("DELETE FROM notes WHERE id=?", (record_id,))
                    deleted_count += 1
                    print(f"   ✂️  删除重复记录 ID={record_id} (与 ID={keep_id} 相差 {time_diff:.1f}秒)")
        
        # 方法2: 清理基于时间窗口的媒体重复（无文本，5秒内来自同一源）
        print("\n🔍 检测方法2: 查找5秒内的重复媒体（无文本或空文本）...")
        
        cursor.execute("""
            SELECT user_id, source_chat_id, 
                   strftime('%Y-%m-%d %H:%M:%S', datetime(timestamp, 'unixepoch')) as time_bucket,
                   media_type, COUNT(*) as count
            FROM notes
            WHERE (message_text IS NULL OR message_text = '') 
            AND media_type IS NOT NULL
            GROUP BY user_id, source_chat_id, time_bucket, media_type
            HAVING count > 1
        """)
        
        media_duplicates = cursor.fetchall()
        print(f"   发现 {len(media_duplicates)} 组可能的媒体重复")
        
        for user_id, source_chat_id, time_bucket, media_type, count in media_duplicates:
            # 获取这个时间窗口内的所有媒体记录
            cursor.execute("""
                SELECT id, timestamp FROM notes
                WHERE user_id=? AND source_chat_id=? 
                AND (message_text IS NULL OR message_text = '')
                AND media_type=?
                AND datetime(timestamp) BETWEEN datetime(?, '-5 seconds') AND datetime(?, '+5 seconds')
                ORDER BY timestamp ASC
            """, (user_id, source_chat_id, media_type, time_bucket, time_bucket))
            
            records = cursor.fetchall()
            if len(records) <= 1:
                continue
            
            # 保留第一条，删除5秒内的其他记录
            keep_id = records[0][0]
            keep_timestamp = datetime.strptime(records[0][1], '%Y-%m-%d %H:%M:%S')
            
            for record_id, timestamp_str in records[1:]:
                record_timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                time_diff = abs((record_timestamp - keep_timestamp).total_seconds())
                
                if time_diff <= 5:
                    cursor.execute("DELETE FROM notes WHERE id=?", (record_id,))
                    deleted_count += 1
                    print(f"   ✂️  删除重复媒体 ID={record_id} (与 ID={keep_id} 相差 {time_diff:.1f}秒)")
        
        # 提交更改
        conn.commit()
        
        # 获取清理后总记录数
        cursor.execute("SELECT COUNT(*) FROM notes")
        total_after = cursor.fetchone()[0]
        
        print("\n" + "="*60)
        print("✅ 清理完成！")
        print("="*60)
        print(f"📊 清理前记录数: {total_before}")
        print(f"📊 删除记录数:   {deleted_count}")
        print(f"📊 清理后记录数: {total_after}")
        print(f"📊 剩余记录率:   {(total_after/total_before*100):.1f}%")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 清理过程中出错: {type(e).__name__}: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    try:
        clean_duplicates()
    except KeyboardInterrupt:
        print("\n\n⚠️  操作被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 脚本执行失败: {e}")
        sys.exit(1)
