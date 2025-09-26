"""
アプリケーションのエントリーポイント。
ここからアプリケーションを起動する。
ロギング設定、FFmpegの存在チェック、メインウィンドウの生成を行う。
"""
import sys
import os
import customtkinter
from tkinter import messagebox
import logging
import shutil
from gui import App
from utils import ffmpeg_executable, setup_logging, application_path

def setup_required_modules():
    """初回起動時に必要なモジュールをバンドルから展開する。"""
    logger = logging.getLogger(__name__)
    if getattr(sys, 'frozen', False):
        required_modules = ["tkinterdnd2", "tkdnd2.8"] # 例として追加
        for module_name in required_modules:
            dest_path = os.path.join(application_path, module_name)
            bundled_path = os.path.join(sys._MEIPASS, module_name)
            if not os.path.exists(dest_path) and os.path.exists(bundled_path):
                logger.info(f"'{module_name}' をバンドルから展開します...")
                try:
                    shutil.copytree(bundled_path, dest_path)
                except Exception as e:
                    logger.error(f"'{module_name}' の展開に失敗しました: {e}")

if __name__ == "__main__":
    # アプリケーション全体のロギングを設定
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("アプリケーションを起動します。")

    # 初回モジュール展開処理を呼び出す
    setup_required_modules()

    # FFmpegが存在しない場合、警告を表示して処理を続行する
    if ffmpeg_executable is None:
        logger.warning("FFmpegが見つかりませんでした。音声処理は実行できません。")
        # メッセージボックス表示のための一時的な非表示ウィンドウ
        root_warn = customtkinter.CTk()
        root_warn.withdraw()
        messagebox.showwarning(
            "FFmpegが見つかりません",
            "FFmpegが見つかりませんでした。音声処理ができません。\n"
            "FFmpegをインストールし、環境変数PATHに追加するか、"
            "実行ファイルと同じフォルダにffmpeg.exeを配置してください。"
        )
        root_warn.destroy()

    try:
        # メインアプリケーションのインスタンスを作成し、実行
        app = App()
        app.mainloop()
    except Exception as e:
        # 予期せぬエラーをキャッチし、ログに記録してユーザーに通知
        logger.critical(f"アプリケーションの実行中に致命的なエラーが発生しました: {e}", exc_info=True)
        root_err = customtkinter.CTk()
        root_err.withdraw()
        messagebox.showerror("致命的なエラー", f"アプリケーションがクラッシュしました。\n詳細はログファイルを確認してください。\n\nエラー: {e}")
        root_err.destroy()
    finally:
        logger.info("アプリケーションを終了します。")