# target_app.py
# Serveur cible volontairement vulnérable – USAGE ÉDUCATIF UNIQUEMENT
# Simule une application web avec formulaire de login sans protection

from flask import Flask, request, jsonify, session, render_template_string
import hashlib
import os
import time

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ─── Base d'utilisateurs simulée (mots de passe hashés SHA-256) ───────────────
USERS = {
    "admin":   hashlib.sha256(b"admin123").hexdigest(),
    "alice":   hashlib.sha256(b"password").hexdigest(),
    "bob":     hashlib.sha256(b"letmein").hexdigest(),
    "charlie": hashlib.sha256(b"qwerty").hexdigest(),
    "root":    hashlib.sha256(b"toor").hexdigest(),
}

# ─── Page HTML du formulaire de login ─────────────────────────────────────────
LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <title>Login – Système Vulnérable</title>
  <style>
    body { font-family: Arial, sans-serif; background: #f0f2f5;
           display: flex; justify-content: center; align-items: center; height: 100vh; }
    .box { background: white; padding: 2rem; border-radius: 8px;
           box-shadow: 0 2px 12px rgba(0,0,0,.15); width: 340px; }
    h2   { text-align: center; color: #333; margin-bottom: 1.5rem; }
    input { width: 100%; padding: .6rem; margin: .4rem 0 1rem;
            border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
    button { width: 100%; padding: .7rem; background: #1976d2;
             color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 1rem; }
    .msg  { text-align: center; margin-top: .8rem; color: red; font-size: .9rem; }
    .warn { background: #fff3cd; border: 1px solid #ffc107;
            padding: .5rem; border-radius: 4px; font-size: .75rem;
            color: #856404; margin-bottom: 1rem; text-align: center; }
  </style>
</head>
<body>
  <div class="box">
    <h2>🔐 Connexion</h2>
    <div class="warn">⚠️ Serveur volontairement vulnérable – Éducatif</div>
    <form method="POST" action="/login">
      <label>Utilisateur</label>
      <input type="text"     name="username" placeholder="admin" required>
      <label>Mot de passe</label>
      <input type="password" name="password" placeholder="••••••••" required>
      <button type="submit">Se connecter</button>
    </form>
    {% if error %}
    <p class="msg">{{ error }}</p>
    {% endif %}
  </div>
</body>
</html>
"""

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template_string(LOGIN_PAGE, error=None)


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Endpoint de login — INTENTIONNELLEMENT non protégé :
      - Pas de rate limiting
      - Pas de CAPTCHA
      - Pas de lockout
      - Message d'erreur identique (pas d'user enumeration ici)
    """
    if request.method == 'GET':
        return render_template_string(LOGIN_PAGE, error=None)

    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()

    if not username or not password:
        return render_template_string(LOGIN_PAGE, error="Champs requis."), 400

    pw_hash = hashlib.sha256(password.encode()).hexdigest()

    if USERS.get(username) == pw_hash:
        session['user'] = username
        # Hydra détecte cette chaîne comme succès
        return "LOGIN_SUCCESS – Bienvenue, {}!".format(username), 200

    # Hydra détecte cette chaîne comme échec (F=Invalid credentials)
    return "Invalid credentials", 401


@app.route('/protected')
def protected():
    if 'user' not in session:
        return "Unauthorized – Veuillez vous connecter.", 401
    return "✅ Zone protégée – Connecté en tant que : {}".format(session['user']), 200


@app.route('/logout')
def logout():
    session.clear()
    return "Déconnecté.", 200


@app.route('/health')
def health():
    """Endpoint de vérification de santé (utilisé par Docker Compose)."""
    return jsonify({"status": "ok", "service": "target", "users": list(USERS.keys())}), 200


# ─── Point d'entrée ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(os.getenv("TARGET_APP_PORT", os.getenv("PORT", "8080")))
    print("=" * 60)
    print("  SERVEUR CIBLE VULNÉRABLE – PORT 8080")
    print("  USAGE STRICTEMENT ÉDUCATIF ET EN ENVIRONNEMENT LOCAL")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
