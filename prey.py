import os
import sys
import time
import socket
import signal
from dataclasses import dataclass
from typing import Optional
from multiprocessing.managers import BaseManager
from multiprocessing import Lock
import random
import errno

# Configuration
HOST = "127.0.0.1"
PORT_SOCKET = 5001
PORT_MANAGER = 5002
AUTHKEY = b"memoirepartagee"

# Definition proie
class PreyState:
    energy: float = 0.0
    active: bool = False
    alive: bool = True
    reproduction_cooldown: int = 15 # 1er cooldown avant de pouvoir se reproduire pour la 1ère fois

# Variables activité/reproduction
H = 5.0  
R = 9.0
ENERGY_LOST_TICK = 0.5   # énergie perdue par tick
EAT_AMOUNT = 3.0      # herbe consommée
EAT_GAIN = 7.0          # énergie gagnée
REPRO_COOLDOWN = 25    # ticks de cooldown après reproduction

class WorldManager(BaseManager):
    pass

WorldManager.register("get_world")
WorldManager.register("get_huntable")
WorldManager.register("get_reproducible_preys")
WorldManager.register("get_reproducible_predators")
WorldManager.register("get_lock")

# Socket join
def join_simulation(role: str = "PREY") -> socket.socket:
    pid = os.getpid()
    msg = f"JOIN {role} {pid}\n".encode()

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((HOST, PORT_SOCKET))
    s.sendall(msg)

    resp = s.recv(64).decode(errors="replace").strip()

    print(f"[proie:{pid}] rejoint env sur {HOST}:{PORT_SOCKET}", flush=True)

    if resp != "OK":
        s.close()
        raise Exception("Join request rejeté par env")
    
    return s

# Memory shared connection
def connect_shared_memory(pid: int):
    memoire_partagee = WorldManager(address=(HOST, PORT_MANAGER), authkey=AUTHKEY)
    memoire_partagee.connect()
    print(f"[proie:{pid}] connectée à la shared memory : {HOST}:{PORT_MANAGER}",flush=True)
    return (memoire_partagee.get_world(),
            memoire_partagee.get_huntable(),
            memoire_partagee.get_reproducible_preys(),
            memoire_partagee.get_reproducible_predators(),
            memoire_partagee.get_lock())

def prey_tick(st: PreyState, world, huntable, reproducible_preys, world_lock) -> None:
    pid = os.getpid()

    # 1) métabolisme
    st.energy -= ENERGY_LOST_TICK
    energy_rounded = round(st.energy, 1)
    print(f"[proie:{pid}] energie : {energy_rounded}", flush=True)
    # cooldown reproduction
    if st.reproduction_cooldown > 0:
        st.reproduction_cooldown -= 1

    # 2) chassable si énergie < H
    if st.energy < H:
        world_lock.acquire()
        try:
            if pid not in huntable:
                huntable.append(pid)
                print(f"[proie:{pid}] est maintenant chassable | huntable list: {list(huntable)}", flush=True)
        finally:
            world_lock.release()
    if st.energy > H:
        world_lock.acquire()
        try:
            if pid in huntable:
                huntable.remove(pid)
                print(f"[proie:{pid}] n'est plus chassable | huntable list: {list(huntable)}", flush=True)
        finally:
            world_lock.release()

    # 3) manger si faim
    if st.energy < H:
        time.sleep(1.5)  # Simuler le temps pour manger (permettre au prédateur d'attraper la proie)
        world_lock.acquire()
        try:
            if world["grass_unity"] >= EAT_AMOUNT:
                world["grass_unity"] -= EAT_AMOUNT
                rounded_grass = round(world["grass_unity"], 1)
                st.energy += EAT_GAIN
                energy_rounded = round(st.energy, 1)
                print(f"[proie:{pid}] a mangé {EAT_AMOUNT} unités d'herbe, son énergie augmente à {energy_rounded}", flush=True)
        finally:
            world_lock.release()

    # 4) reproduction si énergie haute
    if st.energy >= R and st.reproduction_cooldown == 0:
        print(f"[proie:{pid}] peut se reproduire", flush=True)
        world_lock.acquire()
        try:
            if pid not in reproducible_preys:
                reproducible_preys.append(pid)
                print(f"[proie:{pid}] ajoutée à la reproducible preys list", flush=True)
                print(f"[proie:{pid}] reproducible preys list: {list(reproducible_preys)}", flush=True)
                st.reproduction_cooldown = REPRO_COOLDOWN  # reset cooldown
        finally:
            world_lock.release()
    elif st.energy < R:
        world_lock.acquire()
        try:
            if pid in reproducible_preys:
                reproducible_preys.remove(pid)
                print(f"[proie:{pid}] retirée de la reproducible preys list", flush=True)
        finally:
            world_lock.release()

    # 5) mort naturelle
    if st.energy <= 0:
        st.alive = False  

def main():
    st = PreyState()
    pid = os.getpid()
    reason = ""

    # Mort car mangé par predateur
    def est_mange(sig, frame):
        raise SystemExit("MANGÉE par un predateur")

    signal.signal(signal.SIGUSR1, est_mange)

    # Join via la socket
    try:
        s = join_simulation("PREY")
    except Exception as e:
        print(f"[proie] ne peut pas rejoindre env: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Connexion à la mémoire partagée via Manager
    try:
        world, huntable, reproducible_preys, reproducible_predators, world_lock = connect_shared_memory(pid)
    except Exception as e:
        print(f"[proie:{pid}] ne peut pas se connecter à la shared memory: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Inscription dans le monde
    world_lock.acquire()
    try:
        world["preys"] = world.get("preys") + 1
    finally:
        world_lock.release()

    st.energy = random.uniform(8.0, 9.0)  # Initial energy

    # Boucle principale
    try:
        while st.alive:
            # écouter STOP sans bloquer
            try:
                s.settimeout(0.0)
                data = s.recv(1024)  # peut lever Errno 11
                if data and data.decode(errors="replace").strip().startswith("STOP"):
                    reason = "Arrêt de la simulation par env"
                    break

            except OSError as e:
                # Errno 11 = normal en non-bloquant => on ignore
                if e.errno != errno.EAGAIN:
                    pass

            finally:
                s.settimeout(None)

            # tick de vie de la proie
            time.sleep(1.0)
            prey_tick(st, world, huntable, reproducible_preys, world_lock)

        # si on sort car mort "naturelle"
        if reason == "" and (st.alive == False):
            reason = "mort naturelle (énergie inférieure à 0)"

    except KeyboardInterrupt:
        reason = "Interrompu par l'utilisateur (ctrl+c)"

    except Exception as e:
        reason = f"error: {e}"
        print(f"[proie:{pid}] error: {e}", file=sys.stderr, flush=True)

    except SystemExit as e:
        reason = str(e)

    finally:
        if reason == "":
            reason = "INCONNUE"

        print(f"[prey:{pid}] est mort, raison : {reason}", flush=True)

        # prévenir env (ne jamais planter dans le cleanup)
        try:
            s.sendall(f"PROIE {pid} est MORTE, raison : {reason}\n".encode())
        except Exception:
            pass

        # cleanup world (protégé)
        try:
            if reason != "Arrêt de la simulation par env" and reason != "MANGÉE par un predateur":
                world_lock.acquire()
                try:
                    if pid in huntable:
                        huntable.remove(pid)
                    if pid in reproducible_preys:
                        reproducible_preys.remove(pid)
                    world["preys"] = world.get("preys") - 1
                finally:
                    world_lock.release()
        except Exception:
            pass

        try:
            s.close()
        except Exception:
            pass

        sys.exit(0)


if __name__ == "__main__":
    main()

