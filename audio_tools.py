"""
音声解析に関連する関数群。
"""
import numpy as np
from pydub import AudioSegment
from pydub.utils import make_chunks

def analyze_audio_dB(audio_path: str, chunk_length_ms: int, progress_callback) -> tuple:
    """
    指定された音声ファイルのdBFS（デジタルフルスケールに対するデシベル）を解析する。

    Args:
        audio_path (str): 解析対象の音声ファイルパス。
        chunk_length_ms (int): 音声を分割するチャンクの長さ（ミリ秒）。
        progress_callback (Callable): 進捗をGUIに通知するためのコールバック関数。

    Returns:
        tuple: (最小dB, 最大dB, 平均dB, dB値のリスト)
    """
    audio = AudioSegment.from_file(audio_path)
    chunks = make_chunks(audio, chunk_length_ms)
    loudness_dBs = [-90.0] * len(chunks)  # 無音は-infだが、扱いやすいように-90dBとする
    for i, chunk in enumerate(chunks):
        if chunk.rms > 0:  # RMSが0（完全な無音）でなければdBFSを計算
            loudness_dBs[i] = chunk.dBFS
        if i % 20 == 0:  # 処理が重いので、適度に間引いて進捗を通知
            progress_callback(i, len(chunks))
    
    valid_dbs = [db for db in loudness_dBs if db > -90.0] # 有効なdB値のみで統計計算
    if not valid_dbs:
        return -90, -90, -90, []
    
    return min(valid_dbs), max(valid_dbs), np.mean(valid_dbs), loudness_dBs

def detect_silence_based_on_dB(audio_path: str, silence_thresh_dB: float, chunk_length_ms: int) -> list:
    """
    音声ファイルから、指定されたdBしきい値以下の無音区間を検出する。

    Args:
        audio_path (str): 解析対象の音声ファイルパス。
        silence_thresh_dB (float): このdB値未満を無音と判断する。
        chunk_length_ms (int): 音声を分割するチャンクの長さ（ミリ秒）。

    Returns:
        list: 検出された無音区間のリスト [(開始ミリ秒, 終了ミリ秒), ...]
    """
    audio = AudioSegment.from_file(audio_path)
    silence_ranges = []
    is_in_silence, silence_start_time = False, 0
    chunks = make_chunks(audio, chunk_length_ms)
    for i, chunk in enumerate(chunks):
        time_ms = i * chunk_length_ms
        is_silent_chunk = chunk.dBFS < silence_thresh_dB if chunk.rms > 0 else True
        if is_silent_chunk:
            if not is_in_silence:
                # 無音区間の開始
                is_in_silence = True
                silence_start_time = time_ms
        elif is_in_silence:
            # 無音区間の終了
            is_in_silence = False
            silence_ranges.append((silence_start_time, time_ms))
    
    # ファイルの最後まで無音だった場合の処理
    if is_in_silence:
        silence_ranges.append((silence_start_time, len(audio)))
        
    return silence_ranges