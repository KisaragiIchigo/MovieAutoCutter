"""
アプリケーションのGUIを構築・制御するモジュール。
ウィンドウ、ボタン、グラフなどの表示とイベント処理を行う。
"""
import os
import sys
import logging
import tkinter as tk
from tkinter import messagebox
from concurrent.futures import ThreadPoolExecutor

import customtkinter
from tkinterdnd2 import DND_FILES, TkinterDnD
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import moviepy.editor as mp
import numpy as np

from config import load_config, save_config
from utils import (FONT_NORMAL, FONT_LARGE, FONT_BOLD, setup_logging,
                   show_readme)
import business_logic
from business_logic import ProcessingSettings, AnalysisResult

logger = logging.getLogger(__name__)

class App(TkinterDnD.Tk):
    """アプリケーションのルートウィンドウ。"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.title("Movie🎦AutoCutter✂©️2025 KisaragiIchigo")
        self.geometry("700x500")
        if hasattr(sys, '_MEIPASS'): # PyInstallerで実行された場合のアイコン設定
            try:
                icon_path = os.path.join(sys._MEIPASS, "movcut.ico")
                if os.path.exists(icon_path): self.iconbitmap(icon_path)
            except Exception as e:
                logger.warning(f"アイコンファイルの読み込みに失敗しました: {e}")
        self.main_frame = MainApplication(self)
        self.main_frame.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)

    def on_app_close(self):
        """ウィンドウが閉じられるときにスレッドプールを安全にシャットダウンする。"""
        logger.info("Executorをシャットダウンしています...")
        self.main_frame.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()

class MainApplication(customtkinter.CTkFrame):
    """メインアプリケーションフレーム。D&Dエリア、ログ表示、進捗バーなどを配置。"""
    def __init__(self, parent, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.parent = parent
        self.config = load_config()
        self.file_path = None
        self.is_processing = False # 処理中の二重実行を防ぐフラグ
        self.executor = ThreadPoolExecutor(max_workers=1) # 重い処理をバックグラウンドで実行
        self.create_widgets()
        setup_logging(self.log_textbox) # ログ出力をGUIのテキストボックスにリダイレクト

    def create_widgets(self):
        """メインウィンドウのウィジェットを作成・配置する。"""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # D&Dを受け付けるラベル
        self.drop_label = customtkinter.CTkLabel(self, text="動画ファイルをここにドラッグ＆ドロップしてください",
                                                 fg_color="#4169e1", corner_radius=10, font=FONT_LARGE)
        self.drop_label.grid(row=0, column=0, padx=10, pady=10, sticky="nsew", ipady=20)
        
        # ログ表示用テキストボックス
        self.log_textbox = customtkinter.CTkTextbox(self, wrap=tk.WORD, font=FONT_NORMAL)
        self.log_textbox.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.log_textbox.configure(state="disabled")
        
        # 進捗表示フレーム
        progress_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        progress_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        progress_frame.grid_columnconfigure(0, weight=1)
        self.progress_bar = customtkinter.CTkProgressBar(progress_frame)
        self.progress_bar.grid(row=0, column=0, sticky="ew")
        self.progress_bar.set(0)
        self.progress_label = customtkinter.CTkLabel(progress_frame, text="", font=FONT_NORMAL)
        self.progress_label.grid(row=1, column=0, sticky="w")
        
        # ボタンフレーム
        button_frame = customtkinter.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=3, column=0, padx=10, pady=10, sticky="ew")
        self.readme_button = customtkinter.CTkButton(button_frame, text="READMEを表示",
                                                    command=lambda: show_readme(self.parent), font=FONT_NORMAL)
        self.readme_button.pack(side="left")
        
        # D&Dイベントの登録
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.on_drop)

    def update_progress(self, value, maximum, label="", color=None):
        """進捗を更新する。ビジネスロジックやプロセッサから呼び出される。"""
        def _update():
            if maximum > 0: self.progress_bar.set(value / maximum)
            else: self.progress_bar.set(0)
            if color is None: # 通常のテキストカラーを取得
                label_color = customtkinter.ThemeManager.theme["CTkLabel"]["text_color"]
            else:
                label_color = color
            self.progress_label.configure(text=f"{label} ({value}/{maximum})", text_color=label_color)
        self.parent.after(0, _update) # メインスレッドでUIを安全に更新

    def on_drop(self, event):
        """ファイルがドロップされたときの処理。"""
        if self.is_processing:
            logger.warning("現在処理中です。完了するまでお待ちください。")
            return
        raw_path = event.data.strip()
        self.file_path = raw_path.strip('{}') if '{' in raw_path and '}' in raw_path else raw_path
        if not os.path.exists(self.file_path):
            logger.error(f"ファイルが見つかりません - {self.file_path}")
            return
        self.is_processing = True
        logger.info(f"ファイルがドロップされました: {os.path.basename(self.file_path)}")
        self.executor.submit(self.run_analysis_task, self.file_path)

    def run_analysis_task(self, file_path):
        """バックグラウンドでメディア解析タスクを実行する。"""
        result = business_logic.analyze_media(file_path, self.config, self.update_progress)
        self.parent.after(0, self.on_analysis_complete, result)

    def on_analysis_complete(self, result: AnalysisResult):
        """解析完了後、メインスレッドで呼び出され、設定ウィンドウを開く。"""
        if result.error:
            logger.error(f"解析エラー: {result.error}")
            messagebox.showerror("解析エラー", f"ファイルの解析中にエラーが発生しました。")
            self.is_processing = False
            return
        ThresholdWindow(self, self.file_path, self.config, result)

    def start_processing_task(self, settings: ProcessingSettings):
        """バックグラウンドで動画処理タスクを実行する。"""
        try:
            business_logic.process_video(settings, self.update_progress)
        except Exception as e:
            logger.error(f"処理タスクで予期せぬエラー: {e}", exc_info=True)
            messagebox.showerror("処理エラー", f"予期せぬエラーが発生しました: {e}")
        finally:
            self.is_processing = False
            logger.info("全ての処理が完了しました。")

class GraphController:
    """グラフ(Matplotlib)の描画とイベント処理を担当するクラス。"""
    def __init__(self, master, fig, analysis_result, config, audio_entry, video_entry):
        self.master = master
        self.fig = fig
        self.analysis_result = analysis_result
        self.config = config
        self.audio_thresh_entry = audio_entry
        self.video_thresh_entry = video_entry
        self.ax_audio = self.fig.add_subplot(211)
        self.ax_video = self.fig.add_subplot(212)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.master)
        self.audio_line = None
        self.video_line = None

    def get_widget(self):
        return self.canvas.get_tk_widget()

    def initial_draw(self):
        """初期グラフ描画とイベントリスナーの設定。"""
        self.draw_graphs()
        self.fig.canvas.mpl_connect('button_press_event', self.on_graph_click)

    def draw_graphs(self):
        """音声と映像の解析結果をグラフに描画する。"""
        self.ax_audio.clear(); self.ax_video.clear()
        min_db, max_db, avg_db, loudness_dBs = self.analysis_result.audio_data
        min_motion, max_motion, avg_motion, motion_diffs = self.analysis_result.video_data
        
        self.ax_audio.set_title("音声dBレベル（グラフをクリックしてしきい値を設定）")
        if loudness_dBs:
            # ... グラフ描画ロジック ...
            time_axis_audio = np.arange(len(loudness_dBs)) * self.config.get("audio_chunk_ms", 100) / 1000.0
            self.ax_audio.plot(time_axis_audio, loudness_dBs, color='cyan', alpha=0.8)
        self.audio_line = self.ax_audio.axhline(y=float(self.audio_thresh_entry.get()), color='red', linestyle='--')

        self.ax_video.set_title("映像の動き（グラフをクリックしてしきい値を設定）")
        if motion_diffs:
            # ... グラフ描画ロジック ...
            with mp.VideoFileClip(self.analysis_result.file_path) as clip: fps = clip.fps if clip.fps else 30
            time_axis_video = np.arange(len(motion_diffs)) / fps
            self.ax_video.plot(time_axis_video, motion_diffs, color='lime', alpha=0.8)
        self.video_line = self.ax_video.axhline(y=float(self.video_thresh_entry.get()), color='red', linestyle='--')
        
        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()

    def on_graph_click(self, event):
        """グラフがクリックされたときに、しきい値入力欄を更新する。"""
        if event.inaxes == self.ax_audio and event.ydata:
            self.update_threshold_entry(self.audio_thresh_entry, self.audio_line, event.ydata)
        elif event.inaxes == self.ax_video and event.ydata:
            self.update_threshold_entry(self.video_thresh_entry, self.video_line, event.ydata)
        self.canvas.draw()

    def update_threshold_entry(self, entry, line, value):
        """エントリーウィジェットとグラフのしきい値線を更新する。"""
        entry.delete(0, tk.END); entry.insert(0, f"{value:.2f}")
        line.set_ydata([value, value])

class ThresholdWindow(customtkinter.CTkToplevel):
    """しきい値設定用のトップレベルウィンドウ。"""
    def __init__(self, parent_app: MainApplication, file_path, config, analysis_result: AnalysisResult):
        # ... (initの前半は変更なし) ...
        super().__init__(parent_app.parent)
        self.parent_app = parent_app
        self.file_path = file_path
        self.config = config
        self.analysis_result = analysis_result
        analysis_result.file_path = file_path
        self.title("しきい値設定"); self.geometry("900x800")
        self.transient(parent_app.parent)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.create_variables()
        self.create_widgets()
        self.graph_controller = GraphController(self.graph_frame, Figure(figsize=(8, 6), dpi=100), self.analysis_result, self.config, self.audio_thresh_entry, self.video_thresh_entry)
        self.graph_controller.get_widget().grid(row=0, column=0, sticky="nsew")
        self.graph_controller.initial_draw()
        self.toggle_speedup_settings()

    def create_variables(self):
        self.speedup_factor_var = customtkinter.DoubleVar(value=self.config.get("speedup_factor", 5.0))
        self.speedup_volume_var = customtkinter.IntVar(value=self.config.get("speedup_volume_percent", 50))
        self.processing_mode_var = customtkinter.StringVar(value=self.config.get("processing_mode", "カット"))
        self.mode_var = customtkinter.StringVar(value=self.config.get("cut_mode", "音声"))

    def create_widgets(self):
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
        main_frame = customtkinter.CTkFrame(self)
        main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        main_frame.grid_columnconfigure(0, weight=1); main_frame.grid_rowconfigure(0, weight=1)
        self.graph_frame = customtkinter.CTkFrame(main_frame)
        self.graph_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)
        self.graph_frame.grid_columnconfigure(0, weight=1); self.graph_frame.grid_rowconfigure(0, weight=1)
        settings_frame = customtkinter.CTkFrame(main_frame)
        settings_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=10)
        settings_frame.grid_columnconfigure((1, 3), weight=1)
        
        lbl_font, entry_font, combo_font = FONT_NORMAL, FONT_NORMAL, FONT_NORMAL

        # --- 基本設定 ---
        customtkinter.CTkLabel(settings_frame, text="音声しきい値 (dB):", font=lbl_font).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.audio_thresh_entry = customtkinter.CTkEntry(settings_frame)
        self.audio_thresh_entry.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.audio_thresh_entry.insert(0, f"{self.analysis_result.audio_data[2] / 1.5:.2f}")

        customtkinter.CTkLabel(settings_frame, text="映像しきい値:", font=lbl_font).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.video_thresh_entry = customtkinter.CTkEntry(settings_frame)
        self.video_thresh_entry.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.video_thresh_entry.insert(0, f"{self.analysis_result.video_data[2] / 2.0:.2f}")
        
        customtkinter.CTkLabel(settings_frame, text="処理前マージン(秒):", font=lbl_font).grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.pre_cut_entry = customtkinter.CTkEntry(settings_frame)
        self.pre_cut_entry.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        self.pre_cut_entry.insert(0, str(self.config.get("pre_cut_seconds", 2.0)))
        
        customtkinter.CTkLabel(settings_frame, text="処理後マージン(秒):", font=lbl_font).grid(row=3, column=0, padx=5, pady=5, sticky="w")
        self.post_cut_entry = customtkinter.CTkEntry(settings_frame)
        self.post_cut_entry.grid(row=3, column=1, padx=5, pady=5, sticky="ew")
        self.post_cut_entry.insert(0, str(self.config.get("post_cut_seconds", 1.0)))
        
        self.processing_mode_var.trace_add("write", self.toggle_speedup_settings)
        customtkinter.CTkLabel(settings_frame, text="処理モード:", font=lbl_font).grid(row=0, column=2, padx=(10,5), pady=5, sticky="w")
        self.processing_mode_var.trace_add("write", self.toggle_speedup_settings)
        processing_mode_menu = customtkinter.CTkComboBox(settings_frame, variable=self.processing_mode_var, values=["カット", "倍速"], state="readonly", font=combo_font, dropdown_font=combo_font)
        processing_mode_menu.grid(row=0, column=3, padx=5, pady=5, sticky="ew")

        customtkinter.CTkLabel(settings_frame, text="対象:", font=lbl_font).grid(row=1, column=2, padx=(10,5), pady=5, sticky="w")
        mode_menu = customtkinter.CTkComboBox(settings_frame, variable=self.mode_var, values=["音声", "映像"], state="readonly", font=combo_font, dropdown_font=combo_font)
        mode_menu.grid(row=1, column=3, padx=5, pady=5, sticky="ew")

        # 倍速設定と実行ボタン
        self.speedup_frame = customtkinter.CTkFrame(main_frame, fg_color="transparent")
        self.speedup_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        self.speedup_frame.grid_columnconfigure(1, weight=1)
        customtkinter.CTkLabel(self.speedup_frame, text="倍速率 (1.1倍～15倍):", font=lbl_font).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        customtkinter.CTkSlider(self.speedup_frame, from_=1.1, to=15.0, variable=self.speedup_factor_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        customtkinter.CTkEntry(self.speedup_frame, textvariable=self.speedup_factor_var, width=60).grid(row=0, column=2, padx=5, pady=5)
        customtkinter.CTkLabel(self.speedup_frame, text="倍速部分の音量 (%):", font=lbl_font).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        customtkinter.CTkSlider(self.speedup_frame, from_=0, to=100, variable=self.speedup_volume_var).grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        customtkinter.CTkEntry(self.speedup_frame, textvariable=self.speedup_volume_var, width=60).grid(row=1, column=2, padx=5, pady=5)
        self.execute_button = customtkinter.CTkButton(main_frame, text="実行", command=self.execute_processing, font=FONT_BOLD)
        self.execute_button.grid(row=3, column=0, columnspan=2, padx=5, pady=10, ipady=10, sticky="se")


    def on_close(self):
        """ウィンドウが閉じられるときに設定を保存し、親アプリの状態を更新。"""
        self.parent_app.is_processing = False
        self.update_config_and_save()
        self.destroy()

    def toggle_speedup_settings(self, *args):
        """処理モードが「倍速」のときのみ、関連設定を表示する。"""
        if self.processing_mode_var.get() == "倍速": self.speedup_frame.grid()
        else: self.speedup_frame.grid_remove()

    def update_config_and_save(self):
        """UIの状態をconfigに反映し、ファイルに保存する。"""
        self.config["processing_mode"] = self.processing_mode_var.get()
        self.config["cut_mode"] = self.mode_var.get()
        try:
            self.config["pre_cut_seconds"] = float(self.pre_cut_entry.get())
            self.config["post_cut_seconds"] = float(self.post_cut_entry.get())
        except (ValueError, TypeError):
            pass # 不正値なら何もしない
        self.config["speedup_factor"] = self.speedup_factor_var.get()
        self.config["speedup_volume_percent"] = self.speedup_volume_var.get()
        save_config(self.config)

    def execute_processing(self):
        """「実行」ボタンが押されたときの処理。"""
        try:
            settings = ProcessingSettings(
                file_path=self.file_path, config=self.config,
                silence_thresh=float(self.audio_thresh_entry.get()),
                movement_thresh=float(self.video_thresh_entry.get()),
                mode=self.mode_var.get(),
                processing_mode=self.processing_mode_var.get(),
                pre_cut_seconds=float(self.pre_cut_entry.get()),
                post_cut_seconds=float(self.post_cut_entry.get()),
                speedup_factor=self.speedup_factor_var.get(),
                speedup_volume=self.speedup_volume_var.get() / 100.0
            )
        except ValueError as e:
            messagebox.showerror("入力エラー", f"無効な数値が入力されています: {e}"); return
        
        self.update_config_and_save()
        logger.info("処理設定を確定し、実行を開始します...")
        self.parent_app.start_processing_task(settings)
        self.destroy()