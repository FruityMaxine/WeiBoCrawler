import sys
import os
import json
import time
import signal
import subprocess
import threading
import webbrowser
import logging
import configparser
from flask import Flask, render_template, request, jsonify, Response, stream_with_context

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - WebUI - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 全局变量：存储子进程对象
GLOBAL_PROCESS = None
# 全局变量：进程锁，防止并发操作冲突
PROCESS_LOCK = threading.Lock()
# 配置文件路径
CONFIG_FILE = 'config.json'
USER_LIST_FILE = 'user_id_list.txt'

def load_config():
    """读取 config.json 及 logging.conf"""
    config = {}
    
    # 1. 读取 JSON 配置
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"读取JSON配置失败: {e}")

    # --- 数据转换逻辑 (保持原有) ---
    user_id_conf = config.get('user_id_list')
    if isinstance(user_id_conf, list):
        config['user_id_list_raw'] = '\n'.join([str(x) for x in user_id_conf])
        config['user_id_list_mode'] = 'list'
    elif isinstance(user_id_conf, str) and user_id_conf.endswith('.txt'):
        config['user_id_list_mode'] = 'file'
        txt_path = user_id_conf
        if os.path.exists(txt_path):
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    config['user_id_list_raw'] = f.read()
            except:
                config['user_id_list_raw'] = ""
        else:
            config['user_id_list_raw'] = ""
    else:
        config['user_id_list_raw'] = str(user_id_conf)
        config['user_id_list_mode'] = 'unknown'

    if isinstance(config.get('query_list'), list):
        config['query_list_raw'] = ','.join(config['query_list'])
    else:
        config['query_list_raw'] = config.get('query_list', '')

    # --- 2. 新增：读取 logging.conf ---
    try:
        log_conf = configparser.ConfigParser()
        # 必须读取，即使文件不存在也不会报错
        log_conf.read('logging.conf', encoding='utf-8')
        
        # 读取 [handler_consoleHandler] 下的 level 字段
        # 如果读不到，默认给 'INFO'
        level = 'INFO'
        if log_conf.has_option('handler_consoleHandler', 'level'):
            level = log_conf.get('handler_consoleHandler', 'level')
        
        config['logging_level'] = level
    except Exception as e:
        logger.error(f"读取日志配置失败: {e}")
        config['logging_level'] = 'INFO'
        
    # --- 3. 补全缺省的高级配置字段 ---
    if 'mysql_config' not in config:
        config['mysql_config'] = {'host': 'localhost', 'port': 3306, 'user': 'root', 'password': '', 'charset': 'utf8mb4'}
    if 'post_config' not in config:
        config['post_config'] = {'api_url': '', 'api_token': ''}
    if 'mongodb_URI' not in config:
        config['mongodb_URI'] = ''
    if 'store_binary_in_sqlite' not in config:
        config['store_binary_in_sqlite'] = 0

    # --- 4. 补全 LLM 和 通知配置 ---
    if 'llm_config' not in config:
        config['llm_config'] = {'enable': False, 'api_key': '', 'api_base': '', 'model': ''}
    if 'notify_config' not in config:
        config['notify_config'] = {'enable': False, 'push_key': ''}
    if 'cookie_check_config' not in config:
        config['cookie_check_config'] = {'enable': False, 'hidden_weibo_text': '', 'exit_after_check': False}
        
    return config

def save_config_file(new_config):
    """保存配置：同步更新 config.json, user_id_list.txt 和 logging.conf"""
    try:
        # --- 1. 保存 JSON 配置 ---
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            current_config = json.load(f)
        
        # 处理 User ID
        raw_ids = new_config.get('user_id_list_raw', '')
        old_id_conf = current_config.get('user_id_list')
        if isinstance(old_id_conf, str) and old_id_conf.endswith('.txt'):
            try:
                with open(old_id_conf, 'w', encoding='utf-8') as f:
                    f.write(raw_ids)
            except Exception as e:
                return False, f"写入外部文件失败: {e}"
        else:
            id_list = [line.strip() for line in raw_ids.split('\n') if line.strip()]
            current_config['user_id_list'] = id_list

        # 处理 Query List
        raw_query = new_config.get('query_list_raw', '').strip()
        if raw_query:
            raw_query = raw_query.replace('，', ',')
            current_config['query_list'] = [q.strip() for q in raw_query.split(',') if q.strip()]
        else:
            current_config['query_list'] = []

        # === 核心修改：所有开关保存为 Boolean (True/False) ===
        bool_fields = [
            'only_crawl_original', 'remove_html_tag',
            'original_pic_download', 'retweet_pic_download',
            'original_video_download', 'retweet_video_download',
            'original_live_photo_download', 'retweet_live_photo_download',
            'download_comment', 'download_repost', 'user_id_as_folder_name'
        ]
        for field in bool_fields:
            if field in new_config:
                val = new_config[field]
                # 直接保存为布尔值
                current_config[field] = (str(val).lower() == 'true')
        
        # 处理普通字段
        text_fields = ['since_date', 'cookie', 'write_mode', 'start_page', 
                       'page_weibo_count', 'comment_max_download_count', 'repost_max_download_count',
                       'mongodb_URI'] 
        for field in text_fields:
            if field in new_config:
                 current_config[field] = new_config[field]

        # SQLite 二进制开关
        if 'store_binary_in_sqlite' in new_config:
            val = new_config['store_binary_in_sqlite']
            current_config['store_binary_in_sqlite'] = (str(val).lower() == 'true')

        # MySQL
        if 'mysql_config' in new_config:
            if 'mysql_config' not in current_config: current_config['mysql_config'] = {}
            current_config['mysql_config'].update(new_config['mysql_config'])
            if 'port' in current_config['mysql_config']:
                try:
                    current_config['mysql_config']['port'] = int(current_config['mysql_config']['port'])
                except:
                    current_config['mysql_config']['port'] = 3306

        # Post
        if 'post_config' in new_config:
            if 'post_config' not in current_config: current_config['post_config'] = {}
            current_config['post_config'].update(new_config['post_config'])
            
        # LLM 配置
        if 'llm_config' in new_config:
            if 'llm_config' not in current_config: current_config['llm_config'] = {}
            current_config['llm_config'].update(new_config['llm_config'])
            if 'enable' in new_config['llm_config']:
                val = new_config['llm_config']['enable']
                current_config['llm_config']['enable'] = (str(val).lower() == 'true')

        # 通知配置
        if 'notify_config' in new_config:
            if 'notify_config' not in current_config: current_config['notify_config'] = {}
            current_config['notify_config'].update(new_config['notify_config'])
            if 'enable' in new_config['notify_config']:
                val = new_config['notify_config']['enable']
                current_config['notify_config']['enable'] = (str(val).lower() == 'true')

        # Cookie 检查配置
        if 'cookie_check_config' in new_config:
            if 'cookie_check_config' not in current_config: current_config['cookie_check_config'] = {}
            current_config['cookie_check_config'].update(new_config['cookie_check_config'])
            for k in ['enable', 'exit_after_check']:
                if k in new_config['cookie_check_config']:
                    val = new_config['cookie_check_config'][k]
                    current_config['cookie_check_config'][k] = (str(val).lower() == 'true')
                    
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, indent=4, ensure_ascii=False)

        # --- 2. 保存 logging.conf ---
        new_level = new_config.get('logging_level')
        if new_level:
            try:
                log_conf = configparser.ConfigParser()
                log_conf.read('logging.conf', encoding='utf-8')
                if not log_conf.has_section('handler_consoleHandler'):
                    log_conf.add_section('handler_consoleHandler')
                log_conf.set('handler_consoleHandler', 'level', new_level)
                if not log_conf.has_section('logger_weibo'):
                    log_conf.add_section('logger_weibo')
                log_conf.set('logger_weibo', 'level', new_level)
                with open('logging.conf', 'w', encoding='utf-8') as f:
                    log_conf.write(f)
            except Exception as e:
                logger.error(f"保存日志配置失败: {e}")
            
        return True, "所有配置已保存 (JSON/TXT/Log)"
    except Exception as e:
        logger.error(f"保存配置失败: {e}")
        return False, str(e)
    
# --- 路由定义 ---

@app.route('/')
def index():
    """渲染主页"""
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config_api():
    """获取当前配置"""
    cfg = load_config()
    return jsonify(cfg)

@app.route('/api/config', methods=['POST'])
def update_config_api():
    """更新配置"""
    # 检查是否有任务在运行，如果有，建议禁止修改，或者仅提示
    global GLOBAL_PROCESS
    if GLOBAL_PROCESS and GLOBAL_PROCESS.poll() is None:
        return jsonify({"success": False, "message": "爬虫正在运行中，请先停止任务后再修改配置！"}), 403

    data = request.json
    success, msg = save_config_file(data)
    return jsonify({"success": success, "message": msg})


def run_spider_process():
    """后台线程：实际执行 subprocess 的地方"""
    global GLOBAL_PROCESS
    
    # 构造命令
    cmd = [sys.executable, 'weibo.py']
    
    # 设置环境变量
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'     # 强制 Python 不缓存 stdout
    env['WEIBO_WEB_UI_MODE'] = '1'    # 告诉 weibo.py "我是 Web 模式"
    # 【新增】强制子进程使用 UTF-8 输出，不管系统是什么
    env['PYTHONIOENCODING'] = 'utf-8' 
    
    try:
        # Popen 启动子进程
        GLOBAL_PROCESS = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            # text=True,              # 【删除】这一行，因为默认可能会用 GBK
            encoding='utf-8',         # 【新增】强制使用 utf-8 解码
            errors='replace',         # 【新增】遇到无法解码的怪字符直接替换成 ?，防止报错崩溃
            bufsize=1,
            env=env,
            cwd=os.getcwd()
        )
        logger.info(f"爬虫进程已启动，PID: {GLOBAL_PROCESS.pid}")
        
    except Exception as e:
        logger.error(f"启动爬虫失败: {e}")
        GLOBAL_PROCESS = None

@app.route('/api/start', methods=['POST'])
def start_spider():
    """启动爬虫接口"""
    global GLOBAL_PROCESS
    
    with PROCESS_LOCK:
        # 1. 检查是否已有进程在运行
        if GLOBAL_PROCESS is not None:
            # poll() 返回 None 表示进程还在跑
            if GLOBAL_PROCESS.poll() is None:
                return jsonify({"success": False, "message": "爬虫已经在运行中，请勿重复启动！"})
            else:
                # 进程对象还在，但实际已结束（僵尸状态），清理掉
                GLOBAL_PROCESS = None
        
        # 2. 启动新进程
        # 为了不阻塞 Flask 主线程，虽然 Popen 本身是非阻塞的，但在复杂场景下建议清晰管理
        # 这里直接调用即可，因为 Popen 只是“开始运行”，不会等它结束
        run_spider_process()
        
        if GLOBAL_PROCESS:
            return jsonify({"success": True, "message": "爬虫启动成功"})
        else:
            return jsonify({"success": False, "message": "爬虫启动失败，请检查服务器日志"})

@app.route('/api/stop', methods=['POST'])
def stop_spider():
    """停止爬虫接口"""
    global GLOBAL_PROCESS
    
    with PROCESS_LOCK:
        if GLOBAL_PROCESS is None:
            return jsonify({"success": False, "message": "当前没有运行的任务"})
        
        try:
            # 尝试优雅终止
            GLOBAL_PROCESS.terminate()
            
            # 等待一小会儿看它死没死
            try:
                GLOBAL_PROCESS.wait(timeout=2)
            except subprocess.TimeoutExpired:
                # 敬酒不吃吃罚酒，强制击杀
                GLOBAL_PROCESS.kill()
                logger.warning("爬虫进程响应超时，已强制 Kill")
            
            GLOBAL_PROCESS = None
            logger.info("爬虫进程已停止")
            return jsonify({"success": True, "message": "任务已停止"})
            
        except Exception as e:
            logger.error(f"停止进程出错: {e}")
            return jsonify({"success": False, "message": f"停止失败: {str(e)}"})

@app.route('/api/status', methods=['GET'])
def check_status():
    """查询运行状态（供前端轮询）"""
    global GLOBAL_PROCESS
    is_running = False
    
    if GLOBAL_PROCESS:
        if GLOBAL_PROCESS.poll() is None:
            is_running = True
        else:
            # 运行结束，清理对象
            GLOBAL_PROCESS = None
            
    return jsonify({"running": is_running})

@app.route('/stream_logs')
def stream_logs():
    """
    SSE 日志流接口 (防刷屏优化版)
    """
    def generate():
        global GLOBAL_PROCESS
        
        # 初始发送一个连接成功信号
        yield f"data: [System] 日志流已连接\n\n"

        while True:
            # 情况1: 没有任务在运行
            if not GLOBAL_PROCESS or GLOBAL_PROCESS.poll() is not None:
                # 发送注释行作为心跳 (冒号开头会被浏览器忽略，但能保持连接)
                yield ": heartbeat\n\n"
                time.sleep(2) # 2秒发一次心跳
                continue

            # 情况2: 任务正在运行
            proc = GLOBAL_PROCESS
            try:
                # 持续读取管道
                for line in iter(proc.stdout.readline, ''):
                    if line:
                        clean_line = line.rstrip()
                        yield f"data: {clean_line}\n\n"
                    else:
                        break
                
                # 如果读不到内容了，判断进程是否结束
                if proc.poll() is not None:
                    yield f"data: [System] 任务已结束 (Exit Code: {proc.returncode})\n\n"
                    # 此时不要 break，继续进入上面的 while 循环发送心跳
                    # 让前端知道连接还在，只是没任务了
                    GLOBAL_PROCESS = None 
                    
            except Exception as e:
                yield f"data: [System Error] 日志流读取异常: {str(e)}\n\n"
                time.sleep(1)

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/api/captcha_solved', methods=['POST'])
def captcha_solved():
    """接收前端'验证完成'信号，生成文件解除爬虫阻塞"""
    try:
        # 创建信号文件，内容随意，存在即可
        with open('captcha.signal', 'w') as f:
            f.write('ok')
        logger.info("已接收前端指令，生成 captcha.signal 放行信号")
        return jsonify({"success": True, "message": "信号已发送"})
    except Exception as e:
        logger.error(f"生成信号文件失败: {e}")
        return jsonify({"success": False, "message": str(e)})

if __name__ == '__main__':
    # 定义启动参数
    HOST = '0.0.0.0'
    PORT = 5001
    URL = f"http://localhost:{PORT}"

    # 启动一个定时器，在 Flask 启动 1.5 秒后自动打开浏览器
    def open_browser():
        try:
            # 尝试打开默认浏览器
            webbrowser.open_new(URL)
            logger.info(f"已尝试自动打开浏览器: {URL}")
        except Exception as e:
            logger.warning(f"自动打开浏览器失败: {e}")

    # 使用 threading 在后台运行打开浏览器的任务
    threading.Timer(1.5, open_browser).start()

    print(f"启动 WebUI 服务...")
    print(f"请在浏览器访问: {URL}")
    
    # 启动 Flask
    app.run(host=HOST, port=PORT, debug=True, use_reloader=False)