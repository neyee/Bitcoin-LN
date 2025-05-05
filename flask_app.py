from flask import Flask

app = Flask(__name__)

@app.route("/")
def index():
    return "Lightning Wallet Bot Backend Activo!"

def run_flask_app():
    app.run(host="0.0.0.0", port=5000)
