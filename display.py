import sys
import sysv_ipc
import time
import tkinter as tk
from threading import Thread

# Types de commandes de display vers env
COMMANDE_PAUSE = 1
COMMANDE_START = 2
COMMANDE_QUIT = 3
COMMANDE_GROWTH = 4
COMMANDE_GRASS = 5
# Type de message d'env vers display
MSG_STATE =7

def send_command(mq, cmd_type, param=None):
    """ Envoie une commande à env via la MQ """
    if param:
        message = f"{param}".encode()
    else:
        message = "".encode()
    mq.send(message, type=cmd_type)

def update_display(mq, state_label):
    """ Fonction pour lire et afficher l'état de la simulation dans la fenêtre graphique """
    while True:
        try:
            # Lire l'état envoyé par env via MQ
            state, t = mq.receive(type=MSG_STATE)
            state_str = state.decode()
            
            # Mise à jour du texte dans la fenêtre graphique
            state_label.config(text=state_str)

        except sysv_ipc.BusyError:
            time.sleep(0.1) 
            continue

def main():
    # Connexion à la MQ de env
    try:
        mq = sysv_ipc.MessageQueue(1234)
    except sysv_ipc.ExistentialError:
        print("Erreur : Impossible de se connecter à la Message Queue. Assurez-vous que env.py est en cours d'exécution.", flush=True)
        sys.exit(1)

    # Initialisation de la fenêtre tkinter
    root = tk.Tk()
    root.title("Simulation Circle of Life")

    # Affichage état de la simulation
    state_label = tk.Label(root, text="Chargement de l'état...", font=("Helvetica", 14))
    state_label.pack(padx=10, pady=10)

    # Entrée pour les commandes
    command_entry = tk.Entry(root, font=("Helvetica", 12))
    command_entry.pack(pady=10)

    # Rappel des commandes possibles
    command_hint = tk.Label(root, text="Commandes possibles :\nPAUSE, START, QUIT, GROWTH <valeur>, GRASS <valeur>", font=("Helvetica", 10), anchor="w")
    command_hint.pack(pady=10, padx=10)

    def on_command_submit():
        user_input = command_entry.get().strip()
        if user_input.lower() == "pause":
            send_command(mq, COMMANDE_PAUSE)
        elif user_input.lower() == "start":
            send_command(mq, COMMANDE_START)
        elif user_input.lower() == "quit":
            send_command(mq, COMMANDE_QUIT)
            print("Arrêt de la simulation.")
            root.quit()  # Ferme la fenêtre tkinter
        elif user_input.lower().startswith("growth"):
            try:
                _, value = user_input.split()
                send_command(mq, COMMANDE_GROWTH, value)
            except ValueError:
                print("Commande GROWTH invalide. Format attendu : 'GROWTH <valeur>'", flush=True)
        elif user_input.lower().startswith("grass"):
            try:
                _, value = user_input.split()
                send_command(mq, COMMANDE_GRASS, value)
            except ValueError:
                print("Commande GRASS invalide. Format attendu : 'GRASS <valeur>'", flush=True)
        else:
            print("Commande invalide. Essayez 'PAUSE', 'START', 'QUIT' ou 'GROWTH <valeur>'", flush=True)

    # Bouton pour envoyer les commandes
    submit_button = tk.Button(root, text="Envoyer la commande", command=on_command_submit)
    submit_button.pack(pady=10)

    # Lecture de l'état dans un thread séparé pour ne pas bloquer l'interface graphique
    display_thread = Thread(target=update_display, args=(mq, state_label), daemon=True)
    display_thread.start()

    # Lancer la fenêtre tkinter
    root.mainloop()

if __name__ == "__main__":
    main()
