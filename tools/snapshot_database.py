#!/usr/bin/env python3
"""Export application tables in a PostgreSQL READ ONLY transaction to local SQLite.
Run with the Python baseline venv. Output must be inside ignored docs/.
No production DDL/DML is issued. Passwords are excluded from the fixture.
"""
import argparse,json,pathlib,sqlite3,sys,os
from datetime import date,datetime
from decimal import Decimal
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
if 'docs' not in a.output.resolve().parts or a.output.exists():raise SystemExit('Require new local docs/ output; never overwrite a database')
sys.path.insert(0,str(a.source.resolve()));os.chdir(a.source)
from src.core.settings import app_settings
from sqlalchemy import create_engine,text,inspect
s=app_settings();engine=create_engine(s.default_db.uri(),connect_args={'options':'-c default_transaction_read_only=on'})
a.output.parent.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(a.output);manifest={'source_kind':'PostgreSQL READ ONLY','fixture_kind':'SQLite','tables':{},'limitations':['PostgreSQL locking/driver/type semantics not validated','SQLite is not Redis/CouchDB/Supabase/FSM']}
try:
 with engine.connect() as c:
  tr=c.begin();c.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
  for table in ('defaultdb_user','defaultdb_support_ticket','alembic_version'):
   cols=inspect(c).get_columns(table); names=[x['name'] for x in cols];types={x['name']:str(x['type']) for x in cols}
   db.execute('CREATE TABLE "'+table+'" ('+','.join('"'+x+'" '+('INTEGER PRIMARY KEY' if x=='id' and table=='defaultdb_user' else 'TEXT PRIMARY KEY' if x=='id' else 'BOOLEAN' if 'BOOL' in types[x] else 'INTEGER' if 'INT' in types[x] else 'REAL' if any(y in types[x] for y in ('NUMERIC','DOUBLE','REAL')) else 'TEXT') for x in names)+')')
   rows=c.execute(text('SELECT * FROM "'+table+'"')).mappings();n=0
   for row in rows:
    values=[]
    for key in names:
     v=row[key]
     if key=='password':v='excluded-from-test-fixture'
     elif isinstance(v,(dict,list)):v=json.dumps(v)
     elif isinstance(v,(date,datetime)):v=v.isoformat()
     elif isinstance(v,Decimal):v=float(v)
     elif v is not None and not isinstance(v,(str,int,float,bytes)):v=str(v)
     values.append(v)
    db.execute('INSERT INTO "'+table+'" VALUES ('+','.join('?' for _ in names)+')',values);n+=1
   manifest['tables'][table]={'rows':n,'columns':types}
  tr.rollback()
 db.commit();a.output.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2));print(json.dumps({t:v['rows'] for t,v in manifest['tables'].items()}))
finally:db.close();engine.dispose()
