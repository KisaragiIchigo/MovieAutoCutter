"""
映像解析に関連する関数群。
OpenCVを使用して、フレーム間の差分を計算し、動きの少ない静止区間を検出する。
"""

import cv2
import numpy as np
import logging
from typing import Iterator, Tuple

logger = logging.getLogger(__name__)

def get_central_frame_diff(frame1: np.ndarray, frame2: np.ndarray, crop_ratio: float = 0.25) -> float:
    """
    2つのフレームの中央クロップ領域の差分絶対値合計を計算する。
    画面の端（テロップなど）の影響を無視するために中央部のみを比較する。
    """
    if frame1 is None or frame2 is None: return 0.0
    h, w = frame1.shape[:2]
    top, bottom = int(h * crop_ratio), int(h * (1 - crop_ratio))
    left, right = int(w * crop_ratio), int(w * (1 - crop_ratio))
    
    crop_frame1 = frame1[top:bottom, left:right]
    crop_frame2 = frame2[top:bottom, left:right]
    
    if crop_frame1.size == 0: return 0.0
    
    # 差分の絶対値を計算し、ピクセル数で割って正規化
    return np.sum(cv2.absdiff(crop_frame1, crop_frame2)) / crop_frame1.size

def _iterate_frames_for_diff(video_path: str, scale_factor: float, crop_ratio: float) -> Iterator[Tuple[int, float]]:
    """
    動画を1フレームずつ読み込み、前のフレームとの差分を計算して返すイテレータ。
    コードの重複を避けるための共通ヘルパー関数。
    """
    video = cv2.VideoCapture(video_path)
    if not video.isOpened():
        logger.error(f"動画ファイルを開けませんでした: {video_path}")
        return

    try:
        ret, prev_frame = video.read()
        if not ret: return

        # 解析を高速化するためにフレームを縮小し、グレースケールに変換
        prev_frame_resized = cv2.resize(prev_frame, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
        prev_frame_gray = cv2.cvtColor(prev_frame_resized, cv2.COLOR_BGR2GRAY)
        
        frame_num = 0
        while True:
            ret, frame = video.read()
            if not ret: break
            frame_num += 1
            
            frame_resized = cv2.resize(frame, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_AREA)
            frame_gray = cv2.cvtColor(frame_resized, cv2.COLOR_BGR2GRAY)
            
            diff = get_central_frame_diff(prev_frame_gray, frame_gray, crop_ratio)
            yield frame_num, diff
            
            prev_frame_gray = frame_gray
    finally:
        video.release() # 確実にビデオオブジェクトを解放する

def analyze_video_motion(video_path: str, crop_ratio: float, scale_factor: float, progress_callback) -> Tuple[float, float, float, list]:
    """
    動画全体のフレーム間の動き（差分）を解析する。

    Returns:
        tuple: (最小差分, 最大差分, 平均差分, 差分リスト)
    """
    video = cv2.VideoCapture(video_path)
    if not video.isOpened(): return 0, 0, 0, []
    frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    video.release()

    motion_diffs = []
    for i, diff in _iterate_frames_for_diff(video_path, scale_factor, crop_ratio):
        motion_diffs.append(diff)
        if i % 30 == 0: # 30フレームごとに進捗を更新
            progress_callback(i, frame_count)
            
    if not motion_diffs: return 0, 0, 0, []
    
    return min(motion_diffs), max(motion_diffs), np.mean(motion_diffs), motion_diffs

def detect_central_static_frames(video_path: str, movement_thresh: float, crop_ratio: float, scale_factor: float) -> list:
    """
    設定された動きしきい値以下の「静止区間」を検出する。

    Returns:
        list: 検出された静止区間のリスト [(開始ミリ秒, 終了ミリ秒), ...]
    """
    video = cv2.VideoCapture(video_path)
    if not video.isOpened(): return []
    fps = video.get(cv2.CAP_PROP_FPS)
    fps = fps if fps > 0 else 30 # FPSが取得できない場合のフォールバック
    total_frames = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    video.release()
    
    static_ranges = []
    is_in_static, static_start_frame = False, 0

    frame_iterator = _iterate_frames_for_diff(video_path, scale_factor, crop_ratio)
    
    last_frame_num = 0
    for frame_num, diff in frame_iterator:
        is_static_now = diff < movement_thresh
        
        if is_static_now and not is_in_static:
            is_in_static = True
            static_start_frame = frame_num
        elif not is_static_now and is_in_static:
            is_in_static = False
            start_ms = (static_start_frame / fps) * 1000
            end_ms = (frame_num / fps) * 1000
            static_ranges.append((start_ms, end_ms))
        last_frame_num = frame_num

    # ループ終了後、静止区間が続いていた場合の処理
    if is_in_static:
        start_ms = (static_start_frame / fps) * 1000
        end_ms = (total_frames / fps) * 1000 # 最後のフレームまでを区間とする
        static_ranges.append((start_ms, end_ms))

    return static_ranges