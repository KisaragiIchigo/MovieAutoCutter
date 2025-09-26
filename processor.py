# processor.py

import os
import logging
import subprocess
from tkinter import messagebox
import moviepy.editor as mp
import moviepy.audio.fx.all as afx
import tempfile
from typing import Tuple, List

from utils import ensure_unique_filename, ffmpeg_executable

logger = logging.getLogger(__name__)


# FFmpegが一度に扱えるconcatのストリーム数の上限（安全マージン込み）
# これを超えると 'Cannot allocate memory' エラーの危険性が高まる
MAX_CONCAT_STREAMS = 50 

def merge_and_optimize_ranges(ranges, min_duration_ms=500, gap_ms=100) -> list:
    """
    近接または重複する時間範囲をマージして最適化する。
    細切れの処理区間をまとめることで、処理効率を向上させる。
    """
    if not ranges: return []
    sorted_ranges = sorted(ranges, key=lambda x: x[0])
    merged = []
    if not sorted_ranges: return []
    current_start, current_end = sorted_ranges[0]
    for next_start, next_end in sorted_ranges[1:]:
        if next_start < current_end + gap_ms:
            # ギャップが指定ミリ秒未満なら、前の区間と結合
            current_end = max(current_end, next_end)
        else:
            # ギャップが大きければ、新しい区間として開始
            if current_end - current_start >= min_duration_ms:
                merged.append((current_start, current_end))
            current_start, current_end = next_start, next_end
    # 最後の区間を追加
    if current_end - current_start >= min_duration_ms:
        merged.append((current_start, current_end))
    return merged

def _run_ffmpeg_command(command: list, command_description: str) -> bool:
    """FFmpegコマンドをサブプロセスとして実行する共通関数。"""
    logger.info(f"{command_description}を実行します: " + " ".join(f'"{arg}"' if " " in arg else arg for arg in command))
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        if result.stderr: logger.info(f"FFmpeg ({command_description}) stderr:\n" + result.stderr)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpegの実行に失敗しました ({command_description})。")
        logger.error("FFmpeg stdout:\n" + e.stdout)
        logger.error("FFmpeg stderr:\n" + e.stderr)
        messagebox.showerror("エンコードエラー", f"{command_description}中に動画の書き出しに失敗しました。\n詳細はログを確認してください。\n\nエラー: {e.stderr.splitlines()[-1] if e.stderr else 'Unknown'}")
        return False

class _FFmpegFilterBuilder:
    """
    FFmpegの複雑なfilter_complexグラフ文字列を安全に構築するためのヘルパークラス。
    多数のクリップを結合する際のコマンド生成を単純化する。
    """
    def __init__(self, has_audio: bool, fps: float):
        self.has_audio = has_audio
        self.fps = fps
        self.video_filters = []  # 映像処理フィルターのリスト
        self.audio_filters = []  # 音声処理フィルターのリスト
        self.v_concat_inputs = "" # 結合する映像ストリーム名
        self.a_concat_inputs = "" # 結合する音声ストリーム名
        self.stream_counter = 0

    def add_clip(self, start_ms: float, end_ms: float):
        """指定された区間を通常のクリップとして追加する。"""
        if start_ms >= end_ms: return
        start_sec, end_sec = start_ms / 1000.0, end_ms / 1000.0
        # 映像ストリームをトリムして名前を付ける ([v0], [v1]...)
        self.video_filters.append(f"[0:v]trim=start={start_sec}:end={end_sec},setpts=PTS-STARTPTS[v{self.stream_counter}]")
        self.v_concat_inputs += f"[v{self.stream_counter}]"
        if self.has_audio:
            # 音声ストリームをトリムして名前を付ける ([a0], [a1]...)
            self.audio_filters.append(f"[0:a]atrim=start={start_sec}:end={end_sec},asetpts=PTS-STARTPTS[a{self.stream_counter}]")
            self.a_concat_inputs += f"[a{self.stream_counter}]"
        self.stream_counter += 1

    def add_speedup_clip(self, start_ms: float, end_ms: float, factor: float, volume: float):
        """指定された区間を倍速クリップとして追加する。"""
        if start_ms >= end_ms: return
        start_sec, end_sec = start_ms / 1000.0, end_ms / 1000.0
        
        # 映像のタイムスタンプを書き換えて倍速化
        self.video_filters.append(f"[0:v]trim=start={start_sec}:end={end_sec},setpts=PTS/{factor}-STARTPTS[v{self.stream_counter}]")
        self.v_concat_inputs += f"[v{self.stream_counter}]"
        if self.has_audio:
            atempo_chain = self._build_atempo_chain(factor)
            audio_chain = f"asetpts=PTS-STARTPTS"
            if atempo_chain: audio_chain += f",{atempo_chain}"
            audio_chain += f",volume={volume:.4f}"
            self.audio_filters.append(f"[0:a]atrim=start={start_sec}:end={end_sec},{audio_chain}[a{self.stream_counter}]")
            self.a_concat_inputs += f"[a{self.stream_counter}]"
        self.stream_counter += 1

    def _build_atempo_chain(self, factor: float) -> str:
        """atempoフィルターは一度に100倍までしか適用できないため、チェーンを構築する。"""
        if factor <= 1.0: return ""
        filters = []
        while factor > 100.0:
            filters.append("atempo=100.0"); factor /= 100.0
        if factor > 1.0: filters.append(f"atempo={factor:.4f}")
        return ",".join(filters)

    def build(self) -> Tuple[str, str, int]:
        """最終的なフィルターグラフ文字列を生成する。"""
        if self.stream_counter == 0: return "", "", 0
        # 全ての映像クリップを結合
        v_concat_filter = f"{self.v_concat_inputs}concat=n={self.stream_counter}:v=1:a=0,fps={self.fps}[outv]"
        self.video_filters.append(v_concat_filter)
        video_filter_complex = ";".join(self.video_filters)
        
        audio_filter_complex = ""
        if self.has_audio and self.a_concat_inputs:
            # 全ての音声クリップを結合
            a_concat_filter = f"{self.a_concat_inputs}concat=n={self.stream_counter}:v=0:a=1[outa]"
            self.audio_filters.append(a_concat_filter)
            audio_filter_complex = ";".join(self.audio_filters)

        return video_filter_complex, audio_filter_complex, self.stream_counter

def _process_chunk(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, video_duration_ms, config, builder_class, output_path):
    """動画の特定範囲（チャンク）を処理し、一時ファイルとして書き出す。"""
    with mp.VideoFileClip(file_path) as video:
        fps = video.fps if video.fps and video.fps > 0 else 30
        has_audio = video.audio is not None

    pre_cut_ms = pre_cut_seconds * 1000
    post_cut_ms = post_cut_seconds * 1000
    builder = builder_class(has_audio, fps)
    
    speedup_factor = config.get("speedup_factor", 5.0)
    speedup_volume = config.get("speedup_volume_percent", 50) / 100.0
    last_end_ms = 0.0

    for start_ms, end_ms in ranges_to_process:
        # マージンを適用した処理区間の開始・終了時間を計算
        proc_start = start_ms - pre_cut_ms
        proc_end = end_ms + post_cut_ms
        
        # ▼▼▼【バグ修正箇所】▼▼▼
        # 通常区間の終わりを「処理区間の開始時間」ではなく「マージンを適用した開始時間」にする
        builder.add_clip(last_end_ms, proc_start)
        
        if processing_mode == "倍速":
            builder.add_speedup_clip(proc_start, proc_end, speedup_factor, speedup_volume)
        
        # 次の通常区間の開始点として、元の区間の終了時間を使う
        last_end_ms = end_ms
    
    # 最後の処理区間以降の通常区間を追加
    builder.add_clip(last_end_ms, video_duration_ms)
    
    video_fc, audio_fc, stream_count = builder.build()
    if stream_count == 0: return True

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_video_path = os.path.join(temp_dir, "temp_video.mp4")
        temp_audio_path = os.path.join(temp_dir, "temp_audio.m4a")
        video_cmd = [ffmpeg_executable, "-y", "-i", file_path, "-filter_complex", video_fc, "-map", "[outv]", "-an", "-c:v", config["encoder_priority"][0], "-preset", "fast", temp_video_path]
        if not _run_ffmpeg_command(video_cmd, "映像処理"): return False
        if has_audio and audio_fc:
            audio_cmd = [ffmpeg_executable, "-y", "-i", file_path, "-filter_complex", audio_fc, "-map", "[outa]", "-vn", "-c:a", "aac", temp_audio_path]
            if not _run_ffmpeg_command(audio_cmd, "音声処理"): return False
        mux_cmd = [ffmpeg_executable, "-y", "-i", temp_video_path]
        if has_audio and os.path.exists(temp_audio_path): mux_cmd.extend(["-i", temp_audio_path])
        mux_cmd.extend(["-c", "copy", output_path])
        if not _run_ffmpeg_command(mux_cmd, "最終結合処理"): return False
    return True

def _process_with_moviepy(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, config, progress_callback, speedup_factor, speedup_volume):
    """MoviePyを使用して動画を処理する。"""
    try:
        video = mp.VideoFileClip(file_path)
    except Exception as e:
        logger.error(f"MoviePyでファイルを開けませんでした: {e}", exc_info=True)
        messagebox.showerror("ファイルオープンエラー", "動画ファイルを開けませんでした。")
        return

    dir_path, filename = os.path.split(file_path)
    edited_dir = os.path.join(dir_path, "[MovieAutoCutter Remake]")
    os.makedirs(edited_dir, exist_ok=True)
    output_path = os.path.join(edited_dir, ensure_unique_filename(edited_dir, filename))

    pre_cut_ms = pre_cut_seconds * 1000
    post_cut_ms = post_cut_seconds * 1000
    video_duration_ms = video.duration * 1000
    clips = []
    last_end_ms = 0
    total_ranges = len(ranges_to_process)
    for i, (start_ms, end_ms) in enumerate(ranges_to_process):
        proc_start_with_precut = max(last_end_ms, start_ms - pre_cut_ms)
        proc_end_with_postcut = min(video_duration_ms, end_ms + post_cut_ms)
        if proc_start_with_precut > last_end_ms:
            clips.append(video.subclip(last_end_ms / 1000.0, proc_start_with_precut / 1000.0))
        if processing_mode == "倍速" and proc_end_with_postcut > proc_start_with_precut:
            clip_to_speedup = video.subclip(proc_start_with_precut / 1000.0, proc_end_with_postcut / 1000.0)
            sped_up_clip = clip_to_speedup.fx(mp.vfx.speedx, speedup_factor)
            if sped_up_clip.audio:
                 sped_up_clip.audio = sped_up_clip.audio.fx(afx.volumex, speedup_volume)
            clips.append(sped_up_clip)
        last_end_ms = end_ms
        progress_callback(i + 1, total_ranges, "クリップを準備中")
    if last_end_ms < video_duration_ms:
        clips.append(video.subclip(last_end_ms / 1000.0, video.duration))
    if not clips:
        logger.info("処理の結果、クリップが空になりました。"); video.close(); return
    final_clip = mp.concatenate_videoclips(clips, method="compose")
    logger.info("最終的な動画をレンダリング中...")
    encoder_priority = config.get("encoder_priority", ["libx264"])
    cpu_threads = config.get("cpu_encoder_threads", 4)
    success = False
    for codec in encoder_priority:
        try:
            final_clip.write_videofile(output_path, codec=codec, audio_codec="aac", preset="fast", threads=cpu_threads if codec == "libx264" else None, logger=None, fps=video.fps)
            success = True; break
        except Exception:
            logger.warning(f"'{codec}' でのエンコードに失敗しました。")
    final_clip.close(); video.close()
    if success:
        messagebox.showinfo("変換完了", f"動画の変換が完了しました！\n保存場所: {output_path}")
    else:
        messagebox.showerror("エンコードエラー", "動画の書き出しに失敗しました。")

# vvv この関数を修正 vvv
def cut_or_speedup_video(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, config, progress_callback, speedup_factor=5.0, speedup_volume=1.0):
    """動画処理のメインコントローラー。"""
    use_ffmpeg_direct = config.get("use_ffmpeg_direct", True)

    # 修正された部分: FFmpegのフィルターグラフが長くなりすぎる場合にMoviePyモードに切り替える
    if use_ffmpeg_direct:
        with mp.VideoFileClip(file_path) as video:
            has_audio = video.audio is not None
        
        # 処理区間の数と、それらの間に挟まる通常区間の合計ストリーム数で判定
        stream_count = len(ranges_to_process) * 2 + 1
        if has_audio:
            # 音声も処理する場合、音声ストリームも考慮
            stream_count = len(ranges_to_process) * 2 + 1
        
        if stream_count > MAX_CONCAT_STREAMS:
            logger.warning(f"FFmpegのストリーム数が上限({MAX_CONCAT_STREAMS})を超過するため、MoviePyモードに強制的に切り替えます。")
            progress_callback(0, 100, "MoviePyモード強制移行処理中...", "red")
            use_ffmpeg_direct = False

    if use_ffmpeg_direct:
        logger.info("FFmpeg直接呼び出しモードで処理を開始します。")
        try:
            dir_path, filename = os.path.split(file_path)
            edited_dir = os.path.join(dir_path, "[MovieAutoCutter Remake]")
            os.makedirs(edited_dir, exist_ok=True)
            output_path = os.path.join(edited_dir, ensure_unique_filename(edited_dir, filename))
            with mp.VideoFileClip(file_path) as video:
                video_duration_ms = video.duration * 1000
            
            if _process_chunk(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, video_duration_ms, config, _FFmpegFilterBuilder, output_path):
                progress_callback(1, 1, "完了")
                messagebox.showinfo("変換完了", f"動画の変換が完了しました！\n保存場所: {output_path}")
        except Exception as e:
            logger.error(f"FFmpeg直接呼び出しでエラーが発生しました: {e}", exc_info=True)
            logger.warning("MoviePyを使用したフォールバック処理を試みます。")
            _process_with_moviepy(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, config, progress_callback, speedup_factor, speedup_volume)
    else:
        logger.info("MoviePyモードで処理を開始します。")
        _process_with_moviepy(file_path, ranges_to_process, processing_mode, pre_cut_seconds, post_cut_seconds, config, progress_callback, speedup_factor, speedup_volume)