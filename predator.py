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

# Configuration
HOST = "127.0.0.1"
PORT_SOCKET = 5001
PORT_MANAGER = 5002
AUTHKEY = b"memoirepartagee"

# Definition prédateur
class PredatorState:
    energy: float = 0.0
    active: bool = False
    alive: bool = True

# Variables activité/reproduction
H = 5.0  
R = 15.0
ENERGY_LOST_TICK = 0.6    # énergie perdue par tick
EAT_GAIN = 6.0          # énergie gagnée
REPRO_COST = 10.0        # énergie perdue quand reproduction

class WorldManager(BaseManager):
    pass

WorldManager.register("get_world")
WorldManager.register("get_huntable")
WorldManager.register("get_lock")

# Socket join
def join_simulation(role: str = "PREDATOR") -> None:
    """
    Se connecte à env via TCP et envoie 'JOIN PREDATOR <pid>'.
    """
    pid = os.getpid()
    msg = f"{role} (PID : {pid}) : JOINED\n".encode()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT_SOCKET))
        s.sendall(msg)

        resp = s.recv(64).decode(errors="replace").strip()

    print(f"[predator:{pid}] joined env on {HOST}:{PORT_SOCKET}", flush=True)

    if resp != "OK":
        raise Exception("Join request rejected by env")

# Memory shared connection
def connect_shared_memory(pid: int):
    memoire_partagee = WorldManager(address=(HOST, PORT_MANAGER), authkey=AUTHKEY)
    memoire_partagee.connect()
    print(f"[PREDATOR:{pid}] connected to shared memory : {HOST}:{PORT_MANAGER}",flush=True)
    return (memoire_partagee.get_world(),
            memoire_partagee.get_huntable(),
            memoire_partagee.get_lock())
    print(f"[predator:{pid}] huntable type={type(huntable)} repr={repr(huntable)}", flush=True)
    
def predator_tick(st: PredatorState, world, huntable, world_lock) -> None:
    pid = os.getpid()

    # 1) métabolisme
    st.energy -= ENERGY_LOST_TICK
    energy_rounded = round(st.energy, 1)
    print(f"[predator:{pid}] energy : {energy_rounded}", flush=True)

    # 3) manger si faim
    if st.energy < H:
        if st.active == False:
            st.active = True
            print(f"[predator:{pid}] is now active : looking to hunt", flush=True)
        world_lock.acquire()
        try:
            pass # À implémenter : chercher une proie à manger
        finally:
            world_lock.release()

    # 4) reproduction si énergie haute
    if st.energy >= R:
        print(f"[predator:{pid}] can reproduce", flush=True)
        world_lock.acquire()
        try:
            if world["predators"] >= 2: # au moins 2 individus pour reproduire
                st.energy -= REPRO_COST
                # population +1 dans mémoire partagée --> a faire
        finally:
            world_lock.release()

    # 5) mort naturelle
    if st.energy <= 0:
        predator_dead(st, world, huntable, world_lock, reason=1, pid=pid)

# Gestion de la mort du prédateur
def predator_dead(st: PredatorState, world, huntable, world_lock, reason, pid: int) -> None:
    st.alive = False
    if reason == 1:
        print(f"[predator:{pid}] died because of energy<=0", flush=True)
    elif reason == 2:
        print(f"[predator:{pid}] env is quitting, connexion closed", flush=True)
    world_lock.acquire()
    try:
        world["predators"] = world.get("predators") - 1
    finally:
        world_lock.release()
    os.kill(pid, signal.SIGTERM)
    

def main():
    st = PredatorState()
    pid = os.getpid()

    #Join via la socket
    try:
        join_simulation("PREDATOR")
    except Exception as e:
        print(f"[predator] cannot join env: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Connexion à la mémoire partagée via Manager
    try:
        world, huntable, world_lock = connect_shared_memory(pid)
    except Exception as e:
        print(f"[predator:{pid}] cannot connect to shared memory: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Inscription dans le monde
    world_lock.acquire()
    try:
        world["predators"] = world.get("predators") + 1
    finally:
        world_lock.release()
    
    st.energy = random.uniform(8.0, 14.0) #Initial energy

    #Boucle principale
    try:
        while st.alive:
            time.sleep(1.0)
            predator_tick(st, world, huntable, world_lock)

    except KeyboardInterrupt:
        print(f"[predator:{pid}] interrupted by user", flush=True)
        
    except Exception as e:
        print(f"[predator:{pid}] error: {e}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
