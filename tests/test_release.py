import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from akko_monitor import identity

class ReleaseTests(unittest.TestCase):
    def test_discovery_does_not_bind_another_keyboard(self):
        values={r'BTHLE\DEV_AABBCCDDEEFF\fixture':'AKKO 3098 BT-1',
                r'BTHLE\DEV_112233445566\fixture':'Other keyboard'}
        with patch.object(identity,'nodes',lambda:list(values)),patch.object(identity,'read_property',lambda node,*args:((values[node]+'\0').encode('utf-16-le'),18)):
            rows=identity.discover()
        self.assertEqual([r['address'] for r in rows],['AABBCCDDEEFF'])

    def test_no_binding_collects_no_bluetooth(self):
        previous=identity.BT_ADDRESS
        try:
            identity.configure('')
            self.assertEqual(identity.source_for('hid#00001812-0000-1000-8000-00805f9b34fb_0001_aabbccddeeff&col01'),'')
        finally:identity.configure(previous)

    @unittest.skipUnless(shutil.which('git'),'Git unavailable')
    def test_ignore_allowlist_excludes_all_private_roots(self):
        project=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            shutil.copyfile(project/'.gitignore',root/'.gitignore')
            for name in ('app.py','identity.py','settings.json','logs/input.csv','analysis/data.json','research/vendor.exe','verification/result.txt','src/akko_monitor/fixture.py','tests/verification/private.json'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture',encoding='utf8')
            def git(*args):return subprocess.check_output(['git',*args],cwd=root,stderr=subprocess.DEVNULL,text=True)
            git('init','-q');git('add','.')
            self.assertEqual(set(git('ls-files').splitlines()),{'.gitignore','app.py','src/akko_monitor/fixture.py'})

    def test_release_scan(self):
        script=Path(__file__).resolve().parents[1]/'scripts/check-release.py'
        spec=importlib.util.spec_from_file_location('release_check',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(module.check(),[])
