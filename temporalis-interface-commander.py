import curses
import os
import pty
import sys
import tty
import termios
import psutil
import signal
import select
import re
import time
from datetime import datetime

# Variables globales pour le défilement et la fenêtre active
file_scroll_pos = 0
process_scroll_pos = 0
current_window = "files"
last_system_refresh = 0
last_terminal_refresh = 0
input_buffer = ""  # Buffer pour la saisie du terminal
output_lines = []  # Pour stocker les lignes de sortie du terminal
last_directory = ""  # Pour suivre le répertoire actuel du terminal
last_prompt = "$"  # On laisse uniquement le symbole "$" pour le prompt

# Fonction pour quitter proprement avec Ctrl+C
def handle_exit(signum, frame):
    curses.endwin()
    sys.exit(0)

# Configurer le signal SIGINT pour capturer Ctrl+C
signal.signal(signal.SIGINT, handle_exit)

def create_section(window, height, width, y, x, title, active=False):
    """Crée une section avec ou sans surbrillance selon l'état actif"""
    section = window.subwin(height, width, y, x)
    section.attron(curses.color_pair(1))  # Couleur verte pour tout le texte
    section.box()
    section.attroff(curses.color_pair(1))
    section.addstr(0, 1, title[:width - 2])  # Limiter le titre à la largeur de la section
    return section

def display_system_info(section):
    """Affiche l'utilisation CPU et RAM dans la section spécifiée"""
    section.clear()
    section.box()
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    section.addstr(0, 1, "System Info")  # Affiche le titre de la section

    cpu_percents = psutil.cpu_percent(interval=None, percpu=True)  # Utiliser interval=None pour des lectures plus rapides
    ram_usage = psutil.virtual_memory().percent

    for i, cpu_percent in enumerate(cpu_percents):
        bar = '█' * int(cpu_percent / 10)
        section.addstr(i + 1, 1, f"CPU {i+1}: {cpu_percent}% | {bar.ljust(10)}")

    bar_ram = '█' * int(ram_usage / 10)
    section.addstr(len(cpu_percents) + 2, 1, f"RAM usage: {ram_usage}% | {bar_ram.ljust(10)}")

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_directory_contents(section, scroll_pos, directory):
    """Affiche les fichiers et dossiers du répertoire courant du terminal"""
    section.clear()
    section.box()
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    section.addstr(0, 1, "Files/Directories")  # Affiche le titre de la section

    try:
        files = os.listdir(directory)
    except Exception as e:
        files = [f"Error: {e}"]

    max_lines = section.getmaxyx()[0] - 2  # Moins l'espace pour le titre et la bordure
    files_to_display = files[scroll_pos:scroll_pos + max_lines]

    for idx, file in enumerate(files_to_display):
        section.addstr(idx + 1, 1, file[:section.getmaxyx()[1] - 2])  # Ajuste la largeur à la section

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_running_processes(section, scroll_pos):
    """Affiche les processus en cours dans la section spécifiée avec défilement"""
    section.clear()
    section.box()
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    section.addstr(0, 1, "Running Processes")  # Affiche le titre de la section

    try:
        processes = [(p.info['pid'], p.info['name']) for p in psutil.process_iter(['pid', 'name'])]
    except Exception as e:
        processes = [(None, f"Error: {e}")]

    max_lines = section.getmaxyx()[0] - 2  # Moins l'espace pour le titre et la bordure
    processes_to_display = processes[scroll_pos:scroll_pos + max_lines]

    for idx, (pid, name) in enumerate(processes_to_display):
        section.addstr(idx + 1, 1, f"{pid}: {name[:20]}"[:section.getmaxyx()[1] - 2])  # Ajuste la largeur à la section

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_datetime(section):
    """Affiche la date et l'heure dans la section 4"""
    section.clear()
    section.box()
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    section.addstr(0, 1, "Date and Time")  # Affiche le titre de la section

    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    section.addstr(1, 1, now[:section.getmaxyx()[1] - 2])  # Limite l'affichage à la largeur de la section

    section.attroff(curses.color_pair(1))
    section.refresh()

def clean_terminal_output(output):
    """Nettoie la sortie du terminal pour supprimer les séquences d'échappement et garder uniquement le symbole $"""
    ansi_escape = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])|[\x07\x0e\x0f]')
    cleaned_output = ansi_escape.sub('', output)

    # Supprime tout sauf le dernier symbole $ (on garde juste le prompt simple)
    cleaned_output = re.sub(r'.*?(\$)', r'\1', cleaned_output)

    return cleaned_output.strip()

def change_window(window_name):
    """Change la fenêtre active en fonction du nom donné"""
    global current_window
    current_window = window_name

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()  # Initialiser les couleurs
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)  # Couleur verte pour tout le texte

    stdscr.clear()

    max_height, max_width = stdscr.getmaxyx()

    top_height = max_height // 2
    bottom_height = max_height - top_height

    left_width = max_width // 4
    middle_width = max_width // 4
    right_width = max_width // 2

    global file_scroll_pos, process_scroll_pos, last_system_refresh, last_terminal_refresh, input_buffer, output_lines, last_directory, last_prompt

    # Crée les sections une seule fois
    top_section1 = create_section(stdscr, top_height, left_width, 0, 0, "System Info", active=False)
    top_section2 = create_section(stdscr, top_height, left_width, 0, left_width, "Files/Directories", active=True)
    left_section = create_section(stdscr, bottom_height, left_width, top_height, 0, "Running Processes", active=False)
    right_section_output = create_section(stdscr, max_height - 3, right_width, 0, left_width + middle_width, "Terminal Output", active=False)
    right_section_input = create_section(stdscr, 3, right_width, max_height - 3, left_width + middle_width, "Terminal Input", active=False)

    # Sections 4 et 5 : maintenant l'une en dessous de l'autre
    bottom_section1 = create_section(stdscr, bottom_height // 2, middle_width, top_height, left_width, "Date and Time", active=False)
    bottom_section2 = create_section(stdscr, bottom_height // 2, middle_width, top_height + (bottom_height // 2), left_width, "Additional Info", active=False)

    stdscr.refresh()

    # Crée un pseudo-terminal (pty) pour le terminal
    master, slave = pty.openpty()
    shell = os.environ.get('SHELL', '/bin/bash')
    pid = os.fork()

    if pid == 0:
        # Dans le processus enfant
        os.setsid()  # Crée une nouvelle session pour le processus enfant

        # Duplique le pty sur les descripteurs standard
        os.dup2(slave, sys.stdin.fileno())
        os.dup2(slave, sys.stdout.fileno())
        os.dup2(slave, sys.stderr.fileno())
        os.close(master)
        os.close(slave)
        os.execlp(shell, shell)

    # Dans le processus parent, surveille le terminal
    os.close(slave)
    tty.setraw(master)
    curses.noecho()

    try:
        while True:
            current_time = time.time()

            # Rafraîchissement plus rapide pour la section système (0.2 seconde)
            if current_time - last_system_refresh >= 0.2:
                display_system_info(top_section1)
                display_datetime(bottom_section1)  # Mise à jour de l'heure
                last_system_refresh = current_time

            if current_time - last_terminal_refresh >= 0.1:  # Rafraîchissement plus rapide pour le terminal et input
                rlist, _, _ = select.select([master], [], [], 0.1)
                if master in rlist:
                    output = os.read(master, 1024).decode('utf-8', errors='ignore')

                    # Nettoyer la sortie et garder uniquement le symbole $
                    output_cleaned = clean_terminal_output(output)

                    # Stocker la sortie dans les lignes
                    output_lines += output_cleaned.splitlines()

                    # Limite la taille de l'affichage du terminal à la hauteur disponible
                    max_output_lines = right_section_output.getmaxyx()[0] - 2
                    if len(output_lines) > max_output_lines:
                        output_lines = output_lines[-max_output_lines:]

                    # Affichage de la sortie du terminal
                    right_section_output.clear()
                    right_section_output.box()
                    right_section_output.attron(curses.color_pair(1))
                    for idx, line in enumerate(output_lines):
                        right_section_output.addstr(idx + 1, 1, line[:right_width - 2])
                    
                    right_section_output.attroff(curses.color_pair(1))
                    right_section_output.refresh()

                last_terminal_refresh = current_time

            # Mise à jour dynamique du contenu de "Files/Directories"
            current_directory = os.readlink(f'/proc/{pid}/cwd')  # Utilisation du répertoire du terminal
            if current_directory != last_directory:
                file_scroll_pos = 0  # Réinitialise le défilement si le répertoire change
                last_directory = current_directory

            display_directory_contents(top_section2, file_scroll_pos, current_directory)

            # Affichage des processus
            display_running_processes(left_section, process_scroll_pos)

            # Lire l'entrée utilisateur (si aucune touche n'est appuyée, continue la boucle)
            rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
            if rlist:
                key = stdscr.getch()

                # Gestion des touches F1, F2, F3, F4 pour changer la fenêtre active
                if key == curses.KEY_F1:
                    change_window("system_info")
                elif key == curses.KEY_F2:
                    change_window("files")
                elif key == curses.KEY_F3:
                    change_window("processes")
                elif key == curses.KEY_F4:
                    change_window("input")

                # Gérer la saisie dans "Terminal Input" lorsque sélectionné
                if current_window == "input":
                    if key in [curses.KEY_ENTER, 10]:  # Touche Entrée
                        os.write(master, (input_buffer + "\n").encode())  # Envoie la commande au terminal
                        input_buffer = ""  # Réinitialise le buffer après exécution de la commande
                    elif key == 127:  # Touche Retour arrière
                        input_buffer = input_buffer[:-1]
                    elif 32 <= key <= 126:  # Caractères imprimables
                        input_buffer += chr(key)

                    # Afficher le contenu saisi
                    right_section_input.clear()
                    right_section_input.box()
                    right_section_input.attron(curses.color_pair(1))
                    right_section_input.addstr(1, 1, input_buffer[:right_width - 2])
                    right_section_input.attroff(curses.color_pair(1))
                    right_section_input.refresh()

                # Défilement dans la section fichiers ou processus
                if key == curses.KEY_DOWN and current_window == "files":
                    file_scroll_pos += 1  # Défilement vers le bas dans la liste des fichiers
                elif key == curses.KEY_UP and current_window == "files":
                    file_scroll_pos = max(0, file_scroll_pos - 1)  # Défilement vers le haut dans la liste des fichiers
                elif key == curses.KEY_DOWN and current_window == "processes":
                    process_scroll_pos += 1  # Défilement vers le bas dans la liste des processus
                elif key == curses.KEY_UP and current_window == "processes":
                    process_scroll_pos = max(0, process_scroll_pos - 1)  # Défilement vers le haut dans la liste des processus

            stdscr.refresh()

    except KeyboardInterrupt:
        # Gérer proprement la fermeture avec Ctrl+C
        curses.endwin()

curses.wrapper(main)

