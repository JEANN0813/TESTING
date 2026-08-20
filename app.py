# -*- coding: utf-8 -*-
"""
MoodTracker - 纯 Python 版本
无需安装任何第三方库，直接用 Python 运行
"""

import sqlite3
import json
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import re

# ============ 数据库操作 ============

def init_database():
    """初始化数据库"""
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    
    # 创建用户表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 创建情绪日志表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emotion_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            emotion TEXT NOT NULL,
            note TEXT,
            log_date TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ 数据库初始化完成")

def get_db_connection():
    """获取数据库连接"""
    return sqlite3.connect('database.db')

def dict_factory(cursor, row):
    """将查询结果转换为字典"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

# ============ 用户管理 ============

def register_user(username, password, email=""):
    """注册用户"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (username, password, email) VALUES (?, ?, ?)",
            (username, password, email)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return {"success": True, "user_id": user_id, "message": "注册成功"}
    except sqlite3.IntegrityError:
        conn.close()
        return {"success": False, "message": "用户名已存在"}

def login_user(username, password):
    """用户登录"""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM users WHERE username = ? AND password = ?",
        (username, password)
    )
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return {"success": True, "user": user, "message": "登录成功"}
    else:
        return {"success": False, "message": "用户名或密码错误"}

def get_user_by_id(user_id):
    """根据 ID 获取用户信息"""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, username, email, created_at FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

# ============ 情绪日志管理 ============

def add_emotion_log(user_id, emotion, note="", log_date=None):
    """记录情绪"""
    if log_date is None:
        log_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "INSERT INTO emotion_logs (user_id, emotion, note, log_date) VALUES (?, ?, ?, ?)",
        (user_id, emotion, note, log_date)
    )
    conn.commit()
    log_id = cursor.lastrowid
    conn.close()
    
    return {"success": True, "log_id": log_id, "message": "情绪记录成功"}

def get_emotion_logs(user_id, start_date=None, end_date=None):
    """获取情绪日志"""
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    query = "SELECT * FROM emotion_logs WHERE user_id = ?"
    params = [user_id]
    
    if start_date:
        query += " AND log_date >= ?"
        params.append(start_date)
    
    if end_date:
        query += " AND log_date <= ?"
        params.append(end_date)
    
    query += " ORDER BY log_date DESC, created_at DESC"
    
    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()
    
    return logs

def get_calendar_data(user_id, year, month):
    """获取日历数据"""
    start_date = f"{year}-{month:02d}-01"
    
    # 计算月末
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"
    
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute(
        """SELECT log_date, emotion FROM emotion_logs 
           WHERE user_id = ? AND log_date >= ? AND log_date < ?
           ORDER BY log_date DESC, created_at DESC""",
        (user_id, start_date, end_date)
    )
    logs = cursor.fetchall()
    conn.close()
    
    # 按天聚合（取最新的一条）
    daily_emotions = {}
    for log in logs:
        if log['log_date'] not in daily_emotions:
            daily_emotions[log['log_date']] = log['emotion']
    
    return daily_emotions

def get_emotion_stats(user_id, days=30):
    """获取情绪统计"""
    start_date = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT emotion, COUNT(*) as count FROM emotion_logs WHERE user_id = ? AND log_date >= ? GROUP BY emotion",
        (user_id, start_date)
    )
    stats = cursor.fetchall()
    conn.close()
    
    total = sum(s['count'] for s in stats)
    
    return {
        "total": total,
        "days": days,
        "statistics": stats
    }

# ============ HTTP 请求处理器 ============

class MoodTrackerHandler(BaseHTTPRequestHandler):
    """处理 HTTP 请求"""
    
    # 存储登录状态（简单版，用字典模拟 session）
    sessions = {}
    
    def do_GET(self):
        """处理 GET 请求"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        query_params = parse_qs(parsed_url.query)
        
        # 解析 cookie 获取用户 ID
        user_id = self.get_user_id_from_cookie()
        
        if path == '/' or path == '/index.html':
            self.send_html_response(self.get_index_page())
        
        elif path == '/api/calendar':
            if not user_id:
                self.send_json_response({"error": "请先登录"}, 401)
                return
            
            year = int(query_params.get('year', [datetime.datetime.now().year])[0])
            month = int(query_params.get('month', [datetime.datetime.now().month])[0])
            
            data = get_calendar_data(user_id, year, month)
            self.send_json_response({
                "year": year,
                "month": month,
                "data": data
            })
        
        elif path == '/api/stats':
            if not user_id:
                self.send_json_response({"error": "请先登录"}, 401)
                return
            
            days = int(query_params.get('days', [30])[0])
            stats = get_emotion_stats(user_id, days)
            self.send_json_response(stats)
        
        elif path == '/api/logs':
            if not user_id:
                self.send_json_response({"error": "请先登录"}, 401)
                return
            
            logs = get_emotion_logs(user_id)
            self.send_json_response({"logs": logs})
        
        elif path == '/api/user':
            if not user_id:
                self.send_json_response({"error": "请先登录"}, 401)
                return
            
            user = get_user_by_id(user_id)
            if user:
                self.send_json_response(user)
            else:
                self.send_json_response({"error": "用户不存在"}, 404)
        
        else:
            self.send_html_response("<h1>404 - Page Not Found</h1>", 404)
    
    def do_POST(self):
        """处理 POST 请求"""
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        # 读取请求体
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            data = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
            self.send_json_response({"error": "无效的 JSON 数据"}, 400)
            return
        
        if path == '/api/register':
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            email = data.get('email', '').strip()
            
            if not username or not password:
                self.send_json_response({"error": "用户名和密码不能为空"}, 400)
                return
            
            result = register_user(username, password, email)
            if result['success']:
                self.send_json_response(result)
            else:
                self.send_json_response(result, 400)
        
        elif path == '/api/login':
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            
            if not username or not password:
                self.send_json_response({"error": "用户名和密码不能为空"}, 400)
                return
            
            result = login_user(username, password)
            if result['success']:
                # 生成 session token
                import uuid
                session_token = str(uuid.uuid4())
                self.sessions[session_token] = result['user']['id']
                
                # 设置 cookie
                self.send_json_response({
                    "success": True,
                    "user": result['user'],
                    "message": "登录成功"
                }, 200, session_token)
            else:
                self.send_json_response({"error": "用户名或密码错误"}, 401)
        
        elif path == '/api/logout':
            # 清除 session
            cookie = self.headers.get('Cookie', '')
            if 'session=' in cookie:
                token = cookie.split('session=')[1].split(';')[0]
                if token in self.sessions:
                    del self.sessions[token]
            self.send_json_response({"message": "已登出"})
        
        elif path == '/api/log':
            user_id = self.get_user_id_from_cookie()
            if not user_id:
                self.send_json_response({"error": "请先登录"}, 401)
                return
            
            emotion = data.get('emotion', '').strip()
            note = data.get('note', '').strip()
            log_date = data.get('date', datetime.datetime.now().strftime("%Y-%m-%d"))
            
            if not emotion:
                self.send_json_response({"error": "请选择情绪"}, 400)
                return
            
            result = add_emotion_log(user_id, emotion, note, log_date)
            if result['success']:
                self.send_json_response(result)
            else:
                self.send_json_response(result, 400)
        
        else:
            self.send_json_response({"error": "接口不存在"}, 404)
    
    def get_user_id_from_cookie(self):
        """从 cookie 中获取用户 ID"""
        cookie = self.headers.get('Cookie', '')
        if 'session=' in cookie:
            token = cookie.split('session=')[1].split(';')[0]
            return self.sessions.get(token)
        return None
    
    def send_json_response(self, data, status=200, session_token=None):
        """发送 JSON 响应"""
        response = json.dumps(data, ensure_ascii=False)
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        
        if session_token:
            self.send_header('Set-Cookie', f'session={session_token}; Path=/; HttpOnly')
        
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def send_html_response(self, html, status=200):
        """发送 HTML 响应"""
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))
    
    def get_index_page(self):
        """返回首页 HTML"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>MoodTracker - 情绪追踪系统</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 800px;
                    margin: 50px auto;
                    padding: 20px;
                    background: #f5f5f5;
                }
                .container {
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                }
                h1 { color: #333; }
                .emoji { font-size: 48px; }
                .btn {
                    display: inline-block;
                    padding: 10px 20px;
                    margin: 5px;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                    font-size: 16px;
                }
                .btn-primary { background: #007bff; color: white; }
                .btn-success { background: #28a745; color: white; }
                .btn-danger { background: #dc3545; color: white; }
                .btn-warning { background: #ffc107; color: #333; }
                input, textarea, select {
                    display: block;
                    width: 100%;
                    padding: 10px;
                    margin: 10px 0;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    box-sizing: border-box;
                }
                .emotion-grid {
                    display: grid;
                    grid-template-columns: repeat(6, 1fr);
                    gap: 10px;
                    margin: 10px 0;
                }
                .emotion-btn {
                    padding: 15px;
                    border: 2px solid #ddd;
                    border-radius: 10px;
                    background: white;
                    cursor: pointer;
                    font-size: 24px;
                    transition: all 0.3s;
                }
                .emotion-btn:hover {
                    transform: scale(1.05);
                    border-color: #007bff;
                }
                .emotion-btn.selected {
                    border-color: #007bff;
                    background: #e3f2fd;
                }
                .hidden { display: none; }
                .log-item {
                    padding: 10px;
                    margin: 5px 0;
                    background: #f8f9fa;
                    border-radius: 5px;
                }
                #calendar {
                    display: grid;
                    grid-template-columns: repeat(7, 1fr);
                    gap: 5px;
                    margin: 10px 0;
                }
                .calendar-day {
                    padding: 10px;
                    text-align: center;
                    background: white;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    min-height: 60px;
                }
                .calendar-day.empty { background: transparent; border: none; }
                .calendar-day .emotion-icon { font-size: 24px; }
                .calendar-day .day-number { font-weight: bold; }
                .nav-bar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    margin-bottom: 20px;
                }
                .nav-bar .user-info { font-weight: bold; }
                .nav-bar .btn { margin: 0 5px; }
                .month-nav {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    gap: 20px;
                }
                .month-nav button {
                    padding: 5px 15px;
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    background: white;
                    cursor: pointer;
                }
                .month-nav span { font-size: 20px; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <!-- 导航栏 -->
                <div class="nav-bar">
                    <h1>😊 MoodTracker</h1>
                    <div id="authSection">
                        <span id="userInfo" class="user-info hidden"></span>
                        <button class="btn btn-success" id="showRegisterBtn" onclick="showRegister()">注册</button>
                        <button class="btn btn-primary" id="showLoginBtn" onclick="showLogin()">登录</button>
                        <button class="btn btn-danger hidden" id="logoutBtn" onclick="logout()">登出</button>
                    </div>
                </div>
                
                <!-- 登录/注册区域 -->
                <div id="loginForm">
                    <h2>登录</h2>
                    <input type="text" id="loginUsername" placeholder="用户名">
                    <input type="password" id="loginPassword" placeholder="密码">
                    <button class="btn btn-primary" onclick="login()">登录</button>
                    <p><a href="#" onclick="showRegister(); return false;">还没有账号？点此注册</a></p>
                    <div id="loginMessage"></div>
                </div>
                
                <div id="registerForm" class="hidden">
                    <h2>注册</h2>
                    <input type="text" id="regUsername" placeholder="用户名">
                    <input type="password" id="regPassword" placeholder="密码">
                    <input type="email" id="regEmail" placeholder="邮箱（选填）">
                    <button class="btn btn-success" onclick="register()">注册</button>
                    <p><a href="#" onclick="showLogin(); return false;">已有账号？点此登录</a></p>
                    <div id="registerMessage"></div>
                </div>
                
                <!-- 主内容 -->
                <div id="mainContent" class="hidden">
                    <!-- 记录情绪 -->
                    <div style="margin: 20px 0; padding: 15px; background: #e8f5e9; border-radius: 10px;">
                        <h3>📝 今天感觉怎么样？</h3>
                        <div class="emotion-grid" id="emotionGrid">
                            <button class="emotion-btn" data-emotion="happy">😊</button>
                            <button class="emotion-btn" data-emotion="sad">😢</button>
                            <button class="emotion-btn" data-emotion="angry">😡</button>
                            <button class="emotion-btn" data-emotion="anxious">😰</button>
                            <button class="emotion-btn" data-emotion="tired">😴</button>
                            <button class="emotion-btn" data-emotion="excited">🤩</button>
                        </div>
                        <input type="text" id="logNote" placeholder="备注（选填）" style="margin-top: 10px;">
                        <button class="btn btn-primary" onclick="logEmotion()">记录情绪</button>
                        <div id="logMessage"></div>
                    </div>
                    
                    <!-- 日历 -->
                    <div style="margin: 20px 0;">
                        <div class="month-nav">
                            <button onclick="changeMonth(-1)">◀</button>
                            <span id="monthDisplay"></span>
                            <button onclick="changeMonth(1)">▶</button>
                        </div>
                        <div id="calendar"></div>
                    </div>
                    
                    <!-- 统计数据 -->
                    <div style="margin: 20px 0; padding: 15px; background: #e3f2fd; border-radius: 10px;">
                        <h3>📊 近30天情绪统计</h3>
                        <div id="statsDisplay">加载中...</div>
                    </div>
                    
                    <!-- 最近记录 -->
                    <div style="margin: 20px 0;">
                        <h3>📋 最近记录</h3>
                        <div id="recentLogs">加载中...</div>
                    </div>
                </div>
            </div>
            
            <script>
                let currentUser = null;
                let currentYear = new Date().getFullYear();
                let currentMonth = new Date().getMonth() + 1;
                let selectedEmotion = null;
                
                // 情绪图标映射
                const emotionEmojis = {
                    'happy': '😊',
                    'sad': '😢',
                    'angry': '😡',
                    'anxious': '😰',
                    'tired': '😴',
                    'excited': '🤩'
                };
                
                const emotionNames = {
                    'happy': '开心',
                    'sad': '难过',
                    'angry': '生气',
                    'anxious': '焦虑',
                    'tired': '疲惫',
                    'excited': '兴奋'
                };
                
                // 初始化情绪按钮
                document.querySelectorAll('.emotion-btn').forEach(btn => {
                    btn.onclick = function() {
                        document.querySelectorAll('.emotion-btn').forEach(b => b.classList.remove('selected'));
                        this.classList.add('selected');
                        selectedEmotion = this.dataset.emotion;
                    };
                });
                
                // 显示登录
                function showLogin() {
                    document.getElementById('loginForm').classList.remove('hidden');
                    document.getElementById('registerForm').classList.add('hidden');
                    document.getElementById('loginMessage').textContent = '';
                }
                
                // 显示注册
                function showRegister() {
                    document.getElementById('loginForm').classList.add('hidden');
                    document.getElementById('registerForm').classList.remove('hidden');
                    document.getElementById('registerMessage').textContent = '';
                }
                
                // 注册
                async function register() {
                    const username = document.getElementById('regUsername').value.trim();
                    const password = document.getElementById('regPassword').value.trim();
                    const email = document.getElementById('regEmail').value.trim();
                    
                    if (!username || !password) {
                        document.getElementById('registerMessage').textContent = '❌ 用户名和密码不能为空';
                        document.getElementById('registerMessage').style.color = 'red';
                        return;
                    }
                    
                    const response = await fetch('/api/register', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password, email })
                    });
                    
                    const result = await response.json();
                    if (result.success) {
                        document.getElementById('registerMessage').textContent = '✅ 注册成功！请登录';
                        document.getElementById('registerMessage').style.color = 'green';
                        showLogin();
                        document.getElementById('loginUsername').value = username;
                    } else {
                        document.getElementById('registerMessage').textContent = '❌ ' + result.message;
                        document.getElementById('registerMessage').style.color = 'red';
                    }
                }
                
                // 登录
                async function login() {
                    const username = document.getElementById('loginUsername').value.trim();
                    const password = document.getElementById('loginPassword').value.trim();
                    
                    if (!username || !password) {
                        document.getElementById('loginMessage').textContent = '❌ 请输入用户名和密码';
                        document.getElementById('loginMessage').style.color = 'red';
                        return;
                    }
                    
                    const response = await fetch('/api/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    
                    const result = await response.json();
                    if (result.success) {
                        currentUser = result.user;
                        document.getElementById('userInfo').textContent = '👤 ' + currentUser.username;
                        document.getElementById('userInfo').classList.remove('hidden');
                        document.getElementById('loginForm').classList.add('hidden');
                        document.getElementById('registerForm').classList.add('hidden');
                        document.getElementById('mainContent').classList.remove('hidden');
                        document.getElementById('showLoginBtn').classList.add('hidden');
                        document.getElementById('showRegisterBtn').classList.add('hidden');
                        document.getElementById('logoutBtn').classList.remove('hidden');
                        document.getElementById('loginMessage').textContent = '';
                        
                        loadData();
                    } else {
                        document.getElementById('loginMessage').textContent = '❌ ' + result.error;
                        document.getElementById('loginMessage').style.color = 'red';
                    }
                }
                
                // 登出
                async function logout() {
                    await fetch('/api/logout', { method: 'POST' });
                    currentUser = null;
                    document.getElementById('userInfo').classList.add('hidden');
                    document.getElementById('mainContent').classList.add('hidden');
                    document.getElementById('showLoginBtn').classList.remove('hidden');
                    document.getElementById('showRegisterBtn').classList.remove('hidden');
                    document.getElementById('logoutBtn').classList.add('hidden');
                    document.getElementById('loginForm').classList.remove('hidden');
                    document.getElementById('loginPassword').value = '';
                }
                
                // 记录情绪
                async function logEmotion() {
                    if (!selectedEmotion) {
                        document.getElementById('logMessage').textContent = '❌ 请选择一种情绪';
                        document.getElementById('logMessage').style.color = 'red';
                        return;
                    }
                    
                    const note = document.getElementById('logNote').value.trim();
                    const date = new Date().toISOString().split('T')[0];
                    
                    const response = await fetch('/api/log', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ emotion: selectedEmotion, note, date })
                    });
                    
                    const result = await response.json();
                    if (result.success) {
                        document.getElementById('logMessage').textContent = '✅ ' + result.message + '！继续加油 💪';
                        document.getElementById('logMessage').style.color = 'green';
                        document.getElementById('logNote').value = '';
                        selectedEmotion = null;
                        document.querySelectorAll('.emotion-btn').forEach(b => b.classList.remove('selected'));
                        loadData();
                    } else {
                        document.getElementById('logMessage').textContent = '❌ ' + result.error;
                        document.getElementById('logMessage').style.color = 'red';
                    }
                }
                
                // 加载数据
                async function loadData() {
                    await loadCalendar();
                    await loadStats();
                    await loadRecentLogs();
                }
                
                // 加载日历
                async function loadCalendar() {
                    const response = await fetch(`/api/calendar?year=${currentYear}&month=${currentMonth}`);
                    const result = await response.json();
                    
                    document.getElementById('monthDisplay').textContent = `${currentYear}年${currentMonth}月`;
                    
                    const firstDay = new Date(currentYear, currentMonth - 1, 1).getDay();
                    const daysInMonth = new Date(currentYear, currentMonth, 0).getDate();
                    
                    let html = '';
                    const dayNames = ['日', '一', '二', '三', '四', '五', '六'];
                    dayNames.forEach(d => {
                        html += `<div style="text-align:center;font-weight:bold;padding:5px;">${d}</div>`;
                    });
                    
                    for (let i = 0; i < firstDay; i++) {
                        html += '<div class="calendar-day empty"></div>';
                    }
                    
                    for (let day = 1; day <= daysInMonth; day++) {
                        const dateStr = `${currentYear}-${String(currentMonth).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                        const emotion = result.data[dateStr];
                        const emoji = emotion ? emotionEmojis[emotion] || '❓' : '';
                        html += `
                            <div class="calendar-day">
                                <div class="day-number">${day}</div>
                                <div class="emotion-icon">${emoji}</div>
                            </div>
                        `;
                    }
                    
                    document.getElementById('calendar').innerHTML = html;
                }
                
                // 切换月份
                function changeMonth(delta) {
                    currentMonth += delta;
                    if (currentMonth > 12) {
                        currentMonth = 1;
                        currentYear++;
                    } else if (currentMonth < 1) {
                        currentMonth = 12;
                        currentYear--;
                    }
                    loadCalendar();
                }
                
                // 加载统计
                async function loadStats() {
                    const response = await fetch('/api/stats?days=30');
                    const result = await response.json();
                    
                    if (result.total === 0) {
                        document.getElementById('statsDisplay').textContent = '📭 最近30天还没有情绪记录，开始记录吧！';
                        return;
                    }
                    
                    let html = `<p>📊 最近 ${result.days} 天共记录了 ${result.total} 条</p>`;
                    html += '<ul>';
                    result.statistics.forEach(s => {
                        const pct = Math.round(s.count / result.total * 100);
                        html += `<li>${emotionNames[s.emotion] || s.emotion} ${emotionEmojis[s.emotion] || ''}：${s.count} 次 (${pct}%)</li>`;
                    });
                    html += '</ul>';
                    document.getElementById('statsDisplay').innerHTML = html;
                }
                
                // 加载最近记录
                async function loadRecentLogs() {
                    const response = await fetch('/api/logs');
                    const result = await response.json();
                    
                    if (!result.logs || result.logs.length === 0) {
                        document.getElementById('recentLogs').textContent = '📭 还没有记录';
                        return;
                    }
                    
                    const recent = result.logs.slice(0, 10);
                    let html = '';
                    recent.forEach(log => {
                        const emoji = emotionEmojis[log.emotion] || '❓';
                        const name = emotionNames[log.emotion] || log.emotion;
                        html += `
                            <div class="log-item">
                                ${emoji} ${name} - ${log.log_date}
                                ${log.note ? '📝 ' + log.note : ''}
                            </div>
                        `;
                    });
                    document.getElementById('recentLogs').innerHTML = html;
                }
                
                // 检查登录状态
                async function checkLoginStatus() {
                    const response = await fetch('/api/user');
                    if (response.status === 200) {
                        const user = await response.json();
                        if (user && user.id) {
                            currentUser = user;
                            document.getElementById('userInfo').textContent = '👤 ' + user.username;
                            document.getElementById('userInfo').classList.remove('hidden');
                            document.getElementById('loginForm').classList.add('hidden');
                            document.getElementById('registerForm').classList.add('hidden');
                            document.getElementById('mainContent').classList.remove('hidden');
                            document.getElementById('showLoginBtn').classList.add('hidden');
                            document.getElementById('showRegisterBtn').classList.add('hidden');
                            document.getElementById('logoutBtn').classList.remove('hidden');
                            loadData();
                        }
                    }
                }
                
                // 页面加载时检查登录状态
                checkLoginStatus();
            </script>
        </body>
        </html>
        """
    
    def log_message(self, format, *args):
        """覆盖日志输出，使其更简洁"""
        pass

# ============ 启动服务器 ============

def run_server(port=5000):
    """启动服务器"""
    init_database()
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, MoodTrackerHandler)
    
    print("=" * 50)
    print("🚀 MoodTracker 服务已启动")
    print("📁 数据库: database.db")
    print(f"🌐 访问地址: http://127.0.0.1:{port}")
    print("=" * 50)
    print("\n📌 可用功能:")
    print("  1. 用户注册/登录")
    print("  2. 记录每日情绪 (😊😢😡😰😴🤩)")
    print("  3. 查看月历情绪")
    print("  4. 查看情绪统计")
    print("=" * 50)
    print("\n按 Ctrl+C 停止服务器")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 服务器已停止")

if __name__ == '__main__':
    run_server()