# "MovieAutoCutter"/utils.py

"""
共通して使用される便利関数や定数を定義するモジュール。
フォント設定、パス解決、ロギング設定など、アプリケーション全体で必要な機能を提供する。
"""

import os
import sys
import platform
import logging
from pydub.utils import which
from pydub import AudioSegment
import customtkinter
import matplotlib
import shutil


# GUIの描画バックエンドとしてTkAggを指定
matplotlib.use('TkAgg')

def get_font_name() -> str:
    """OSに応じて適切な日本語フォント名を返す。"""
    os_name = platform.system()
    if os_name == "Windows": return "Meiryo"
    elif os_name == "Darwin": return "Hiragino Sans"
    else: return "sans-serif" # Linuxなど

FONT_NAME = get_font_name()
try:
    # Matplotlibのデフォルトフォントを設定
    matplotlib.rcParams['font.family'] = FONT_NAME
    matplotlib.rcParams['font.size'] = 9
except Exception:
    matplotlib.rcParams['font.family'] = 'sans-serif' # フォント設定失敗時のフォールバック
    
# アプリケーション内で使用するフォント定義
FONT_NORMAL = (FONT_NAME, 13)
FONT_LARGE = (FONT_NAME, 16)
FONT_BOLD = (FONT_NAME, 16, "bold")

# CustomTkinterのテーマ設定
customtkinter.set_appearance_mode("System")
customtkinter.set_default_color_theme("blue")

def get_application_path() -> str:
    """
    アプリケーションの実行パスを取得する。
    PyInstallerでexe化された場合はexeのあるディレクトリを、
    スクリプトとして実行された場合はこのファイルのあるディレクトリを返す。
    """
    if getattr(sys, 'frozen', False):
        # exeとして実行されている場合
        return os.path.dirname(sys.executable)
    else:
        # スクリプトとして実行されている場合
        return os.path.dirname(os.path.abspath(__file__))

# このパスをアプリケーション全体で共有する
application_path = get_application_path()

def get_ffmpeg_path() -> str or None:
    """
    システム内のFFmpeg実行可能ファイルのパスを検索する。
    exeにバンドルされたffmpegを優先的に探す。
    初回起動時にexeから外部に展開する処理を追加。
    """
    # PyInstallerでパッケージ化されている場合
    if getattr(sys, 'frozen', False):
        # 実行ファイルと同じフォルダにffmpeg.exeがあるか確認
        dest_path = os.path.join(application_path, "ffmpeg.exe")
        if os.path.exists(dest_path):
            return dest_path
        
        # なければ、_MEIPASSからコピーする
        bundled_path = os.path.join(sys._MEIPASS, "ffmpeg.exe")
        if os.path.exists(bundled_path):
            try:
                shutil.copy2(bundled_path, dest_path)
                return dest_path
            except Exception as e:
                logger.error(f"バンドルされたffmpegの展開に失敗しました: {e}")
                
    # 環境変数PATHからffmpegを検索
    return which("ffmpeg")

ffmpeg_executable = get_ffmpeg_path()
if ffmpeg_executable:
    AudioSegment.converter = ffmpeg_executable

def setup_logging(textbox_widget=None):
    """アプリケーションのロギングを設定する。ファイルとGUIテキストボックスに出力。"""
    log_dir = os.path.join(application_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "moviecutapp.log")
    
    # 既存のハンドラをクリアして再設定
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', encoding='utf-8', handlers=[logging.FileHandler(log_file_path, mode='w'), logging.StreamHandler(sys.stdout)])
    
    # GUIのテキストボックスにもログを出力するカスタムハンドラ
    if textbox_widget:
        class TextboxHandler(logging.Handler):
            def __init__(self, textbox):
                super().__init__(); self.textbox = textbox
                self.setFormatter(logging.Formatter('%(message)s')); self.setLevel(logging.INFO)
            def emit(self, record): self.textbox.after(0, self.append_message, self.format(record))
            def append_message(self, msg):
                self.textbox.configure(state="normal"); self.textbox.insert(customtkinter.END, msg + "\n")
                self.textbox.see(customtkinter.END); self.textbox.configure(state="disabled")
        root_logger.addHandler(TextboxHandler(textbox_widget))

def ensure_unique_filename(directory: str, filename: str) -> str:
    """同名ファイルが存在する場合、連番を付けてユニークなファイル名を返す。"""
    base, ext = os.path.splitext(filename)
    counter = 1
    unique_filename = filename
    while os.path.exists(os.path.join(directory, unique_filename)):
        unique_filename = f"{base}_{counter}{ext}"
        counter += 1
    return unique_filename

def show_readme(parent):
    """READMEを表示する新しいウィンドウを開く。"""
    readme_window = customtkinter.CTkToplevel(parent)
    readme_window.title("README"); readme_window.geometry("900x550"); readme_window.transient(parent)
    
    readme_text_content = (
        "【ツールタイトル】\n"
        "MovieAutoCutter\n\n"
        "【ツール概要】\n"
        "動画の無音区間や動きのない区間をアルゴリズムが解析し、自動でカットまたは倍速処理するアプリケーションです。\n\n"
        "【特徴】\n"
        "- 簡単操作: 動画ファイルをドラッグ＆ドロップするだけで解析が始まります。\n"
        "- 直感的な「しきい値」設定: 解析結果のグラフをクリックするだけで、カットや倍速の基準となるしきい値を直感的に設定できます。\n"
        "- 2つの処理モード: 不要な区間を完全に「カット」するか、高速再生する「倍速」モードかを選択できます。\n"
        "- 柔軟な解析対象: 「音声のみ」「映像の動きのみ」「両方」のいずれかを基準に処理対象区間を決められます。\n"
        "- 安定性重視の自動モード切替: カット・倍速区間が非常に多い動画を処理する場合、メモリ不足によるクラッシュを防ぐため、自動的に低速ながら安定した「MoviePyモード」に切り替わります。\n"
        "- GPUエンコード対応: NVIDIA(NVENC)等のGPUエンコード環境では、動画の書き出しが高速になる可能性があります。\n\n"
        "【使い方】\n"
        "1. 動画ファイルをウィンドウにドラッグ＆ドロップします。\n"
        "2. 解析完了後、グラフと設定ウィンドウが表示されます。\n"
        "3. グラフ上のカットしたい部分（例：静かな部分、動きのない部分）をクリックし、しきい値（赤い点線）を調整します。\n"
        "4. 処理モード（カット or 倍速）、対象（音声/映像）を選択します。\n"
        "5. 処理前マージン（デフォルト2秒）と処理後マージン（デフォルト1秒）を設定します。これは、処理区間の少し手前と後を処理を開始するための時間です。\n"
        "6. 「実行」ボタンをクリックすると処理が開始されます。\n"
        "7. 処理済みの動画は、元の動画があるフォルダ内の `[MovieAutoCutter]` フォルダに保存されます。\n\n"
        "【注意】\n"
        "- 平均しきい値から大きく外れた値を設定すると、意図しない結果になる可能性があります。\n"
        "- MoviePyモードに切り替わった場合、処理に時間がかかることがあります。\n\n"
        "©️2025 KisaragiIchigo"
    )

    textbox = customtkinter.CTkTextbox(readme_window, wrap="word", font=FONT_NORMAL)
    textbox.pack(expand=True, fill='both', padx=10, pady=10)
    textbox.insert("0.0", readme_text_content)
    textbox.configure(state="disabled")