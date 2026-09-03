#!/usr/bin/env python3
"""
数据迁移脚本 - 将旧的数据文件迁移到 data/ 目录
Migration Script - Migrate old data files to data/ directory

使用方法 / Usage:
    python migrate_data.py
"""

import os
import shutil

def migrate_data():
    print("=" * 60)
    print("数据迁移脚本 | Data Migration Script")
    print("=" * 60)
    print()
    
    # 创建 data 目录
    os.makedirs('data', exist_ok=True)
    os.makedirs(os.path.join('data', 'media'), exist_ok=True)
    print("✅ 已创建 data/ 目录结构")
    print("✅ Created data/ directory structure")
    print()
    
    migrated = False
    
    # 迁移 notes.db
    if os.path.exists('notes.db') and not os.path.exists(os.path.join('data', 'notes.db')):
        shutil.move('notes.db', os.path.join('data', 'notes.db'))
        print("✅ 已迁移 notes.db 到 data/notes.db")
        print("✅ Migrated notes.db to data/notes.db")
        migrated = True
    elif os.path.exists(os.path.join('data', 'notes.db')):
        print("ℹ️  data/notes.db 已存在，跳过迁移")
        print("ℹ️  data/notes.db already exists, skipping")
    else:
        print("ℹ️  未找到 notes.db 文件")
        print("ℹ️  notes.db not found")
    print()
    
    # 迁移 media 目录
    if os.path.exists('media') and os.path.isdir('media'):
        # 检查是否有文件
        media_files = [f for f in os.listdir('media') if os.path.isfile(os.path.join('media', f))]
        if media_files:
            print(f"📂 发现 {len(media_files)} 个媒体文件")
            print(f"📂 Found {len(media_files)} media files")
            
            # 移动所有文件
            for filename in media_files:
                src = os.path.join('media', filename)
                dst = os.path.join('data', 'media', filename)
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                    print(f"   ✓ {filename}")
            
            print()
            print("✅ 已迁移所有媒体文件到 data/media/")
            print("✅ Migrated all media files to data/media/")
            print()
            
            # 询问是否删除旧目录
            response = input("是否删除旧的 media/ 目录？(y/N) | Delete old media/ directory? (y/N): ").strip().lower()
            if response == 'y':
                shutil.rmtree('media')
                print("✅ 已删除旧的 media/ 目录")
                print("✅ Deleted old media/ directory")
            else:
                print("ℹ️  保留旧的 media/ 目录（可手动删除）")
                print("ℹ️  Kept old media/ directory (you can delete it manually)")
            
            migrated = True
        else:
            print("ℹ️  media/ 目录为空")
            print("ℹ️  media/ directory is empty")
    else:
        print("ℹ️  未找到 media/ 目录")
        print("ℹ️  media/ directory not found")
    
    print()
    print("=" * 60)
    if migrated:
        print("🎉 迁移完成！所有数据已安全移动到 data/ 目录")
        print("🎉 Migration complete! All data safely moved to data/ directory")
        print()
        print("💡 提示：")
        print("   - data/ 目录独立于代码，更新时不会被覆盖")
        print("   - 定期备份 data/ 目录以保护你的数据")
        print()
        print("💡 Tips:")
        print("   - data/ directory is independent of code updates")
        print("   - Regularly backup data/ directory to protect your data")
    else:
        print("ℹ️  没有需要迁移的数据")
        print("ℹ️  No data needs to be migrated")
    print("=" * 60)

if __name__ == "__main__":
    try:
        migrate_data()
    except Exception as e:
        print()
        print(f"❌ 错误 | Error: {e}")
        print()
        import traceback
        traceback.print_exc()
