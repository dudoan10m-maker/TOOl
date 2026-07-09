from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, time, re

app = Flask(__name__)
CORS(app)  # Cho phép frontend gọi từ mọi domain (Netlify, localhost, v.v.)

# ═══════════════════════════════════════════════════════════════
# LƯU DỮ LIỆU RA FILE JSON — sống sót qua các lần request trong
# cùng 1 lần chạy service. LƯU Ý: Render free tier KHÔNG có ổ đĩa
# bền vững — mỗi lần deploy lại / service ngủ rồi thức dậy lại có
# thể bị mất file này. Nếu cần dữ liệu không bao giờ mất, nên
# chuyển sang Render Postgres (free tier có) thay vì file JSON.
# ═══════════════════════════════════════════════════════════════
DATA_FILE = 'data.json'

def _load():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'accounts': [], 'maintenance': {'locked': False, 'message': ''}}

def _save(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print('[WARN] Không ghi được data.json:', e)

DB = _load()  # {'accounts': [...], 'maintenance': {...}}


def find_account(account_id):
    for acc in DB['accounts']:
        if acc.get('id') == account_id:
            return acc
    return None


# ─────────────────────────────────────────────────────────────
# 1. POST /register — Đăng ký tài khoản
# Frontend gửi: {id, name, password, email, createdAt, assignedKey, device}
# Chặn trùng: cùng tên + cùng IP, hoặc trùng email
# ─────────────────────────────────────────────────────────────
def _get_client_ip():
    fwd = request.headers.get('X-Forwarded-For', '')
    if fwd:
        return fwd.split(',')[0].strip()
    return request.remote_addr or 'unknown'

@app.route('/register', methods=['POST'])
def register():
    data = request.json or {}
    acc_id = data.get('id')
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip().lower()
    client_ip = _get_client_ip()

    if not acc_id or not name:
        return jsonify({'error': 'Thiếu id hoặc name'}), 400

    existing = find_account(acc_id)
    if existing:
        # Đăng ký lại từ đúng máy/tài khoản cũ -> cập nhật, không tính là trùng
        existing.update({
            'name': name,
            'email': email,
            'password': data.get('password'),
            'device': data.get('device'),
            'ip': client_ip,
        })
        _save(DB)
        return jsonify({'message': 'Registered successfully'}), 201

    # Chặn trùng tên + IP (cùng người đăng ký nhiều lần)
    dup_name_ip = next((a for a in DB['accounts']
                         if a.get('name', '').strip().lower() == name.lower()
                         and a.get('ip') == client_ip), None)
    if dup_name_ip:
        return jsonify({'error': 'Tên này đã đăng ký từ thiết bị/mạng của bạn rồi!'}), 409

    # Chặn trùng email
    dup_email = next((a for a in DB['accounts']
                       if a.get('email', '').strip().lower() == email and email), None)
    if dup_email:
        return jsonify({'error': 'Email này đã được đăng ký!'}), 409

    DB['accounts'].append({
        'id': acc_id,
        'name': name,
        'password': data.get('password'),
        'email': email,
        'createdAt': data.get('createdAt', int(time.time() * 1000)),
        'assignedKey': None,
        'assignedAt': None,
        'device': data.get('device'),
        'ip': client_ip,
    })

    _save(DB)
    return jsonify({'message': 'Registered successfully'}), 201


# ─────────────────────────────────────────────────────────────
# 2. GET /accounts — Admin lấy toàn bộ danh sách tài khoản
# Frontend cần đúng dạng {"accounts": [...]}
# ─────────────────────────────────────────────────────────────
@app.route('/accounts', methods=['GET'])
def get_accounts():
    accs = sorted(DB['accounts'], key=lambda a: a.get('createdAt', 0), reverse=True)
    return jsonify({'accounts': accs}), 200


# ─────────────────────────────────────────────────────────────
# 3. POST /assign-key — Admin cấp key cho 1 tài khoản
# Frontend gửi: {accountId, key, exp}
# ─────────────────────────────────────────────────────────────
@app.route('/assign-key', methods=['POST'])
def assign_key():
    data = request.json or {}
    account_id = data.get('accountId')
    key = data.get('key')
    exp = data.get('exp')

    acc = find_account(account_id)
    if not acc:
        return jsonify({'error': 'Không tìm thấy tài khoản'}), 404

    acc['assignedKey'] = key
    acc['assignedAt'] = int(time.time() * 1000)
    acc['keyExpiry'] = exp

    _save(DB)
    return jsonify({'message': 'Key assigned', 'key': key}), 200


# ─────────────────────────────────────────────────────────────
# 4. GET /my-account?id=... — User tự kiểm tra tài khoản của mình
# Frontend cần field "assignedKey" (không phải "key")
# ─────────────────────────────────────────────────────────────
@app.route('/my-account', methods=['GET'])
def my_account():
    account_id = request.args.get('id')
    acc = find_account(account_id)
    if not acc:
        return jsonify({'error': 'Account not found'}), 404

    return jsonify({
        'id': acc['id'],
        'name': acc['name'],
        'assignedKey': acc.get('assignedKey')
    }), 200


# ─────────────────────────────────────────────────────────────
# 5. GET /inbox?device=... — Hộp thư: trả các key đã cấp cho
# những tài khoản đăng ký TỪ thiết bị này.
# Frontend cần dạng {"keys": [{id, key, note, orderId}]}
# ─────────────────────────────────────────────────────────────
@app.route('/inbox', methods=['GET'])
def inbox():
    device = request.args.get('device')
    out = []
    for acc in DB['accounts']:
        if acc.get('device') == device and acc.get('assignedKey'):
            out.append({
                'id': 'ACCKEY_' + acc['id'],
                'key': acc['assignedKey'],
                'note': '🎁 Admin đã cấp key cho tài khoản "' + acc['name'] + '"',
                'orderId': ''
            })
    return jsonify({'keys': out}), 200


# ─────────────────────────────────────────────────────────────
# 6. POST /verify-key — Xác thực key khi kích hoạt / gia hạn
# Frontend gửi: {key, device}  →  cần trả {valid: bool, days: number}
# Vì hệ thống tạo key hiện tại vẫn chạy local trên máy admin (chưa
# đồng bộ key string lên server), route này CHỈ kiểm tra định dạng
# + kiểm tra nếu key đó từng được /assign-key cấp thì còn hạn không.
# ─────────────────────────────────────────────────────────────
KEY_DURATIONS = {
    '1GIO': 1/24, '12GIO': 0.5, '1DAY': 1, '4DAY': 4,
    '1TUAN': 7, '1THANG': 30,
}

@app.route('/verify-key', methods=['POST'])
def verify_key():
    data = request.json or {}
    key = (data.get('key') or '').strip().upper()

    # Nếu key này từng được cấp qua /assign-key -> kiểm tra hạn thật
    for acc in DB['accounts']:
        if acc.get('assignedKey') == key:
            exp = acc.get('keyExpiry')
            if exp and exp <= int(time.time() * 1000):
                return jsonify({'valid': False, 'error': 'Key đã hết hạn'}), 200
            return jsonify({'valid': True, 'days': 1}), 200

    # Không tìm thấy trong hệ thống cấp key -> kiểm tra định dạng
    # SHADOW-<GÓI>-<MÃ> để không chặn các key admin tạo local (cũ)
    m = re.match(r'^SHADOW-([A-Z0-9]+)-[A-Z0-9]+$', key)
    if m:
        plan = m.group(1)
        days = KEY_DURATIONS.get(plan, 1)
        return jsonify({'valid': True, 'days': days}), 200

    return jsonify({'valid': False, 'error': 'Key sai định dạng'}), 200


# ─────────────────────────────────────────────────────────────
# 7. GET /api/status — Trạng thái bảo trì
# ─────────────────────────────────────────────────────────────
@app.route('/api/status', methods=['GET'])
def api_status():
    return jsonify(DB.get('maintenance', {'locked': False, 'message': ''})), 200

@app.route('/api/status', methods=['POST'])
def set_status():
    """Admin gọi route này để bật/tắt bảo trì (tuỳ chọn, có thể nối vào admin panel sau)."""
    data = request.json or {}
    DB['maintenance'] = {
        'locked': bool(data.get('locked', False)),
        'message': data.get('message', '')
    }
    _save(DB)
    return jsonify(DB['maintenance']), 200


# ─────────────────────────────────────────────────────────────
# 8. POST /login — Đăng nhập bằng email + mật khẩu (đăng nhập
# từ thiết bị khác với thiết bị đã đăng ký)
# Frontend gửi: {email, password}
# Cần trả: {success: bool, account: {...}}
# ─────────────────────────────────────────────────────────────
@app.route('/login', methods=['POST'])
def login():
    data = request.json or {}
    email = data.get('email')
    password = data.get('password')

    for acc in DB['accounts']:
        if acc.get('email') == email and acc.get('password') == password:
            return jsonify({'success': True, 'account': acc}), 200

    return jsonify({'success': False, 'error': 'Sai email hoặc mật khẩu'}), 200


# ─────────────────────────────────────────────────────────────
# 9. POST /delete-account — Admin xoá 1 tài khoản (dọn trùng lặp...)
# Frontend gửi: {accountId}
# ─────────────────────────────────────────────────────────────
@app.route('/delete-account', methods=['POST'])
def delete_account():
    data = request.json or {}
    account_id = data.get('accountId')
    before = len(DB['accounts'])
    DB['accounts'] = [a for a in DB['accounts'] if a.get('id') != account_id]
    if len(DB['accounts']) == before:
        return jsonify({'error': 'Không tìm thấy tài khoản'}), 404
    _save(DB)
    return jsonify({'message': 'Deleted'}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
