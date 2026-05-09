# app.py
# API REST principale + Server-Sent Events (SSE)
# Contrôle et supervision du moteur Hydra

import json
import time
import logging
import os
import queue
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from hydra_engine import (
    start_attack,
    stop_attack,
    get_stats,
    is_running,
    result_queue,
)

# ─── Configuration ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [API] %(levelname)s – %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/stream": {"origins": "*"}})

# Rate limiting sur l'API de contrôle (pas sur le stream)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["500 per hour"],
    storage_uri="memory://",
)

# Session courante
current_session: dict = {
    "active": False,
    "config": None,
    "thread": None,
}

WORDLISTS_DIR = os.path.join(os.path.dirname(__file__), "wordlists")
DEFAULT_TARGET_HOST = os.getenv("TARGET_HOST", "target")
DEFAULT_TARGET_PORT = int(os.getenv("TARGET_PORT", "8080"))
ALLOW_EXTERNAL_TARGETS = os.getenv("ALLOW_EXTERNAL_TARGETS", "false").lower() == "true"
ALLOWED_TARGETS = {
    item.strip()
    for item in os.getenv("ALLOWED_TARGETS", f"{DEFAULT_TARGET_HOST},target,172.20.0.10").split(",")
    if item.strip()
}


def parse_int_field(data: dict, name: str, default: int, minimum: int, maximum: int) -> tuple[int | None, str | None]:
    try:
        value = int(data.get(name, default))
    except (TypeError, ValueError):
        return None, f"{name} doit etre un entier."
    if value < minimum or value > maximum:
        return None, f"{name} doit etre compris entre {minimum} et {maximum}."
    return value, None


def validate_login_url(value: str) -> str | None:
    if not value or not value.startswith("/"):
        return "login_url doit commencer par '/'."
    if any(ch.isspace() for ch in value):
        return "login_url ne doit pas contenir d'espaces."
    return None


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS API
# ═══════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Sert le dashboard web."""
    return send_from_directory(app.static_folder, "index.html")


# ─── POST /api/start ──────────────────────────────────────────────────────────
@app.route("/api/start", methods=["POST"])
@limiter.limit("10 per minute")
def api_start():
    """
    Démarre une session de test Hydra.

    Body JSON :
      {
        "target_ip":   "127.0.0.1",
        "port":        8080,
        "login_url":   "/login",
        "username":    "admin",
        "wordlist":    "common.txt",
        "fail_string": "Invalid credentials",
        "threads":     4
      }

    Réponses :
      200 – session démarrée
      409 – attaque déjà en cours
      400 – paramètres invalides
    """
    if is_running():
        return jsonify({"error": "Une attaque est déjà en cours. Arrêtez-la d'abord."}), 409

    data = request.get_json(force=True, silent=True) or {}

    # Validation basique
    target_ip = data.get("target_ip", DEFAULT_TARGET_HOST).strip()
    if not target_ip:
        return jsonify({"error": "target_ip est requis."}), 400
    if not ALLOW_EXTERNAL_TARGETS and target_ip not in ALLOWED_TARGETS:
        return jsonify({
            "error": "Cible non autorisee pour ce labo.",
            "allowed_targets": sorted(ALLOWED_TARGETS),
        }), 400

    port, err = parse_int_field(data, "port", DEFAULT_TARGET_PORT, 1, 65535)
    if err:
        return jsonify({"error": err}), 400

    threads, err = parse_int_field(data, "threads", 4, 1, 16)
    if err:
        return jsonify({"error": err}), 400

    login_url = data.get("login_url", "/login").strip() or "/login"
    url_error = validate_login_url(login_url)
    if url_error:
        return jsonify({"error": url_error}), 400

    username = data.get("username", "admin").strip() or "admin"
    fail_string = data.get("fail_string", "Invalid credentials").strip()
    if not fail_string:
        return jsonify({"error": "fail_string est requis."}), 400

    wordlist_name = data.get("wordlist", "common.txt")
    wordlist_path = os.path.join(WORDLISTS_DIR, os.path.basename(wordlist_name))
    if not os.path.isfile(wordlist_path):
        return jsonify({"error": f"Fichier wordlist introuvable : {wordlist_name}"}), 400

    config = {
        "target_ip":    target_ip,
        "port":         port,
        "login_url":    login_url,
        "username":     username,
        "wordlist_path": wordlist_path,
        "wordlist":     os.path.basename(wordlist_path),
        "fail_string":  fail_string,
        "threads":      threads,
    }

    thread = start_attack(config)
    current_session.update({"active": True, "config": config, "thread": thread})

    logger.info("Session démarrée : %s", config)
    return jsonify({"status": "started", "config": config}), 200


# ─── POST /api/stop ───────────────────────────────────────────────────────────
@app.route("/api/stop", methods=["POST"])
def api_stop():
    """Arrête la session en cours."""
    stop_attack()
    current_session["active"] = False
    logger.info("Session arrêtée manuellement.")
    return jsonify({"status": "stopped"}), 200


# ─── GET /api/stats ───────────────────────────────────────────────────────────
@app.route("/api/stats")
def api_stats():
    """Statistiques de la session courante."""
    stats = get_stats()
    stats["config"] = current_session.get("config")
    return jsonify(stats), 200


# ─── GET /api/wordlists ───────────────────────────────────────────────────────
@app.route("/api/wordlists")
def api_wordlists():
    """Liste les wordlists disponibles avec leur taille."""
    lists = []
    if os.path.isdir(WORDLISTS_DIR):
        for fname in sorted(os.listdir(WORDLISTS_DIR)):
            fpath = os.path.join(WORDLISTS_DIR, fname)
            if os.path.isfile(fpath):
                with open(fpath) as f:
                    count = sum(1 for _ in f)
                lists.append({"name": fname, "entries": count})
    return jsonify(lists), 200


# ─── GET /api/status ──────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    """Santé de l'API."""
    return jsonify({
        "status": "ok",
        "running": is_running(),
        "version": "1.0.0",
        "group": "Groupe 20 – UNIKIN 2026",
        "default_target": DEFAULT_TARGET_HOST,
        "default_port": DEFAULT_TARGET_PORT,
        "allowed_targets": sorted(ALLOWED_TARGETS),
        "external_targets_enabled": ALLOW_EXTERNAL_TARGETS,
    }), 200


# ═══════════════════════════════════════════════════════════════
# SERVER-SENT EVENTS (SSE)
# ═══════════════════════════════════════════════════════════════

@app.route("/stream")
def stream():
    """
    Flux SSE – push des résultats Hydra en temps réel vers le browser.

    Le client ouvre une connexion persistante GET /stream.
    Le serveur envoie des événements au format :
        data: {"timestamp":"...","username":"...","password":"...","success":false}\n\n

    Un heartbeat est envoyé toutes les secondes pour maintenir la connexion.
    """
    def generate():
        logger.info("Client SSE connecté depuis %s.", request.remote_addr)
        heartbeat_interval = 1.0   # secondes
        last_heartbeat = time.time()

        while True:
            try:
                # Essayer de lire un résultat de la queue
                item = result_queue.get(timeout=heartbeat_interval)
                yield "data: {}\n\n".format(json.dumps(item))

            except queue.Empty:
                # Queue vide → envoyer heartbeat
                now = time.time()
                if now - last_heartbeat >= heartbeat_interval:
                    yield 'data: {"ping": true}\n\n'
                    last_heartbeat = now

                # Arrêter le stream si plus rien n'est actif ET la queue est vide
                if not is_running() and result_queue.empty():
                    yield 'data: {"done": true}\n\n'
                    logger.info("Stream SSE fermé – session terminée.")
                    return

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":     "no-cache",
            "X-Accel-Buffering": "no",      # Désactive le buffering nginx
            "Connection":        "keep-alive",
        }
    )


# ═══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  BRUTESCOPE API – PORT 5000")
    print("  Dashboard : http://localhost:5000")
    print("  API Stats  : http://localhost:5000/api/stats")
    print("  SSE Stream : http://localhost:5000/stream")
    print("=" * 60)
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,      # Requis pour SSE + requêtes simultanées
        use_reloader=False,
    )
