"""Isolated Python baseline entrypoint; never load production connections.
Start: baseline/.venv/bin/python -m uvicorn tools.fixture_server:app --port 18101 --workers 4
Requires TEST_SQLITE_PATH and FIXTURE_UPSTREAM. Run from the Rust worktree.
"""
import os,sys,pathlib,time,asyncio,copy
if not os.environ.get('TEST_SQLITE_PATH') or not os.environ.get('FIXTURE_UPSTREAM'):raise RuntimeError('Explicit isolated fixture paths are required')
source=os.environ['PYTHON_BASELINE_SOURCE'];sys.path.insert(0,source)
for k,v in {'API_KEY_SECRET':'fixture-admin','DEFAULT_DB_HOST':'127.0.0.1','DEFAULT_DB_PORT':'1','DEFAULT_DB_USER':'fixture','DEFAULT_DB_PASSWORD':'fixture','DEFAULT_DB_NAME':'fixture','SUPABASE_URL':os.environ['FIXTURE_UPSTREAM'],'SUPABASE_SECRET_KEY':'fixture','CERTIFICATIONS_SERVICE_KEY':'fixture-service','SUPPORT_COUCHDB_URL':'','TELEMETRY_COUCHDB_URL':'','REDIS_URL':'memory://','FERNET_KEY_SECRET':'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=','SERVER_FERNET_KEY_SECRET':'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=','ENVIRONMENT':'production'}.items():os.environ[k]=v
from src.dal.local.redis_adapter import RedisAdapter
class MemoryRedis:
 def __init__(self,*a,**kw):self.values={};self._namespace='api_for_apps:'
 async def connect(self):pass
 async def close(self):pass
 def k(self,*p):return self._namespace+':'.join(str(x) for x in p if x is not None and str(x))
 async def get(self,k):
  v=self.values.get(k);return copy.deepcopy(v[0]) if v and v[1]>time.monotonic() else None
 async def set(self,key,value,ex=None,nx=False):
  if nx and await self.get(key) is not None:return False
  self.values[key]=(copy.deepcopy(value),time.monotonic()+(ex or 86400));return True
 async def getdel(self,k):v=await self.get(k);self.values.pop(k,None);return v
 async def delete(self,*ks):
  for k in ks:self.values.pop(k,None)
 async def incr(self,k,amount=1):
  n=(await self.get(k) or 0)+amount;old=self.values.get(k);self.values[k]=(n,old[1] if old else time.monotonic()+86400);return n
 async def expire(self,k,ttl):
  if k in self.values:self.values[k]=(self.values[k][0],time.monotonic()+ttl)
 async def ttl(self,k):return int(self.values[k][1]-time.monotonic()) if k in self.values else -2
import src.dal.local.redis_adapter as rc
rc.RedisAdapter=MemoryRedis
from sqlalchemy import create_engine
from src.dal.local.db_adapter import DBAdapter
original_init=DBAdapter.__init__
def init(self,engine=None):original_init(self,engine or create_engine('sqlite:///'+os.environ['TEST_SQLITE_PATH'],connect_args={'check_same_thread':False}))
DBAdapter.__init__=init
import main
main.RedisAdapter=MemoryRedis
from src.domain.services.local_proxy_service import LocalProxyService
LocalProxyService.get_full_url=lambda self,app,path:os.environ['FIXTURE_UPSTREAM']+path
app=main.app
from src.core.settings import app_settings
app_settings().PUBLIC_PROXY_ROUTES['reports']['GET'] += ['/bytes/*','/delay/*','/failure']
