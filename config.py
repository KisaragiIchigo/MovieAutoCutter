"""
設定ファイルの読み書きを担当するモジュール。
設定はJSON形式で保存され、アプリケーションの動作をカスタマイズする。
"""

import os
import json
from utils import application_path

CONFIG_DIR = os.path.join(application_path, "config")
os.makedirs(CONFIG_DIR, exist_ok=True) 
CONFIG_FILE = os.path.join(CONFIG_DIR, "[config]moviecut_config.json")

def load_config() -> dict:
    """
    設定ファイル(moviecutconfig.json)を読み込む。
    ファイルが存在しない、または破損している場合はデフォルト設定を返す。
    """
    default = default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as file:
                config = json.load(file)
                # デフォルト設定を読み込んだ設定で上書き（新しい設定項目への追従のため）
                default.update(config)
                return default
        except json.JSONDecodeError:
            return default
    return default

def default_config() -> dict:
    """
    デフォルトの設定値を返す。
    初回起動時や設定ファイルが壊れている場合に使用される。
    """
    return {
        "processing_mode": "カット",
        "cut_mode": "映像音声",
        "pre_cut_seconds": 2.0,  # 処理区間の手前に設けるマージン（秒）
        "post_cut_seconds": 1.0,  # 処理区間の後に設けるマージン（秒）
        "speedup_factor": 5.0,  # 倍速モードのデフォ倍率
        "speedup_volume_percent": 50,  # 倍速時の音量（パーセント）
        "video_analysis_scale": 0.25,  # 映像解析時の解像度スケール（小さいほど高速）
        "min_silence_duration_ms": 500,  # 無音と判断する最小時間（ミリ秒）
        "min_static_duration_ms": 500,  # 静止と判断する最小時間（ミリ秒）
        "use_ffmpeg_direct": True,  # FFmpeg直接呼び出しを優先するか
        "encoder_priority": ["h264_nvenc", "h2ve_videotoolbox", "libx264"], # 優先使用するエンコーダー
        "cpu_encoder_threads": 4  # CPUエンコード時のスレッド数
    }

def save_config(config: dict):
    """
    現在の設定をJSONファイルに保存する。
    """
    with open(CONFIG_FILE, "w") as file:
        json.dump(config, file, indent=4)