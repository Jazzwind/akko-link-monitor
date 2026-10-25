"""Copy-only verified merge. Archiving originals is a separate explicit step."""
import hashlib
from pathlib import Path
import shutil
import uuid

def manifest(folder):
    if folder.is_symlink() or getattr(folder.lstat(),'st_file_attributes',0)&0x400:
        raise OSError('日志会话根目录含链接')
    result={}
    for p in sorted(folder.rglob('*')):
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400:
            raise OSError('日志中含链接，停止自动迁移')
        if p.is_file():result[str(p.relative_to(folder))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result

def merge_logs(source,destination):
    source=Path(source).absolute();destination=Path(destination).absolute()
    if source.name!='logs' or destination.name!='logs':raise ValueError('Only named log directories may be merged')
    if not source.exists():return []
    # Verify resolved absolute roots and containment before copying.
    if source.resolve()!=source or destination.resolve()!=destination:
        raise OSError('日志根目录含链接，不自动迁移')
    if source==destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Source and destination must be disjoint log roots')
    destination.mkdir(parents=True,exist_ok=True)
    records=[]
    for folder in sorted(source.iterdir()):
        if not folder.is_dir():raise OSError('旧日志根目录存在非会话文件，保留原件')
        if folder.resolve().parent!=source or folder.is_symlink():raise OSError('旧会话目录越界')
        before=manifest(folder);target=destination/folder.name;index=1
        while target.exists() and (not target.is_dir() or manifest(target)!=before):
            target=destination/f'{folder.name}-legacy-{index}';index+=1
        if not target.exists():
            staging=destination/('.migrating-'+uuid.uuid4().hex)
            shutil.copytree(folder,staging)
            if manifest(staging)!=before or manifest(folder)!=before:
                raise OSError('日志在迁移时发生变化；原件保留')
            staging.rename(target)
        if manifest(target)!=before or manifest(folder)!=before:raise OSError('迁移核验失败；原件保留')
        if folder.resolve().parent!=source or target.resolve().parent!=destination:raise OSError('迁移目录越界')
        records.append({'source_session':folder.name,'destination_session':target.name,'file_count':len(before),'source_retained':True})
    return records
