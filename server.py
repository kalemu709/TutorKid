#!/usr/bin/env python3
"""Small, stateless web server for Chinese character practice."""
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from io import BytesIO
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
from pypdf import PdfReader

HAN = re.compile(r"^[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]$")
HAN_ANY = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
TEXT_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
IMAGE_TYPES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
RATE_LOCK = threading.Lock()
RATE_BUCKETS = defaultdict(deque)
AI_SLOTS = threading.BoundedSemaphore(4)
OCR_LOCK = threading.Lock()
OCR_ENGINE = None
OCR_DETECTION_MODEL = "PP-OCRv5_server_det"
OCR_RECOGNITION_MODEL = "PP-OCRv5_server_rec"
# A text box holding only one of these symbols is almost always the lookalike character.
OCR_LOOKALIKES = {"+": "十", "＋": "十"}
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def response_text(result):
    return "".join(
        content.get("text", "")
        for item in result.get("output", [])
        for content in item.get("content", [])
        if content.get("type") == "output_text"
    )


def upstream_error(exc):
    try:
        payload = json.loads(exc.read().decode("utf-8"))
        error = payload.get("error", {})
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])[:500]
    except Exception:
        pass
    return f"The AI service returned HTTP {getattr(exc, 'code', 'error')}."


class UploadTooLarge(Exception):
    pass


class OcrBusy(Exception):
    pass


def request_response(body, key, timeout):
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(upstream_error(exc)) from None
    return response_text(result).strip()


def unique_in_order(characters):
    return list(dict.fromkeys(characters))


def image_type(data):
    for signature, mime in IMAGE_TYPES:
        if data.startswith(signature):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def decode_text(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if not TEXT_CONTROL.search(text):
            return text
    return None


def pdf_characters(data):
    reader = PdfReader(BytesIO(data), strict=False)
    if len(reader.pages) > MAX_PDF_PAGES:
        raise UploadTooLarge(f"This PDF has more than {MAX_PDF_PAGES} pages. Split it into smaller practice sheets.")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    characters = []
    for index, line in enumerate(lines[:-1]):
        if line.isdigit() and HAN.fullmatch(lines[index + 1]):
            characters.append(lines[index + 1])
    if not characters:
        characters = [line for line in lines if HAN.fullmatch(line)]
    return characters, len(reader.pages)


def load_ocr():
    global OCR_ENGINE
    if OCR_ENGINE is None:
        from paddleocr import TextDetection, TextRecognition
        OCR_ENGINE = (
            TextDetection(model_name=OCR_DETECTION_MODEL),
            TextRecognition(model_name=OCR_RECOGNITION_MODEL),
        )
    return OCR_ENGINE


def reading_order(boxes):
    """Sort (top, bottom, left, right) boxes into rows, top to bottom, then left to right."""
    rows = []
    for box in sorted(boxes, key=lambda item: item[0]):
        middle = (box[0] + box[1]) / 2
        if rows and middle < rows[-1][0]:
            rows[-1][1].append(box)
        else:
            rows.append([box[1], [box]])
    return [box for _, row in rows for box in sorted(row, key=lambda item: item[2])]


def image_characters(data):
    import numpy
    from PIL import Image

    with Image.open(BytesIO(data)) as image:
        pixels = numpy.ascontiguousarray(numpy.array(image.convert("RGB"))[:, :, ::-1])
    height, width = pixels.shape[:2]
    if not OCR_LOCK.acquire(timeout=30):
        raise OcrBusy()
    try:
        detector, recognizer = load_ocr()
        boxes = []
        for polygon in detector.predict(pixels)[0]["dt_polys"]:
            xs, ys = polygon[:, 0], polygon[:, 1]
            top, bottom = max(int(ys.min()), 0), min(int(ys.max()) + 1, height)
            left, right = max(int(xs.min()), 0), min(int(xs.max()) + 1, width)
            if bottom > top and right > left:
                boxes.append((top, bottom, left, right))
        crops = [
            numpy.ascontiguousarray(pixels[top:bottom, left:right])
            for top, bottom, left, right in reading_order(boxes)
        ]
        texts = [item["rec_text"] for item in recognizer.predict(crops)] if crops else []
    finally:
        OCR_LOCK.release()
    texts = [OCR_LOOKALIKES.get(text.strip(), text) for text in texts]
    return unique_in_order(HAN_ANY.findall("".join(texts)))


def generate_example(character, key):
    prompt = f"Create one accurate beginner Chinese character-learning entry for {character}."
    instructions = (
        "You are a careful Mandarin Chinese tutor. Return only a JSON object with string fields "
        "pinyin, meaning, example_word, example_sentence, sentence_translation. Keep meaning concise "
        "in English. The natural simplified Chinese word must contain the requested character. "
        "Keep the sentence short and beginner friendly. No markdown."
    )
    body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "instructions": instructions,
        "input": prompt,
        "max_output_tokens": 350,
    }
    raw = request_response(body, key, timeout=30)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("The AI response was not valid JSON.") from None
        parsed = json.loads(raw[start:end + 1])
    clean = {
        field: str(parsed.get(field, "")).strip()[:240]
        for field in ("pinyin", "meaning", "example_word", "example_sentence", "sentence_translation")
    } if isinstance(parsed, dict) else {}
    if not (clean.get("meaning") and clean.get("example_word") and character in clean["example_word"] and clean.get("example_sentence")):
        raise ValueError(f"The AI response did not include a complete example for {character}.")
    return clean


def within_limit(ip, name, limit, seconds=60):
    now = time.monotonic()
    key = (ip, name)
    with RATE_LOCK:
        bucket = RATE_BUCKETS[key]
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        if len(RATE_BUCKETS) > 10000:
            for old_key in list(RATE_BUCKETS)[:1000]:
                if not RATE_BUCKETS[old_key] or RATE_BUCKETS[old_key][-1] <= now - seconds:
                    RATE_BUCKETS.pop(old_key, None)
        return True


class Handler(BaseHTTPRequestHandler):
    server_version = "HanziPractice/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self, maximum):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request size.") from None
        if not 0 < length <= maximum:
            raise ValueError("Request is empty or exceeds the size limit.")
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError("The request was incomplete.")
        return data

    def client_ip(self):
        # Cloud Run's direct connection address avoids trusting caller-supplied headers.
        return self.client_address[0]

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/tts-status":
            return self.send_json(200, {"enabled": bool(os.environ.get("OPENAI_API_KEY", "").strip())})
        static = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/chinese": ("index.html", "text/html; charset=utf-8"),
            "/math": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        item = static.get(path)
        if not item:
            self.send_error(404)
            return
        filename, content_type = item
        body = (ROOT / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/extract":
            return self.extract_characters()
        if path == "/api/ai-example":
            return self.ai_example()
        if path == "/api/speech":
            return self.speech()
        return self.send_json(404, {"error": "Unknown endpoint."})

    def extract_characters(self):
        try:
            data = self.read_body(MAX_UPLOAD_BYTES)
        except ValueError:
            return self.send_json(400, {"error": "Choose a PDF, text file, or image smaller than 30 MB."})
        if data.startswith(b"%PDF-"):
            return self.extract_pdf(data)
        if image_type(data):
            return self.extract_image(data)
        return self.extract_text(data)

    def extract_pdf(self, data):
        try:
            characters, pages = pdf_characters(data)
        except UploadTooLarge as exc:
            return self.send_json(413, {"error": str(exc)})
        except Exception as exc:
            return self.send_json(400, {"error": "Could not read that PDF: " + str(exc)[:300]})
        if not characters:
            return self.send_json(422, {"error": "No selectable Chinese characters found. Try a text-based PDF, a screenshot, or paste characters into the box."})
        return self.send_json(200, {"characters": characters, "pages": pages})

    def extract_text(self, data):
        text = decode_text(data)
        if text is None:
            return self.send_json(415, {"error": "Unsupported file. Choose a PDF, a UTF-8 or GB18030 text file, or a PNG, JPEG, WebP, or GIF image."})
        characters = unique_in_order(HAN_ANY.findall(text))
        if not characters:
            return self.send_json(422, {"error": "No Chinese characters found in that text file."})
        return self.send_json(200, {"characters": characters})

    def extract_image(self, data):
        if len(data) > MAX_IMAGE_BYTES:
            return self.send_json(413, {"error": "Choose an image smaller than 10 MB."})
        if not within_limit(self.client_ip(), "image", 10):
            return self.send_json(429, {"error": "Image reading limit reached for this minute. Please wait and try again."})
        try:
            characters = image_characters(data)
        except OcrBusy:
            return self.send_json(503, {"error": "The image reader is busy. Try again shortly."})
        except Exception as exc:
            return self.send_json(400, {"error": "Could not read characters from that image: " + str(exc)[:300]})
        if not characters:
            return self.send_json(422, {"error": "No Chinese characters found in that image. Try a clearer or closer screenshot."})
        return self.send_json(200, {"characters": characters})

    def ai_example(self):
        if not within_limit(self.client_ip(), "example", 20):
            return self.send_json(429, {"error": "Practice example limit reached for this minute. Please wait and try again."})
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            return self.send_json(503, {"error": "AI examples are not enabled. Configure the API key for this service."})
        try:
            payload = json.loads(self.read_body(4096).decode("utf-8"))
            character = payload.get("character", "")
            if not isinstance(character, str) or not HAN.fullmatch(character):
                return self.send_json(400, {"error": "Choose one Chinese character."})
            if not AI_SLOTS.acquire(timeout=1):
                return self.send_json(503, {"error": "The example service is busy. Try again shortly."})
            try:
                example = generate_example(character, os.environ["OPENAI_API_KEY"].strip())
            finally:
                AI_SLOTS.release()
            return self.send_json(200, {"example": example})
        except RuntimeError as exc:
            return self.send_json(502, {"error": "AI example request failed: " + str(exc)[:500]})
        except Exception as exc:
            return self.send_json(502, {"error": "Could not generate a complete example: " + str(exc)[:500]})

    def speech(self):
        if not within_limit(self.client_ip(), "speech", 45):
            return self.send_json(429, {"error": "Reading limit reached for this minute. Please wait before listening again."})
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            return self.send_json(503, {"error": "AI voice is not enabled. This device can use its built-in Chinese voice."})
        try:
            payload = json.loads(self.read_body(12000).decode("utf-8"))
            text = payload.get("text", "")
            if not isinstance(text, str) or not text.strip() or len(text) > 1000 or not re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", text):
                return self.send_json(400, {"error": "Provide a short Chinese practice prompt."})
            if not AI_SLOTS.acquire(timeout=1):
                return self.send_json(503, {"error": "The reading service is busy. Try again shortly."})
            try:
                body = {
                    "model": os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts"),
                    "voice": os.environ.get("OPENAI_TTS_VOICE", "coral"),
                    "input": text,
                    "instructions": "Speak Mandarin Chinese with a gentle, warm, natural female voice. Use clear standard pronunciation, a calm encouraging tone, soft warmth, and unhurried pacing. Pause naturally between the character, example word, and example sentence. Read only the supplied Chinese text.",
                    "response_format": "mp3",
                }
                req = urllib.request.Request(
                    "https://api.openai.com/v1/audio/speech",
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=35) as response:
                    audio = response.read()
            finally:
                AI_SLOTS.release()
            if not audio:
                return self.send_json(502, {"error": "The speech service returned an empty audio clip."})
            return self.send_bytes(200, audio, "audio/mpeg")
        except urllib.error.HTTPError as exc:
            return self.send_json(502, {"error": "AI voice generation failed: " + upstream_error(exc)})
        except Exception as exc:
            return self.send_json(502, {"error": "AI voice generation failed: " + str(exc)[:500]})


if __name__ == "__main__":
    default_port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    port = int(os.environ.get("PORT", default_port))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Chinese Character Practice is ready on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
