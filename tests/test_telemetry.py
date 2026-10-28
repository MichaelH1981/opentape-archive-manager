"""Lightweight counters and job-scoped buffer projection; no hardware."""
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from otam.web.control import Control
from otam.web.progress import job_progress
from otam.web.telemetry import Sampler, publish, snapshot


class Telemetry(unittest.TestCase):
    def test_cpu_deltas_distinguish_one_core_from_whole_host(self):
        with patch('otam.web.telemetry.time.monotonic', side_effect=[10, 15]), \
             patch('otam.web.telemetry.time.process_time', side_effect=[20, 24]), \
             patch('otam.web.telemetry.os.cpu_count', return_value=2), \
             patch('otam.web.telemetry.Path.open', side_effect=[
                 io.StringIO('cpu 100 0 100 800 0 0 0 0\n'),
                 io.StringIO('cpu 150 0 150 870 30 0 0 0\n')]):
            sampler = Sampler()
            self.assertIsNone(sampler.sample()['worker_cpu_percent'])
            result = sampler.sample()
        self.assertEqual(result['worker_cpu_percent'], 80)
        self.assertEqual(result['host_cpu_percent'], 50)
        self.assertEqual(result['host_iowait_percent'], 15)
        self.assertEqual(result['interval_seconds'], 5)
        self.assertEqual(result['cpu_count'], 2)

    def test_missing_host_counters_and_reset_never_become_zero_load(self):
        with patch('otam.web.telemetry.Path.open', side_effect=OSError):
            sampler = Sampler()
            sampler.sample()
            result = sampler.sample()
            self.assertIsNotNone(result['worker_cpu_percent'])
            self.assertIsNone(result['host_cpu_percent'])
        with patch('otam.web.telemetry.Path.open', return_value=io.StringIO('cpu 1 0 1 8 0 0 0 0\n')):
            sampler.previous = (0, 0, (100, 0, 100, 800, 0, 0, 0, 0))
            self.assertIsNone(sampler.sample()['host_cpu_percent'])

    def test_publish_reuses_one_heartbeat_commit_and_keeps_no_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            control = Control(Path(tmp))
            commits = []
            connect = control.connect
            from contextlib import contextmanager
            @contextmanager
            def traced():
                with connect() as db:
                    db.set_trace_callback(lambda sql: commits.append(sql))
                    yield db
            with patch.object(control, 'connect', traced):
                publish(control, Sampler())
            self.assertEqual(sum(sql == 'COMMIT' for sql in commits), 1)
            publish(control, Sampler())
            with connect() as db:
                self.assertEqual(db.execute('select count(*) from settings').fetchone()[0], 2)
                self.assertEqual(db.execute('select count(*) from commands').fetchone()[0], 0)
            value = control.get('worker_telemetry')
            with patch('otam.web.telemetry.time.time', return_value=value['time'] + 5):
                self.assertTrue(snapshot(control, value['time'])['fresh'])
                self.assertFalse(snapshot(control, 0)['fresh'])
            with patch('otam.web.telemetry.time.time', return_value=value['time'] + 21):
                self.assertFalse(snapshot(control, value['time'])['fresh'])

    def test_buffer_projection_cannot_leak_other_archive_or_previous_phase(self):
        db = sqlite3.connect(':memory:');self.addCleanup(db.close);db.row_factory=sqlite3.Row
        db.executescript('''
            create table staged_archives(archive_id,job_id,phase,state,progress_bytes,total_bytes,updated);
            create table archives(job_id,state);
            create table events(seq integer primary key,job_id,time,event,details_json);
            insert into staged_archives values('tar','job','TAPE_READBACK','RUNNING',100,1000,10);
        ''')
        def event(archive, phase, amount):
            db.execute('insert into events(job_id,time,event,details_json) values(?,?,?,?)',
                       ('job', 10, 'io_progress', json.dumps({'archive':archive,'phase':phase,
                        'read_buffer_bytes':1024,'read_buffered_bytes':amount})))
        event('tar','TAPE_WRITE',200)
        self.assertIsNone(job_progress(db,'job',None,'RUNNING')['io'])
        event('tar','TAPE_READBACK',0)
        event('other','TAPE_READBACK',999)
        result=job_progress(db,'job',None,'RUNNING')['io']
        self.assertEqual(result['read_buffered_bytes'],0)
        self.assertEqual(result['sample_time'],10)
        self.assertEqual(result['archive'],'tar')
