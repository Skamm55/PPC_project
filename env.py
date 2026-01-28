import sys
import socket
import time
from multiprocessing.managers import BaseManager, DictProxy, ListProxy, AcquirerProxy
import multiprocessing as mp
import sysv_ipc
import signal
import os
import threading
import subprocess

# Configuration
HOST = "127.0.0.1"
PORT_SOCKET = 5001
PORT_MANAGER = 5002
MQ_KEY = 1234  # Clé pour MessageQueue
AUTHKEY = b"memoirepartagee"

# Liste des sockets clients (prédateurs/proies) (evite que la socket se close a la fin de la fonction)
CLIENTS = []

# Types de commandes display vers env
COMMANDE_PAUSE = 1
COMMANDE_START = 2
COMMANDE_QUIT = 3
COMMANDE_GROWTH = 4
COMMANDE_GRASS = 5
# Types de message d'env vers display
MSG_STATE = 7

#Remote Manager shared data (env <-> prey/pred)
world = {
    "preys": 0,
    "predators": 0,
    "grass_plant": 40,
    "grass_unity": 0.0,
    "drought": 0,
    "drought_duration": 0,
    "pause": 0,
    "grass_growth": 0.1,
    "quit": 0
}

huntable = []  # PIDs des proies chassables (energy < H)
reproducible_preys = []  # PIDs des proies reproductibles (energy > R)
reproducible_predators = []  # PIDs des prédateurs reproductibles (energy > R)
world_lock = mp.Lock()

def get_world():
    return world

def get_huntable():
    return huntable

def get_reproducible_preys():
    return reproducible_preys

def get_reproducible_predators():
    return reproducible_predators

def get_lock():
    return world_lock

class WorldManager(BaseManager):
    pass

WorldManager.register("get_world", callable=get_world, proxytype=DictProxy)
WorldManager.register("get_huntable", callable=get_huntable, proxytype=ListProxy)
WorldManager.register("get_reproducible_preys", callable=get_reproducible_preys, proxytype=ListProxy)
WorldManager.register("get_reproducible_predators", callable=get_reproducible_predators, proxytype=ListProxy)
WorldManager.register("get_lock", callable=get_lock, proxytype=AcquirerProxy)


# Variables locales statiques
DROUGHT_DURATION = 15
DROUGHT_PERIOD = 30

# Fonctions message queue
def mq_poll_commands(mq: sysv_ipc.MessageQueue):
    while True:
        try:
            msg, t = mq.receive(block=False)
        except sysv_ipc.BusyError:
            return  # plus de messages
        except Exception as e:
            print("[env] Erreur dans la MQ:", e, flush=True)
            return

        text = msg.decode(errors="replace").strip()

        world_lock.acquire()
        try:
            if t == COMMANDE_PAUSE:
                world["pause"] = 1

            elif t == COMMANDE_START:
                world["pause"] = 0

            elif t == COMMANDE_QUIT:
                world["quit"] = 1
                return

            elif t == COMMANDE_GROWTH:
                new_growth = msg.decode().strip()
                try:
                    world["grass_growth"] = float(new_growth)
                    print(f"[env] Croissance de l'herbe définie à {new_growth}", flush=True)
                except ValueError:
                    pass

            elif t == COMMANDE_GRASS:
                new_grass = msg.decode().strip()
                try:
                    value = int(new_grass)
                    world["grass_plant"] = value
                    print(f"[env] Nombre de plants d'herbe défini à {value} unités", flush=True)
                except ValueError:
                    pass
            else:
                pass
        finally:
            world_lock.release()

# Envoi état via MQ
def mq_send_state(mq: sysv_ipc.MessageQueue):
    world_lock.acquire()
    try:
        grass_unity_rounded = round(float(world["grass_unity"]), 1)
        st = (
            f"predateurs={world['predators']} | "
            f"proies={world['preys']} | "
            f"plants d'herbe={world['grass_plant']} | "
            f"unités d'herbe={grass_unity_rounded} | "
            f"sécheresse={world['drought']} | "
            f"pause={world['pause']} | "
            f"coef pousse={world['grass_growth']}"
        )
    finally:
        world_lock.release()
    try:
        mq.send(st.encode(), type=MSG_STATE)
    except Exception as e:
        print("[env] MQ send error:", e, flush=True)

# Socket server (join predator/prey)
def setup_server_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT_SOCKET))
    s.listen(20)  # backlog
    s.settimeout(0.2)  # pour ne pas bloquer la boucle principale
    return s

def socket_accept_one(server_socket: socket.socket):
    try:
        conn, addr = server_socket.accept()
    except socket.timeout:
        return
    except Exception as e:
        print("[env] socket accept error:", e, flush=True)
        return

    try:
        data = conn.recv(1024)
        if not data:
            return

        line = data.decode(errors="replace").strip()
        conn.sendall(b"OK")

        print(f"[env] SOCKET_JOIN | from={addr[0]}:{addr[1]} | {line}", flush=True)

        CLIENTS.append(conn)  # garder la connexion ouverte

    except Exception as e:
        print("[env] join socket error:", e, flush=True)
        conn.close()

# Lecture non bloquante de toutes les connexions clients
def socket_read_all():
    dead_conns = []

    for conn in CLIENTS:
        conn.settimeout(0.0)        # lecture non bloquante
        try:
            data = conn.recv(1024)
        except OSError:
            continue
        if not data:               # client déconnecté
            dead_conns.append(conn)
            continue
        msg = data.decode().strip()
        if msg:
            print(f"[env] {msg}")
        conn.settimeout(None)

    for conn in dead_conns:
        CLIENTS.remove(conn)
        conn.close()

# Close toutes les sockets clients proprement
def stop_everyone():
    for conn in CLIENTS:
        try:
            conn.sendall(b"STOP\n")
        except Exception:
            pass
    time.sleep(1) # sinon socket se ferme avant que prey/predator reçoivent STOP


# Appel de la sécheresse périodique
def drought_call():
    global drought_timer

    world_lock.acquire()
    try:
        if world["quit"] == 1:
            return

        if world["drought"] == 0:
            world["drought"] = 1
            world["drought_duration"] = DROUGHT_DURATION
            print(f"[env] Sécheresse déclenchée | durée : {DROUGHT_DURATION}s", flush=True)
    finally:
        world_lock.release()
    # reprogrammation → périodique
    drought_timer = threading.Timer(DROUGHT_PERIOD, drought_call)
    drought_timer.daemon = True
    drought_timer.start()

# Simulation tick :
def simulation_tick():
    world_lock.acquire()
    try:
        # Gestion de la sécheresse
        if world["drought"] == 1:  # Si la sécheresse est activée
            if world["drought_duration"] > 0:
                world["drought_duration"] -= 1  # Décrémente la durée restante
            else:
                world["drought"] = 0
                print("[env] Sécheresse terminée", flush=True)

        if world["drought"] == 0 and world["pause"] == 0:
            # Calcul de la croissance totale basée sur le nombre de plants
            growth_increment = (world["grass_plant"] - int(world["grass_unity"])) * world["grass_growth"]

            # Si l'herbe actuelle est inférieure à la cible
            if world["grass_unity"] < world["grass_plant"]:
                # Ajouter la croissance à l'herbe actuelle
                world["grass_unity"] += growth_increment

                # Si l'herbe dépasse la quantité cible, on réajuste pour ne pas dépasser
                if world["grass_unity"] > world["grass_plant"]:
                    world["grass_unity"] = world["grass_plant"]
    finally:
        world_lock.release()

    # Reproduction des proies
    if len(reproducible_preys) >= 2:
        print(f"[env] Reproduction des proies possible, individus reproductibles : {len(reproducible_preys)}", flush=True)
        # Création d'une nouvelle proie
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "wsl", "--cd", "/home/maksim_npl/PPC_project", sys.executable, "prey.py"], cwd="/mnt/c")
            print(f"[env] Une nouvelle proie est née !", flush=True)
            reproducible_preys.clear()  # Réinitialiser la liste après reproduction
        except Exception as e:
            print(f"[env] Erreur lors de la création d'une nouvelle proie : {e}", flush=True)
    
    # Reproduction des prédateurs
    if len(reproducible_predators) >= 2:
        print(f"[env] Reproduction des prédateurs possible, individus reproductibles : {len(reproducible_predators)}", flush=True)
        # Création d'un nouveau prédateur
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "wsl", "--cd", "/home/maksim_npl/PPC_project", sys.executable, "predator.py"], cwd="/mnt/c")
            print(f"[env] Un nouveau prédateur est né !", flush=True)
            reproducible_predators.clear()  # Réinitialiser la liste après reproduction
        except Exception as e:
            print(f"[env] Erreur lors de la création d'un nouveau prédateur : {e}", flush=True)

# Main :
def main():
    global drought_timer

    # Message Queue avec display
    mq = sysv_ipc.MessageQueue(MQ_KEY, sysv_ipc.IPC_CREAT)
    server_socket = setup_server_socket()

    # mémoire partagée avec proies/prédateurs (remote manager) : serveur
    memoire_partagee_srv = WorldManager(address=(HOST, PORT_MANAGER), authkey=AUTHKEY)
    server = memoire_partagee_srv.get_server()

    # serveur manager en thread daemon pour ne pas bloquer le tick de env
    memoire_partagee_thread = threading.Thread(target=server.serve_forever, daemon=True)
    memoire_partagee_thread.start()

    print(
        f"[env] READY | MQ (key={MQ_KEY}) | Socket={HOST}:{PORT_SOCKET} | RemoteManager={HOST}:{PORT_MANAGER}",
        flush=True
    )

    # sécheresse périodique
    drought_timer = threading.Timer(DROUGHT_PERIOD, drought_call)
    drought_timer.daemon = True
    drought_timer.start()

    # Calcul temps initial
    last_state = time.time()

    try:
        while True:
            mq_poll_commands(mq)

            world_lock.acquire()
            try:
                if world["quit"] == 1:
                    break
                paused = (world["pause"] == 1)
            finally:
                world_lock.release()

            socket_accept_one(server_socket)
            socket_read_all()

            if not paused:
                simulation_tick()

            now = time.time()
            if now - last_state >= 0.5:
                mq_send_state(mq)
                last_state = now

            time.sleep(1)
    except KeyboardInterrupt:
        print("[env] Interrompu par l'utilisateur (ctrl+c)", flush=True)

    finally:
        print("[env] Fermeture de l'environnement...", flush=True)
        try:
            if drought_timer is not None:
                drought_timer.cancel()
        except Exception:
            pass
        try:
            stop_everyone()
            for c in CLIENTS:
                try: c.close()
                except: pass
            server_socket.close()
        except Exception:
            pass
        try:
            mq.remove()
        except Exception:
            pass

        print("[env] Env arrêté et nettoyé", flush=True)

if __name__ == "__main__":
    main()
