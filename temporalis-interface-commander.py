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
current_window = "input"  # Focus par défaut sur l'input du terminal
last_system_refresh = 0
last_terminal_refresh = 0
input_buffer = ""  # Buffer pour la saisie du terminal
output_lines = []  # Pour stocker les lignes de sortie du terminal
last_directory = ""  # Pour suivre le répertoire actuel du terminal
last_prompt = "$"  # On laisse uniquement le symbole "$" pour le prompt

# Liste des programmes interactifs que nous allons traiter
interactive_programs = ["nano", "vim", "vi", "htop", "less", "more", "man"]

# Fonction pour quitter proprement avec Ctrl+C ou F8
def handle_exit(signum=None, frame=None):
    curses.endwin()
    sys.exit(0)

# Configurer le signal SIGINT pour capturer Ctrl+C
signal.signal(signal.SIGINT, handle_exit)

def create_section(window, height, width, y, x, title):
    """Crée une section avec un titre"""
    section = window.subwin(height, width, y, x)
    section.attron(curses.color_pair(1))  # Couleur verte pour tout le texte
    section.box()
    section.attroff(curses.color_pair(1))
    section.addstr(0, 1, title[:width - 2])  # Limiter le titre à la largeur de la section
    section.refresh()
    return section

def display_system_info(section):
    """Affiche l'utilisation CPU et RAM dans la section spécifiée"""
    section.attron(curses.color_pair(1))  # Couleur verte
    max_y, max_x = section.getmaxyx()
    
    cpu_percents = psutil.cpu_percent(interval=None, percpu=True)  # Utiliser interval=None pour des lectures plus rapides
    ram_usage = psutil.virtual_memory().percent

    section.addstr(1, 1, " " * (max_x - 2))  # Effacer l'ancienne ligne
    for i, cpu_percent in enumerate(cpu_percents):
        bar = '█' * int(cpu_percent / 10)
        section.addstr(i + 1, 1, f"CPU {i+1}: {cpu_percent}% | {bar.ljust(10)}")

    bar_ram = '█' * int(ram_usage / 10)
    section.addstr(len(cpu_percents) + 2, 1, f"RAM usage: {ram_usage}% | {bar_ram.ljust(10)}")

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_directory_contents(section, scroll_pos, directory):
    """Affiche les fichiers et dossiers du répertoire courant du terminal, en vidant la section avant chaque mise à jour"""
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    max_y, max_x = section.getmaxyx()

    # Effacer tout le contenu avant d'afficher les nouveaux fichiers
    section.clear()
    section.box()  # Recréer la bordure après avoir effacé le contenu

    try:
        files = os.listdir(directory)
    except Exception as e:
        files = [f"Error: {e}"]

    files_to_display = files[scroll_pos:scroll_pos + max_y - 2]

    for idx, file in enumerate(files_to_display):
        section.addstr(idx + 1, 1, f"{file.ljust(max_x - 2)}")  # Effacer l'ancienne ligne et afficher le fichier

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_running_processes(section, scroll_pos):
    """Affiche les processus en cours dans la section spécifiée avec défilement"""
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    max_y, max_x = section.getmaxyx()
    
    try:
        processes = [(p.info['pid'], p.info['name']) for p in psutil.process_iter(['pid', 'name'])]
    except Exception as e:
        processes = [(None, f"Error: {e}")]

    processes_to_display = processes[scroll_pos:scroll_pos + max_y - 2]

    for idx, (pid, name) in enumerate(processes_to_display):
        section.addstr(idx + 1, 1, f"{pid}: {name[:20]}".ljust(max_x - 2))  # Affiche et efface l'ancienne ligne

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_datetime(section):
    """Affiche la date et l'heure dans la section 4"""
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    max_y, max_x = section.getmaxyx()

    now = datetime.now().strftime("%H:%M:%S - %d/%m/%Y")
    section.addstr(1, 1, f"{now.ljust(max_x - 2)}")  # Limite l'affichage à la largeur de la section

    section.attroff(curses.color_pair(1))
    section.refresh()

def display_additional_info(section):
    """Affiche les informations supplémentaires avec les touches à utiliser"""
    section.attron(curses.color_pair(1))  # Couleur verte pour le texte
    section.addstr(1, 1, "F1 = System Info")
    section.addstr(2, 1, "F2 = Files/Directories")
    section.addstr(3, 1, "F3 = Running Processes")
    section.addstr(4, 1, "F4 = Terminal Input")
    section.addstr(5, 1, "F5 = Terminal Output")
    section.addstr(6, 1, "F6 = Clear Input")
    section.addstr(7, 1, "F7 = Clear Output")
    section.addstr(8, 1, "F8 = Exit Program")
    section.refresh()

def clean_terminal_output(output):
    """Nettoie la sortie du terminal pour supprimer les séquences d'échappement et garder uniquement le symbole $"""
    ansi_escape = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])|[\x07\x0e\x0f]')
    cleaned_output = ansi_escape.sub('', output)

    # Supprime tout sauf le dernier symbole $ (on garde juste le prompt simple)
    cleaned_output = re.sub(r'.*?(\$)', r'\1', cleaned_output)

    return cleaned_output.strip()

def update_terminal_input(section, input_buffer, width):
    """Met à jour l'affichage du texte dans la zone de saisie du terminal sans effacer le titre"""
    section.attron(curses.color_pair(1))
    section.move(1, 1)  # Place le curseur à l'endroit où commence l'input (ligne 1, colonne 1)
    section.clrtoeol()  # Efface la ligne actuelle, sauf la bordure
    section.addstr(1, 1, input_buffer.ljust(width - 2))  # Réécrit le buffer dans la zone d'input
    section.attroff(curses.color_pair(1))
    section.refresh()

def clear_terminal_output(section):
    """Efface le contenu de la section terminal output"""
    global output_lines
    output_lines = []  # Réinitialise les lignes de sortie
    section.clear()  # Efface tout le contenu de la section
    section.box()  # Recrée la bordure après avoir effacé le contenu
    section.refresh()

def run_interactive_program(command):
    """Exécute un programme interactif comme nano, vim, etc., en sortant temporairement de curses"""
    curses.endwin()  # Fermer temporairement curses
    os.system(command)  # Exécuter le programme
    curses.initscr()  # Réinitialiser curses
    curses.curs_set(0)  # Cacher à nouveau le curseur
    curses.start_color()  # Initialiser les couleurs
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)

def main(stdscr):
    global current_window  # Déclarer current_window comme global pour éviter l'erreur
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
    top_section1 = create_section(stdscr, top_height, left_width, 0, 0, "System Info")
    top_section2 = create_section(stdscr, top_height, left_width, 0, left_width, "Files/Directories")
    left_section = create_section(stdscr, bottom_height, left_width, top_height, 0, "Running Processes")
    right_section_output = create_section(stdscr, max_height - 3, right_width, 0, left_width + middle_width, "Terminal Output")
    right_section_input = create_section(stdscr, 3, right_width, max_height - 3, left_width + middle_width, "Terminal Input")

    # Section Date and Time
    bottom_section1 = create_section(stdscr, bottom_height // 2, middle_width, top_height, left_width, "Date and Time")

    # Section Additional Info avec les touches
    bottom_section2 = create_section(stdscr, bottom_height // 2, middle_width, top_height + (bottom_height // 2), left_width, "Additional Info")

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

            # Rafraîchissement toutes les 0.5 secondes pour éviter le clignotement
            if current_time - last_system_refresh >= 0.5:
                display_system_info(top_section1)
                display_datetime(bottom_section1)  # Mise à jour de l'heure
                display_additional_info(bottom_section2)  # Afficher les instructions
                last_system_refresh = current_time

            if current_time - last_terminal_refresh >= 0.5:  # Rafraîchissement du terminal et input
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

                # Gestion des touches F1, F2, F3, F4, F5, F6, F7, F8 pour changer la fenêtre active et les actions
                if key == curses.KEY_F1:
                    current_window = "system_info"
                elif key == curses.KEY_F2:
                    current_window = "files"
                elif key == curses.KEY_F3:
                    current_window = "processes"
                elif key == curses.KEY_F4:
                    current_window = "input"
                elif key == curses.KEY_F5:
                    current_window = "output"
                elif key == curses.KEY_F6:
                    input_buffer = ""  # Efface l'input du terminal
                    update_terminal_input(right_section_input, input_buffer, right_width)
                elif key == curses.KEY_F7:
                    clear_terminal_output(right_section_output)  # Vider la sortie du terminal
                elif key == curses.KEY_F8:
                    handle_exit(None, None)  # Ferme le programme proprement

                # Gérer la saisie dans "Terminal Input" lorsque sélectionné
                if current_window == "input":
                    if key in [curses.KEY_ENTER, 10]:  # Touche Entrée
                        if input_buffer.strip():  # Vérifie si la commande n'est pas vide
                            command = input_buffer.strip().split()[0]  # Récupère juste la commande (sans arguments)
                            if command in interactive_programs:  # Si c'est un programme interactif
                                run_interactive_program(input_buffer)  # Exécute le programme
                            else:
                                os.write(master, (input_buffer + "\n").encode())  # Envoie la commande au terminal
                        input_buffer = ""  # Réinitialise le buffer après exécution de la commande
                    elif key in [127, 8]:  # Touche Retour arrière (Backspace)
                        if len(input_buffer) > 0:
                            input_buffer = input_buffer[:-1]  # Supprimer le dernier caractère du buffer
                    elif 32 <= key <= 126:  # Caractères imprimables
                        input_buffer += chr(key)

                    # Afficher le contenu saisi et le remplacer par des espaces si nécessaire
                    update_terminal_input(right_section_input, input_buffer, right_width)

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
