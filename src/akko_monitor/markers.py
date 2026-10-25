"""Explicit incident marks persist independently of continuous logging."""
import json
import os
from pathlib import Path
import time
import uuid
from datetime import datetime

class MarkerStore:
    def __init__(self,folder):self.path=Path(folder)/'manual-markers.jsonl'
    def append(self,context,when=None):
        row=dict(context,marker_id=uuid.uuid4().hex,
                 event_time=datetime.fromtimestamp(time.time() if when is None else when).astimezone().isoformat(timespec='milliseconds'),
                 classification='subjective_user_observation_not_confirmed_fault')
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.open('a',encoding='utf8',newline='\n') as f:
            f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())
        return row
