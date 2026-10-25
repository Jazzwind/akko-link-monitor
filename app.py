"""Compatibility launcher; implementation lives in src/akko_monitor."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
if __name__=='__main__':
    try:
        from akko_monitor.entry import main
        raise SystemExit(main())
    except Exception:
        import traceback,ctypes
        from akko_monitor.paths import DATA
        DATA.mkdir(parents=True,exist_ok=True)
        (DATA/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        ctypes.windll.user32.MessageBoxW(None,'启动失败，请检查本地数据目录的 startup-error.log。','AKKO Link Monitor',16)
        raise
