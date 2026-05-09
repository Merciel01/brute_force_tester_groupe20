# api/Dockerfile
# Image basée sur Kali Linux pour disposer de Hydra nativement

FROM kalilinux/kali-rolling:latest

LABEL maintainer="Groupe 20 – UNIKIN 2026"
LABEL description="BruteScope API – Moteur Hydra + Flask REST"

# ── Mise à jour et installation des dépendances système ───────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      hydra \
      python3 \
      python3-pip \
      python3-dev \
      curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dépendances Python ────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

# ── Code source ───────────────────────────────────────────────────────────────
COPY app.py          .
COPY hydra_engine.py .

# ── Wordlists ─────────────────────────────────────────────────────────────────
COPY wordlists/ ./wordlists/

# ── Port exposé ───────────────────────────────────────────────────────────────
EXPOSE 5000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
  CMD curl -sf http://localhost:5000/api/status || exit 1

# ── Démarrage ─────────────────────────────────────────────────────────────────
CMD ["python3", "app.py"]
