import os
import re
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, jsonify, Response
from markupsafe import Markup, escape
from database import init_database, get_notes, get_note_count, get_sources, verify_user, update_password, update_username, get_note_by_id, update_note, delete_note, DATA_DIR
from config import load_webdav_config, load_viewer_config, save_viewer_config, load_watch_config, save_watch_config, reload_monitored_sources, get_monitored_sources
from bot.storage.webdav_client import WebDAVClient, StorageManager
from bot.handlers.instances import get_acc_instance, get_bot_instance
from web_setup import load_visible_config, save_configuration, start_session_auth, submit_code, submit_password, get_setup_status
import batch_forward
import math
import requests
import sys
from urllib.parse import urlencode
from app_settings import get_app_settings, save_app_preferences

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-change-this-in-production')


@app.after_request
def disable_sensitive_response_caching(response):
    if request.path == '/' or request.path == '/login' or request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return response

# 初始化数据库
init_database()

# 每页显示的笔记数量
NOTES_PER_PAGE = 50

# 初始化存储管理器
def init_storage_manager():
    """初始化存储管理器"""
    try:
        webdav_config = load_webdav_config()
        media_dir = os.path.join(DATA_DIR, 'media')

        if webdav_config.get('enabled', False):
            url = webdav_config.get('url', '').strip()
            username = webdav_config.get('username', '').strip()
            password = webdav_config.get('password', '').strip()
            base_path = webdav_config.get('base_path', '/telegram_media')

            if url and username and password:
                try:
                    webdav_client = WebDAVClient(url, username, password, base_path)
                    if webdav_client.test_connection():
                        return StorageManager(media_dir, webdav_client)
                except Exception:
                    pass

        return StorageManager(media_dir)
    except Exception:
        return StorageManager(os.path.join(DATA_DIR, 'media'))

storage_manager = init_storage_manager()

# 自定义Jinja2过滤器：高亮搜索关键词
@app.template_filter('highlight')
def highlight_filter(text, search_query):
    if not text or not search_query:
        return text
    
    # 转义HTML特殊字符
    text = escape(text)
    search_query = escape(search_query)
    
    # 使用正则表达式进行不区分大小写的替换
    pattern = re.compile(re.escape(str(search_query)), re.IGNORECASE)
    highlighted = pattern.sub(lambda m: f'<span class="highlight">{m.group()}</span>', str(text))
    
    return Markup(highlighted)

@app.route('/')
def home():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if verify_user(username, password):
            session['username'] = username
            return redirect(url_for('home'))
        else:
            return render_template('login.html', error='用户名或密码错误')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


def _setup_config_from_form(token='', api_id='', api_hash=''):
    config = load_visible_config()
    config['token'] = token or config.get('token', '')
    config['api_id'] = api_id or config.get('api_id', '')
    config['api_hash'] = api_hash or config.get('api_hash', '')
    return config


def _redirect_to_dashboard():
    """Keep legacy B-project pages from opening as a second UI."""
    if 'username' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('home'))


def _redirect_to_setup_dashboard(**values):
    """Return to the merged dashboard with non-sensitive setup state."""
    if 'username' not in session:
        return redirect(url_for('login'))

    query = urlencode({key: value for key, value in values.items() if value})
    target = url_for('home') + (('?' + query) if query else '')
    return redirect(target)


def _restart_bot_instances():
    try:
        from bot.handlers.instances import stop_and_clear_instances
        stop_and_clear_instances()
    except Exception:
        pass


@app.route('/api/setup/state')
def api_setup_state():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    return jsonify(load_visible_config())


@app.route('/api/setup/status')
def api_setup_status():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    setup_id = str(request.args.get('setup_id') or '').strip()
    if not setup_id:
        return jsonify({'error': 'setup_id 不能为空'}), 400

    return jsonify(get_setup_status(setup_id))


@app.route('/api/app-settings', methods=['GET'])
def api_app_settings():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    return jsonify(get_app_settings())


@app.route('/api/app-settings', methods=['POST'])
def api_app_settings_save():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    has_timezone = 'timezone' in data
    has_batch_notifications = (
        'batch_completion_notifications_enabled' in data
    )
    if not has_timezone and not has_batch_notifications:
        return jsonify({'error': '没有需要保存的设置'}), 400

    timezone_name = None
    if has_timezone:
        timezone_name = str(data.get('timezone') or '').strip()
        if not timezone_name:
            return jsonify({'error': '时区不能为空'}), 400

    batch_completion_notifications_enabled = None
    if has_batch_notifications:
        batch_completion_notifications_enabled = bool(
            data.get('batch_completion_notifications_enabled')
        )

    try:
        settings = save_app_preferences(
            timezone_name=timezone_name,
            batch_completion_notifications_enabled=(
                batch_completion_notifications_enabled
            ),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    saved_fields = []
    if has_timezone:
        saved_fields.append('时区设置已保存')
    if has_batch_notifications:
        saved_fields.append('通知设置已保存')
    return jsonify({
        'ok': True,
        **settings,
        'message': '，'.join(saved_fields),
    })


@app.route('/api/setup/save', methods=['POST'])
def api_setup_save():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    token = str(data.get('token') or '').strip()
    api_id = str(data.get('api_id') or '').strip()
    api_hash = str(data.get('api_hash') or '').strip()

    if not token or not api_id or not api_hash:
        return jsonify({'error': 'Bot Token、API ID 和 API Hash 均不能为空'}), 400

    try:
        int(api_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'API ID 必须是纯数字'}), 400

    saved = save_configuration(
        token,
        api_id,
        api_hash,
        preserve_existing_session=True
    )
    try:
        from bot.handlers.instances import stop_and_clear_instances
        stop_and_clear_instances()
    except Exception:
        pass
    saved['message'] = 'Bot 配置已保存，后台服务会自动重新加载。'
    return jsonify(saved)


@app.route('/api/setup/start', methods=['POST'])
def api_setup_start():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    sys.stdout.write(
        "[web-setup] POST /api/setup/start received keys={} "
        "client={} cf_ray={}\n".format(
            sorted(data.keys()),
            request.headers.get('X-Forwarded-For') or request.remote_addr,
            request.headers.get('CF-Ray'),
        )
    )
    sys.stdout.flush()
    token = str(data.get('token') or '').strip()
    api_id = str(data.get('api_id') or '').strip()
    api_hash = str(data.get('api_hash') or '').strip()
    phone_number = str(data.get('phone_number') or '').strip()

    result = start_session_auth(token, api_id, api_hash, phone_number)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/setup/code', methods=['POST'])
def api_setup_code():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    setup_id = str(data.get('setup_id') or '').strip()
    code = str(data.get('code') or '').strip()
    if not setup_id:
        return jsonify({'error': '登录流程 ID 不能为空'}), 400

    result = submit_code(setup_id, code)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/setup/password', methods=['POST'])
def api_setup_password():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    setup_id = str(data.get('setup_id') or '').strip()
    password = str(data.get('password') or '')
    if not setup_id:
        return jsonify({'error': '登录流程 ID 不能为空'}), 400

    result = submit_password(setup_id, password)
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/api/admin/password', methods=['POST'])
def api_admin_password():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
    current_username = str(data.get('current_username') or '').strip()
    new_username = str(data.get('new_username') or '').strip()
    current_password = str(data.get('current_password') or '')
    new_password = str(data.get('new_password') or '')
    confirm_password = str(data.get('confirm_password') or '')

    if current_username != session['username']:
        return jsonify({'error': '当前用户名不正确'}), 400
    if not verify_user(current_username, current_password):
        return jsonify({'error': '当前密码不正确'}), 400

    username_changed = bool(new_username and new_username != current_username)
    password_changed = bool(new_password)
    if not username_changed and not password_changed:
        return jsonify({'error': '请填写新用户名或新密码'}), 400

    if username_changed:
        if len(new_username) < 1 or len(new_username) > 32:
            return jsonify({'error': '用户名长度需为 1 到 32 个字符'}), 400
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', new_username):
            return jsonify({'error': '用户名只能包含字母、数字、下划线、点和连字符'}), 400
        try:
            update_username(current_username, new_username)
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400

    if password_changed:
        if len(new_password) < 6:
            return jsonify({'error': '新密码长度至少为 6 个字符'}), 400
        if new_password != confirm_password:
            return jsonify({'error': '两次输入的新密码不一致'}), 400
        update_password(current_username, new_password)

    if username_changed:
        session['username'] = new_username

    message = '账号信息更新成功'
    if username_changed and password_changed:
        message = '用户名和密码更新成功'
    elif username_changed:
        message = '用户名更新成功'
    elif password_changed:
        message = '密码更新成功'
    return jsonify({'ok': True, 'message': message})


@app.route('/api/admin/webdav', methods=['GET', 'POST'])
def api_admin_webdav():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    if request.method == 'GET':
        return jsonify(load_webdav_config())

    data = request.get_json(silent=True) or {}
    config = {
        'enabled': bool(data.get('enabled')),
        'url': str(data.get('url') or '').strip(),
        'username': str(data.get('username') or '').strip(),
        'password': str(data.get('password') or ''),
        'base_path': str(data.get('base_path') or '/telegram_media').strip(),
        'keep_local_copy': bool(data.get('keep_local_copy')),
    }

    if config['enabled'] and config['url'] and config['username'] and config['password']:
        test_client = WebDAVClient(
            config['url'],
            config['username'],
            config['password'],
            config['base_path'],
        )
        if not test_client.test_connection():
            return jsonify({'error': 'WebDAV 连接测试失败，请检查配置'}), 400

    from config import save_webdav_config
    save_webdav_config(config)

    global storage_manager
    storage_manager = init_storage_manager()
    return jsonify({'ok': True, 'config': config, 'message': 'WebDAV 配置已保存'})


@app.route('/api/admin/calibration', methods=['GET', 'POST'])
def api_admin_calibration():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    from database import get_calibration_config, update_calibration_config, get_calibration_stats

    if request.method == 'GET':
        config = get_calibration_config() or {}
        stats = get_calibration_stats()
        return jsonify({'config': config, 'stats': stats})

    data = request.get_json(silent=True) or {}
    try:
        config = {
            'enabled': 1 if data.get('enabled') else 0,
            'filter_mode': str(data.get('filter_mode') or 'empty_only'),
            'first_delay': int(data.get('first_delay') or 600),
            'retry_delay_1': int(data.get('retry_delay_1') or 3600),
            'retry_delay_2': int(data.get('retry_delay_2') or 14400),
            'retry_delay_3': int(data.get('retry_delay_3') or 28800),
            'max_retries': int(data.get('max_retries') or 3),
            'concurrent_limit': int(data.get('concurrent_limit') or 5),
            'timeout_per_magnet': int(data.get('timeout_per_magnet') or 30),
            'batch_timeout': int(data.get('batch_timeout') or 300),
        }
    except (TypeError, ValueError):
        return jsonify({'error': '校准参数必须是有效数字'}), 400

    update_calibration_config(config)

    try:
        from bot.services.calibration_manager import get_calibration_manager
        get_calibration_manager().reload_config()
    except Exception:
        pass

    stats = get_calibration_stats()
    return jsonify({'ok': True, 'config': config, 'stats': stats, 'message': '自动校准配置已保存'})


@app.route('/api/admin/viewer', methods=['GET', 'POST'])
def api_admin_viewer():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    if request.method == 'GET':
        return jsonify(load_viewer_config())

    data = request.get_json(silent=True) or {}
    viewer_url = str(data.get('viewer_url') or '').strip()
    if not viewer_url:
        return jsonify({'error': '观看网站 URL 不能为空'}), 400
    if not (viewer_url.startswith('http://') or viewer_url.startswith('https://')):
        return jsonify({'error': 'URL 必须以 http:// 或 https:// 开头'}), 400

    config = {'viewer_url': viewer_url}
    save_viewer_config(config)
    return jsonify({'ok': True, 'config': config, 'message': '观看网站配置已保存'})


@app.route('/setup')
def setup():
    return _redirect_to_dashboard()


@app.route('/setup/save', methods=['POST'])
def setup_save():
    if 'username' not in session:
        return redirect(url_for('login'))

    token = str(request.form.get('token') or '').strip()
    api_id = str(request.form.get('api_id') or '').strip()
    api_hash = str(request.form.get('api_hash') or '').strip()

    if not token or not api_id or not api_hash:
        return _redirect_to_setup_dashboard(
            setup_error='Bot Token、API ID 和 API Hash 均不能为空'
        )

    try:
        int(api_id)
    except (TypeError, ValueError):
        return _redirect_to_setup_dashboard(setup_error='API ID 必须是纯数字')

    save_configuration(
        token,
        api_id,
        api_hash,
        preserve_existing_session=True
    )
    _restart_bot_instances()
    return _redirect_to_setup_dashboard(
        setup_message='Bot 配置已保存，后台服务会自动重新加载。'
    )


@app.route('/setup/start', methods=['POST'])
def setup_start():
    if 'username' not in session:
        return redirect(url_for('login'))

    token = str(request.form.get('token') or '').strip()
    api_id = str(request.form.get('api_id') or '').strip()
    api_hash = str(request.form.get('api_hash') or '').strip()
    phone_number = str(request.form.get('phone_number') or '').strip()

    sys.stdout.write(
        "[web-setup] POST /setup/start received client={} cf_ray={}\n".format(
            request.headers.get('X-Forwarded-For') or request.remote_addr,
            request.headers.get('CF-Ray'),
        )
    )
    sys.stdout.flush()

    result = start_session_auth(token, api_id, api_hash, phone_number)
    if 'error' in result:
        return _redirect_to_setup_dashboard(setup_error=result['error'])

    return _redirect_to_setup_dashboard(
        setup=result.get('setup_id'),
        stage='code',
        phone=result.get('phone_number') or phone_number,
        action='start',
    )


@app.route('/setup/code', methods=['POST'])
def setup_code():
    if 'username' not in session:
        return redirect(url_for('login'))

    setup_id = str(request.form.get('setup_id') or '').strip()
    code = str(request.form.get('code') or '').strip()
    phone_number = str(request.form.get('phone_number') or '').strip()

    result = submit_code(setup_id, code)
    if 'error' in result:
        return _redirect_to_setup_dashboard(
            setup=result.get('setup_id') or setup_id,
            stage=result.get('stage') or 'code',
            phone=phone_number,
            action='code',
            setup_error=result['error'],
        )

    return _redirect_to_setup_dashboard(
        setup=result.get('setup_id') or setup_id,
        stage=result.get('stage') or 'code',
        phone=phone_number,
        action='code',
    )


@app.route('/setup/password', methods=['POST'])
def setup_password():
    if 'username' not in session:
        return redirect(url_for('login'))

    setup_id = str(request.form.get('setup_id') or '').strip()
    password = str(request.form.get('password') or '')
    phone_number = str(request.form.get('phone_number') or '').strip()

    result = submit_password(setup_id, password)
    if 'error' in result:
        return _redirect_to_setup_dashboard(
            setup=result.get('setup_id') or setup_id,
            stage=result.get('stage') or 'password',
            phone=phone_number,
            action='password',
            setup_error=result['error'],
        )

    return _redirect_to_setup_dashboard(
        setup=result.get('setup_id') or setup_id,
        stage='password',
        phone=phone_number,
        action='password',
    )


def extract_all_magnets_from_text(message_text):
    """从笔记文本中提取所有磁力链接

    Returns:
        list: 包含所有磁力链接的列表
    """
    if not message_text:
        return []

    # 正则匹配所有magnet链接
    magnet_pattern = r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+(?:[&?][^\s\n]*)?'
    magnets = re.findall(magnet_pattern, message_text, re.IGNORECASE)

    return magnets

def extract_dn_from_magnet(magnet_link, message_text=None, filename=None):
    """从磁力链接中提取dn参数（文件名），如果没有则从笔记文本提取

    优先级：filename字段 > magnet_link的dn参数 > message_text提取
    """
    # 优先使用filename字段（校准后的完整文件名）
    if filename:
        return filename

    if not magnet_link:
        return None

    # 其次尝试从磁力链接中提取 dn= 参数
    match = re.search(r'[&?]dn=([^&]+)', magnet_link)
    if match:
        from urllib.parse import unquote
        return unquote(match.group(1))

    # 如果磁力链接没有dn参数，从笔记文本中提取
    if message_text:
        # 提取文本开头到第一个#号的内容作为文件名
        # 如果没有#号，则使用整个文本
        if '#' in message_text:
            # 找到第一个#的位置
            hash_pos = message_text.index('#')
            filename = message_text[:hash_pos]
        else:
            filename = message_text

        # 去除末尾空格和换行符
        filename = filename.rstrip()

        # 去除开头空格
        filename = filename.lstrip()

        # 移除magnet链接行（如果在开头）
        lines = filename.split('\n')
        filtered_lines = []
        for line in lines:
            # 跳过magnet链接行
            if not line.lower().strip().startswith('magnet:'):
                filtered_lines.append(line)

        if filtered_lines:
            filename = '\n'.join(filtered_lines).strip()

        # 如果文件名包含多行，只取第一行
        if '\n' in filename:
            filename = filename.split('\n')[0].strip()

        if filename:
            return filename

    return None

def extract_all_dns_from_note(note):
    """从笔记中提取所有磁力链接的dn参数

    Args:
        note: 笔记字典，包含magnet_link、message_text和filename

    Returns:
        list: [{'magnet': 磁力链接, 'dn': dn参数, 'info_hash': info_hash}, ...]
    """
    dns = []
    message_text = note.get('message_text', '')
    filename = note.get('filename')  # 获取校准后的完整文件名

    # 从笔记文本提取所有磁力链接
    all_magnets = extract_all_magnets_from_text(message_text)

    # 如果没有找到任何磁力链接，尝试使用magnet_link字段
    if not all_magnets and note.get('magnet_link'):
        all_magnets = [note['magnet_link']]

    # 为每个磁力链接提取dn和info_hash
    for magnet in all_magnets:
        # 优先使用filename字段（校准后的完整文件名）
        dn = extract_dn_from_magnet(magnet, message_text, filename)

        # 提取info_hash
        info_hash_match = re.search(r'xt=urn:btih:([a-zA-Z0-9]+)', magnet, re.IGNORECASE)
        info_hash = info_hash_match.group(1) if info_hash_match else None

        if dn or info_hash:  # 只要有dn或info_hash就添加
            dns.append({
                'magnet': magnet,
                'dn': dn,
                'info_hash': info_hash
            })

    return dns

@app.route('/notes')
def notes():
    return _redirect_to_dashboard()

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    return _redirect_to_dashboard()


@app.route('/admin/webdav', methods=['GET', 'POST'])
def admin_webdav():
    return _redirect_to_dashboard()

@app.route('/media/<path:storage_location>')
def media(storage_location):
    """提供媒体文件访问（支持本地和 WebDAV）"""
    if 'username' not in session:
        return redirect(url_for('login'))

    try:
        # URL 解码存储位置
        from urllib.parse import unquote
        storage_location = unquote(storage_location)

        # 获取文件路径或 URL
        file_path_or_url = storage_manager.get_file_path(storage_location)

        if not file_path_or_url:
            return "File not found", 404

        # 如果是 HTTP/HTTPS URL（WebDAV），代理请求
        if file_path_or_url.startswith('http://') or file_path_or_url.startswith('https://'):
            try:
                # 获取 WebDAV 配置用于认证
                webdav_config = load_webdav_config()
                username = webdav_config.get('username', '')
                password = webdav_config.get('password', '')

                # 代理请求到 WebDAV 服务器
                response = requests.get(
                    file_path_or_url,
                    auth=(username, password),
                    stream=True,
                    timeout=30
                )

                if response.status_code == 200:
                    # 返回文件内容
                    return Response(
                        response.iter_content(chunk_size=8192),
                        content_type=response.headers.get('Content-Type', 'application/octet-stream'),
                        headers={
                            'Content-Disposition': f'inline; filename="{os.path.basename(storage_location)}"'
                        }
                    )
                else:
                    return f"Failed to fetch from WebDAV: {response.status_code}", 502

            except Exception as e:
                return f"Error fetching from WebDAV: {str(e)}", 502

        # 本地文件
        else:
            if os.path.exists(file_path_or_url):
                media_dir = os.path.dirname(file_path_or_url)
                filename = os.path.basename(file_path_or_url)
                return send_from_directory(media_dir, filename)
            else:
                return "File not found", 404

    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/edit_note/<int:note_id>', methods=['GET', 'POST'])
def edit_note(note_id):
    return _redirect_to_dashboard()

@app.route('/delete_note/<int:note_id>', methods=['POST'])
def delete_note_route(note_id):
    if 'username' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401

    if delete_note(note_id):
        return jsonify({'success': True, 'reload': False})
    else:
        return jsonify({'success': False, 'error': '删除失败'}), 500

@app.route('/toggle_favorite/<int:note_id>', methods=['POST'])
def toggle_favorite_route(note_id):
    if 'username' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401

    from database import toggle_favorite
    if toggle_favorite(note_id):
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'error': '操作失败'}), 500

@app.route('/admin/viewer', methods=['GET', 'POST'])
def admin_viewer():
    return _redirect_to_dashboard()

@app.route('/admin/calibration', methods=['GET', 'POST'])
def admin_calibration():
    return _redirect_to_dashboard()

@app.route('/admin/calibration/queue')
def admin_calibration_queue():
    return _redirect_to_dashboard()

@app.route('/api/calibration/task/<int:task_id>/retry', methods=['POST'])
def api_retry_calibration_task(task_id):
    """API: 手动重试校准任务"""
    if 'username' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401

    try:
        from database import update_calibration_task
        # 立即重试（延迟0秒）
        success = update_calibration_task(task_id, 'retrying', next_retry_seconds=0)

        if success:
            return jsonify({'success': True, 'message': '任务已加入重试队列'})
        else:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/calibration/task/<int:task_id>/delete', methods=['POST'])
def api_delete_calibration_task(task_id):
    """API: 删除校准任务"""
    if 'username' not in session:
        return jsonify({'success': False, 'error': '未登录'}), 401

    try:
        from database import delete_calibration_task
        success = delete_calibration_task(task_id)

        if success:
            return jsonify({'success': True, 'message': '任务已删除'})
        else:
            return jsonify({'success': False, 'error': '任务不存在'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/calibrate/<int:note_id>', methods=['POST'])
def api_calibrate(note_id):
    """API: 校准磁力链接的dn参数（支持多个磁力链接）"""
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    try:
        from database import get_note_by_id, update_note_with_calibrated_dns

        note = get_note_by_id(note_id)
        if not note:
            return jsonify({'error': '笔记不存在'}), 404

        # 提取所有磁力链接
        all_dns = extract_all_dns_from_note(note)
        if not all_dns:
            return jsonify({'error': '没有找到磁力链接'}), 404

        # 使用独立进程调用校准脚本，为每个磁力链接校准
        import subprocess
        calibrated_results = []

        for dn_info in all_dns:
            info_hash = dn_info['info_hash']
            if not info_hash:
                continue

            try:
                # 确定脚本路径（支持容器和本地环境）
                script_path = '/app/calibrate_helper.py' if os.path.exists('/app/calibrate_helper.py') else os.path.join(os.path.dirname(__file__), 'calibrate_helper.py')

                result = subprocess.run(
                    ['python3', script_path, info_hash],
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.returncode == 0:
                    filename = result.stdout.strip()
                    calibrated_results.append({
                        'info_hash': info_hash,
                        'old_magnet': dn_info['magnet'],
                        'filename': filename,
                        'success': True
                    })
                else:
                    error_msg = result.stderr.strip() if result.stderr else '未知错误'
                    calibrated_results.append({
                        'info_hash': info_hash,
                        'old_magnet': dn_info['magnet'],
                        'error': error_msg,
                        'success': False
                    })

            except subprocess.TimeoutExpired:
                calibrated_results.append({
                    'info_hash': info_hash,
                    'old_magnet': dn_info['magnet'],
                    'error': '校准超时（30秒）',
                    'success': False
                })
            except Exception as e:
                calibrated_results.append({
                    'info_hash': info_hash,
                    'old_magnet': dn_info['magnet'],
                    'error': f'执行失败: {str(e)}',
                    'success': False
                })

        # 更新数据库
        if update_note_with_calibrated_dns(note_id, calibrated_results):
            # 统计成功和失败
            success_count = sum(1 for r in calibrated_results if r['success'])
            fail_count = len(calibrated_results) - success_count

            # 调试：读取更新后的笔记
            updated_note = get_note_by_id(note_id)
            print(f"[DEBUG] 校准后笔记 {note_id}:")
            print(f"  message_text: {updated_note.get('message_text', '')[:200]}")
            print(f"  magnet_link: {updated_note.get('magnet_link', '')}")
            print(f"  filename: {updated_note.get('filename', '')}")

            # 手动校准成功后，清理对应的自动校准任务
            if success_count > 0:
                try:
                    from database import delete_calibration_tasks_by_note_id
                    deleted = delete_calibration_tasks_by_note_id(note_id)
                    if deleted > 0:
                        print(f"[INFO] 已清理 {deleted} 个自动校准任务（note_id={note_id}）")
                except Exception as e:
                    print(f"[WARNING] 清理自动校准任务失败（不影响手动校准）: {e}")

            response_data = {
                'success': True,
                'total': len(calibrated_results),
                'success_count': success_count,
                'fail_count': fail_count,
                'results': calibrated_results
            }
            return jsonify(response_data)
        else:
            return jsonify({'error': '更新数据库失败'}), 500

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/status')
def api_status():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    acc = get_acc_instance()
    bot = get_bot_instance()
    bot_running = bool(bot is not None and getattr(bot, 'is_connected', False))
    user_client_running = bool(acc is not None and getattr(acc, 'is_connected', False))
    dual_end_ready = bot_running and user_client_running

    return jsonify({
        'web_ready': True,
        'bot_ready': bool(bot is not None),
        'bot_running': bot_running,
        'user_client_ready': bool(acc is not None),
        'user_client_running': user_client_running,
        'dual_end_ready': dual_end_ready,
        'monitored_sources_count': len(get_monitored_sources()),
        'data_dir': DATA_DIR,
    })


@app.route('/api/history', methods=['GET', 'POST', 'DELETE'])
def api_history():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    if request.method == 'GET':
        return jsonify(batch_forward.list_history())

    if request.method == 'DELETE':
        batch_forward.clear_history()
        return jsonify({'ok': True})

    data = request.get_json(silent=True) or {}
    if not data.get('id'):
        return jsonify({'error': 'id required'}), 400
    batch_forward.save_history(data)
    return jsonify({'ok': True})


@app.route('/api/batch-forward', methods=['POST'])
def api_batch_forward():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    spec = request.get_json(silent=True) or {}
    try:
        job_id = batch_forward.submit_batch_task(spec)
        return jsonify({'jobId': job_id, 'status': 'running'}), 202
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400


@app.route('/api/batch-forward/<job_id>', methods=['GET'])
def api_batch_forward_status(job_id):
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    status = batch_forward.batch_status(job_id)
    if status is None:
        return jsonify({'error': 'job not found'}), 404
    return jsonify(status)


@app.route('/api/batch-forward/<job_id>/cancel', methods=['POST'])
def api_batch_forward_cancel(job_id):
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    if batch_forward.cancel_batch_task(job_id):
        return jsonify({'ok': True})
    return jsonify({'error': 'job not found'}), 404


@app.route('/api/watch-config', methods=['GET', 'POST'])
def api_watch_config():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    if request.method == 'GET':
        return jsonify(load_watch_config())

    data = request.get_json(silent=True) or {}
    user_id = str(data.get('user_id') or '')
    key = str(data.get('key') or '')
    watch = data.get('watch')
    if not user_id or not key or not isinstance(watch, dict):
        return jsonify({'error': 'user_id, key, watch are required'}), 400

    config = load_watch_config()
    config.setdefault(user_id, {})[key] = watch
    save_watch_config(config)
    return jsonify({'ok': True, 'watch_config': config})


@app.route('/api/watch-config/<path:watch_path>', methods=['PUT', 'DELETE'])
def api_watch_config_item(watch_path):
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    parts = [p for p in watch_path.split('/') if p]
    if len(parts) < 2:
        return jsonify({'error': 'path should be /user_id/key'}), 400

    user_id, key = parts[0], parts[1]
    config = load_watch_config()

    if request.method == 'DELETE':
        if user_id in config and key in config[user_id]:
            del config[user_id][key]
            if not config[user_id]:
                del config[user_id]
            save_watch_config(config)
            return jsonify({'ok': True, 'watch_config': config})
        return jsonify({'error': 'not found'}), 404

    data = request.get_json(silent=True) or {}
    if not isinstance(data.get('watch'), dict):
        return jsonify({'error': 'watch is required'}), 400
    config.setdefault(user_id, {})[key] = data['watch']
    save_watch_config(config)
    return jsonify({'ok': True, 'watch_config': config})


@app.route('/api/notes')
def api_notes():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    page = request.args.get('page', 1, type=int)
    search = request.args.get('search')
    source = request.args.get('source')
    limit = 50
    offset = (page - 1) * limit
    notes = get_notes(
        source_chat_id=source,
        search_query=search,
        limit=limit,
        offset=offset,
    )
    total = get_note_count(source_chat_id=source, search_query=search)
    return jsonify({'notes': notes, 'total': total, 'sources': get_sources()})


@app.route('/api/sources')
def api_sources():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    return jsonify(get_sources())


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False)
