from pathlib import Path
import json,tempfile,threading,unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from operations import Store,money
from app import make_dispatch
from web import server,ApiError

class Operations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'care.db';self.store=Store(self.path)
    def tearDown(self): self.tmp.cleanup()
    def test_money_exactness_and_invalid_values(self):
        self.assertEqual(money('0.29'),29)
        for value in ['-1','0','1.001','NaN','Infinity',True,0.29]:
            with self.assertRaises(ApiError): money(value)
    def test_demo_balances_and_seed_protection(self):
        self.store.demo();d=self.store.snapshot()
        self.assertEqual(d['summary']['outstanding_cents'],130000)
        self.assertEqual(d['summary']['payments_cents'],100000)
        self.assertTrue(d['synthetic_demo'])
        with self.assertRaises(ApiError):self.store.demo()
    def test_foreign_keys_uniqueness_and_archiving_preserve_history(self):
        r=self.store.resident({'name':'Demo','unit':'A'})
        with self.assertRaises(ApiError):self.store.resident({'name':'Other','unit':'A'})
        with self.assertRaises(ApiError):self.store.ledger({'resident_id':999,'entry_type':'payment','amount':'1.00','entry_date':'2026-11-19','note':'Demo'})
        self.store.ledger({'resident_id':r['id'],'entry_type':'charge','amount':'1250.29','entry_date':'2026-11-19','note':'Demo'})
        self.store.resident_status(r['id'],{'status':'archived'})
        self.assertEqual(self.store.snapshot()['residents'][0]['balance_cents'],125029)
    def test_inventory_transaction_rolls_back_failed_adjustment(self):
        r=self.store.item({'sku':'X','name':'Demo','stock':2,'minimum':3})
        before=len(self.store.snapshot()['audit'])
        with self.assertRaises(ApiError):self.store.adjust(r['id'],{'delta':-3,'reason':'Too much'})
        self.assertEqual(self.store.snapshot()['inventory'][0]['stock'],2)
        self.assertEqual(len(self.store.snapshot()['audit']),before)
        self.assertEqual(self.store.adjust(r['id'],{'delta':5,'reason':'Delivery'})['stock'],7)
    def test_tasks_validation_and_csv_formula_protection(self):
        r=self.store.task({'title':'Demo','owner':'Team','due_date':'2000-01-01'})
        self.assertTrue(self.store.snapshot()['tasks'][0]['overdue'])
        self.store.task_status(r['id'],{'status':'done'})
        self.assertFalse(self.store.snapshot()['tasks'][0]['overdue'])
        with self.assertRaises(ApiError):self.store.task({'title':'Demo','owner':'Team','due_date':'2026-02-30'})
        self.store.resident({'name':'=1+1','unit':'A'})
        self.assertIn("'=1+1",self.store.balances_csv())
        self.assertEqual(Store(self.path).snapshot()['residents'][0]['name'],'=1+1')
    def test_http_write_requires_session_and_rejects_other_origins(self):
        app=server(make_dispatch(self.store));t=threading.Thread(target=app.serve_forever,kwargs={'poll_interval':.01},daemon=True);t.start()
        base=f'http://127.0.0.1:{app.server_port}'
        try:
            with urlopen(base+'/api/session') as r: token=json.load(r)['token']
            payload=json.dumps({'name':'Demo','unit':'A'}).encode()
            for headers in [{'Content-Type':'application/json'},{'Content-Type':'application/json','X-Local-Token':token,'Origin':'https://other.example'}]:
                with self.assertRaises(HTTPError) as error:urlopen(Request(base+'/api/residents',payload,headers))
                self.assertEqual(error.exception.code,403)
            with urlopen(Request(base+'/api/residents',payload,{'Content-Type':'application/json','X-Local-Token':token})) as r:self.assertEqual(json.load(r)['id'],1)
            with urlopen(base+'/api/state') as r:self.assertEqual(json.load(r)['summary']['active_residents'],1)
        finally:app.shutdown();t.join();app.server_close()
if __name__=='__main__':unittest.main()
