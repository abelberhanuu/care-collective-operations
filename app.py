import argparse,re
from operations import Store
from web import ApiError,Response,run

def make_dispatch(store):
    def dispatch(method,path,data,query):
        if method=='GET' and path=='/api/state': return store.snapshot()
        if method=='GET' and path=='/api/balances.csv': return Response(store.balances_csv(),'text/csv; charset=utf-8')
        if method=='POST':
            handlers={'/api/residents':store.resident,'/api/ledger':store.ledger,'/api/inventory':store.item,'/api/tasks':store.task}
            if path in handlers: return handlers[path](data)
            match=re.fullmatch(r'/api/(residents|inventory|tasks)/(\d+)/(status|adjust)',path)
            if match:
                kind,identifier,action=match.groups()
                handler={('residents','status'):store.resident_status,('inventory','adjust'):store.adjust,('tasks','status'):store.task_status}.get((kind,action))
                if handler: return handler(int(identifier),data)
        raise ApiError('Not found.',404)
    return dispatch

def main():
    p=argparse.ArgumentParser(description='Local synthetic-data operations prototype')
    p.add_argument('--database',default='data/care.db');p.add_argument('--port',type=int,default=8766);p.add_argument('--demo',action='store_true')
    args=p.parse_args();store=Store(args.database)
    if args.demo:
        try: store.demo()
        except ApiError as exc: p.exit(2,str(exc)+'\n')
    run(make_dispatch(store),args.port)
if __name__=='__main__': main()
