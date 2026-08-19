from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import json

# ============ 初始化应用 ============
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# ============ 数据库模型 ============
class User(db.Model):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    security_question = db.Column(db.String(200))  # 密保问题
    security_answer = db.Column(db.String(200))    # 密保答案（存哈希）
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关系：一个用户有多条情绪日志
    emotion_logs = db.relationship('EmotionLog', backref='user', lazy=True, cascade='all, delete-orphan')

class EmotionLog(db.Model):
    __tablename__ = 'emotion_log'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emotion = db.Column(db.String(30), nullable=False)
    note = db.Column(db.String(300))
    logged_date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============ 辅助函数 ============
def get_current_user():
    """获取当前登录用户"""
    user_id = session.get('user_id')
    if not user_id:
        return None
    return User.query.get(user_id)

def login_required():
    """检查是否登录（装饰器用）"""
    if 'user_id' not in session:
        return False
    return True

# ============ 用户认证 API ============

@app.route('/api/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.get_json()
    
    # 检查必填字段
    if not all(k in data for k in ['username', 'email', 'password']):
        return jsonify({'error': 'Missing required fields'}), 400
    
    # 检查用户名是否已存在
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    # 检查邮箱是否已存在
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already registered'}), 400
    
    # 创建用户
    user = User(
        username=data['username'],
        email=data['email'],
        password_hash=generate_password_hash(data['password']),
        security_question=data.get('security_question', ''),
        security_answer=generate_password_hash(data.get('security_answer', '')) if data.get('security_answer') else ''
    )
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({'message': 'Registration successful', 'user_id': user.id}), 201

@app.route('/api/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.get_json()
    
    if not data.get('username') or not data.get('password'):
        return jsonify({'error': 'Username and password required'}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    
    if not user or not check_password_hash(user.password_hash, data['password']):
        return jsonify({'error': 'Invalid username or password'}), 401
    
    # 保存登录状态
    session['user_id'] = user.id
    session['username'] = user.username
    
    return jsonify({
        'message': 'Login successful',
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email
        }
    }), 200

@app.route('/api/logout', methods=['POST'])
def logout():
    """用户登出"""
    session.clear()
    return jsonify({'message': 'Logout successful'}), 200

@app.route('/api/profile', methods=['GET'])
def get_profile():
    """获取用户资料"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify({
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'created_at': user.created_at.isoformat()
    }), 200

@app.route('/api/profile', methods=['PUT'])
def update_profile():
    """更新用户资料"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    
    if 'email' in data:
        # 检查新邮箱是否被占用
        existing = User.query.filter_by(email=data['email']).first()
        if existing and existing.id != user.id:
            return jsonify({'error': 'Email already in use'}), 400
        user.email = data['email']
    
    if 'username' in data:
        existing = User.query.filter_by(username=data['username']).first()
        if existing and existing.id != user.id:
            return jsonify({'error': 'Username already in use'}), 400
        user.username = data['username']
    
    if 'password' in data:
        user.password_hash = generate_password_hash(data['password'])
    
    db.session.commit()
    return jsonify({'message': 'Profile updated successfully'}), 200

@app.route('/api/delete-account', methods=['DELETE'])
def delete_account():
    """删除账号（级联删除所有情绪日志）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # 验证密码
    data = request.get_json()
    if not data.get('password') or not check_password_hash(user.password_hash, data['password']):
        return jsonify({'error': 'Invalid password'}), 401
    
    db.session.delete(user)
    db.session.commit()
    session.clear()
    
    return jsonify({'message': 'Account deleted successfully'}), 200

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    """忘记密码 - 通过密保验证"""
    data = request.get_json()
    
    if not data.get('username') or not data.get('security_answer'):
        return jsonify({'error': 'Username and security answer required'}), 400
    
    user = User.query.filter_by(username=data['username']).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    # 验证密保答案
    if not check_password_hash(user.security_answer, data['security_answer']):
        return jsonify({'error': 'Incorrect security answer'}), 401
    
    # 生成临时重置码（简单版本：返回新密码，实际项目中应发送邮件）
    import random
    import string
    new_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    
    return jsonify({
        'message': 'Password reset successful',
        'new_password': new_password  # 实际项目中应通过邮件发送
    }), 200

# ============ 情绪日志 API ============

@app.route('/api/logs', methods=['POST'])
def add_emotion_log():
    """记录情绪日志"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.get_json()
    
    if not data.get('emotion'):
        return jsonify({'error': 'Emotion is required'}), 400
    
    # 解析日期
    log_date = datetime.utcnow().date()
    if data.get('date'):
        try:
            log_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    log = EmotionLog(
        user_id=user.id,
        emotion=data['emotion'],
        note=data.get('note', ''),
        logged_date=log_date
    )
    
    db.session.add(log)
    db.session.commit()
    
    return jsonify({
        'message': 'Log added successfully',
        'log_id': log.id,
        'emotion': log.emotion,
        'date': log.loged_date.isoformat()
    }), 201

@app.route('/api/logs', methods=['GET'])
def get_emotion_logs():
    """获取所有情绪日志（可过滤日期范围）"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    query = EmotionLog.query.filter_by(user_id=user.id)
    
    # 日期过滤
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    if start_date:
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d').date()
            query = query.filter(EmotionLog.logged_date >= start)
        except ValueError:
            pass
    
    if end_date:
        try:
            end = datetime.strptime(end_date, '%Y-%m-%d').date()
            query = query.filter(EmotionLog.logged_date <= end)
        except ValueError:
            pass
    
    logs = query.order_by(EmotionLog.logged_date.desc()).all()
    
    return jsonify({
        'logs': [{
            'id': log.id,
            'emotion': log.emotion,
            'note': log.note,
            'date': log.logged_date.isoformat(),
            'created_at': log.created_at.isoformat()
        } for log in logs]
    }), 200

@app.route('/api/logs/<int:log_id>', methods=['PUT'])
def update_emotion_log(log_id):
    """修改情绪日志"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    log = EmotionLog.query.get(log_id)
    if not log:
        return jsonify({'error': 'Log not found'}), 404
    
    if log.user_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    data = request.get_json()
    
    if 'emotion' in data:
        log.emotion = data['emotion']
    if 'note' in data:
        log.note = data['note']
    
    db.session.commit()
    
    return jsonify({
        'message': 'Log updated successfully',
        'log_id': log.id
    }), 200

@app.route('/api/logs/<int:log_id>', methods=['DELETE'])
def delete_emotion_log(log_id):
    """删除情绪日志"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    log = EmotionLog.query.get(log_id)
    if not log:
        return jsonify({'error': 'Log not found'}), 404
    
    if log.user_id != user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    db.session.delete(log)
    db.session.commit()
    
    return jsonify({'message': 'Log deleted successfully'}), 200

# ============ 日历数据 API ============

@app.route('/api/calendar/<int:year>/<int:month>', methods=['GET'])
def get_calendar_data(year, month):
    """获取某月每天的日历数据"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # 计算月份范围
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    # 查询该月所有日志
    logs = EmotionLog.query.filter_by(user_id=user.id).filter(
        EmotionLog.logged_date >= start_date,
        EmotionLog.logged_date <= end_date
    ).all()
    
    # 按天聚合（取当天最新的一条）
    daily_emotions = {}
    for log in logs:
        date_str = log.logged_date.isoformat()
        daily_emotions[date_str] = log.emotion
    
    return jsonify({
        'year': year,
        'month': month,
        'data': daily_emotions
    }), 200

@app.route('/api/calendar/today', methods=['GET'])
def get_today_emotion():
    """获取今天的情绪状态"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Unauthorized'}), 401
    
    today = datetime.utcnow().date()
    log = EmotionLog.query.filter_by(
        user_id=user.id,
        logged_date=today
    ).order_by(EmotionLog.created_at.desc()).first()
    
    return jsonify({
        'date': today.isoformat(),
        'has_log': log is not None,
        'emotion': log.emotion if log else None,
        'note': log.note if log else None
    }), 200

# ============ 提供给 Member C 的数据访问函数 ============

def get_user_logs_for_analysis(user_id, days=30):
    """
    获取用户最近N天的情绪日志（供 Member C 分析用）
    """
    start_date = datetime.utcnow().date() - timedelta(days=days)
    return EmotionLog.query.filter_by(user_id=user_id).filter(
        EmotionLog.logged_date >= start_date
    ).order_by(EmotionLog.logged_date).all()

def get_emotion_stats(user_id, days=30):
    """
    获取情绪统计数据（供 Member C 使用）
    """
    logs = get_user_logs_for_analysis(user_id, days)
    
    stats = {}
    for log in logs:
        stats[log.emotion] = stats.get(log.emotion, 0) + 1
    
    return {
        'total_logs': len(logs),
        'statistics': stats,
        'period_days': days
    }

# ============ 初始化数据库 ============

@app.before_first_request
def create_tables():
    """创建数据库表（如果不存在）"""
    db.create_all()
    print("✅ 数据库已初始化！")
    print("📊 表结构：user, emotion_log")

# ============ 启动应用 ============

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("=" * 50)
        print("🚀 MoodTracker 后端服务已启动")
        print("📁 数据库: database.db")
        print("🌐 访问地址: http://127.0.0.1:5000")
        print("=" * 50)
        print("\n📌 可用 API 端点:")
        print("  POST   /api/register     - 注册")
        print("  POST   /api/login        - 登录")
        print("  POST   /api/logout       - 登出")
        print("  GET    /api/profile      - 获取资料")
        print("  PUT    /api/profile      - 更新资料")
        print("  DELETE /api/delete-account - 删除账号")
        print("  POST   /api/forgot-password - 忘记密码")
        print("  POST   /api/logs         - 记录情绪")
        print("  GET    /api/logs         - 获取日志")
        print("  PUT    /api/logs/<id>    - 修改日志")
        print("  DELETE /api/logs/<id>    - 删除日志")
        print("  GET    /api/calendar/<year>/<month> - 日历数据")
        print("=" * 50)
    
    app.run(debug=True, host='0.0.0.0', port=5000)