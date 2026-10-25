"""Per-user writable data, separate from the source checkout."""
import json
import os
import uuid
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'AkkoLinkMonitor'
DATA = Path(os.environ.get('AKKO_MONITOR_DATA_DIR') or
            Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'AkkoLinkMonitor')

def prepare():
    DATA.mkdir(parents=True,exist_ok=True)
    for name in ('logs','runtime'): (DATA/name).mkdir(exist_ok=True)
    probe=DATA/('.storage-probe-'+uuid.uuid4().hex)
    try:
        probe.write_bytes(b'')
        if probe.resolve().parent!=DATA.resolve():
            raise RuntimeError('数据目录被系统重定向；请从 Windows 桌面运行 Start-Monitor.vbs 或命名启动器。')
    finally:probe.unlink(missing_ok=True)
    try:import_legacy_data()
    except (OSError,ValueError,KeyError) as exc:
        save_json(DATA/'legacy-import-error.json',{'error':str(exc)})
    old=PROJECT/'settings.json'
    if not (DATA/'settings.json').exists() and old.exists():
        settings=json.loads(old.read_text(encoding='utf8'))
        if isinstance(settings,dict):
            allowed={k:v for k,v in settings.items() if k in ('hold_seconds','modifier_seconds','power_queries_enabled')}
            save_json(DATA/'settings.json',allowed)
    if (PROJECT/'logs').exists() and not os.environ.get('AKKO_MONITOR_DATA_DIR') and DATA.absolute()==DEFAULT_DATA.absolute():
        from .log_migration import merge_logs
        try:
            migrated=merge_logs(PROJECT/'logs',DATA/'logs')
            if migrated:save_json(DATA/'log-migration.json',{'verified_sessions':migrated})
            (DATA/'log-migration-error.json').unlink(missing_ok=True)
            (DATA/'legacy-locations.json').unlink(missing_ok=True)
        except (OSError,ValueError) as exc:
            save_json(DATA/'log-migration-error.json',{'error':str(exc)})

def import_legacy_data():
    """Import only this app's older MSIX-local data into the desktop root."""
    runtime_default=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'AkkoLinkMonitor'
    if os.environ.get('AKKO_MONITOR_DATA_DIR') or DATA.absolute()!=runtime_default.absolute():return
    packages=Path(os.environ.get('LOCALAPPDATA',DATA.parent))/'Packages'
    if not packages.exists():return
    from .log_migration import merge_logs
    imported=[]
    for package in packages.iterdir():
        old=package/'LocalCache/Local/AkkoLinkMonitor'
        if not old.is_dir() or old.resolve()==DATA.resolve():continue
        for name in ('settings.json','device.json'):
            source=old/name;target=DATA/name
            if source.exists() and (not target.exists() or source.stat().st_mtime>target.stat().st_mtime):
                shutil.copy2(source,target)
        source=old/'manual-markers.jsonl';target=DATA/'manual-markers.jsonl'
        if source.exists():
            lines=target.read_text(encoding='utf8').splitlines() if target.exists() else []
            known={json.loads(line)['marker_id'] for line in lines if line.strip()}
            previous=source.read_text(encoding='utf8').splitlines()
            for line in previous:
                if not line.strip():continue
                identity=json.loads(line)['marker_id']
                if identity not in known:lines.append(line);known.add(identity)
            temp=target.with_suffix('.tmp')
            temp.write_text('\n'.join(lines)+'\n',encoding='utf8');os.replace(temp,target)
            verified={json.loads(line)['marker_id'] for line in target.read_text(encoding='utf8').splitlines() if line.strip()}
            if not all(json.loads(line)['marker_id'] in verified for line in previous if line.strip()):
                raise OSError('旧手动标记校验失败')
        if (old/'logs').exists():
            imported.extend(merge_logs(old/'logs',DATA/'logs'))
    if imported:save_json(DATA/'msix-log-migration.json',{'verified_sessions':imported})

def save_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(temp,path)
