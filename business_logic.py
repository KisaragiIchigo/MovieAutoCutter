"""
アプリケーションの「頭脳」部分。
GUIからの指示を受け取り、解析(tools)と処理(processor)の各モジュールを呼び出し、
データの受け渡しや処理フローを制御する。
"""
import os
import logging
import moviepy.editor as mp
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox
from typing import Callable

from utils import application_path, ffmpeg_executable
from audio_tools import analyze_audio_dB, detect_silence_based_on_dB
from video_tools import analyze_video_motion, detect_central_static_frames
from processor import merge_and_optimize_ranges, cut_or_speedup_video

logger = logging.getLogger(__name__)

# --- データ転送用のクラス ---
class AnalysisResult:
    """解析結果を保持するためのデータクラス。"""
    def __init__(self, audio_data=None, video_data=None, error=None):
        self.audio_data = audio_data
        self.video_data = video_data
        self.error = error
        self.file_path = "" # 処理中にファイルパスが必要な場合があるため

class ProcessingSettings:
    """GUIから受け取った処理設定を保持するためのデータクラス。"""
    def __init__(self, file_path, config, silence_thresh, movement_thresh, mode, processing_mode, pre_cut_seconds, post_cut_seconds, speedup_factor=5.0, speedup_volume=0.5):
        self.file_path = file_path
        self.config = config
        self.silence_thresh = silence_thresh
        self.movement_thresh = movement_thresh
        self.mode = mode
        self.processing_mode = processing_mode
        self.pre_cut_seconds = pre_cut_seconds
        self.post_cut_seconds = post_cut_seconds
        self.speedup_factor = speedup_factor
        self.speedup_volume = speedup_volume

# --- 解析ロジック ---
def analyze_media(file_path: str, config: dict, progress_callback) -> AnalysisResult:
    """
    動画ファイルの音声と映像を並行して解析する。
    重い処理なので、スレッドプールを使用してUIが固まるのを防ぐ。
    """
    audio_path = os.path.join(application_path, "temp_audio.wav")
    try:
        def progress_wrapper(base_progress, total_range, task_name):
            # 全体(100%)のうち、各タスクが占める割合に応じて進捗を再計算するラッパー
            def inner_callback(value, maximum):
                progress_value = base_progress + (value / maximum) * total_range
                progress_callback(progress_value, 100, task_name)
            return inner_callback

        with ThreadPoolExecutor(max_workers=2) as executor:
            # 音声解析と映像解析を別々のスレッドで実行
            future_audio = executor.submit(_analyze_audio_task, file_path, config, progress_wrapper(0, 50, "音声解析中"), audio_path)
            future_video = executor.submit(_analyze_video_task, file_path, config, progress_wrapper(50, 50, "映像解析中"))
            audio_data, video_data = future_audio.result(), future_video.result()

        if isinstance(audio_data, Exception) or isinstance(video_data, Exception):
             raise (audio_data if isinstance(audio_data, Exception) else video_data)

        progress_callback(100, 100, "解析完了")
        return AnalysisResult(audio_data=audio_data, video_data=video_data)
    except Exception as e:
        logger.error(f"メディアファイルの解析中にエラーが発生しました: {e}", exc_info=True)
        return AnalysisResult(error=e)
    finally:
        # 一時ファイルを削除
        if os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except OSError as e: logger.warning(f"一時音声ファイルの削除に失敗しました: {e}")

def _analyze_audio_task(file_path, config, progress_callback, audio_path):
    """音声解析を実行するタスク。"""
    try:
        logger.info("音声ファイルを抽出・解析中...")
        if not ffmpeg_executable:
            logger.warning("ffmpegが見つからないため、音声解析をスキップします。")
            return -90, -90, -90, []
        
        with mp.VideoFileClip(file_path) as video_clip:
            if video_clip.audio:
                # 動画から音声をwavとして一時的に抽出
                video_clip.audio.write_audiofile(audio_path, codec="pcm_s16le", logger=None)
                min_db, max_db, avg_db, loudness_dBs = analyze_audio_dB(
                    audio_path, config.get("audio_chunk_ms", 100), progress_callback)
                logger.info(f"音声解析完了: 平均dB={avg_db:.2f}")
                return min_db, max_db, avg_db, loudness_dBs
            else:
                logger.warning("動画に音声トラックがありません。音声解析をスキップします。")
                progress_callback(1, 1); return -90, -90, -90, []
    except Exception as e:
        logger.error(f"音声解析タスクでエラー: {e}", exc_info=True); return e

def _analyze_video_task(file_path, config, progress_callback):
    """映像解析を実行するタスク。"""
    try:
        logger.info("映像の動きを解析中...")
        min_motion, max_motion, avg_motion, motion_diffs = analyze_video_motion(
            file_path, config.get("video_crop_ratio", 0.25),
            config.get("video_analysis_scale", 0.25), progress_callback)
        logger.info(f"映像解析完了: 平均動き量={avg_motion:.2f}")
        return min_motion, max_motion, avg_motion, motion_diffs
    except Exception as e:
        logger.error(f"映像解析タスクでエラー: {e}", exc_info=True); return e


# --- 処理ロジック ---
def create_progress_callback_adapter(progress_callback: Callable) -> Callable:
    """
    processorに渡すためのprogress_callbackを生成する。
    引数の数が異なるコールバックを仲介するためのアダプター。
    """
    def adapter(value, maximum, label="", color=None):
        progress_callback(value, maximum, label or "動画をレンダリング中", color)
    return adapter

def process_video(settings: ProcessingSettings, progress_callback):
    """GUIから受け取った設定に基づき、動画処理のフロー全体を制御する。"""
    try:
        # ... (前半の区間検出ロジックは変更なし) ...
        mode, config = settings.mode, settings.config
        silence_ranges, static_ranges = [], []
        if mode in ["音声", "映像音声"]:
            if ffmpeg_executable:
                audio_path = os.path.join(application_path, "temp_audio_detect.wav")
                try:
                    with mp.VideoFileClip(settings.file_path) as vc:
                        if vc.audio:
                            logger.info("無音区間を検出中..."); vc.audio.write_audiofile(audio_path, codec="pcm_s16le", logger=None)
                            silence_ranges = detect_silence_based_on_dB(audio_path, settings.silence_thresh, config.get("audio_chunk_ms", 100))
                            logger.info(f"無音区間候補を {len(silence_ranges)}箇所検出しました。")
                finally:
                    if os.path.exists(audio_path): os.remove(audio_path)
        if mode in ["映像", "映像音声"]:
            logger.info("静止区間を検出中...")
            static_ranges = detect_central_static_frames(
                settings.file_path, settings.movement_thresh, config.get("video_crop_ratio", 0.25),
                config.get("video_analysis_scale", 0.25))
            logger.info(f"静止区間候補を {len(static_ranges)}箇所検出しました。")
        logger.info("カット範囲を統合・最適化中...")
        if mode == "音声": ranges_to_process = merge_and_optimize_ranges(silence_ranges, config.get("min_silence_duration_ms", 500))
        elif mode == "映像": ranges_to_process = merge_and_optimize_ranges(static_ranges, config.get("min_static_duration_ms", 500))
        else:
            merged_silence = merge_and_optimize_ranges(silence_ranges, config.get("min_silence_duration_ms", 500))
            merged_static = merge_and_optimize_ranges(static_ranges, config.get("min_static_duration_ms", 500))
            ranges_to_process = merge_and_optimize_ranges(merged_silence + merged_static, 100)
        if not ranges_to_process:
            messagebox.showinfo("情報", "処理対象となる区間が見つかりませんでした。"); return
        logger.info(f"最終的な処理対象区間: {len(ranges_to_process)}箇所")

        # 処理モジュールに最終的な設定を渡して実行
        cut_or_speedup_video(
            settings.file_path,
            ranges_to_process,
            settings.processing_mode,
            settings.pre_cut_seconds,
            settings.post_cut_seconds,
            config,
            create_progress_callback_adapter(progress_callback),
            speedup_factor=settings.speedup_factor,
            speedup_volume=settings.speedup_volume
        )
            
    except Exception as e:
        logger.error(f"動画処理中に致命的なエラーが発生しました: {e}", exc_info=True)
        messagebox.showerror("処理エラー", f"予期せぬエラーが発生しました。")