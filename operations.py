"""SQLite operations prototype. All demo records are synthetic."""
from contextlib import contextmanager
from datetime import date,datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
import csv,io,json,re,sqlite3
from web import ApiError

def text(value,name,maximum=160):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>maximum:
        raise ApiError(f'{name} must contain 1–{maximum} characters.')
    return value.strip()
def integer(value,name,minimum=0):
    if isinstance(value,bool) or not re.fullmatch(r'-?\d+',str(value)):
        raise ApiError(f'{name} must be an integer.')
    n=int(value)
    if not minimum<=n<=1000000000: raise ApiError(f'{name} is outside the allowed range.')
    return n
def money(value):
    if isinstance(value,(bool,float)) or not re.fullmatch(r'\d{1,9}(\.\d{1,2})?',str(value)):
        raise ApiError('Amount must be a positive decimal string with at most 2 decimal places.')
    cents=int(Decimal(str(value))*100)
    if not 0<cents<=1000000000: raise ApiError('Amount is outside the allowed range.')
    return cents
def day(value):
    try: return date.fromisoformat(str(value)).isoformat()
    except ValueError: raise ApiError('Use an ISO date: YYYY-MM-DD.')
def choice(value,options,name):
    if value not in options: raise ApiError(f'Invalid {name}.')
    return value

class Store:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS residents(id INTEGER PRIMARY KEY,name TEXT NOT NULL,unit TEXT NOT NULL UNIQUE,status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')));
            CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,resident_id INTEGER NOT NULL REFERENCES residents(id),entry_type TEXT NOT NULL CHECK(entry_type IN ('charge','payment')),amount_cents INTEGER NOT NULL CHECK(amount_cents>0),entry_date TEXT NOT NULL,note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY,sku TEXT NOT NULL UNIQUE,name TEXT NOT NULL,stock INTEGER NOT NULL CHECK(stock>=0),minimum INTEGER NOT NULL CHECK(minimum>=0));
            CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY,title TEXT NOT NULL,owner TEXT NOT NULL,due_date TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','doing','done')));
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,event TEXT NOT NULL,entity_id INTEGER NOT NULL,details TEXT NOT NULL);
            """)
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db: yield db
        except sqlite3.IntegrityError as exc:
            raise ApiError('A unique value already exists or a referenced record is invalid.',409) from exc
        finally: db.close()
    def audit(self,db,event,entity,details):
        db.execute('INSERT INTO audit(created_at,event,entity_id,details) VALUES(?,?,?,?)',
          (datetime.now(timezone.utc).isoformat(),event,entity,json.dumps(details)))
    def resident(self,data):
        name=text(data.get('name'),'Name');unit=text(data.get('unit'),'Unit',30)
        with self.db() as db:
            identifier=db.execute('INSERT INTO residents(name,unit) VALUES(?,?)',(name,unit)).lastrowid
            self.audit(db,'resident.created',identifier,{'unit':unit})
        return {'id':identifier}
    def resident_status(self,identifier,data):
        status=choice(data.get('status'),('active','archived'),'status')
        with self.db() as db:
            if not db.execute('UPDATE residents SET status=? WHERE id=?',(status,identifier)).rowcount:
                raise ApiError('Resident not found.',404)
            self.audit(db,'resident.status',identifier,{'status':status})
        return {'id':identifier,'status':status}
    def ledger(self,data):
        resident_id=integer(data.get('resident_id'),'Resident ID',1)
        kind=choice(data.get('entry_type'),('charge','payment'),'entry type')
        cents=money(data.get('amount'));entry_date=day(data.get('entry_date'))
        note=text(data.get('note'),'Note')
        with self.db() as db:
            identifier=db.execute('INSERT INTO ledger(resident_id,entry_type,amount_cents,entry_date,note) VALUES(?,?,?,?,?)',
              (resident_id,kind,cents,entry_date,note)).lastrowid
            self.audit(db,'ledger.created',identifier,{'resident_id':resident_id,'entry_type':kind,'amount_cents':cents})
        return {'id':identifier}
    def item(self,data):
        values=(text(data.get('sku'),'SKU',40),text(data.get('name'),'Name'),
                integer(data.get('stock'),'Stock'),integer(data.get('minimum'),'Minimum'))
        with self.db() as db:
            identifier=db.execute('INSERT INTO inventory(sku,name,stock,minimum) VALUES(?,?,?,?)',values).lastrowid
            self.audit(db,'inventory.created',identifier,{'sku':values[0]})
        return {'id':identifier}
    def adjust(self,identifier,data):
        delta=integer(data.get('delta'),'Adjustment',-1000000000)
        if delta==0: raise ApiError('Adjustment cannot be zero.')
        reason=text(data.get('reason'),'Reason')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT stock FROM inventory WHERE id=?',(identifier,)).fetchone()
            if row is None: raise ApiError('Inventory item not found.',404)
            stock=row['stock']+delta
            if not 0<=stock<=1000000000: raise ApiError('Adjustment would put stock outside the allowed range.')
            db.execute('UPDATE inventory SET stock=? WHERE id=?',(stock,identifier))
            self.audit(db,'inventory.adjusted',identifier,{'delta':delta,'reason':reason,'stock':stock})
        return {'id':identifier,'stock':stock}
    def task(self,data):
        values=(text(data.get('title'),'Title'),text(data.get('owner'),'Owner'),day(data.get('due_date')))
        with self.db() as db:
            identifier=db.execute('INSERT INTO tasks(title,owner,due_date) VALUES(?,?,?)',values).lastrowid
            self.audit(db,'task.created',identifier,{'title':values[0]})
        return {'id':identifier}
    def task_status(self,identifier,data):
        status=choice(data.get('status'),('open','doing','done'),'task status')
        with self.db() as db:
            if not db.execute('UPDATE tasks SET status=? WHERE id=?',(status,identifier)).rowcount:
                raise ApiError('Task not found.',404)
            self.audit(db,'task.status',identifier,{'status':status})
        return {'id':identifier,'status':status}
    def snapshot(self):
        with self.db() as db:
            db.execute('BEGIN')
            residents=[dict(r) for r in db.execute("""SELECT r.*,
             COALESCE(SUM(CASE WHEN l.entry_type='charge' THEN l.amount_cents ELSE 0 END),0) AS charges_cents,
             COALESCE(SUM(CASE WHEN l.entry_type='payment' THEN l.amount_cents ELSE 0 END),0) AS payments_cents
             FROM residents r LEFT JOIN ledger l ON l.resident_id=r.id GROUP BY r.id ORDER BY r.id""")]
            for row in residents: row['balance_cents']=row['charges_cents']-row['payments_cents']
            inventory=[dict(r) for r in db.execute('SELECT *,stock<=minimum AS low_stock FROM inventory ORDER BY id')]
            tasks=[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY due_date,id')]
            today=datetime.now(timezone.utc).date().isoformat()
            for row in tasks: row['overdue']=row['status']!='done' and row['due_date']<today
            audit=[dict(r) for r in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 30')]
            metadata=dict(db.execute('SELECT key,value FROM metadata'))
            ledger=[dict(r) for r in db.execute('SELECT * FROM ledger ORDER BY entry_date DESC,id DESC LIMIT 100')]
        return {'synthetic_demo':metadata.get('demo')=='true','residents':residents,'inventory':inventory,
          'tasks':tasks,'audit':audit,'ledger':ledger,'summary':{
          'active_residents':sum(r['status']=='active' for r in residents),
          'outstanding_cents':sum(max(0,r['balance_cents']) for r in residents),
          'payments_cents':sum(r['payments_cents'] for r in residents),
          'low_stock_items':sum(r['low_stock'] for r in inventory),
          'open_tasks':sum(r['status']!='done' for r in tasks)}}
    def balances_csv(self):
        out=io.StringIO(newline='');writer=csv.writer(out)
        writer.writerow(['resident_id','name','unit','status','charges','payments','balance'])
        safe=lambda v: "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v
        for r in self.snapshot()['residents']:
            writer.writerow([r['id'],safe(r['name']),safe(r['unit']),r['status'],
              Decimal(r['charges_cents'])/100,Decimal(r['payments_cents'])/100,Decimal(r['balance_cents'])/100])
        return out.getvalue()
    def demo(self):
        with self.db() as db:
            if any(db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('residents','ledger','inventory','tasks','audit')):
                raise ApiError('Demo seeding requires an empty database.')
            today=datetime.now(timezone.utc).date().isoformat()
            db.executemany('INSERT INTO residents(name,unit) VALUES(?,?)',[('Avery Demo','A-101'),('Jordan Example','A-102')])
            db.executemany('INSERT INTO ledger(resident_id,entry_type,amount_cents,entry_date,note) VALUES(?,?,?,?,?)',
                [(1,'charge',120000,today,'Synthetic opening charge'),(1,'payment',100000,today,'Synthetic payment'),(2,'charge',110000,today,'Synthetic opening charge')])
            db.execute("INSERT INTO inventory(sku,name,stock,minimum) VALUES('PAPER-01','Paper towels',3,5)")
            db.execute("INSERT INTO tasks(title,owner,due_date) VALUES('Review reorder list','Demo team',?)",(today,))
            db.execute("INSERT OR REPLACE INTO metadata VALUES('demo','true')")
            self.audit(db,'demo.seeded',0,{'synthetic':True})
