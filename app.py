from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Cho phép frontend gọi

# Danh sách account tạm (sau này thay bằng database)
accounts = []
keys = {}

# 1. POST /register - Đăng ký tài khoản
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    
    # Kiểm tra trùng
    for acc in accounts:
        if acc['username'] == username:
            return jsonify({'error': 'Username already exists'}), 400
    
    accounts.append({'username': username, 'password': password})
    return jsonify({'message': 'Registered successfully'}), 201

# 2. GET /accounts - Lấy danh sách tài khoản
@app.route('/accounts', methods=['GET'])
def get_accounts():
    return jsonify(accounts), 200

# 3. POST /assign-key - Gán key cho tài khoản
@app.route('/assign-key', methods=['POST'])
def assign_key():
    data = request.json
    username = data.get('username')
    key = data.get('key')
    
    keys[username] = key
    return jsonify({'message': 'Key assigned', 'key': key}), 200

# 4. GET /my-account - Lấy thông tin account theo id
@app.route('/my-account', methods=['GET'])
def my_account():
    user_id = request.args.get('id')
    
    # Tìm account theo id (giả định id là username)
    for acc in accounts:
        if acc['username'] == user_id:
            return jsonify({
                'username': acc['username'],
                'key': keys.get(acc['username'], 'No key')
            }), 200
    
    return jsonify({'error': 'Account not found'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)