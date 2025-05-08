import datetime
import json
import os
import queue
import random
import threading
import struct
import subprocess
import sys
import time
import webbrowser
from ctypes import POINTER, cast
from threading import Thread

import simpleaudio as sa
import vosk
import yaml
from comtypes import CLSCTX_ALL
from fuzzywuzzy import fuzz
from pycaw.pycaw import (
    AudioUtilities,
    IAudioEndpointVolume
)
from rich import print
import sounddevice as sd
import numpy as np
from flask import Flask, render_template, jsonify
import pyautogui
import pygetwindow as gw

import config
import tts
# Импортируем модуль пользовательских команд
import custom_commands

app = Flask(__name__)

# Constants
CDIR = os.getcwd()
VA_CMD_LIST = yaml.safe_load(
    open('commands.yaml', 'rt', encoding='utf8'),
)

# Добавляем пользовательские команды к списку команд
VA_CMD_LIST.update(custom_commands.command_manager.get_command_phrases())

# VOSK setup
model = vosk.Model("model_small")
samplerate = 16000
device = 1  # Microphone device
kaldi_rec = vosk.KaldiRecognizer(model, samplerate)
q = queue.Queue()

# Global state variables
is_listening = True
current_status = "Готов к работе"
last_command = None
is_active = False
active_until = 0  # Timestamp when active listening should end
ACTIVE_WINDOW = 10  # Seconds to stay active after wake word

# Wake words and stop phrases
WAKE_WORDS = ["джарвис", "jarvis", "джарвиз", "жарвис"]
STOP_WORDS = [
    "перестань слушать", "отдыхай", "замолчи", "стоп", 
    "джарвис отдыхай", "джарвис стоп", "джарвис замолчи"
]

# Print available audio devices
print("\nДоступные аудиоустройства:")
print(sd.query_devices())
print("\nТекущее устройство:", device)

def normalize_text(text):
    """Normalize text for better comparison"""
    text = text.lower()
    text = ' '.join(text.split())
    text = ''.join(c for c in text if c.isalnum() or c.isspace())
    return text

def find_best_match(text, commands):
    """Find best matching command"""
    text = normalize_text(text)
    best_match = None
    best_score = 0
    
    for cmd, variants in commands.items():
        for variant in variants:
            variant = normalize_text(variant)
            ratio = fuzz.ratio(text, variant)
            partial_ratio = fuzz.partial_ratio(text, variant)
            token_sort_ratio = fuzz.token_sort_ratio(text, variant)
            
            score = max(ratio, partial_ratio, token_sort_ratio)
            
            if score > best_score:
                best_score = score
                best_match = (cmd, variant, score)
    
    return best_match

def play(phrase, wait_done=True):
    """Play sound response"""
    filename = f"{CDIR}\\sound\\"

    if phrase == "greet":
        filename += f"greet{random.choice([1, 2, 3])}.wav"
    elif phrase == "ok":
        filename += f"ok{random.choice([1, 2, 3])}.wav"
    elif phrase == "not_found":
        filename += "not_found.wav"
    elif phrase == "thanks":
        filename += "thanks.wav"
    elif phrase == "run":
        filename += "run.wav"
    elif phrase == "stupid":
        filename += "stupid.wav"
    elif phrase == "ready":
        filename += "ready.wav"
    elif phrase == "off":
        filename += "off.wav"

    wave_obj = sa.WaveObject.from_wave_file(filename)
    play_obj = wave_obj.play()

    if wait_done:
        play_obj.wait_done()

def q_callback(indata, frames, time, status):
    """Audio callback for VOSK"""
    if status:
        print(status, file=sys.stderr)
    audio_data = np.frombuffer(indata, dtype=np.int16)
    audio_data = np.clip(audio_data * 1.5, -32768, 32767).astype(np.int16)
    q.put(bytes(audio_data))

def check_wake_word(text):
    """Check if text contains wake word"""
    text = normalize_text(text)
    return any(wake_word in text for wake_word in WAKE_WORDS)

def check_stop_word(text):
    """Check if text contains stop word"""
    text = normalize_text(text)
    return any(stop_word in text for stop_word in STOP_WORDS)

def refresh_commands():
    """Обновляет список команд, включая пользовательские"""
    global VA_CMD_LIST
    # Загружаем стандартные команды
    VA_CMD_LIST = yaml.safe_load(
        open('commands.yaml', 'rt', encoding='utf8'),
    )
    # Добавляем пользовательские команды
    VA_CMD_LIST.update(custom_commands.command_manager.get_command_phrases())
    return VA_CMD_LIST

def process_commands():
    """Main command processing loop"""
    global is_listening, current_status, last_command, is_active, active_until
    
    # Обновляем список команд перед началом работы
    refresh_commands()
    
    with sd.RawInputStream(samplerate=samplerate,
                          blocksize=16000,
                          device=device,
                          dtype='int16',
                          channels=1,
                          callback=q_callback):
        
        while is_listening:
            try:
                data = q.get()
                if kaldi_rec.AcceptWaveform(data):
                    result = json.loads(kaldi_rec.Result())
                    if result.get("text", "").strip():
                        voice = result["text"]
                        current_status = f"Распознано: {voice}"
                        
                        # Check for wake word
                        if check_wake_word(voice):
                            is_active = True
                            active_until = time.time() + ACTIVE_WINDOW
                            current_status = "Слушаю..."
                            play("greet")
                            continue
                            
                        # Check for stop word
                        if check_stop_word(voice):
                            is_active = False
                            current_status = "Готов к работе"
                            play("off")
                            continue
                            
                        # Process commands only in active mode
                        if is_active:
                            if time.time() > active_until:
                                is_active = False
                                current_status = "Готов к работе"
                                continue
                                
                            best_match = find_best_match(voice, VA_CMD_LIST)
                            if best_match:
                                cmd, matched_text, score = best_match
                                current_status = f"Выполняю: {matched_text}"
                                last_command = matched_text
                                
                                execute_cmd(cmd, voice)
                                # Reset active window after command
                                active_until = time.time() + ACTIVE_WINDOW
                            else:
                                current_status = "Команда не распознана"
                                play("not_found")
            except Exception as e:
                print(f"Ошибка в process_commands: {e}")
                current_status = "Ошибка обработки команды"

def va_respond(voice: str):
    print(f"Распознано: {voice}")

    # Ищем лучшее совпадение среди всех команд
    best_match = find_best_match(voice, VA_CMD_LIST)

    if best_match is None:
        return False
        
    cmd, matched_text, score = best_match
    print(f"Найдена команда: {matched_text} (схожесть: {score}%)")
    
    execute_cmd(cmd, voice)
    return True

def execute_cmd(cmd: str, voice: str):
    # Проверяем, является ли команда пользовательской
    if cmd.startswith('custom_cmd_'):
        success, response = custom_commands.command_manager.execute_command(cmd)
        if success:
            if config.USE_TTS and response:
                tts.say(response)
            else:
                play("ok")
        else:
            play("not_found")
        return

    # Стандартные команды
    if cmd == 'open_calculator':
        subprocess.Popen(['calc'])
        play("ok")
    elif cmd == 'open_vk':
        webbrowser.open('https://vk.com')
        play("ok")
    elif cmd == 'open_discord':
        webbrowser.open('https://discord.com/app')
        play("ok")
    elif cmd == 'open_youtube':
        webbrowser.open('https://www.youtube.com')
        play("ok")
    elif cmd == 'open_telegram':
        subprocess.Popen([r'C:\Users\bunny\AppData\Roaming\Telegram Desktop\Telegram.exe'])
        play("ok")
    elif cmd == 'open_cursor':
        subprocess.Popen([r'C:\Users\bunny\AppData\Local\Programs\cursor\Cursor.exe'])
        play("ok")
    elif cmd == 'open_vscode':
        subprocess.Popen([r'C:\Users\bunny\AppData\Local\Programs\Microsoft VS Code\Code.exe'])
        play("ok")
    elif cmd == 'open_sublime':
        subprocess.Popen([r'C:\Program Files\Sublime Text 3\sublime_text.exe'])
        play("ok")
    elif cmd == 'open_photoshop':
        subprocess.Popen([r'C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe'])
        play("ok")
    elif cmd == 'open_blender':
        subprocess.Popen([r'C:\Program Files (x86)\Steam\steamapps\common\Blender.exe'])
        play("ok")
    elif cmd == 'open_dota2':
        subprocess.Popen(r'C:\Program Files (x86)\Steam\steamapps\common\dota 2 beta\game\bin\win64\dota2.exe')
        play("ok")
    elif cmd == 'open_superwav':
        subprocess.Popen(r'C:\Program Files (x86)\Steam\steamapps\common\SUPERVIVE\SUPERVIVE.exe')
        play("ok")
    elif cmd == 'music':
        webbrowser.open('https://music.youtube.com')
        play("ok")

    elif cmd == 'music_off':
        subprocess.Popen([f'{CDIR}\\custom-commands\\Stop music.exe'])
        time.sleep(0.2)
        play("ok")

    elif cmd == 'music_save':
        subprocess.Popen([f'{CDIR}\\custom-commands\\Save music.exe'])
        time.sleep(0.2)
        play("ok")

    elif cmd == 'music_pause':
        focus_youtube_music()
        pyautogui.press('space')
        play("ok")

    elif cmd == 'music_next':
        focus_youtube_music()
        pyautogui.hotkey('shift', 'n')
        play("ok")

    elif cmd == 'music_prev':
        focus_youtube_music()
        pyautogui.hotkey('shift', 'p')
        play("ok")

    elif cmd == 'music_volup':
        focus_youtube_music()
        pyautogui.press('up')
        play("ok")

    elif cmd == 'music_voldown':
        focus_youtube_music()
        pyautogui.press('down')
        play("ok")

    elif cmd == 'sound_off':
        play("ok", True)
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(1, None)

    elif cmd == 'sound_on':
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        volume.SetMute(0, None)
        play("ok")

    elif cmd == 'thanks':
        play("thanks")

    elif cmd == 'stupid':
        play("stupid")

    elif cmd == 'gaming_mode_on':
        play("ok")
        subprocess.check_call([f'{CDIR}\\custom-commands\\Switch to gaming mode.exe'])
        play("ready")

    elif cmd == 'gaming_mode_off':
        play("ok")
        subprocess.check_call([f'{CDIR}\\custom-commands\\Switch back to workspace.exe'])
        play("ready")

    elif cmd == 'switch_to_headphones':
        play("ok")
        subprocess.check_call([f'{CDIR}\\custom-commands\\Switch to headphones.exe'])
        time.sleep(0.5)
        play("ready")

    elif cmd == 'switch_to_dynamics':
        play("ok")
        subprocess.check_call([f'{CDIR}\\custom-commands\\Switch to dynamics.exe'])
        time.sleep(0.5)
        play("ready")

def focus_youtube_music():
    try:
        for w in gw.getAllTitles():
            if 'YouTube Music' in w:
                win = gw.getWindowsWithTitle(w)[0]
                win.activate()
                return True
    except Exception as e:
        print(f"[JARVIS] Не удалось активировать окно YouTube Music: {e}")
    return False

def always_listen():
    global is_listening, current_status, last_command, is_active
    samplerate = 16000
    device = 1
    model = vosk.Model("model_small")
    kaldi_rec = vosk.KaldiRecognizer(model, samplerate)
    q = queue.Queue()

    def q_callback(indata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        audio_data = np.frombuffer(indata, dtype=np.int16)
        audio_data = np.clip(audio_data * 1.5, -32768, 32767).astype(np.int16)
        q.put(bytes(audio_data))

    with sd.RawInputStream(samplerate=samplerate,
                          blocksize=16000,
                          device=device,
                          dtype='int16',
                          channels=1,
                          callback=q_callback):
        while is_listening:
            current_status = "Готов к работе"
            is_active = False
            print("[JARVIS] Ожидание ключевого слова 'Джарвис'...")
            # 1. Ждем wake word
            while is_listening:
                data = q.get()
                if kaldi_rec.AcceptWaveform(data):
                    result = json.loads(kaldi_rec.Result())
                    text = result.get("text", "").strip().lower()
                    if any(w in text for w in WAKE_WORDS):
                        current_status = "Слушаю команды..."
                        is_active = True
                        print(f"[JARVIS] Активирован! Ключевое слово: {text}")
                        play("greet")
                        break
            # 2. Слушаем несколько команд подряд, пока не будет 10 секунд тишины
            print("[JARVIS] Ожидание команд (таймер сбрасывается после каждой)...")
            last_command_time = time.time()
            while is_listening and (time.time() - last_command_time < 10):
                data = q.get()
                if kaldi_rec.AcceptWaveform(data):
                    result = json.loads(kaldi_rec.Result())
                    text = result.get("text", "").strip().lower()
                    if text:
                        # Проверка на стоп-фразу
                        if any(stop in text for stop in STOP_WORDS):
                            print(f"[JARVIS] Получена стоп-фраза: {text}. Ассистент уходит отдыхать.")
                            current_status = "Ожидание ключевого слова 'Джарвис'..."
                            is_active = False
                            break
                        last_command_time = time.time()  # сбрасываем таймер
                        current_status = f"Распознано: {text}"
                        print(f"[JARVIS] Получена команда: {text}")
                        best_match = find_best_match(text, VA_CMD_LIST)
                        if best_match:
                            cmd, matched_text, score = best_match
                            current_status = f"Выполняю: {matched_text}"
                            last_command = matched_text
                            print(f"[JARVIS] Выполняю команду: {matched_text} (совпадение: {score}%)")
                            execute_cmd(cmd, text)
                        else:
                            current_status = "Команда не распознана"
                            print("[JARVIS] Команда не распознана")
            print("[JARVIS] 10 секунд тишины. Возврат к ожиданию 'Джарвис'.")
            is_active = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify({
        'is_listening': is_listening,
        'current_status': current_status,
        'last_command': last_command
    })

@app.route('/api/start')
def start_listening():
    global is_listening
    if not is_listening:
        is_listening = True
        Thread(target=process_commands, daemon=True).start()
        return jsonify({'status': 'started'})
    return jsonify({'status': 'already_running'})

@app.route('/api/stop')
def stop_listening():
    global is_listening
    is_listening = False
    return jsonify({'status': 'stopped'})

if __name__ == '__main__':
    import logging
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QFrame
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtCore import QUrl, Qt, QSize
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWebChannel import QWebChannel
    from PyQt6.QtCore import pyqtSlot, QObject

    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # Enable high-DPI scaling for better quality (env vars only)
    import os
    os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
    os.environ['QT_SCALE_FACTOR'] = '1'

    threading.Thread(target=always_listen, daemon=True).start()
    def run_flask():
        app.run(debug=False, port=5000, host='127.0.0.1')
    threading.Thread(target=run_flask, daemon=True).start()

    class Bridge(QObject):
        def __init__(self, window):
            super().__init__()
            self.window = window
        @pyqtSlot(int, int)
        def moveWindow(self, dx, dy):
            self.window.move(self.window.x() + dx, self.window.y() + dy)

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('JARVIS')
            self.setFixedSize(700, 750)  # или нужный вам размер
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setStyleSheet('QMainWindow { background: transparent; }')

            self.web = QWebEngineView()
            self.web.setStyleSheet('background: transparent; border-radius: 0;')
            html_path = os.path.abspath('reactor_ui.html')
            self.web.load(QUrl.fromLocalFile(html_path))

            # QWebChannel for JS <-> Python
            self.channel = QWebChannel()
            self.bridge = Bridge(self)
            self.channel.registerObject('pyBridge', self.bridge)
            self.web.page().setWebChannel(self.channel)

            main_widget = QWidget()
            main_widget.setStyleSheet('background: transparent;')
            main_layout = QHBoxLayout(main_widget)
            main_layout.setContentsMargins(0, 0, 0, 0)
            main_layout.setSpacing(0)
            main_layout.addWidget(self.web)
            self.setCentralWidget(main_widget)
            self.oldPos = None

    app_qt = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app_qt.exec())
