"""Local sound matcher for Arena Breakout: Infinite Field Merchant.

Feature edition (based on zhx441's original, MIT):
- Live UI language switcher: Russian / English / 中文 (item names localized too).
- Compact, Apple-flavoured dark redesign.
- Mini in-game overlay window: small always-on-top panel with the current match,
  optional mouse click-through; main window keeps full controls.
- Settings persisted in settings_local.json (language, filters, window state).
Recognition logic (Matcher) is unchanged from the original.
"""

from __future__ import annotations

import ctypes
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
SETTINGS_PATH = BASE / 'settings_local.json'


# ---------------------------------------------------------------- localization

LANGS = ['ru', 'en', 'zh']
LANG_NAMES = {'ru': 'Русский', 'en': 'English', 'zh': '中文'}

CATEGORY_L10N = {
    'ru': {
        'Building Materials': 'Стройматериалы', 'Collectibles': 'Коллекционные',
        'Computer Parts': 'Комплектующие ПК', 'Electronics': 'Электроника',
        'Energy Items': 'Энергетика', 'Flammables': 'Горючее',
        'Household Items': 'Бытовые товары', 'Instruments': 'Приборы',
        'Miscellaneous Medical Item': 'Медицина', 'Miscellaneous Military Item': 'Военное',
        'Paper': 'Бумага', 'Tools': 'Инструменты',
    },
    'en': None,  # catalog categories are already English
    'zh': {
        'Building Materials': '建筑材料', 'Collectibles': '收藏品',
        'Computer Parts': '电脑配件', 'Electronics': '电子产品',
        'Energy Items': '能源物品', 'Flammables': '易燃品',
        'Household Items': '家居用品', 'Instruments': '仪器',
        'Miscellaneous Medical Item': '医疗物品', 'Miscellaneous Military Item': '军用物品',
        'Paper': '纸制品', 'Tools': '工具',
    },
}

RARITY_L10N = {
    'ru': {6: 'Красный', 5: 'Золотой', 4: 'Фиолетовый', 3: 'Синий', 2: 'Зелёный', 1: 'Белый'},
    'en': {6: 'Red', 5: 'Gold', 4: 'Purple', 3: 'Blue', 2: 'Green', 1: 'White'},
    'zh': {6: '红', 5: '金', 4: '紫', 3: '蓝', 2: '绿', 1: '白'},
}

NAME_RU = {
    'Acoustic Panel': 'Акустическая панель',
    'Aerospace Navigator': 'Аэрокосмический навигатор',
    'Air Tightness Tester': 'Тестер герметичности',
    'Amber Heart of Heaven': 'Янтарное сердце небес',
    'Ancient Golden Mask Replica': 'Реплика древней золотой маски',
    'Antenna': 'Антенна',
    'Antique Teapot': 'Антикварный чайник',
    'Arched Corrugated Steel Plate': 'Арочная гофрированная плита',
    'Automated External Defibrillator': 'Автоматический дефибриллятор',
    'Bag of Cement': 'Мешок цемента',
    'Bag of Fertilizer': 'Мешок удобрений',
    'Battery': 'Батарея',
    'Battery-Powered Positive Electrode Module': 'Аккумуляторный модуль электрода',
    'Bios.': 'BIOS-плата',
    'Blocker Injector': 'Инъектор блокатора',
    'Blood Glucose Meter Set': 'Набор глюкометра',
    'Blower': 'Воздуходувка',
    'Blowtorch': 'Паяльная лампа',
    'Broken LCD': 'Разбитый ЖК-дисплей',
    'Brooch': 'Брошь',
    'Bundle of Rice Paper': 'Связка рисовой бумаги',
    'Camera': 'Фотоаппарат',
    'Camping Stove': 'Кемпинговая печь',
    'Camping Tarp': 'Кемпинговый тент',
    'Cannon Shell': 'Артиллерийский снаряд',
    'Capacitance Analyzer': 'Анализатор ёмкости',
    'Capsule TV': 'Капсульный телевизор',
    'Car Battery': 'Автомобильный аккумулятор',
    'Chip Processor': 'Процессор (чип)',
    'Classic Radio': 'Классическое радио',
    'Commemorative Coin': 'Памятная монета',
    'D-size Battery': 'Батарея типа D',
    'DVD': 'DVD-привод',
    'Data Cable': 'Кабель для передачи данных',
    'Deluxe Tea Set': 'Роскошный чайный сервиз',
    'Desk Clock': 'Настольные часы',
    'Diamond Ring': 'Кольцо с бриллиантом',
    'Disinfectant': 'Дезинфицирующее средство',
    'Document': 'Документ',
    'Double-Neck Lute': 'Двухгрифовая лютня',
    'Dried Flower Bookmark': 'Закладка из сухих цветов',
    'EEG': 'ЭЭГ (энцефалограф)',
    'Electric Drill': 'Электродрель',
    'Electronic Stethoscope': 'Электронный стетоскоп',
    'Film Stock': 'Киноплёнка',
    'Flashlight': 'Фонарик',
    'Floppy Drive': 'Дисковод дискет',
    'Folder': 'Папка с документами',
    'Fuel Tank': 'Топливный бак',
    'GU-470 Portable Recorder': 'Портативный рекордер GU-470',
    'Game Cartridge': 'Игровой картридж',
    'Game Console': 'Игровая консоль',
    'Gas Analyzer': 'Газоанализатор',
    'Gem Necklace': 'Ожерелье с самоцветами',
    'Gilded Cage Music Box': 'Позолоченная музыкальная шкатулка',
    'Gimbal': 'Стабилизатор (гимбал)',
    'Glucose Injection': 'Инъекция глюкозы',
    'Glue Gun': 'Клеевой пистолет',
    'Gold Block': 'Золотой слиток',
    'Gold Bracelet': 'Золотой браслет',
    'Gold Cheetah Statue': 'Статуэтка золотого гепарда',
    'Gold Cube': 'Золотой куб',
    'Gold Cup': 'Золотой кубок',
    'Gold Lion Statue': 'Статуэтка золотого льва',
    'Gold Pen': 'Золотая ручка',
    'Gold Phone': 'Золотой телефон',
    'Gold Snake': 'Золотая змея',
    'Gold Watch': 'Золотые часы',
    'Gold-rimmed Glasses': 'Очки в золотой оправе',
    'Graphics Card': 'Видеокарта',
    'Gungnir Blueprint Fragments': 'Фрагменты чертежа «Гунгнир»',
    'Handheld Calculator': 'Карманный калькулятор',
    'Handheld Fill Light': 'Ручная подсветка',
    'Handheld Receiver': 'Портативный приёмник',
    'Handheld Salinity Meter': 'Карманный солемер',
    'Handheld Tester': 'Портативный тестер',
    'Hardcover': 'Книга в твёрдом переплёте',
    'Hearing Aid': 'Слуховой аппарат',
    'Heavenly Sphere': 'Небесная сфера',
    'Hefra Egg': 'Яйцо Хефры',
    'High Energy Fuel': 'Высокоэнергетическое топливо',
    'High Power Flashlight': 'Мощный фонарь',
    'Hydraulic Expander': 'Гидравлический расширитель',
    'Hydraulic Rebar Cutter': 'Гидравлические ножницы для арматуры',
    'Hydraulic Wrench': 'Гидравлический гайковёрт',
    'Impact-resistant Hard Rubber': 'Ударопрочная резина',
    'Infrared Therapy Lamp': 'Инфракрасная лампа для терапии',
    'Insulin Pump': 'Инсулиновая помпа',
    'Jade Bracelet': 'Нефритовый браслет',
    'K7-L Cipher Machine': 'Шифровальная машина K7-L',
    'Kerosene Lamp': 'Керосиновая лампа',
    'Laptop Computer': 'Ноутбук',
    'Large-Caliber Artillery Gunpowder Pack': 'Пороховой заряд крупного калибра',
    'Laser Pointer Module': 'Модуль лазерного целеуказателя',
    'Lens': 'Линза (объектив)',
    'Leveler': 'Строительный уровень',
    'Light Meter': 'Экспонометр',
    'Lute': 'Лютня',
    'Lyre': 'Лира',
    'MRID Clamshell Laptop': 'Раскладной ноутбук MRID',
    'Magnesium Flint': 'Магниевое огниво',
    'Majestic Sculpture': 'Величественная скульптура',
    'Medical Scissors': 'Медицинские ножницы',
    'Medical Sponge': 'Медицинская губка',
    'Metal Heart': 'Металлическое сердце',
    'Military Canteen': 'Армейская фляга',
    'Military Radio': 'Военная рация',
    'Military Tool Kit': 'Армейский набор инструментов',
    'Mutant Evolution Sketch': 'Зарисовка эволюции мутанта',
    'Mutant Heart Sample': 'Образец сердца мутанта',
    'Mutated Tissue Mass': 'Мутировавшая ткань',
    'Ni-Cd Battery Pack': 'Никель-кадмиевый аккумулятор',
    'Nitrocellulose': 'Нитроцеллюлоза',
    'Northern Stars Amber Drink': 'Янтарный напиток «Северные звёзды»',
    'Oil': 'Масло (нефть)',
    'Oil Bottle': 'Бутылка масла',
    'Oil Drum': 'Бочка с топливом',
    'Optoelectronic Hyperspace Model': 'Оптоэлектронная модель «Гиперпространство»',
    'Oscilloscope': 'Осциллограф',
    'PSU': 'Блок питания',
    'Palladium Wire': 'Палладиевая проволока',
    'Paracord': 'Паракорд',
    'Peacock Fan': 'Веер из павлиньих перьев',
    'Personal Digital Assistant': 'КПК (карманный компьютер)',
    "Phaethon's Clock": 'Часы Фаэтона',
    'Pheromone Test Kit': 'Набор теста на феромоны',
    'Photo Frame': 'Фоторамка',
    'Pipe Cleaning Kit': 'Комплект для чистки труб',
    'Pipe Wrench': 'Трубный ключ',
    'Plaster Sculpture': 'Гипсовая скульптура',
    'Pocket Watch': 'Карманные часы',
    'Porcelain': 'Фарфор',
    'Portable Fuel Canister': 'Портативная канистра с топливом',
    'Portable Jack': 'Портативный домкрат',
    'Portable Transceiver': 'Портативная рация',
    'Power Cable': 'Силовой кабель',
    'Propane Tank': 'Баллон с пропаном',
    'Prototype Calculation Module': 'Прототип вычислительного модуля',
    'Quantum 2000 Toy Robot': 'Игрушечный робот «Квант 2000»',
    'RAM': 'Оперативная память',
    'Radio': 'Радиоприёмник',
    'Rangefinder Binoculars': 'Дальномерный бинокль',
    'Raw Diamond Ore': 'Необработанная алмазная руда',
    'Real Matrix': '«Настоящая матрица»',
    'Receiver': 'Приёмник',
    'Record Player': 'Проигрыватель винила',
    'Rubber Pad': 'Резиновая прокладка',
    'SSD': 'SSD-накопитель',
    'Safety Hammer': 'Аварийный молоток',
    'Sergey 1 Satellite Model': 'Модель спутника «Сергей-1»',
    'Signal Jammer': 'Глушитель сигнала',
    'Silver Badge': 'Серебряный значок',
    'Silver Chain': 'Серебряная цепочка',
    'Skyhook Synchronized Array Mirror': 'Зеркало синхронной решётки «Скайхук»',
    'Solar Charger': 'Солнечное зарядное устройство',
    'Solar Panel': 'Солнечная панель',
    'Sound-Muffling Cotton': 'Шумопоглощающий хлопок',
    'Space Boy Comic': 'Комикс «Космический мальчик»',
    'Space Lab Toybox': 'Набор «Космическая лаборатория»',
    'Spur': 'Шпора',
    'Stamp': 'Почтовая марка',
    'Stamp Album': 'Альбом марок',
    'Star of Kamona Pendant': 'Подвеска «Звезда Камоны»',
    'Studio Monitor': 'Студийный монитор',
    'Syringe': 'Шприц',
    'T-147 Individual Communication Device': 'Средство связи T-147',
    'TI Module': 'Модуль TI',
    'Target Positioning Module': 'Модуль позиционирования цели',
    'Thermometer': 'Термометр',
    'Three-Axis Gyro Controller Prototype': 'Прототип трёхосевого гироконтроллера',
    'Titanium Alloy Plate': 'Пластина из титанового сплава',
    'Toland Access Card': 'Карта доступа «Толанд»',
    'Toolbox': 'Ящик с инструментами',
    'Toolkit': 'Набор инструментов',
    'UPS Unit': 'ИБП (бесперебойник)',
    'VGA Display Cable': 'Кабель монитора VGA',
    'Vase': 'Ваза',
    'Vector Processor': 'Векторный процессор',
    'Video Camera': 'Видеокамера',
    'Vintage Typewriter': 'Винтажная печатная машинка',
    'Voice of Civilization Gold Record': 'Золотая пластинка «Голос цивилизации»',
    "Voss' Journal": 'Дневник Восса',
    'Watch': 'Часы',
    'Wave Filter': 'Волновой фильтр',
    'Weapon Parts': 'Части оружия',
    'Wood Board': 'Доска',
    'Working LCD': 'Рабочий ЖК-дисплей',
}

STR = {
    'ru': {
        'app_title': 'Полевой торговец · Звук → Предмет',
        'header': '🎧 Полевой торговец',
        'header_sub': 'звук → предмет',
        'subtitle': 'Передвиньте загадочный товар — программа покажет группу звуков-кандидатов. '
                    'Предметы внутри группы различайте по клеткам и цене.',
        'device': 'Устройство звука игры',
        'size': 'Клетки товара',
        'start': '▶  Начать',
        'stop': '⏹  Остановить',
        'recognize': '⟳  Распознать 2,3 с',
        'auto': 'Авто',
        'pin': 'Поверх окон',
        'clickthrough': 'Сквозной мини',
        'mini_btn': '▣  Мини-окно',
        'mini_title': 'Мини',
        'status_idle': '1) Выберите устройство звука игры   2) нажмите «Начать»   3) передвигайте товар',
        'status_stopped': '⏸ Остановлено.',
        'listening': 'Слушаю',
        'status_not_enough': 'Недостаточно звука — включите прослушивание и передвиньте товар',
        'status_matched': '✅ Распознано — сузьте список размером в клетках',
        'err_listen': '⚠ Не удалось слушать устройство: ',
        'err_match': '⚠ Ошибка распознавания: ',
        'err_play': '⚠ Не удалось воспроизвести: ',
        'err_dev_title': 'Устройство не найдено',
        'err_dev_msg': 'Нет доступных устройств вывода. Проверьте звук Windows.',
        'banner_wait': '🎧 Ожидаю звук…',
        'banner_none': '🔇 Распознаваемый звук не обнаружен',
        'banner_unsure': '🤔 Звук неуверенный — передвиньте ещё раз',
        'conf_quick': 'быстрое совпадение',
        'conf_low': 'тихий звук — перепроверьте',
        'conf_music': 'фильтр помех — перепроверьте',
        'conf_again': 'лучше прослушайте ещё раз',
        'conf_ok': 'совпадение уверенное ✔',
        'action_pickup': 'поднятие',
        'action_drop': 'укладка',
        'score': 'Совпадение',
        'peak': 'Пик звука',
        'group_word': 'ГРУППА',
        'items_match': 'под фильтр',
        'price': 'цена у торговца:',
        'hint': 'Группы звуков и предметы — ▶ сравнить звук на слух; предметы одной группы звучат одинаково',
        'empty': 'Для этого размера кандидатов нет — проверьте клетки или передвиньте ещё раз',
        'footer': 'Громкость прослушивания выровнена · Совпадение — НЕ шанс выпадения · abibuilder.com · v{ver}',
        'pickup_btn': '▶ Поднять',
        'drop_btn': '▶ Положить',
        'previewing': '🎧 Прослушиваю: ',
        'previewed': '✅ Прослушано: ',
        'mini_more': 'и ещё {n}',
        'mini_hint': 'Фильтр клеток применяется',
        'no_category': 'без категории',
    },
    'en': {
        'app_title': 'Field Merchant · Sound → Item',
        'header': '🎧 Field Merchant',
        'header_sub': 'sound → item',
        'subtitle': 'Drag a mystery good — the app shows candidate sound groups. '
                    'Tell items inside a group apart by grid size and price.',
        'device': 'Game audio device',
        'size': 'Item grid size',
        'start': '▶  Start',
        'stop': '⏹  Stop',
        'recognize': '⟳  Recognize last 2.3 s',
        'auto': 'Auto',
        'pin': 'Always on top',
        'clickthrough': 'Click-through mini',
        'mini_btn': '▣  Mini window',
        'mini_title': 'Mini',
        'status_idle': '1) Pick the game audio device   2) press Start   3) drag mystery goods',
        'status_stopped': '⏸ Stopped.',
        'listening': 'Listening',
        'status_not_enough': 'Not enough audio yet — start listening and drag the item',
        'status_matched': '✅ Matched — narrow the list by grid size',
        'err_listen': '⚠ Cannot listen to this device: ',
        'err_match': '⚠ Recognition failed: ',
        'err_play': '⚠ Playback failed: ',
        'err_dev_title': 'Device not found',
        'err_dev_msg': 'No playback devices available. Check Windows sound settings.',
        'banner_wait': '🎧 Waiting for sound…',
        'banner_none': '🔇 No recognizable sound',
        'banner_unsure': '🤔 Sound inconclusive — drag the item again',
        'conf_quick': 'quick match',
        'conf_low': 'quiet sound — double-check',
        'conf_music': 'music-filter match — double-check',
        'conf_again': 'better listen once more',
        'conf_ok': 'confident match ✔',
        'action_pickup': 'pickup',
        'action_drop': 'put-down',
        'score': 'Match',
        'peak': 'Peak',
        'group_word': 'GROUP',
        'items_match': 'match filter',
        'price': 'trader price:',
        'hint': 'Sound groups and items — press ▶ to compare by ear; items in one group sound the same',
        'empty': 'No candidates for this size — check the grid or drag again',
        'footer': 'Preview volume normalized · Match score is NOT drop chance · abibuilder.com · v{ver}',
        'pickup_btn': '▶ Pick up',
        'drop_btn': '▶ Put down',
        'previewing': '🎧 Previewing: ',
        'previewed': '✅ Previewed: ',
        'mini_more': '+{n} more',
        'mini_hint': 'Grid filter applies',
        'no_category': 'no category',
    },
    'zh': {
        'app_title': '暗区战地商人 · 听声识物',
        'header': '🎧 暗区战地商人',
        'header_sub': '听声识物',
        'subtitle': '拖动神秘货物，识别拾起或放下音效；结果按声音组展示，组内物品需结合占格判断。',
        'device': '游戏播放设备',
        'size': '货物占格（可旋转）',
        'start': '▶  开始监听',
        'stop': '⏹  停止监听',
        'recognize': '⟳  识别最近 2.3 秒',
        'auto': '自动识别',
        'pin': '窗口置顶',
        'clickthrough': '小窗鼠标穿透',
        'mini_btn': '▣  小窗',
        'mini_title': '小窗',
        'status_idle': '选择游戏使用的播放设备，然后点击开始监听。',
        'status_stopped': '已停止监听。',
        'listening': '正在监听',
        'status_not_enough': '还没有收集到足够的声音，请先开始监听并拖动物品。',
        'status_matched': '已识别。可用货物占格进一步筛选候选物品。',
        'err_listen': '⚠ 无法监听此设备：',
        'err_match': '⚠ 识别失败：',
        'err_play': '⚠ 音效播放失败：',
        'err_dev_title': '找不到设备',
        'err_dev_msg': '没有可用的系统播放设备。请检查 Windows 音频设置。',
        'banner_wait': '🎧 等待声音…',
        'banner_none': '🔇 未检测到可识别的声音',
        'banner_unsure': '🤔 声音不够明确，请再拖动一次',
        'conf_quick': '快速匹配',
        'conf_low': '低音量匹配，建议复核',
        'conf_music': '音乐抗干扰匹配，建议复核',
        'conf_again': '建议再听一次',
        'conf_ok': '匹配明确 ✔',
        'action_pickup': '拾起',
        'action_drop': '放下',
        'score': '匹配分',
        'peak': '峰值强度',
        'group_word': '音效组',
        'items_match': '件符合占格',
        'price': '联系人价格',
        'hint': '候选声音组及物品：点击 ▶ 试听数据库音效；同组物品共用声音',
        'empty': '当前占格没有候选物品；请核对占格或再录一次。',
        'footer': '试听音量已统一 · 匹配分与峰值强度均不是掉落概率 · abibuilder.com · v{ver}',
        'pickup_btn': '▶ 拾起',
        'drop_btn': '▶ 放下',
        'previewing': '正在试听：',
        'previewed': '已试听：',
        'mini_more': '还有 {n} 件',
        'mini_hint': '占格筛选生效中',
        'no_category': '未分类',
    },
}

SIZES = ['any', '1x1', '1x2', '2x1', '2x2', '2x3', '3x2']
SIZE_DISPLAY = {
    'ru': {'any': 'Любой', '1x1': '1×1', '1x2': '1×2', '2x1': '2×1', '2x2': '2×2', '2x3': '2×3', '3x2': '3×2'},
    'en': {'any': 'Any', '1x1': '1×1', '1x2': '1×2', '2x1': '2×1', '2x2': '2×2', '2x3': '2×3', '3x2': '3×2'},
    'zh': {'any': '不限', '1x1': '1×1', '1x2': '1×2', '2x1': '2×1', '2x2': '2×2', '2x3': '2×3', '3x2': '3×2'},
}

SAMPLE_RATE = 24000
CAPTURE_RATE = 48000
WINDOW_SECONDS = 2.3

# Apple-flavoured dark palette
BG = '#161719'
PANEL = '#1f2125'
PANEL2 = '#2a2d33'
BORDER = '#3a3e45'
TEXT = '#f5f5f7'
MUTED = '#98989d'
ACCENT = '#0a84ff'
ACCENT_DARK = '#0060df'
GREEN = '#30d158'
ORANGE = '#ff9f0a'
GOLD = '#ffd60a'
CYAN = '#64d2ff'
RARITY_COLOR = {6: '#ff453a', 5: '#ffd60a', 4: '#bf5af2', 3: '#64d2ff', 2: '#30d158', 1: '#f5f5f7'}


def font_family(lang: str) -> str:
    return 'Microsoft YaHei UI' if lang == 'zh' else 'Segoe UI'


def fmt_price(value: int) -> str:
    return f'{value:,}'.replace(',', ' ')


def score_bar(fraction: float) -> str:
    filled = round(max(0.0, min(1.0, fraction)) * 8)
    return '█' * filled + '░' * (8 - filled)


def items_word(n: int, lang: str) -> str:
    if lang == 'ru':
        if n % 100 in (11, 12, 13, 14):
            return 'предметов'
        if n % 10 == 1:
            return 'предмет'
        if n % 10 in (2, 3, 4):
            return 'предмета'
        return 'предметов'
    if lang == 'en':
        return 'item' if n == 1 else 'items'
    return '件物品'


def localized_category(category: str, lang: str) -> str:
    table = CATEGORY_L10N[lang]
    return category if table is None else table.get(category, category)


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


class PillButton(tk.Canvas):
    """Rounded "pill" button drawn on a canvas, macOS-flavoured."""

    def __init__(self, master, text: str, command, bg: str = ACCENT, fg: str = '#ffffff',
                 font_size: int = 10, padding_x: int = 16, height: int = 32, lang: str = 'en', **kwargs):
        self.pad = padding_x
        self.desired_h = height
        super().__init__(master, height=height, highlightthickness=0, bg=BG, **kwargs)
        family = font_family(lang)
        self.font = (family, font_size, 'bold')
        self.text = text
        self.command = command
        self.bg = bg
        self.fg = fg
        self._pressed = False
        self._draw()
        self.bind('<ButtonPress-1>', self._on_press)
        self.bind('<ButtonRelease-1>', self._on_release)
        self.bind('<Enter>', lambda _e: (setattr(self, '_hover', True), self._draw()))
        self.bind('<Leave>', lambda _e: (setattr(self, '_hover', False), self._draw()))

    def configure_text(self, text: str) -> None:
        self.text = text
        self._draw()

    def _on_press(self, _event) -> None:
        self._pressed = True
        self._draw()

    def _on_release(self, _event) -> None:
        self._pressed = False
        self._draw()
        if self.command:
            self.command()

    def _draw(self) -> None:
        self.delete('all')
        width = max(self.font[1] * int(len(self.text) * 0.62) + self.pad * 2, 60)
        self.configure(width=width)
        fill = self.bg
        if getattr(self, '_hover', False) and not self._pressed:
            fill = self._lighten(self.bg)
        elif self._pressed:
            fill = self._darken(self.bg)
        radius = self.desired_h // 2
        self.create_round_rect(1, 1, width - 1, self.desired_h - 1, radius, fill=fill, outline='')
        self.create_text(width // 2, self.desired_h // 2, text=self.text, font=self.font, fill=self.fg)

    def create_round_rect(self, x1, y1, x2, y2, r, **kwargs):
        points = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
                  x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.create_polygon(points, smooth=True, **kwargs)

    @staticmethod
    def _lighten(color: str) -> str:
        return '#%02x%02x%02x' % tuple(min(255, int(c * 1.18) + 12) for c in
                                       (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)))

    @staticmethod
    def _darken(color: str) -> str:
        return '#%02x%02x%02x' % tuple(max(0, int(c * 0.82)) for c in
                                       (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)))


class MiniOverlay:
    """Small always-on-top window with macOS-style chrome showing the current match."""

    def __init__(self, app: 'App') -> None:
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.configure(bg=BORDER)
        geometry = app.settings.get('mini_geo', '')
        if geometry:
            self.win.geometry(geometry)
        else:
            self.win.geometry(f'+{self.win.winfo_screenwidth() - 340}+120')
        self.visible = True
        self._drag_pos = None

        self.header = tk.Canvas(self.win, height=34, bg=PANEL, highlightthickness=0)
        self.header.pack(fill='x')
        self.header.create_oval(10, 11, 22, 23, fill='#ff5f57', outline='')
        self.header.create_oval(28, 11, 40, 23, fill='#febc2e', outline='')
        self.header.create_oval(46, 11, 58, 23, fill='#28c840', outline='')
        self.title_id = self.header.create_text(70, 17, anchor='w', fill=MUTED,
                                                font=(font_family(app.lang), 9, 'bold'))
        self.header.tag_bind(self.header.find_closest(10, 17)[0], '<Button-1>', lambda _e: self.hide())
        self.header.bind('<Button-1>', self._drag_start, add='+')
        self.header.bind('<B1-Motion>', self._drag_move, add='+')

        body = tk.Frame(self.win, bg=BG)
        body.pack(fill='both', expand=True)
        self.banner = tk.Label(body, text=STR[app.lang]['banner_wait'], bg=BG, fg=TEXT,
                               anchor='w', padx=12, pady=8, font=(font_family(app.lang), 11, 'bold'),
                               wraplength=280, justify='left')
        self.banner.pack(fill='x')
        self.list = tk.Text(body, height=7, wrap='word', bg=BG, fg=TEXT, relief='flat',
                            padx=12, pady=6, font=(font_family(app.lang), 9),
                            insertbackground='white', state='disabled', width=34)
        self.list.pack(fill='both', expand=True)
        for rarity, color in RARITY_COLOR.items():
            self.list.tag_configure(f'r{rarity}', foreground=color, font=(font_family(app.lang), 10, 'bold'))
        self.list.tag_configure('muted', foreground=MUTED, font=(font_family(app.lang), 8))
        self.list.tag_configure('rich', foreground=GOLD, font=(font_family(app.lang), 9, 'bold'))
        self.photos: list[ImageTk.PhotoImage] = []
        self.win.attributes('-alpha', 0.97)
        self._apply_click_through()
        self._keep_top()

    def _keep_top(self) -> None:
        if self.visible:
            self.win.attributes('-topmost', True)
            self.win.after(2000, self._keep_top)

    def _drag_start(self, event) -> None:
        self._drag_pos = (event.x, event.y)

    def _drag_move(self, event) -> None:
        if self._drag_pos:
            x = self.win.winfo_x() + event.x - self._drag_pos[0]
            y = self.win.winfo_y() + event.y - self._drag_pos[1]
            self.win.geometry(f'+{x}+{y}')
            self.app.settings['mini_geo'] = f'+{x}+{y}'

    def hide(self) -> None:
        self.visible = False
        self.win.withdraw()
        self.app.on_mini_hidden()

    def destroy(self) -> None:
        self.visible = False
        self.win.destroy()

    def _apply_click_through(self) -> None:
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -16)
            if self.app.click_through.get():
                style |= 0x80000 | 0x20  # WS_EX_LAYERED | WS_EX_TRANSPARENT
            else:
                style &= ~0x20
            ctypes.windll.user32.SetWindowLongW(hwnd, -16, style)
        except Exception:
            pass

    def apply_click_through(self) -> None:
        self.win.after(50, self._apply_click_through)

    def set_language(self, lang: str) -> None:
        self.header.itemconfigure(self.title_id, text=STR[lang]['mini_title'])
        self.banner.configure(font=(font_family(lang), 11, 'bold'))
        self.list.configure(font=(font_family(lang), 9))
        for rarity in RARITY_COLOR:
            self.list.tag_configure(f'r{rarity}', font=(font_family(lang), 10, 'bold'))
        self.list.tag_configure('muted', font=(font_family(lang), 8))
        self.list.tag_configure('rich', font=(font_family(lang), 9, 'bold'))

    def show_match(self, banner_text: str, banner_kind: str, rows: list[dict]) -> None:
        colors = {'good': ('#17301f', GREEN), 'warn': ('#33270d', ORANGE), 'info': (BG, CYAN)}
        bg, fg = colors.get(banner_kind, (BG, TEXT))
        self.banner.configure(bg=bg, fg=fg, text=banner_text)
        self.photos.clear()
        self.list.configure(state='normal')
        self.list.delete('1.0', 'end')
        shown = rows[:6]
        for row in shown:
            if row.get('photo') is not None:
                self.photos.append(row['photo'])
                self.list.image_create('end', image=row['photo'], padx=6)
            self.list.insert('end', row['name'] + '\n', f"r{row['rarity']}")
            price_tag = 'rich' if row['price'] >= 1_000_000 else 'muted'
            self.list.insert('end', f"   {row['size']}  ·  {fmt_price(row['price'])}\n", price_tag)
        hidden = len(rows) - len(shown)
        if hidden > 0:
            more = STR[self.app.lang]['mini_more'].replace('{n}', str(hidden))
            self.list.insert('end', more + '\n', 'muted')
        self.list.configure(state='disabled')


class App:
    def __init__(self, root: tk.Tk, lang: str = None) -> None:
        self.root = root
        try:
            self.settings = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
        except Exception:
            self.settings = {}
        self.lang = lang or self.settings.get('lang', 'zh')
        if self.lang not in LANGS:
            self.lang = 'zh'
        self.lang_var = tk.StringVar(value=LANG_NAMES[self.lang])
        root.title(STR[self.lang]['app_title'])
        root.geometry('800x620')
        root.minsize(700, 540)
        root.configure(bg=BG)
        self.matcher = Matcher()
        self.devices = [mic for mic in sc.all_microphones(include_loopback=True) if mic.isloopback]
        default = sc.default_speaker()
        self.device_name = tk.StringVar(value=next((mic.name for mic in self.devices if mic.name == default.name), self.devices[0].name if self.devices else ''))
        self.size = tk.StringVar(value=self.settings.get('size', 'any'))
        if self.size.get() not in SIZES:
            self.size.set('any')
        self.auto = tk.BooleanVar(value=self.settings.get('auto', True))
        self.pin_window = tk.BooleanVar(value=self.settings.get('pin', True))
        self.click_through = tk.BooleanVar(value=self.settings.get('clickthrough', False))
        self.status = tk.StringVar()
        self.top_result = tk.StringVar()
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
        self.banner_info: tuple[str, int, str, float, str, str] | None = None
        self.photos: list[ImageTk.PhotoImage] = []
        self.preview_buttons: list[ttk.Button] = []
        self.previewing = False
        self.preview_until = 0.0
        self.mini: MiniOverlay | None = None
        self._build()
        self._apply_banner_state()
        if self.settings.get('mini', True):
            self._mini_show()
        self._toggle_pin()
        root.after(75, self._drain_messages)
        root.after(250, self._auto_tick)
        root.protocol('WM_DELETE_WINDOW', self._close)

    # ------------------------------------------------------------- UI building

    def L(self, key: str) -> str:
        return STR[self.lang][key]

    def f(self, size: int, bold: bool = False) -> tuple:
        return (font_family(self.lang), size, 'bold') if bold else (font_family(self.lang), size)

    def _build(self) -> None:
        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                continue  # the mini overlay is rebuilt-in-place, not destroyed
            child.destroy()
        self.photos.clear()
        self.preview_buttons.clear()
        self.root.configure(bg=BG)
        self.root.title(self.L('app_title'))
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=TEXT, font=self.f(9))
        style.configure('TButton', padding=(10, 6), font=self.f(9), background=PANEL2,
                        foreground=TEXT, borderwidth=0, focusthickness=1, focuscolor=BORDER)
        style.map('TButton', background=[('pressed', BORDER), ('active', '#34383f')])
        style.configure('Small.TButton', padding=(5, 1), font=self.f(8), background=PANEL2, foreground=CYAN)
        style.map('Small.TButton', background=[('pressed', BORDER), ('active', '#34383f')])
        style.configure('TCombobox', padding=4, fieldbackground=PANEL2, background=PANEL2,
                        foreground=TEXT, arrowcolor=ACCENT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL2)], foreground=[('readonly', TEXT)])
        style.configure('TCheckbutton', background=BG, foreground=TEXT, font=self.f(9), focuscolor=BG)
        style.map('TCheckbutton', background=[('active', BG)], indicatorcolor=[('selected', ACCENT), ('!selected', PANEL2)])

        frame = ttk.Frame(self.root, padding=(16, 12, 16, 10))
        frame.pack(fill='both', expand=True)
        frame.lang = self.lang

        top = ttk.Frame(frame)
        top.pack(fill='x')
        ttk.Label(top, text=self.L('header'), font=self.f(15, True)).pack(side='left')
        ttk.Label(top, text='  ' + self.L('header_sub'), foreground=ACCENT, font=self.f(10)).pack(side='left', pady=(4, 0))
        lang_combo = ttk.Combobox(top, textvariable=self.lang_var, values=[LANG_NAMES[code] for code in LANGS],
                                  width=8, state='readonly')
        lang_combo.pack(side='right', padx=(8, 0))
        lang_combo.bind('<<ComboboxSelected>>', self._on_lang_selected)
        mini_button = ttk.Button(top, text=self.L('mini_btn'), command=self._mini_show)
        mini_button.pack(side='right', padx=(8, 0))
        ttk.Label(frame, text=self.L('subtitle'), foreground=MUTED, wraplength=740,
                  justify='left').pack(anchor='w', pady=(2, 10))

        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Label(row, text=self.L('device')).pack(side='left')
        self.device_combo = ttk.Combobox(row, textvariable=self.device_name, values=[mic.name for mic in self.devices],
                                         width=48, state='readonly')
        self.device_combo.pack(side='left', padx=7, fill='x', expand=True)
        ttk.Label(row, text=self.L('size')).pack(side='left', padx=(8, 0))
        size_values = [SIZE_DISPLAY[self.lang][code] for code in SIZES]
        size_combo = ttk.Combobox(row, textvariable=self.size, values=size_values, width=7, state='readonly')
        self.size.set(SIZE_DISPLAY[self.lang][self.size_code()])
        size_combo.pack(side='left', padx=7)
        size_combo.bind('<<ComboboxSelected>>', self._on_size_selected)

        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(12, 8))
        self.listen_button = PillButton(controls, self.L('start'), self._toggle, height=30, lang=self.lang)
        self.listen_button.pack(side='left')
        ttk.Button(controls, text=self.L('recognize'), command=lambda: self._submit(False)).pack(side='left', padx=8)
        ttk.Checkbutton(controls, text=self.L('auto'), variable=self.auto).pack(side='left', padx=(4, 8))
        ttk.Checkbutton(controls, text=self.L('pin'), variable=self.pin_window, command=self._toggle_pin).pack(side='left', padx=4)
        ttk.Checkbutton(controls, text=self.L('clickthrough'), variable=self.click_through,
                        command=lambda: (self._save(), self.mini.apply_click_through() if self.mini else None)).pack(side='left', padx=4)
        self.status_label = ttk.Label(frame, textvariable=self.status, foreground=ACCENT,
                                      wraplength=740, justify='left', font=self.f(9))
        self.status_label.pack(anchor='w')

        self.banner = tk.Label(frame, textvariable=self.top_result, bg=PANEL, fg=TEXT, anchor='w',
                               padx=14, pady=11, font=self.f(12, True), wraplength=740, justify='left')
        self.banner.pack(fill='x', pady=(8, 8), ipady=2)

        ttk.Label(frame, text=self.L('hint'), foreground=MUTED, font=self.f(8)).pack(anchor='w')
        result_frame = ttk.Frame(frame)
        result_frame.pack(fill='both', expand=True, pady=(5, 6))
        self.results = tk.Text(result_frame, height=14, wrap='word', bg=PANEL, fg=TEXT, insertbackground='white',
                               font=self.f(9), relief='flat', padx=14, pady=10, state='disabled',
                               highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER)
        self.results.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(result_frame, orient='vertical', command=self.results.yview)
        scrollbar.pack(side='right', fill='y')
        self.results.configure(yscrollcommand=scrollbar.set)
        self.results.tag_configure('group', foreground=CYAN, font=self.f(10, True), spacing1=10, spacing3=4)
        self.results.tag_configure('score', foreground=ACCENT, font=self.f(9))
        self.results.tag_configure('count', foreground=MUTED, font=self.f(9))
        for rarity, color in RARITY_COLOR.items():
            self.results.tag_configure(f'r{rarity}', foreground=color, font=self.f(10, True))
        self.results.tag_configure('en', foreground=MUTED, font=self.f(8))
        self.results.tag_configure('category', foreground='#d9b36c', font=self.f(8))
        self.results.tag_configure('detail', foreground=MUTED, font=self.f(8), lmargin1=62)
        self.results.tag_configure('rich', foreground=GOLD, font=self.f(9, True))
        self.results.tag_configure('hint', foreground=MUTED, font=self.f(9, 'italic'), spacing1=4)
        self.results.tag_configure('sep', foreground=BORDER, font=(self.f(8)[0], 8))
        ttk.Label(frame, text=self.L('footer').replace('{ver}', CATALOG['data_version']),
                  foreground='#6d6d72', font=self.f(7)).pack(anchor='w')

        if self.listening:
            self.listen_button.configure_text(self.L('stop'))
            self.status.set(f"🔊 {self.L('listening')}: {self.device_name.get()}")
        else:
            self.status.set(self.L('status_idle'))
        if self.last_ranked:
            self._render(self.last_ranked, self.last_metric)

    def size_code(self) -> str:
        for code in SIZES:
            if SIZE_DISPLAY[self.lang].get(code) == self.size.get():
                return code
        display_any_by_lang = {lang: SIZE_DISPLAY[lang]['any'] for lang in LANGS}
        if self.size.get() in display_any_by_lang.values():
            return 'any'
        for lang in LANGS:
            for code in SIZES:
                if SIZE_DISPLAY[lang][code] == self.size.get():
                    return code
        return 'any'

    def _on_size_selected(self, _event) -> None:
        self.settings['size'] = self.size_code()
        self._save()
        if self.last_ranked:
            self._render(self.last_ranked, self.last_metric)

    def _on_lang_selected(self, _event) -> None:
        names_to_code = {LANG_NAMES[code]: code for code in LANGS}
        code = names_to_code.get(self.lang_var.get(), 'zh')
        self._set_language(code)

    def _set_language(self, code: str) -> None:
        self.lang = code
        self.settings['lang'] = code
        self._save()
        if self.mini:
            self.mini.set_language(code)
        self._build()
        self._apply_banner_state()

    def _apply_banner_state(self) -> None:
        if self.banner_info:
            kind, sound_id, action, score, metric, conf_key = self.banner_info
            action_word = self.L('action_pickup' if action == 'pickup' else 'action_drop')
            if metric == 'cos':
                score_label = f"{self.L('score')} {score*100:.0f}/100"
            else:
                score_label = f"{self.L('peak')} {score:.1f}"
            self._banner(f"🔊 {self.L('group_word')} {sound_id} · {action_word} · {score_label} · {self.L(conf_key)}", kind)
        else:
            self._banner(self.L('banner_wait'))
        if self.mini and self.last_ranked:
            self._mini_refresh()

    def _save(self) -> None:
        try:
            SETTINGS_PATH.write_text(json.dumps(self.settings, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception:
            pass

    # ------------------------------------------------------------ mini overlay

    def _mini_show(self) -> None:
        if self.mini and self.mini.visible:
            return
        self.mini = MiniOverlay(self)
        self.mini.set_language(self.lang)
        self._apply_banner_state()
        self.settings['mini'] = True
        self._save()

    def on_mini_hidden(self) -> None:
        self.settings['mini'] = False
        self._save()

    def _mini_refresh(self) -> None:
        if not (self.mini and self.mini.visible and self.last_ranked):
            return
        if not self.mini.win.winfo_exists():
            self.mini = None
            return
        sound_id, _action, _score = self.last_ranked[0]
        rows = self._filtered_items(sound_id)
        rows = sorted(rows, key=lambda x: x.get('contactPrice') or 0, reverse=True)
        prepared = []
        for item in rows[:8]:
            photo = self._item_photo(item, 26)
            name = self._item_name(item)
            prepared.append({'photo': photo, 'name': name, 'rarity': item.get('rarity') or 1,
                             'price': item.get('contactPrice', 0),
                             'size': f"{item['size'][0]}×{item['size'][1]}"})
        self.mini.show_match(self.top_result.get(), getattr(self, '_banner_kind', 'idle'), prepared)

    # ---------------------------------------------------------------- capture

    def _toggle(self) -> None:
        if self.listening:
            self.listening = False
            self.listen_button.configure_text(self.L('start'))
            self.status.set(self.L('status_stopped'))
            self._banner(self.L('banner_wait'))
            if self.mini:
                self.mini.banner.configure(text=self.L('banner_wait'), bg=BG, fg=TEXT)
            return
        device = next((mic for mic in self.devices if mic.name == self.device_name.get()), None)
        if device is None:
            messagebox.showerror(self.L('err_dev_title'), self.L('err_dev_msg'))
            return
        self.chunks.clear()
        self.listening = True
        self.listen_button.configure_text(self.L('stop'))
        self.status.set(f"🔊 {self.L('listening')}: {device.name}")
        threading.Thread(target=self._capture, args=(device,), daemon=True).start()

    def _toggle_pin(self) -> None:
        self.root.attributes('-topmost', self.pin_window.get())
        self.settings['pin'] = self.pin_window.get()
        self._save()

    def _capture(self, device) -> None:
        try:
            with device.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=4800) as recorder:
                while self.listening:
                    chunk = recorder.record(numframes=4800).astype(np.float32)
                    with self.audio_lock:
                        self.chunks.append(chunk)
        except Exception as exc:
            self.messages.put(('error', self.L('err_listen') + str(exc)))

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
                self.status.set(self.L('status_not_enough'))
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
            self.messages.put(('error', self.L('err_match') + str(exc)))

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
                if hasattr(self, 'listen_button'):
                    self.listen_button.configure_text(self.L('start'))
            elif not self.previewing:
                self._show(message[1], message[2], message[3])
        self.root.after(75, self._drain_messages)

    # ---------------------------------------------------------------- display

    def _item_name(self, item: dict) -> str:
        if self.lang == 'ru':
            return NAME_RU.get(item['name'], item['name'])
        if self.lang == 'zh':
            return item.get('nameZh') or item['name']
        return item['name']

    def _item_photo(self, item: dict, px: int) -> ImageTk.PhotoImage | None:
        icon = BASE / 'icons' / f"{item['id']}.png"
        if not icon.exists():
            return None
        try:
            with Image.open(icon) as source:
                picture = source.convert('RGBA')
                picture.thumbnail((px, px), Image.Resampling.LANCZOS)
                canvas = Image.new('RGBA', (px + 8, px + 8), (0, 0, 0, 0))
                canvas.alpha_composite(picture, ((canvas.width - picture.width) // 2, (canvas.height - picture.height) // 2))
            return ImageTk.PhotoImage(canvas)
        except Exception:
            return None

    def _banner(self, text: str, kind: str = 'idle') -> None:
        colors = {'idle': (PANEL, TEXT), 'good': ('#17301f', GREEN), 'warn': ('#33270d', ORANGE), 'info': (PANEL, CYAN)}
        bg, fg = colors.get(kind, colors['idle'])
        self.banner.configure(bg=bg, fg=fg)
        self.top_result.set(text)
        self._banner_kind = kind

    def _filtered_items(self, sound_id: int) -> list[dict]:
        items = [item for item in CATALOG['items'] if item['soundId'] == sound_id]
        code = self.size_code()
        if code != 'any':
            a, b = map(int, code.split('x'))
            items = [item for item in items if sorted(item['size']) == sorted([a, b])]
        return items

    def _show(self, ranked: list[tuple[int, str, float]], prominent: list[tuple[int, str, float]], automatic: bool) -> None:
        if not ranked and not prominent:
            if not automatic:
                self._banner(self.L('banner_none'), 'info')
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
                self._banner(self.L('banner_unsure'), 'warn')
                self._render(ranked[:3], 'cos')
            self.tentative = None
            return
        sound_id, action, score = ranked[0]
        gap = score - (ranked[1][2] if len(ranked) > 1 else 0.0)
        if automatic:
            if metric == 'peak':
                conf_key, kind = 'conf_music', 'warn'
            elif score >= 0.40 and gap >= 0.15:
                conf_key, kind = 'conf_quick', 'good'
            else:
                conf_key, kind = 'conf_low', 'warn'
            now = time.monotonic()
            previous = self.tentative
            count = previous[2] + 1 if previous and previous[0] == sound_id and now - previous[1] <= 1.0 else 1
            self.tentative = (sound_id, now, count)
            if count < 2 and not (metric == 'cos' and score >= 0.75 and gap >= 0.30):
                return
            if self.last_match[0] != sound_id and now - self.last_match[1] < 0.75 and (metric == 'peak' or score < 0.75):
                return
        elif metric == 'peak':
            conf_key, kind = 'conf_music', 'warn'
        elif score < 0.60:
            conf_key, kind = 'conf_again', 'warn'
        else:
            conf_key, kind = 'conf_ok', 'good'
        if automatic and self.last_match[0] == sound_id and time.monotonic() - self.last_match[1] < 3:
            return
        self.last_match = (sound_id, time.monotonic())
        self.banner_info = (kind, sound_id, action, score, metric, conf_key)
        self._apply_banner_state()
        self.status.set(self.L('status_matched'))
        self._render(ranked[:3], metric)

    def _render(self, ranked: list[tuple[int, str, float]], metric: str = 'cos') -> None:
        self.last_ranked = ranked
        self.last_metric = metric
        for button in self.preview_buttons:
            button.destroy()
        self.preview_buttons.clear()
        self.photos.clear()
        self.results.configure(state='normal')
        self.results.delete('1.0', 'end')
        for index, (sound_id, action, score) in enumerate(ranked, 1):
            items = sorted(self._filtered_items(sound_id), key=lambda x: x.get('contactPrice') or 0, reverse=True)
            if metric == 'cos':
                score_label = f"{self.L('score')} {score*100:.0f}/100 {score_bar(score)}"
            else:
                score_label = f"{self.L('peak')} {score:.1f} {score_bar(score / 15)}"
            count_text = f"{len(items)} {items_word(len(items), self.lang)} {self.L('items_match')}" if self.lang != 'zh' \
                else f"{self.L('items_match')} {len(items)} 件"
            self.results.insert('end', f'{index}.  {self.L("group_word")} {sound_id}  ·  ', 'group')
            self.results.insert('end', f'{score_label}  ·  ', 'score')
            self.results.insert('end', f'{count_text}\n', 'count')
            if items:
                for item in items:
                    rarity = item.get('rarity') or 1
                    photo = self._item_photo(item, 40)
                    if photo is not None:
                        self.photos.append(photo)
                        self.results.image_create('end', image=photo, padx=4, pady=1)
                    else:
                        self.results.insert('end', '  •  ')
                    self.results.insert('end', f' {self._item_name(item)}  ', f'r{rarity}')
                    if self.lang == 'ru':
                        self.results.insert('end', f'[{item["name"]}]  ', 'en')
                    category = item.get('category', '')
                    category_text = localized_category(category, self.lang) if category else self.L('no_category')
                    self.results.insert('end', f'· {category_text} · {RARITY_L10N[self.lang].get(rarity, "—")}\n', 'category')
                    for preview_action, label_key in (('pickup', 'pickup_btn'), ('drop', 'drop_btn')):
                        button = ttk.Button(
                            self.results, text=self.L(label_key), style='Small.TButton',
                            command=lambda sid=sound_id, act=preview_action: self._preview(sid, act),
                        )
                        self.preview_buttons.append(button)
                        self.results.window_create('end', window=button, padx=2)
                    price = item.get('contactPrice', 0)
                    price_tail = f"{fmt_price(price)}\n" if price < 1_000_000 else ''
                    self.results.insert('end', f'      {item["size"][0]}×{item["size"][1]}  ·  {self.L("price")} ', 'detail')
                    if price_tail:
                        self.results.insert('end', price_tail, 'detail')
                    else:
                        self.results.insert('end', f'💰 {fmt_price(price)}\n', 'rich')
            else:
                self.results.insert('end', '   ' + self.L('empty') + '\n', 'hint')
            if index < len(ranked):
                self.results.insert('end', '─' * 90 + '\n', 'sep')
        self.results.configure(state='disabled')
        self.results.yview_moveto(0)
        self._mini_refresh()

    def _preview(self, sound_id: int, action: str) -> None:
        if self.previewing:
            return
        self.previewing = True
        self.tentative = None
        action_word = self.L('action_pickup' if action == 'pickup' else 'action_drop')
        self.status.set(f"{self.L('previewing')}{self.L('group_word')} {sound_id} · {action_word}")
        threading.Thread(target=self._play_reference, args=(sound_id, action, self.device_name.get()), daemon=True).start()

    def _play_reference(self, sound_id: int, action: str, device_name: str) -> None:
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
            action_word = self.L('action_pickup' if action == 'pickup' else 'action_drop')
            self.messages.put(('preview_done', f"{self.L('previewed')}{self.L('group_word')} {sound_id} · {action_word}"))
        except Exception as exc:
            self.messages.put(('preview_error', self.L('err_play') + str(exc)))

    def _close(self) -> None:
        self.listening = False
        self.settings['auto'] = self.auto.get()
        self.settings['pin'] = self.pin_window.get()
        self.settings['clickthrough'] = self.click_through.get()
        self._save()
        self.root.destroy()


if __name__ == '__main__':
    initial_lang = None
    for arg in sys.argv[1:]:
        if arg.startswith('--lang='):
            initial_lang = arg.split('=', 1)[1]
    window = tk.Tk()
    App(window, lang=initial_lang)
    window.mainloop()
