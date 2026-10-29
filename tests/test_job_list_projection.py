"""Frequent job polling must not materialize historical file inventories."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from otam.catalog import Catalog
from otam.web.query import CatalogView


class JobListProjection(TestCase):
    def test_listing_retains_parent_linkage_without_python_file_inventory(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'catalog.sqlite';catalog=Catalog(path)
            job=catalog.job('archive',None,'VERIFIED')
            value={'parent_job':'parent','archives':[{'files':[{'path':'heavyInventorySentinel','size':123}]}]}
            with catalog.db:catalog.db.execute('update jobs set plan_json=? where id=?',(json.dumps(value),job))
            original=json.loads
            def small_only(text,*args,**kwargs):
                self.assertNotIn('heavyInventorySentinel',text)
                return original(text,*args,**kwargs)
            with patch('otam.web.query.json.loads',side_effect=small_only):
                rows=CatalogView(SimpleNamespace(role='archive',catalog=path),None).jobs()
            self.assertEqual(rows[0]['id'],job)
            self.assertEqual(rows[0]['parent_job'],'parent')
            self.assertNotIn('plan_summary',rows[0])
            self.assertNotIn('plan_json',rows[0])
            self.assertIsNone(rows[0]['progress'])
            catalog.close()
