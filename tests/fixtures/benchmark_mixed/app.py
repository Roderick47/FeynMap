from flask import Flask, render_template
app = Flask(__name__)


def helper():
    return []


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/api/items')
def items():
    return helper()
