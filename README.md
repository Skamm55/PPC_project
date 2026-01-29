# PPC_project

# 🌍 Circle of Life – Simulation concurrente (Python)

## 📌 Description

Ce projet implémente une **simulation concurrente multi-processus** composée de :

- un **environnement central** (`env.py`)
- une **interface graphique** (`display.py`)
- des **processus indépendants** représentant :
  - des proies (`prey.py`)
  - des prédateurs (`predator.py`)

La communication entre processus repose sur :
- des **Message Queues** (entre env et display)
- des **sockets TCP** (entre env et prey/predator)
- une **mémoire partagée** via un **remote manager** (entre env et prey/predator)

---

## 🧰 Prérequis

### 💻 Système
- Linux / Ubuntu  
- Compatible avec **WSL (Windows Subsystem for Linux)**

### 🐍 Python
- Python **3.10** ou supérieur

### 📦 Bibliothèques Python externes

La bibliothèque suivante doit être installée :

    pip install sysv_ipc

---

## ▶️ Exécution du programme

⚠️ **L’ordre de lancement doit impérativement être respect.**

### 1️⃣ Lancer l’environnement

Dans un premier terminal Ubuntu / WSL :

    python3 env.py

➡️ Ce processus doit rester actif pendant toute la durée de la simulation.

---

### 2️⃣ Lancer l’interface graphique

Dans un second terminal :

    python3 display.py

- Une fenêtre graphique s’ouvre
- Cette fenêtre permet d'observer l'évolution de monde au cours de la simulation (population, herbe, sécheresse)
- Cette fenêtre permet de contrôler la simulation (plants d'herbe, coefficient de pousse, start/pause, quitter la simulation)
- Les commandes disponibles et leur utilisation sont expliquées directement dans l’interface

---

### 3️⃣ Ajouter des proies et des prédateurs

Chaque proie ou prédateur correspond à un **processus indépendant**.

Dans des terminaux séparés :

    python3 prey.py
    python3 predator.py

➡️ Chaque processus rejoint automatiquement la simulation.

---

### 4️⃣ Quitter la simulation / Arrêter les processus

La façon la plus propre d'arrêter le processus et de faire la commande **QUIT** dans l'interface graphique

Cependant il est aussi possible d'arrêter manuellement les processus (ctrl+c), les programmes sont pensés pour gérer cette fermeture manuelle.

### 5️⃣ Lecture des données

**Evolution de la population, quantité d'herbe, sécheresse, état du système (pause ou non)** --> fenêtre graphique de `display.py`

**Connexion des individus à l'environnement, naissance par reproduction, mort des individus, début et fin sécheresse** --> terminal de `env.py`

**Evolution de l'énergie d'un individu, du fait qu'il se nourrisse, qu'il puisse se reproduire** --> terminal de `prey.py` ou `predator.py`

## 📝 Remarques

- `env.py` doit **toujours** être lancé avant les autres fichiers
- Il est possible de lancer **plusieurs proies et prédateurs simultanément**
- La reproduction des proies/prédateurs génère de nouveaux terminaux, trop d'individus fonctionnant simultanément peut entrainer un plantage de la simulation.

---

