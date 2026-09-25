"""Local sound matcher for Arena Breakout: Infinite Field Merchant."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import soundcard as sc
import soundfile as sf
from scipy.signal import butter, fftconvolve, resample_poly, sosfilt
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import ttk, messagebox


BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
CATALOG = json.loads((BASE / 'catalog.json').read_text(encoding='utf-8'))
SOUNDS_BY_ID = {sound['id']: sound for sound in CATALOG['sounds']}
SAMPLE_RATE = 24000
CAPTURE_RATE = 48000
WINDOW_SECONDS = 2.3


def mono_24k(data: np.ndarray, input_rate: int) -> np.ndarray:
    data = np.asarray(data, dtype=np.float32)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if input_rate == SAMPLE_RATE:
        return data
    if input_rate == CAPTURE_RATE:
        return resample_poly(data, 1, 2).astype(np.float32)
    import math
    factor = math.gcd(input_rate, SAMPLE_RATE)
    return resample_poly(data, SAMPLE_RATE // factor, input_rate // factor).astype(np.float32)


class Matcher:
    def __init__(self) -> None:
        self.filter = butter(3, (180, 8500), btype='bandpass', fs=SAMPLE_RATE, output='sos')
        self.music_filter = butter(3, (1600, 9500), btype='bandpass', fs=SAMPLE_RATE, output='sos')
        self.refs: list[tuple[int, str, np.ndarray, float]] = []
        self.fast_refs: list[tuple[int, str, np.ndarray, float]] = []
        self.music_refs: list[tuple[int, str, np.ndarray, float]] = []
        self.fast_music_refs: list[tuple[int, str, np.ndarray, float]] = []
        for sound in CATALOG['sounds']:
            for action in ('pickup', 'drop'):
                path = BASE / 'reference' / (sound[action] + '.ogg')
                data, rate = sf.read(str(path), dtype='float32')
                mono = mono_24k(data, rate)
                for sound_filter, full_refs, fast_refs in (
                    (self.filter, self.refs, self.fast_refs),
                    (self.music_filter, self.music_refs, self.fast_music_refs),
                ):
                    waveform = sosfilt(sound_filter, mono).astype(np.float32)
                    # The quiet tail varies most with game volume and overlapping sounds.
                    power = np.convolve(waveform * waveform, np.ones(240) / 240, mode='same')
                    active = np.flatnonzero(power > power.max() * 0.015)
                    if len(active):
                        lo = max(0, int(active[0]) - 480)
                        hi = min(len(waveform), int(active[-1]) + 480)
                        waveform = waveform[lo:hi]
                    energy = float(np.dot(waveform, waveform))
                    full_refs.append((sound['id'], action, waveform, energy))
                    prefix = waveform[:min(len(waveform), int(0.30 * SAMPLE_RATE))]
                    fast_refs.append((sound['id'], action, prefix, float(np.dot(prefix, prefix))))

    def match(self, data: np.ndarray, rate: int, fast: bool = False) -> list[tuple[int, str, float]]:
        return self.match_with_prominence(data, rate, fast)[0]

    def match_with_prominence(self, data: np.ndarray, rate: int, fast: bool = False) -> tuple[list[tuple[int, str, float]], list[tuple[int, str, float]]]:
        mono = mono_24k(data, rate)
        if len(mono) < 5000 or float(np.max(np.abs(mono))) < 0.0002:
            return [], []
        best: dict[int, tuple[str, float]] = {}
        prominent: dict[int, tuple[str, float]] = {}
        for sound_filter, refs in (
            (self.filter, self.fast_refs if fast else self.refs),
            (self.music_filter, self.fast_music_refs if fast else self.music_refs),
        ):
            signal = sosfilt(sound_filter, mono).astype(np.float32)
            cosine, peaks = self._match_signal(signal, refs)
            for sound_id, (action, score) in cosine.items():
                if sound_id not in best or score > best[sound_id][1]:
                    best[sound_id] = (action, score)
            for sound_id, (action, score) in peaks.items():
                if sound_id not in prominent or score > prominent[sound_id][1]:
                    prominent[sound_id] = (action, score)
        def ranked(scores):
            return sorted(((sid, action, score) for sid, (action, score) in scores.items()),
                          key=lambda entry: entry[2], reverse=True)
        return ranked(best), ranked(prominent)

    @staticmethod
    def _match_signal(signal: np.ndarray, refs: list[tuple[int, str, np.ndarray, float]]) -> tuple[dict[int, tuple[str, float]], dict[int, tuple[str, float]]]:
        integral = np.r_[0.0, np.cumsum(signal.astype(np.float64) ** 2)]
        best: dict[int, tuple[str, float]] = {}
        prominent: dict[int, tuple[str, float]] = {}
        for sound_id, action, reference, energy in refs:
            length = len(reference)
            if length > len(signal) or energy <= 0:
                continue
            numerator = fftconvolve(signal, reference[::-1], mode='valid')
            center = float(np.mean(numerator))
            spread = max(float(np.std(numerator)), 1e-12)
            peak = max(0.0, (float(np.max(numerator)) - center) / spread)
            if sound_id not in prominent or peak > prominent[sound_id][1]:
                prominent[sound_id] = (action, peak)
            local_energy = np.maximum(integral[length:] - integral[:-length], 0.0)
            # Sliding prefix sums can lose precision in near-silent windows after a loud sound.
            # Ignore those windows before normalizing, rather than producing values above 100%.
            energy_floor = max(float(local_energy.max()) * 1e-6, length * 1e-10)
            valid = local_energy > energy_floor
            if not np.any(valid):
                continue
            normalized = numerator[valid] / np.sqrt(local_energy[valid] * energy)
            score = float(np.clip(np.max(normalized), 0.0, 1.0))
            if sound_id not in best or score > best[sound_id][1]:
                best[sound_id] = (action, score)
        return best, prominent


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title('暗区战地商人 · 听声识物')
        root.geometry('860x640')
        root.minsize(720, 520)
        self.matcher = Matcher()
        self.devices = [mic for mic in sc.all_microphones(include_loopback=True) if mic.isloopback]
        default = sc.default_speaker()
        self.device_name = tk.StringVar(value=next((mic.name for mic in self.devices if mic.name == default.name), self.devices[0].name if self.devices else ''))
        self.size = tk.StringVar(value='不限')
        self.auto = tk.BooleanVar(value=True)
        self.pin_window = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value='选择游戏使用的播放设备，然后点击开始监听。')
        self.top_result = tk.StringVar(value='等待声音…')
        self.listening = False
        self.busy = False
        self.audio_lock = threading.Lock()
        self.chunks: deque[np.ndarray] = deque(maxlen=35)
        self.messages: queue.Queue = queue.Queue()
        self.last_auto = 0.0
        self.last_match = (None, 0.0)
        self.tentative: tuple[int, float, int] | None = None
        self.last_ranked: list[tuple[int, str, float]] = []
        self.last_metric = 'cos'
        self.photos: list[ImageTk.PhotoImage] = []
        self.preview_buttons: list[ttk.Button] = []
        self.previewing = False
        self.preview_until = 0.0
        self._build()
        self._toggle_pin()
        root.after(75, self._drain_messages)
        root.after(250, self._auto_tick)
        root.protocol('WM_DELETE_WINDOW', self._close)

    def _build(self) -> None:
        self.root.configure(bg='#101824')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#101824')
        style.configure('TLabel', background='#101824', foreground='#d7e4ee', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', padding=8, font=('Microsoft YaHei UI', 10))
        style.configure('TCombobox', padding=5)
        frame = ttk.Frame(self.root, padding=20)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='战地商人 · 听声识物', font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='拖动神秘货物，识别拾起或放下音效；结果按声音组展示，组内物品需要结合占格判断。').pack(anchor='w', pady=(5, 16))

        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Label(row, text='游戏播放设备').pack(side='left')
        self.device_combo = ttk.Combobox(row, textvariable=self.device_name, values=[mic.name for mic in self.devices], width=53, state='readonly')
        self.device_combo.pack(side='left', padx=8, fill='x', expand=True)
        ttk.Label(row, text='货物占格（可旋转）').pack(side='left', padx=(10, 0))
        size_combo = ttk.Combobox(row, textvariable=self.size, values=['不限', '1×1', '1×2', '2×1', '2×2', '2×3', '3×2'], width=7, state='readonly')
        size_combo.pack(side='left', padx=8)
        size_combo.bind('<<ComboboxSelected>>', lambda _event: self._render(self.last_ranked, self.last_metric) if self.last_ranked else None)

        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=15)
        self.listen_button = ttk.Button(controls, text='开始监听', command=self._toggle)
        self.listen_button.pack(side='left')
        ttk.Button(controls, text='识别最近 2.3 秒', command=lambda: self._submit(False)).pack(side='left', padx=8)
        ttk.Checkbutton(controls, text='自动尝试识别', variable=self.auto).pack(side='left', padx=10)
        ttk.Checkbutton(controls, text='窗口置顶', variable=self.pin_window, command=self._toggle_pin).pack(side='left', padx=10)
        ttk.Label(frame, textvariable=self.status, foreground='#85bce9').pack(anchor='w', pady=(0, 10))

        top = tk.Label(frame, textvariable=self.top_result, bg='#183148', fg='#f4f8fb', anchor='w', padx=15, pady=15,
                       font=('Microsoft YaHei UI', 14, 'bold'))
        top.pack(fill='x', pady=(0, 12))

        ttk.Label(frame, text='候选声音组及物品：点击物品旁的按钮试听数据库音效；同组物品共用声音').pack(anchor='w')
        result_frame = ttk.Frame(frame)
        result_frame.pack(fill='both', expand=True, pady=(6, 8))
        self.results = tk.Text(result_frame, height=18, wrap='word', bg='#142231', fg='#d7e4ee', insertbackground='white',
                               font=('Microsoft YaHei UI', 10), relief='flat', padx=15, pady=12, state='disabled')
        self.results.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=self.results.yview)
        scrollbar.pack(side='right', fill='y')
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.tag_configure('group', foreground='#82c7ed', font=('Microsoft YaHei UI', 11, 'bold'), spacing1=10, spacing3=8)
        self.results.tag_configure('item', foreground='#ecf4fa', font=('Microsoft YaHei UI', 11))
        self.results.tag_configure('detail', foreground='#9db1bd', font=('Microsoft YaHei UI', 9))
        ttk.Label(frame, text=f"试听音量已统一 · 匹配分与峰值强度均不是掉落概率 · 数据版本 {CATALOG['data_version']}",
                  foreground='#8ca0ae').pack(anchor='w')

    def _toggle(self) -> None:
        if self.listening:
            self.listening = False
            self.listen_button.configure(text='开始监听')
            self.status.set('已停止监听。')
            return
        device = next((mic for mic in self.devices if mic.name == self.device_name.get()), None)
        if device is None:
            messagebox.showerror('找不到设备', '没有可用的系统播放设备。请检查 Windows 音频设置。')
            return
        self.chunks.clear()
        self.listening = True
        self.listen_button.configure(text='停止监听')
        self.status.set(f'正在监听：{device.name}')
        threading.Thread(target=self._capture, args=(device,), daemon=True).start()

    def _toggle_pin(self) -> None:
        self.root.attributes('-topmost', self.pin_window.get())

    def _capture(self, device) -> None:
        try:
            with device.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=4800) as recorder:
                while self.listening:
                    chunk = recorder.record(numframes=4800).astype(np.float32)
                    with self.audio_lock:
                        self.chunks.append(chunk)
        except Exception as exc:
            self.messages.put(('error', f'无法监听此设备：{exc}'))

    def _snapshot(self) -> np.ndarray | None:
        with self.audio_lock:
            chunks = list(self.chunks)
        if not chunks:
            return None
        return np.concatenate(chunks)[-int(CAPTURE_RATE * WINDOW_SECONDS):]

    def _submit(self, automatic: bool) -> None:
        if self.busy or self.previewing or time.monotonic() < self.preview_until:
            return
        snapshot = self._snapshot()
        if snapshot is None or len(snapshot) < CAPTURE_RATE // 2:
            if not automatic:
                self.status.set('还没有收集到足够的声音，请先开始监听并拖动物品。')
            return
        if automatic:
            snapshot = snapshot[-int(CAPTURE_RATE * 1.2):]
        self.busy = True
        threading.Thread(target=self._recognize, args=(snapshot, automatic), daemon=True).start()

    def _recognize(self, snapshot: np.ndarray, automatic: bool) -> None:
        try:
            ranked, prominent = self.matcher.match_with_prominence(snapshot, CAPTURE_RATE, fast=automatic)
            self.messages.put(('match', ranked, prominent, automatic))
        except Exception as exc:
            self.messages.put(('error', f'识别失败：{exc}'))

    def _auto_tick(self) -> None:
        now = time.monotonic()
        if self.listening and self.auto.get() and not self.previewing and now >= self.preview_until and now - self.last_auto > 0.25:
            self.last_auto = now
            self._submit(True)
        self.root.after(250, self._auto_tick)

    def _drain_messages(self) -> None:
        while True:
            try:
                message = self.messages.get_nowait()
            except queue.Empty:
                break
            if message[0] in ('preview_done', 'preview_error'):
                self.previewing = False
                self.preview_until = time.monotonic() + 0.6
                with self.audio_lock:
                    self.chunks.clear()
                self.status.set(message[1])
                continue
            self.busy = False
            if message[0] == 'error':
                self.status.set(message[1])
                self.listening = False
                self.listen_button.configure(text='开始监听')
            elif not self.previewing:
                self._show(message[1], message[2], message[3])
        self.root.after(75, self._drain_messages)

    def _show(self, ranked: list[tuple[int, str, float]], prominent: list[tuple[int, str, float]], automatic: bool) -> None:
        if not ranked and not prominent:
            if not automatic:
                self.top_result.set('未检测到可识别的声音')
            return
        cos_score = ranked[0][2] if ranked else 0.0
        cos_gap = cos_score - (ranked[1][2] if len(ranked) > 1 else 0.0)
        use_cos = (cos_score >= 0.24 and cos_gap >= (0.12 if automatic else 0.10))
        peak_score = prominent[0][2] if prominent else 0.0
        peak_gap = peak_score - (prominent[1][2] if len(prominent) > 1 else 0.0)
        use_peak = peak_score >= 7.0 and peak_gap >= 2.0
        if use_cos:
            metric = 'cos'
        elif use_peak:
            metric = 'peak'
            ranked = prominent
        else:
            if not automatic:
                self.top_result.set('声音不够明确，请再拖动一次')
                self._render(ranked[:3], 'cos')
            self.tentative = None
            return
        sound_id, action, score = ranked[0]
        gap = score - (ranked[1][2] if len(ranked) > 1 else 0.0)
        if automatic:
            if metric == 'peak':
                confidence = '音乐抗干扰匹配，建议复核'
            elif score >= 0.40 and gap >= 0.15:
                confidence = '快速匹配'
            else:
                confidence = '低音量匹配，建议复核'
            now = time.monotonic()
            previous = self.tentative
            count = previous[2] + 1 if previous and previous[0] == sound_id and now - previous[1] <= 1.0 else 1
            self.tentative = (sound_id, now, count)
            if count < 2 and not (metric == 'cos' and score >= 0.75 and gap >= 0.30):
                return
            if self.last_match[0] != sound_id and now - self.last_match[1] < 0.75 and (metric == 'peak' or score < 0.75):
                return
        elif metric == 'peak':
            confidence = '音乐抗干扰匹配，建议复核'
        else:
            confidence = '建议再听一次' if score < 0.60 else '匹配明确'
        if automatic and self.last_match[0] == sound_id and time.monotonic() - self.last_match[1] < 3:
            return
        self.last_match = (sound_id, time.monotonic())
        score_label = f'匹配分 {score*100:.0f}/100' if metric == 'cos' else f'音效峰值强度 {score:.1f}'
        self.top_result.set(f'音效组 {sound_id} · {"拾起" if action == "pickup" else "放下"} · {score_label} · {confidence}')
        self.status.set('已识别。可用货物占格进一步筛选候选物品。')
        self._render(ranked[:3], metric)

    def _render(self, ranked: list[tuple[int, str, float]], metric: str = 'cos') -> None:
        self.last_ranked = ranked
        self.last_metric = metric
        size = self.size.get()
        for button in self.preview_buttons:
            button.destroy()
        self.preview_buttons.clear()
        self.photos.clear()
        self.results.configure(state='normal')
        self.results.delete('1.0', 'end')
        for index, (sound_id, action, score) in enumerate(ranked, 1):
            items = [item for item in CATALOG['items'] if item['soundId'] == sound_id]
            if size != '不限':
                a, b = map(int, size.split('×'))
                items = [item for item in items if sorted(item['size']) == sorted([a, b])]
            score_label = f'匹配分 {score*100:.0f}/100' if metric == 'cos' else f'音效峰值强度 {score:.1f}'
            self.results.insert('end', f'{index}. 音效组 {sound_id}  ·  {score_label}  ·  {len(items)} 件符合占格的物品\n', 'group')
            if items:
                for item in sorted(items, key=lambda x: x.get('contactPrice') or 0, reverse=True):
                    icon = BASE / 'icons' / f"{item['id']}.png"
                    if icon.exists():
                        try:
                            with Image.open(icon) as source:
                                picture = source.convert('RGBA')
                                picture.thumbnail((48, 48), Image.Resampling.LANCZOS)
                                canvas = Image.new('RGBA', (54, 54), (0, 0, 0, 0))
                                canvas.alpha_composite(picture, ((54-picture.width)//2, (54-picture.height)//2))
                            photo = ImageTk.PhotoImage(canvas)
                            self.photos.append(photo)
                            self.results.image_create('end', image=photo, padx=7, pady=3)
                        except Exception:
                            self.results.insert('end', '  •  ')
                    else:
                        self.results.insert('end', '  •  ')
                    self.results.insert('end', f"{item['nameZh']}  ", 'item')
                    for preview_action, label in (('pickup', '▶ 拾起'), ('drop', '▶ 放下')):
                        button = ttk.Button(
                            self.results, text=label, width=7,
                            command=lambda sid=sound_id, act=preview_action, name=item['nameZh']: self._preview(sid, act, name),
                        )
                        self.preview_buttons.append(button)
                        self.results.window_create('end', window=button, padx=3)
                    self.results.insert('end', '\n')
                    self.results.insert('end', f"      {item['size'][0]}×{item['size'][1]}  ·  联系人价格 {item.get('contactPrice', 0):,}\n", 'detail')
            else:
                self.results.insert('end', '   当前占格没有候选物品；请核对占格或再录一次。\n', 'detail')
            self.results.insert('end', '\n')
        self.results.configure(state='disabled')
        self.results.yview_moveto(0)

    def _preview(self, sound_id: int, action: str, item_name: str) -> None:
        if self.previewing:
            return
        self.previewing = True
        self.tentative = None
        self.status.set(f'正在试听：{item_name} · {"拾起" if action == "pickup" else "放下"}')
        threading.Thread(target=self._play_reference, args=(sound_id, action, item_name, self.device_name.get()), daemon=True).start()

    def _play_reference(self, sound_id: int, action: str, item_name: str, device_name: str) -> None:
        try:
            sound = SOUNDS_BY_ID[sound_id]
            audio, rate = sf.read(str(BASE / 'reference' / (sound[action] + '.ogg')), dtype='float32')
            if audio.ndim == 1:
                audio = np.column_stack((audio, audio))
            peak = float(np.max(np.abs(audio)))
            if peak > 0:
                audio = np.asarray(audio * min(4.0, 0.5 / peak), dtype=np.float32)
            speaker = next((device for device in sc.all_speakers() if device.name == device_name), sc.default_speaker())
            speaker.play(audio, samplerate=rate, channels=[0, 1])
            self.messages.put(('preview_done', f'已试听：{item_name} · {"拾起" if action == "pickup" else "放下"}'))
        except Exception as exc:
            self.messages.put(('preview_error', f'音效播放失败：{exc}'))

    def _close(self) -> None:
        self.listening = False
        self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    App(window)
    window.mainloop()
