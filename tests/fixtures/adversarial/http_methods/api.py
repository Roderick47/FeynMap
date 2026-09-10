from flask import Flask
app = Flask(__name__)


@app.route('/items', methods=['GET'])
def get_items():
    return []


@app.route('/items', methods=['POST'])
def post_items():
    return []
