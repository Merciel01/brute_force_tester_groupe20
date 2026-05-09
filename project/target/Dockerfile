# target/Dockerfile
FROM python:3.11-slim

LABEL maintainer="Groupe 20 – UNIKIN 2026"
LABEL description="Serveur cible vulnérable – Usage éducatif uniquement"

WORKDIR /app

# Dépendances minimales
RUN pip install --no-cache-dir flask==3.0.0

COPY target_app.py .

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "target_app.py"]
