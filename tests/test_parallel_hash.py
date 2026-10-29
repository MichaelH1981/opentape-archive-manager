"""Both independent SHA-256 checks must survive producer/consumer separation."""
import hashlib
import io
import json
import tarfile
import threading
import uuid
from unittest import TestCase
from unittest.mock import patch

from otam.archive import inspect_stream, verify_stream, MANIFEST, add_bytes
from otam.common import FORMAT, SafetyError
from otam.prefetch import PrefetchReader
from tests.test_prefetch import Records


def fixture():
    data=b'payload\0'*20000
    manifest={'format':FORMAT,'archive_id':str(uuid.uuid4()),'media_id':str(uuid.uuid4()),
              'files':[{'path':'file','size':len(data),'sha256':hashlib.sha256(data).hexdigest()}]}
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w',format=tarfile.PAX_FORMAT) as tar:
        add_bytes(tar,MANIFEST,json.dumps(manifest).encode());add_bytes(tar,'data/file',data)
    return manifest,out.getvalue()+b'extra padding through physical filemark'


def reader(blob):
    block=65536
    return PrefetchReader(Records([blob[i:i+block] for i in range(0,len(blob),block)]+[b'',AssertionError('crossed filemark')]),
                          block,2*block,hash_archive=True)


class ParallelHash(TestCase):
    def test_same_manifest_full_hash_and_padding_in_one_read_pass(self):
        manifest,blob=fixture()
        with reader(blob) as stream:
            found,checksum,size=inspect_stream(stream,manifest)
            self.assertEqual(found,manifest)
            self.assertEqual(checksum,hashlib.sha256(blob).hexdigest())
            self.assertEqual(size,len(blob))
            self.assertEqual(stream.source.calls,(len(blob)+65535)//65536+1)
            self.assertEqual(stream.metrics()['archive_hash_mode'],'producer')
            self.assertEqual(stream.archive_digest(),(checksum,len(blob)))
        self.assertFalse(stream.thread.is_alive())
        with self.assertRaises(ValueError):stream.archive_digest()

    def test_archive_hash_updates_belong_to_producer_thread(self):
        original=hashlib.sha256;threads=[]
        class Hash:
            def __init__(self):self.value=original()
            def update(self,data):threads.append(threading.get_ident());self.value.update(data)
            def hexdigest(self):return self.value.hexdigest()
        with patch('otam.prefetch.hashlib.sha256',Hash):
            stream=PrefetchReader(Records([b'abcd',b'']),4,8,hash_archive=True)
        with stream:
            self.assertEqual(stream.read(),b'abcd');stream.archive_digest()
        self.assertTrue(threads)
        self.assertEqual(set(threads),{stream.thread.ident})
        self.assertNotEqual(stream.thread.ident,threading.get_ident())

    def test_digest_before_consumption_and_after_early_close_is_forbidden(self):
        stream=PrefetchReader(Records([b'abcd']*50+[b'']),4,8,hash_archive=True)
        with self.assertRaises(ValueError):stream.archive_digest()
        stream.close()
        with self.assertRaises(ValueError):stream.archive_digest()
        self.assertFalse(stream.thread.is_alive())

    def test_errors_after_valid_tar_end_never_return_a_digest(self):
        manifest,blob=fixture()
        block=len(blob)
        with PrefetchReader(Records([blob,OSError('read failed after TAR end')]),block,block,hash_archive=True) as stream:
            with self.assertRaisesRegex(OSError,'read failed'):inspect_stream(stream,manifest)
            with self.assertRaisesRegex(OSError,'read failed'):stream.archive_digest()

    def test_file_hash_and_full_archive_hash_remain_independently_required(self):
        manifest,blob=fixture();checksum=hashlib.sha256(blob).hexdigest()
        wrong={**manifest,'files':[{**manifest['files'][0],'sha256':'0'*64}]}
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as tar:
            add_bytes(tar,MANIFEST,json.dumps(wrong).encode());add_bytes(tar,'data/file',b'payload\0'*20000)
        bad=out.getvalue()
        with reader(bad) as stream:
            with self.assertRaisesRegex(SafetyError,'SHA-256 mismatch'):
                verify_stream(stream,hashlib.sha256(bad).hexdigest(),len(bad),wrong)
        with reader(blob) as stream:
            with self.assertRaisesRegex(SafetyError,'SHA-256/byte count mismatch'):
                verify_stream(stream,'0'*64,len(blob),manifest)
        with reader(blob) as stream:
            with self.assertRaisesRegex(SafetyError,'SHA-256/byte count mismatch'):
                verify_stream(stream,checksum,len(blob)+1,manifest)
