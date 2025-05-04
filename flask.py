 --- Keep-alive usando Flask ---
app = Flask('')

@app.route('/')
def home():
    return "Bot activo."

class ServerThread(threading.Thread):
    def run(self):
        make_server('0.0.0.0', 8080, app).serve_forever()

ServerThread().start()
