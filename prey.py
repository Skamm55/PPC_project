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

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT_SOCKET))
        s.sendall(msg)

        resp = s.recv(64).decode(errors="replace").strip()

    print(f"[prey:{pid}] joined env on {HOST}:{PORT_SOCKET}", flush=True)

    if resp != "OK":
        s.close()
        raise Exception("Join request rejected by env")
    
    return s

# Memory shared connection
def connect_shared_memory(pid: int):
    memoire_partagee = WorldManager(address=(HOST, PORT_MANAGER), authkey=AUTHKEY)
    memoire_partagee.connect()
    print(f"[PREY:{pid}] connected to shared memory : {HOST}:{PORT_MANAGER}",flush=True)
    return (memoire_partagee.get_world(),
            memoire_partagee.get_huntable(),
            memoire_partagee.get_reproducible_preys(),
            memoire_partagee.get_reproducible_predators(),
            memoire_partagee.get_lock())
    print(f"[prey:{pid}] huntable type={type(huntable)} repr={repr(huntable)}", flush=True)

def prey_tick(st: PreyState, world, huntable, reproducible_preys, world_lock) -> None:
    pid = os.getpid()

    # 1) métabolisme
    st.energy -= ENERGY_LOST_TICK
    energy_rounded = round(st.energy, 1)
    print(f"[prey:{pid}] energy : {energy_rounded}", flush=True)
    # cooldown reproduction
    if st.reproduction_cooldown > 0:
        st.reproduction_cooldown -= 1

    # 2) chassable si énergie < H
    if st.energy < H:
        world_lock.acquire()
        try:
            if pid not in huntable:
                huntable.append(pid)
                print(f"[prey:{pid}] is now huntable | huntable list: {list(huntable)}", flush=True)
        finally:
            world_lock.release()
    if st.energy > H:
        world_lock.acquire()
        try:
            if pid in huntable:
                huntable.remove(pid)
                print(f"[prey:{pid}] is no longer huntable | huntable list: {list(huntable)}", flush=True)
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
                print(f"[prey:{pid}] eats {EAT_AMOUNT} units of grass | new grass unity: {rounded_grass} | gains {EAT_GAIN} energy from eating | new energy: {energy_rounded}", flush=True)
        finally:
            world_lock.release()

    # 4) reproduction si énergie haute
    if st.energy >= R and st.reproduction_cooldown == 0:
        print(f"[prey:{pid}] can reproduce", flush=True)
        world_lock.acquire()
        try:
            if pid not in reproducible_preys:
                reproducible_preys.append(pid)
                print(f"[prey:{pid}] added to reproducible preys list", flush=True)
                print(f"[prey:{pid}] reproducible preys list: {list(reproducible_preys)}", flush=True)
                st.reproduction_cooldown = REPRO_COOLDOWN  # reset cooldown
        finally:
            world_lock.release()
    elif st.energy < R:
        world_lock.acquire()
        try:
            if pid in reproducible_preys:
                reproducible_preys.remove(pid)
                print(f"[prey:{pid}] removed from reproducible preys list", flush=True)
        finally:
            world_lock.release()

    # 5) mort naturelle
    if st.energy <= 0:
        st.alive = False  

def main():
    st = PreyState()
    pid = os.getpid()
    reason = ""

    #Join via la socket
    try:
        s = join_simulation("PREY")
    except Exception as e:
        print(f"[prey] cannot join env: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Connexion à la mémoire partagée via Manager
    try:
        world, huntable, reproducible_preys, reproducible_predators, world_lock = connect_shared_memory(pid)
    except Exception as e:
        print(f"[prey:{pid}] cannot connect to shared memory: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Inscription dans le monde
    world_lock.acquire()
    try:
        world["preys"] = world.get("preys") + 1
    finally:
        world_lock.release()
    
    st.energy = random.uniform(8.0, 9.0) #Initial energy

    #Boucle principale
    try:
        while st.alive:
            time.sleep(1.0)
            prey_tick(st, world, huntable, reproducible_preys, world_lock)
            s.settimeout(0.0)
            data = s.recv(1024)
            if data:
                if data.decode(errors="replace").strip().startswith("STOP"):
                    reason = "ENV_SHUTDOWN"
                    break
            s.settimeout(None)
        
        if st.alive!=False:
            reason="natural death (energy<=0)"

    except KeyboardInterrupt:
        reason="interrupted by user (ctrl+c)"
        
    except Exception as e:
        print(f"[prey:{pid}] error: {e}", file=sys.stderr, flush=True)
    
    finally:
        print(f"[prey:{pid}] dying because : {reason}", flush=True)
        s.sendall(f"DIED PREY {pid} {reason}\n".encode())
        world_lock.acquire()
        try:
            if pid in huntable:
                huntable.remove(pid)
            if pid in reproducible_preys:
                reproducible_preys.remove(pid)
            world["preys"] = world.get("preys") - 1
        finally:
            world_lock.release()
        s.close()
        os.kill(pid, signal.SIGTERM)


if __name__ == "__main__":
    main()
