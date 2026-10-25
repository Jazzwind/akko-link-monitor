"""Native desktop fixture with real UI/tray/entry and no hardware collection."""
from unittest.mock import patch
from akko_monitor import app,identity
from akko_monitor.entry import main
from test_app_detection import FakeReceiver,FakeTelemetry,FakeBluetooth

with patch.object(app,'Receiver',FakeReceiver),patch.object(app,'Telemetry',FakeTelemetry),patch.object(app,'BluetoothMonitor',FakeBluetooth),patch.object(app,'inventory',lambda:[]),patch.object(identity,'initialize',lambda:[]):
    raise SystemExit(main())
