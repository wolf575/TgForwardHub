import os
import re
import json
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, flash, jsonify, Response
from markupsafe import Markup, escape
from database import init_database, get_notes, get_note_count, get_sources, verify_user, update_password, get_note_by_id, update_note, delete_note, DATA_DIR
from config import load_webdav_config, load_viewer_config, save_viewer_config, load_watch_config, save_watch_config, reload_monitored_sources, get_monitored_sources
from bot.storage.webdav_client import WebDAVClient, StorageManager
from bot.handlers.instances import get_acc_instance, get_bot_instance
from web_setup import load_visible_config, save_configuration, start_session_auth, submit_code, submit_password
import batch_forward
import math
import requests

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-secret-key-change-this-in-production')

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


@app.route('/api/setup/state')
def api_setup_state():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401
    return jsonify(load_visible_config())


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
    saved['message'] = 'Bot 配置已保存。修改凭据后需要重启服务才会生效。'
    return jsonify(saved)


@app.route('/api/setup/start', methods=['POST'])
def api_setup_start():
    if 'username' not in session:
        return jsonify({'error': '未登录'}), 401

    data = request.get_json(silent=True) or {}
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


@app.route('/setup')
def setup():
    if 'username' not in session:
        return redirect(url_for('login'))
    config = load_visible_config()
    return render_template(
        'setup.html',
        config=config,
        stage='idle',
        setup_id='',
        phone_number='',
        message=None,
        error=None,
        generated_session=''
    )


@app.route('/setup/save', methods=['POST'])
def setup_save():
    if 'username' not in session:
        return redirect(url_for('login'))

    token = request.form.get('token', '').strip()
    api_id = request.form.get('api_id', '').strip()
    api_hash = request.form.get('api_hash', '').strip()

    if not token or not api_id or not api_hash:
        return render_template(
            'setup.html',
            config=_setup_config_from_form(token, api_id, api_hash),
            stage='idle',
            setup_id='',
            phone_number='',
            error='Bot Token、API ID 和 API Hash 均不能为空',
            generated_session=''
        )

    try:
        int(api_id)
    except (TypeError, ValueError):
        return render_template(
            'setup.html',
            config=_setup_config_from_form(token, api_id, api_hash),
            stage='idle',
            setup_id='',
            phone_number='',
            error='API ID 必须是纯数字',
            generated_session=''
        )

    saved = save_configuration(
        token,
        api_id,
        api_hash,
        preserve_existing_session=True
    )
    return render_template(
        'setup.html',
        config=saved,
        stage='saved',
        setup_id='',
        phone_number='',
        message='Bot 配置已保存。修改凭据后需要重启服务才会生效。',
        error=None,
        generated_session=''
    )


@app.route('/setup/start', methods=['POST'])
def setup_start():
    if 'username' not in session:
        return redirect(url_for('login'))

    token = request.form.get('token', '').strip()
    api_id = request.form.get('api_id', '').strip()
    api_hash = request.form.get('api_hash', '').strip()
    phone_number = request.form.get('phone_number', '').strip()

    config = _setup_config_from_form(token, api_id, api_hash)

    result = start_session_auth(token, api_id, api_hash, phone_number)
    if 'error' in result:
        return render_template(
            'setup.html',
            config=config,
            stage='idle',
            setup_id='',
            phone_number=phone_number,
            error=result['error'],
            generated_session=''
        )

    return render_template(
        'setup.html',
        config=config,
        stage='code',
        setup_id=result['setup_id'],
        phone_number=result.get('phone_number', phone_number),
        message='验证码已发送到 Telegram，请输入验证码。',
        error=None,
        generated_session=''
    )


@app.route('/setup/code', methods=['POST'])
def setup_code():
    if 'username' not in session:
        return redirect(url_for('login'))

    setup_id = request.form.get('setup_id', '')
    code = request.form.get('code', '').strip()
    phone_number = request.form.get('phone_number', '')
    config = _setup_config_from_form(
        request.form.get('token', ''),
        request.form.get('api_id', ''),
        request.form.get('api_hash', '')
    )

    result = submit_code(setup_id, code)
    if 'error' in result:
        return render_template(
            'setup.html',
            config=config,
            stage=result.get('stage', 'code'),
            setup_id=result.get('setup_id', setup_id),
            phone_number=phone_number,
            error=result['error'],
            generated_session=''
        )

    if result.get('stage') == 'password':
        return render_template(
            'setup.html',
            config=config,
            stage='password',
            setup_id=result.get('setup_id', setup_id),
            phone_number=phone_number,
            message=result.get('message'),
            error=None,
            generated_session=''
        )

    return render_template(
        'setup.html',
        config=result.get('saved', config),
        stage='done',
        setup_id='',
        phone_number=phone_number,
        message=result.get('message'),
        error=None,
        generated_session=result.get('session_string', '')
    )


@app.route('/setup/password', methods=['POST'])
def setup_password():
    if 'username' not in session:
        return redirect(url_for('login'))

    setup_id = request.form.get('setup_id', '')
    password = request.form.get('password', '')
    phone_number = request.form.get('phone_number', '')
    config = _setup_config_from_form(
        request.form.get('token', ''),
        request.form.get('api_id', ''),
        request.form.get('api_hash', '')
    )

    result = submit_password(setup_id, password)
    if 'error' in result:
        return render_template(
            'setup.html',
            config=config,
            stage=result.get('stage', 'password'),
            setup_id=result.get('setup_id', setup_id),
            phone_number=phone_number,
            error=result['error'],
            generated_session=''
        )

    return render_template(
        'setup.html',
        config=result.get('saved', config),
        stage='done',
        setup_id='',
        phone_number=phone_number,
        message=result.get('message'),
        error=None,
        generated_session=result.get('session_string', '')
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
    if 'username' not in session:
        return redirect(url_for('login'))

    # 获取分页和过滤参数
    page = request.args.get('page', 1, type=int)
    source_filter = request.args.get('source', None)
    search_query = request.args.get('search', None)
    date_from = request.args.get('date_from', None)
    date_to = request.args.get('date_to', None)
    favorite_only = request.args.get('favorite', None) == '1'

    # 计算偏移量
    offset = (page - 1) * NOTES_PER_PAGE

    # 获取笔记
    notes_list = get_notes(source_chat_id=source_filter, search_query=search_query,
                          date_from=date_from, date_to=date_to, favorite_only=favorite_only,
                          limit=NOTES_PER_PAGE, offset=offset)

    # 获取观看网站配置
    viewer_config = load_viewer_config()
    viewer_url = viewer_config.get('viewer_url', '')

    # 为每条笔记添加所有磁力链接和观看链接
    for note in notes_list:
        # 提取所有dn参数
        all_dns = extract_all_dns_from_note(note)
        note['all_dns'] = all_dns

        # 为向后兼容，保留单个watch_url（使用第一个dn）
        if all_dns and viewer_url:
            note['watch_url'] = viewer_url + all_dns[0]['dn'] if all_dns[0]['dn'] else None
        else:
            note['watch_url'] = None

    # 获取总数和来源列表
    total_count = get_note_count(source_chat_id=source_filter, search_query=search_query,
                                 date_from=date_from, date_to=date_to, favorite_only=favorite_only)
    sources = get_sources()

    # 计算总页数
    total_pages = math.ceil(total_count / NOTES_PER_PAGE) if total_count > 0 else 1

    return render_template('notes.html',
                         notes=notes_list,
                         sources=sources,
                         total_count=total_count,
                         current_page=page,
                         total_pages=total_pages,
                         selected_source=source_filter,
                         search_query=search_query,
                         date_from=date_from,
                         date_to=date_to,
                         favorite_only=favorite_only,
                         viewer_url=viewer_url)

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # 验证当前密码
        if not verify_user(session['username'], current_password):
            return render_template('admin.html', error='当前密码不正确')

        # 验证新密码
        if len(new_password) < 6:
            return render_template('admin.html', error='新密码长度至少为 6 个字符')

        if new_password != confirm_password:
            return render_template('admin.html', error='两次输入的新密码不一致')

        # 更新密码
        update_password(session['username'], new_password)
        return render_template('admin.html', success='密码更新成功')

    return render_template('admin.html')


@app.route('/admin/webdav', methods=['GET', 'POST'])
def admin_webdav():
    """WebDAV 配置管理"""
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            # 获取表单数据
            enabled = request.form.get('enabled') == 'on'
            url = request.form.get('url', '').strip()
            username = request.form.get('webdav_username', '').strip()
            password = request.form.get('webdav_password', '').strip()
            base_path = request.form.get('base_path', '/telegram_media').strip()
            keep_local_copy = request.form.get('keep_local_copy') == 'on'

            # 构建配置
            config = {
                'enabled': enabled,
                'url': url,
                'username': username,
                'password': password,
                'base_path': base_path,
                'keep_local_copy': keep_local_copy
            }

            # 如果启用了 WebDAV，测试连接
            if enabled and url and username and password:
                try:
                    test_client = WebDAVClient(url, username, password, base_path)
                    if not test_client.test_connection():
                        return render_template('admin_webdav.html',
                                             config=config,
                                             error='WebDAV 连接测试失败，请检查配置')
                except Exception as e:
                    return render_template('admin_webdav.html',
                                         config=config,
                                         error=f'WebDAV 连接失败: {str(e)}')

            # 保存配置
            from config import save_webdav_config
            save_webdav_config(config)

            # 重新初始化存储管理器
            global storage_manager
            storage_manager = init_storage_manager()

            return render_template('admin_webdav.html',
                                 config=config,
                                 success='WebDAV 配置已保存')

        except Exception as e:
            config = load_webdav_config()
            return render_template('admin_webdav.html',
                                 config=config,
                                 error=f'保存配置失败: {str(e)}')

    # GET 请求，加载当前配置
    config = load_webdav_config()
    return render_template('admin_webdav.html', config=config)

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
    if 'username' not in session:
        return redirect(url_for('login'))

    note = get_note_by_id(note_id)
    if not note:
        flash('笔记不存在')
        return redirect(url_for('notes'))

    if request.method == 'POST':
        new_text = request.form.get('message_text', '').strip()
        if update_note(note_id, new_text):
            flash('笔记更新成功')
            return_url = request.form.get('return_url', url_for('notes'))
            return redirect(return_url)
        else:
            flash('更新失败')

    return render_template('edit_note.html', note=note, return_url=request.referrer or url_for('notes'))

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
    """观看网站配置管理"""
    if 'username' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        try:
            # 获取表单数据
            viewer_url = request.form.get('viewer_url', '').strip()

            # 验证URL格式
            if not viewer_url:
                return render_template('admin_viewer.html',
                                     config={'viewer_url': viewer_url},
                                     error='观看网站URL不能为空')

            if not (viewer_url.startswith('http://') or viewer_url.startswith('https://')):
                return render_template('admin_viewer.html',
                                     config={'viewer_url': viewer_url},
                                     error='URL必须以 http:// 或 https:// 开头')

            # 构建配置
            config = {
                'viewer_url': viewer_url
            }

            # 保存配置
            save_viewer_config(config)

            return render_template('admin_viewer.html',
                                 config=config,
                                 success='观看网站配置已保存')

        except Exception as e:
            config = load_viewer_config()
            return render_template('admin_viewer.html',
                                 config=config,
                                 error=f'保存配置失败: {str(e)}')

    # GET 请求，加载当前配置
    config = load_viewer_config()
    return render_template('admin_viewer.html', config=config)

@app.route('/admin/calibration', methods=['GET', 'POST'])
def admin_calibration():
    """自动校准配置管理"""
    if 'username' not in session:
        return redirect(url_for('login'))

    from database import get_calibration_config, update_calibration_config, get_calibration_stats

    if request.method == 'POST':
        try:
            # 获取表单数据
            config = {
                'enabled': 1 if request.form.get('enabled') == 'on' else 0,
                'filter_mode': request.form.get('filter_mode', 'empty_only'),
                'first_delay': int(request.form.get('first_delay', 600)),
                'retry_delay_1': int(request.form.get('retry_delay_1', 3600)),
                'retry_delay_2': int(request.form.get('retry_delay_2', 14400)),
                'retry_delay_3': int(request.form.get('retry_delay_3', 28800)),
                'max_retries': int(request.form.get('max_retries', 3)),
                'concurrent_limit': int(request.form.get('concurrent_limit', 5)),
                'timeout_per_magnet': int(request.form.get('timeout_per_magnet', 30)),
                'batch_timeout': int(request.form.get('batch_timeout', 300))
            }

            # 保存配置
            update_calibration_config(config)

            # 重新加载校准管理器配置
            from bot.services.calibration_manager import get_calibration_manager
            manager = get_calibration_manager()
            manager.reload_config()

            # 获取统计信息
            stats = get_calibration_stats()

            return render_template('admin_calibration.html',
                                 config=config,
                                 stats=stats,
                                 success='自动校准配置已保存')

        except Exception as e:
            config = get_calibration_config()
            stats = get_calibration_stats()
            return render_template('admin_calibration.html',
                                 config=config,
                                 stats=stats,
                                 error=f'保存配置失败: {str(e)}')

    # GET 请求，加载当前配置
    config = get_calibration_config()
    stats = get_calibration_stats()
    return render_template('admin_calibration.html', config=config, stats=stats)

@app.route('/admin/calibration/queue')
def admin_calibration_queue():
    """校准任务队列查看"""
    if 'username' not in session:
        return redirect(url_for('login'))

    from database import get_all_calibration_tasks, get_calibration_stats

    # 获取过滤参数
    status_filter = request.args.get('status', '')
    page = int(request.args.get('page', 1))
    per_page = 50

    # 获取任务列表
    tasks = get_all_calibration_tasks(
        status=status_filter if status_filter else None,
        limit=per_page,
        offset=(page - 1) * per_page
    )

    # 获取统计信息
    stats = get_calibration_stats()

    return render_template('admin_calibration_queue.html',
                         tasks=tasks,
                         stats=stats,
                         status_filter=status_filter,
                         page=page)

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
