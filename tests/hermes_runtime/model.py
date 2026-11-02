"""Offline chat-completions fixture for the real Hermes image smoke test."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

MODEL = "qwen3:4b-instruct-2507-q4_K_M"
REPLY = "Hermes-Modelltest erfolgreich."


class Model(BaseHTTPRequestHandler):
    def respond(self, data, mime="application/json"):
        body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.respond({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or data.get("model") != MODEL:
            return self.send_error(400)
        # This fixture runs without a task token. No general computer tools allowed.
        if data.get("tools"):
            return self.send_error(403, "Unexpected tools in restricted chat")
        base = {"id": "smoke", "model": MODEL, "created": 1}
        if not data.get("stream"):
            return self.respond(dict(base, object="chat.completion", choices=[{
                "index": 0, "message": {"role": "assistant", "content": REPLY}, "finish_reason": "stop"}]))
        events = []
        for delta, reason in [({"role": "assistant", "content": REPLY}, None), ({}, "stop")]:
            chunk = dict(base, object="chat.completion.chunk", choices=[{
                "index": 0, "delta": delta, "finish_reason": reason}])
            events.append("data: " + json.dumps(chunk))
        self.respond("\n\n".join(events + ["data: [DONE]", ""]), "text/event-stream")


HTTPServer(("0.0.0.0", 11434), Model).serve_forever()
