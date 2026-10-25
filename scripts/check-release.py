"""Read-only release allowlist and accidental personal-data/secret checks."""
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
TOP_FILES={'.gitignore','README.md','LICENSE','app.py','Start-Monitor.vbs'}
TOP_DIRS={'src','tests','docs','scripts'}

def public_files():
    files=[ROOT/n for n in sorted(TOP_FILES) if (ROOT/n).is_file()]
    for folder in sorted(TOP_DIRS):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file()
                     and not any(part in ('__pycache__','verification') for part in p.relative_to(ROOT).parts)
                     and p.suffix not in ('.pyc','.pyo','.log','.tmp','.lnk','.jsonl'))
    return sorted(files)

def check():
    issues=[];private=[]
    # Inputs only from local ignored data, never embed this user's identifiers.
    for p in (ROOT/'identity.py',ROOT/'verification/legacy-source/identity.py'):
        if p.exists():private+=re.findall(r"BT_ADDRESS\s*=\s*['\"]([0-9A-Fa-f]{12})",p.read_text(encoding='utf8'))
    username=os.environ.get('USERNAME','')
    for p in public_files():
        relative=str(p.relative_to(ROOT))
        if p.is_symlink():issues.append(relative+': 不允许发布符号链接');continue
        if p.suffix.lower() in ('.exe','.dll','.zip','.dat','.csv'):
            issues.append(relative+': 非发布源文件');continue
        try:text=p.read_text(encoding='utf-8-sig')
        except UnicodeError:issues.append(relative+': 非 UTF-8 文本');continue
        if any(v.lower() in text.lower() for v in private):issues.append(relative+': 包含本机蓝牙地址')
        if re.search(r'(?i)[a-z]:[\\/]Users[\\/](?!Public[\\/])',text):issues.append(relative+': 包含个人绝对路径')
        if username and re.search(r'\b'+re.escape(username)+r'\b',text,re.I):issues.append(relative+': 包含当前 Windows 用户名')
        if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})',text):issues.append(relative+': 疑似 GitHub 令牌')
    return issues

if __name__=='__main__':
    issues=check()
    for issue in issues:print(issue)
    print(f'发布候选 {len(public_files())} 个文件；问题 {len(issues)} 项。真实日志、分析、配置及固件不在候选中。')
    raise SystemExit(bool(issues))
