#!/usr/bin/env python3
"""Central source-only route discovery. Never reads downstream OpenAPI endpoints.
Run from api_for_apps. Reads sibling sources without importing their applications.
Unknown contracts remain marked x-discovery-gaps. Central overrides can fill them.
"""
import ast,json,pathlib,re,argparse,hashlib,os
ROOT=pathlib.Path(__file__).resolve().parents[1]
def discover_workspace():
 env=os.environ.get('ASODYA_WORKSPACE')
 if env and pathlib.Path(env).is_dir():return pathlib.Path(env).resolve()
 if (ROOT.parent/'certifications_api').is_dir():return ROOT.parent.resolve()
 git_file=ROOT/'.git'
 if git_file.is_file():
  try:
   text=git_file.read_text().strip()
   if text.startswith('gitdir:'):
    gd=pathlib.Path(text[7:].strip())
    ws=gd.parents[3]
    if (ws/'certifications_api').is_dir():return ws.resolve()
  except Exception:pass
 for p in ROOT.parents:
  if (p/'certifications_api').is_dir():return p.resolve()
 return ROOT.parent.resolve()
p=argparse.ArgumentParser();p.add_argument('--workspace',type=pathlib.Path,default=None);p.add_argument('--check',action='store_true');a=p.parse_args()
if a.workspace is None:a.workspace=discover_workspace()
if not a.workspace.is_dir():raise SystemExit(f"Workspace directory not found: {a.workspace}")
def source_hash(repo,extension):
 h=hashlib.sha256()
 for f in sorted(repo.rglob('*.'+extension)):
  if any(x.startswith('.') or x in ('build','dist','target','tests','docs','tools','__pycache__') for x in f.relative_to(repo).parts):continue
  h.update(str(f.relative_to(repo)).encode());h.update(b'\0');h.update(f.read_bytes());h.update(b'\0')
 return h.hexdigest()
OUT=ROOT/'src/presentation/assets/openapi.json';OVERRIDE=ROOT/'src/presentation/assets/descriptions.json';components={};operations={};gaps=[];seen=set()
def literal(n,default=None):
 try:return ast.literal_eval(n)
 except Exception:
  if isinstance(n,ast.JoinedStr) and all(isinstance(v,ast.Constant) for v in n.values):return ''.join(v.value for v in n.values)
  return default
def keywords(call):return {k.arg:literal(k.value) for k in call.keywords}
def schema(n):
 if n is None:return {}
 if isinstance(n,ast.Constant) and n.value is None:return {'type':'null'}
 if isinstance(n,ast.BinOp) and isinstance(n.op,ast.BitOr):return {'anyOf':[schema(n.left),schema(n.right)]}
 name=ast.unparse(n)
 if name in ('str','String','&str'):return {'type':'string'}
 if name in ('int','i64','u64','usize','i32'):return {'type':'integer'}
 if name in ('float','f64'):return {'type':'number'}
 if name=='bool':return {'type':'boolean'}
 if isinstance(n,ast.Subscript):
  typ=ast.unparse(n.value)
  if typ in ('Optional','Option'):return {'anyOf':[schema(n.slice),{'type':'null'}]}
  if typ in ('List','list','Vec'):return {'type':'array','items':schema(n.slice)}
  if typ in ('dict','Dict'):return {'type':'object','additionalProperties':True}
 if name in components:return {'$ref':'#/components/schemas/'+name}
 return {}
def register_models(tree,namespace):
 for node in tree.body:
  if not isinstance(node,ast.ClassDef):continue
  if not any('BaseModel' in ast.unparse(b) for b in node.bases):continue
  components.setdefault(node.name,{'type':'object','properties':{}})
 for node in tree.body:
  if not isinstance(node,ast.ClassDef) or node.name not in components:continue
  props={};required=[]
  for n in node.body:
   if not isinstance(n,ast.AnnAssign) or not isinstance(n.target,ast.Name):continue
   sc=schema(n.annotation);name=n.target.id
   if n.value is None:required.append(name)
   elif isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='Field':
    kw=keywords(n.value)
    if 'default' not in kw and 'default_factory' not in kw:required.append(name)
    for src,dst in [('min_length','minLength'),('max_length','maxLength'),('ge','minimum'),('le','maximum'),('pattern','pattern'),('description','description')]:
     if kw.get(src) is not None:sc[dst]=kw[src]
    if 'default' in kw:sc['default']=kw['default']
   else:sc['default']=literal(n.value)
   props[name]=sc
  components[node.name]={'type':'object','properties':props,**({'required':required} if required else {})}
def operation(app,path,method,summary,description,params,body,responses,source,ws=False,unknown=None,deprecated=False):
 if path in ('/docs','/scalar','/openapi.json') and app!='gateway':return
 path=re.sub(r'\{(\w+):path\}',r'{\1}',path)
 full=path if app=='gateway' else '/apps/'+app+'/v1'+('/' if not path.startswith('/') else '')+path
 if method=='websocket':method='get';ws=True
 key=(full,method.lower())
 if key in seen:return
 seen.add(key);security=[]
 defaults=json.loads((ROOT/'src/core/defaults.json').read_text());suffix=path
 import fnmatch
 def match(table):return any(fnmatch.fnmatchcase(suffix,x) for x in defaults.get(table,{}).get(app,{}).get(method.upper(),[]))
 admin='logs' in suffix.split('/') or match('ADMIN_PROTECTED_PROXY_ROUTES')
 if app!='gateway':level='administrator' if admin else 'session' if match('FORCE_AUTH_PROXY_ROUTES') or not match('PUBLIC_PROXY_ROUTES') else 'public'
 else:level='administrator' if full.endswith('/logs/stream') or (full.endswith('/client-error') and method.lower()=='get') else 'session' if full.startswith(('/user/info/','/apps/support/')) else 'public'
 if level!='public':security=[{'SessionCookie':[]},{'AdminKey':[]}] if level=='administrator' else [{'SessionCookie':[]}]
 narrative=f'{summary}. This operation belongs to {app}. Send requests through the Asodya gateway at the path shown here. '
 narrative+= {'public':'The gateway allows anonymous access to this operation. The backend can apply additional validation.','session':'Use the sid session cookie. Mutable session requests also require the csrf cookie and matching X-CSRF-Token header.','administrator':'Administrative access is required before execution. Use the administrative credential or an authorized administrator session. Mutable session requests require CSRF validation.'}[level]
 if description:narrative+='\n\n'+description
 if ws:narrative+='\n\nThis endpoint upgrades to WebSocket. Use wss://api.asodya.com with the same path. Authorize before connecting. It streams live log entries and does not create a log archive.'
 op={'operationId':re.sub('[^a-zA-Z0-9_]','_',app+'_'+method+'_'+path),'tags':[app],'summary':summary,'description':narrative,'parameters':params,'responses':responses or {'default':{'description':'Response contract not declared in source; inspect the implementation.','content':{'application/json':{'schema':{}}}}},'security':security,'x-source':source,'x-access-level':level}
 if deprecated:op['deprecated']=True
 for param in re.findall(r'\{(\w+)\}',full):
  if not any(p['name']==param and p['in']=='path' for p in op['parameters']):op['parameters'].append({'name':param,'in':'path','required':True,'schema':{'type':'string'}})
 if level!='public' and method.lower() in ('post','put','patch','delete'):op['parameters'].append({'name':'X-CSRF-Token','in':'header','required':False,'schema':{'type':'string'},'description':'Required for cookie-authenticated mutation requests. Must equal the csrf cookie and session token. Administrative API-key calls bypass CSRF.'})
 if body:op['requestBody']=body
 if ws:op['x-websocket']=True
 if unknown:op['x-discovery-gaps']=unknown;gaps.append({'path':full,'method':method,'gaps':unknown})
 op['x-codeSamples']=[{'lang':'Shell','label':'cURL','source':f"curl --request {method.upper()} 'https://api.asodya.com{full}'"+(' \\\n  --cookie \"sid=<session>; csrf=<csrf>\"' if level!='public' else '')+(' \\\n  --header \"Content-Type: application/json\" \\\n  --data \''+json.dumps(example(body['content']['application/json']['schema']))+'\'' if body and 'application/json' in body['content'] else '')}]
 operations.setdefault(full,{})[method.lower()]=op

def example(s):
 if '$ref' in s:return example(components.get(s['$ref'].split('/')[-1],{}))
 if 'anyOf' in s:return example(next((x for x in s['anyOf'] if x.get('type')!='null'),{}))
 if 'default' in s and s['default'] is not None:return s['default']
 if s.get('type')=='object':return {k:('user@example.com' if k=='email' else 'reports' if k=='app' else example(v)) for k,v in s.get('properties',{}).items()}
 if s.get('type')=='array':return []
 if s.get('type')=='integer':return 1
 if s.get('type')=='number':return 1.0
 if s.get('type')=='boolean':return True
 return 'example'

def infer_return(n):
 if isinstance(n,ast.Dict):
  props={}
  for k,v in zip(n.keys,n.values):
   if isinstance(k,ast.Constant) and isinstance(k.value,str):props[k.value]=infer_return(v)
  return {'type':'object','properties':props,'additionalProperties':True}
 if isinstance(n,ast.List):return {'type':'array','items':infer_return(n.elts[0]) if n.elts else {}}
 if isinstance(n,ast.Constant):
  if n.value is None:return {'type':'null'}
  if isinstance(n.value,bool):return {'type':'boolean','example':n.value}
  if isinstance(n.value,int):return {'type':'integer','example':n.value}
  if isinstance(n.value,str):return {'type':'string','example':n.value}
 if isinstance(n,ast.Call):
  name=ast.unparse(n.func)
  if name in components:return {'$ref':'#/components/schemas/'+name}
  for k in n.keywords:
   if k.arg=='content':return infer_return(k.value)
 return {}

def python_app(app,repo):
 files=[f for f in repo.rglob('*.py') if not any(x.startswith('.') or x in ('tests','docs','target','tools','build','dist','__pycache__') for x in f.relative_to(repo).parts)]
 trees=[]
 for f in files:
  try:t=ast.parse(f.read_text())
  except (SyntaxError,UnicodeError):continue
  trees.append((f,t));register_models(t,app)
 for f,t in trees:register_models(t,app)
 # Router prefixes are inferred statically. Cross-module include prefixes are resolved by imported symbol.
 prefix_by_symbol={};include_prefix={}
 for f,t in trees:
  imports={}
  for n in ast.walk(t):
   if isinstance(n,ast.ImportFrom):
    for alias in n.names:imports[alias.asname or alias.name]=alias.name
   if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func).endswith('APIRouter'):
    for target in n.targets:
     if isinstance(target,ast.Name):prefix_by_symbol[(str(f),target.id)]=keywords(n.value).get('prefix') or ''
   if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='include_router' and n.args:
    name=ast.unparse(n.args[0]).split('.')[-1];prefix=keywords(n).get('prefix') or '';include_prefix[name]=prefix
 for f,t in trees:
  for n in ast.walk(t):
   if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
   for dec in n.decorator_list:
    if not isinstance(dec,ast.Call) or not isinstance(dec.func,ast.Attribute) or not dec.args:continue
    method=dec.func.attr
    if method not in ('get','post','put','patch','delete','head','options','api_route','websocket'):continue
    raw=literal(dec.args[0]);
    if not isinstance(raw,str):continue
    router=ast.unparse(dec.func.value);prefix=prefix_by_symbol.get((str(f),router),'')+''
    prefix=include_prefix.get(router,'')+prefix
    if app=='gateway':
     prefix={'user_info_v1':'/user/info/v1','user_sync_v1':'/user/sync/v1','hello_user_v1':'/user/v1','hello_apps_v1':'/apps/api/v1','exchange_app_route_v1':'/apps/api/v1','telemetry_router':'/apps/api/v1','support_v1':'/apps/support/v1','waitlist_router':'/apps/certifications/v1'}.get(router,prefix)
     if router=='apps_proxy_v1':continue
    path=prefix+raw;kw=keywords(dec);params=[];body=None;unknown=[]
    args=n.args.args;defaults=[None]*(len(args)-len(n.args.defaults))+list(n.args.defaults)
    for arg,default in zip(args,defaults):
     name=arg.arg;ann=ast.unparse(arg.annotation) if arg.annotation else '';sc=schema(arg.annotation)
     if name in ('self','request','response','background_tasks') or ann in ('Request','Response','BackgroundTasks','RedisAdapter','WebSocket'):continue
     if isinstance(default,ast.Call) and any(x in ast.unparse(default.func) for x in ('Depends','Security')):continue
     if ann in components:
      body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/'+ann},'example':example(components[ann])}}};continue
     if 'UploadFile' in ann or isinstance(default,ast.Call) and ast.unparse(default.func)=='File':body={'required':True,'content':{'multipart/form-data':{'schema':{'type':'object','properties':{name:{'type':'string','format':'binary'}}}}}};continue
     where='path' if '{'+name+'}' in path else 'query';param={'name':name,'in':where,'required':where=='path' or default is None,'schema':sc}
     if isinstance(default,ast.Call):
      dk=keywords(default)
      if dk.get('alias'):param['name']=dk['alias']
      for src,dst in [('ge','minimum'),('le','maximum'),('min_length','minLength'),('max_length','maxLength')]:
       if dk.get(src) is not None:sc[dst]=dk[src]
     params.append(param)
    status=kw.get('status_code');
    if status is None:
     # Resolve common FastAPI status constants without importing service code.
     for k in dec.keywords:
      if k.arg=='status_code':
       match=re.search(r'HTTP_(\d+)',ast.unparse(k.value));status=int(match.group(1)) if match else None
    status=status or 200
    response_schema=None
    for k in dec.keywords:
     if k.arg=='response_model':response_schema=schema(k.value)
    responses={str(status):{'description':'Successful operation.','content':{'application/json':{'schema':response_schema or {}}}},'403':{'description':'Authentication or permission requirement not satisfied.'},'422':{'description':'Request validation failed.'}}
    if response_schema is None:
     response_schema=schema(n.returns)
     inferred=[infer_return(x.value) for x in ast.walk(n) if isinstance(x,ast.Return) and x.value is not None]
     inferred=[x for x in inferred if x]
     if inferred:response_schema=inferred[0] if len(inferred)==1 else {'anyOf':inferred}
     if response_schema:responses[str(status)]['content']['application/json']['schema']=response_schema
     else:unknown.append('Dynamic response shape: source has no declared model or directly inspectable return object.')
    if any(isinstance(x,ast.Await) and isinstance(x.value,ast.Call) and ast.unparse(x.value.func).endswith('.json') for x in ast.walk(n)) and body is None:unknown.append('Request JSON is read dynamically; central schema override required.')
    methods=kw.get('methods') or [method]
    for meth in methods:operation(app,path,meth.lower(),kw.get('summary') or n.name.replace('_',' ').capitalize(),kw.get('description') or ast.get_docstring(n) or '',params.copy(),body,responses,str(f.relative_to(a.workspace))+':'+str(n.lineno),method=='websocket',unknown)

def rust_schema(typ):
 typ=typ.strip().replace('serde_json::','')
 if typ.startswith('Option<'):return {'anyOf':[rust_schema(typ[7:-1]),{'type':'null'}]}
 if typ.startswith('Vec<'):return {'type':'array','items':rust_schema(typ[4:-1])}
 if typ.startswith('Paged<'):return {'type':'object','properties':{'items':{'type':'array','items':rust_schema(typ[6:-1])}},'additionalProperties':True}
 if typ in ('String','str','Uuid'):return {'type':'string'}
 if typ in ('i64','u64','usize','i32','u32'):return {'type':'integer'}
 if typ in ('f64','f32'):return {'type':'number'}
 if typ=='bool':return {'type':'boolean'}
 if typ in ('I18nText',) or 'HashMap<' in typ or 'BTreeMap<' in typ:return {'type':'object','additionalProperties':True}
 if typ in components:return {'$ref':'#/components/schemas/'+typ}
 return {}
def rust_models(repo, source="engine/src"):
 texts=[]
 for f in (repo/source).rglob('*.rs'):
  text=f.read_text();texts.append((f,text))
  for m in re.finditer(r'(?:pub\s+)?struct (\w+)(?:<[^>]+>)?\s*\{',text):components.setdefault(m.group(1),{'type':'object'})
 for f,text in texts:
  for m in re.finditer(r'(?:pub\s+)?struct (\w+)(?:<[^>]+>)?\s*\{',text):
   end=text.find('\n}',m.end());body=text[m.end():end];props={};required=[];attrs='';doc=[]
   for line in body.splitlines():
    line=line.strip()
    if line.startswith('///'):doc.append(line[3:].strip());continue
    if line.startswith('#['):attrs+=line;continue
    fm=re.match(r'(?:pub\s+)?(\w+):\s*(.+),?$',line)
    if not fm:continue
    k,typ=fm.groups();sc=rust_schema(typ.rstrip(','))
    if doc:sc['description']=' '.join(doc)
    if not typ.startswith('Option<') and 'default' not in attrs:required.append(k)
    props[k]=sc;attrs='';doc=[]
   components[m.group(1)]={'type':'object','properties':props,**({'required':required}if required else {})}
 return texts

def rust_reports(repo):
 f=repo/'engine/src/presentation/api/server.rs'
 if not f.exists():return
 text=f.read_text();bindings={};source_texts=rust_models(repo);handlers={}
 for sf,st in source_texts:
  if '/presentation/api/' not in str(sf):continue
  for hm in re.finditer(r'pub async fn (\w+)\s*\((.*?)\)\s*->[^\{]+\{',st,re.S):handlers[hm.group(1)]=(hm.group(2),st[max(0,st.rfind('#[utoipa::path(',0,hm.start())):hm.start()])
 for m in re.finditer(r'let\s+(\w+)\s*=\s*([^;]+);',text,re.S):bindings[m.group(1)]=m.group(2)
 def chunks(text):
  for match in re.finditer(r'\.route\(\s*"([^"]+)"\s*,',text):
   start=match.end();depth=1;i=start;quote=False
   while i<len(text) and depth:
    if text[i]=='"' and (i==0 or text[i-1]!='\\'):quote=not quote
    if not quote:
     if text[i]=='(':depth+=1
     if text[i]==')':depth-=1
    i+=1
   yield match.group(1),text[start:i-1],match.start()
 boundary=text.find('pub fn router');boundary=boundary if boundary>=0 else text.find('pub fn build');boundary=text.find('.route("/openapi.json"') if boundary<0 else boundary
 for path,expr,pos in chunks(text):
  expr=bindings.get(expr.strip(),expr);methods=re.findall(r'\b(get|post|put|patch|delete|head|options)\(',expr)
  if not methods:gaps.append({'source':str(f),'route':path,'gaps':['Unresolved Rust method expression: '+expr[:80]]});continue
  path=re.sub(r':([A-Za-z_]\w*)',r'{\1}',path)
  prefixes=[''] if pos>=boundary else ['/projects/{project}/admin','/admin/projects/{project}']
  for prefix in prefixes:
   for method in set(methods):
    if prefix.startswith('/projects/') and method=='get' and path in ('/schemas','/grants','/calculations','/reports/{report}/datasets/{dataset}/snapshots'):continue
    hm=re.search(r'\b'+method+r'\((?:\w+::)*([a-zA-Z_]\w*)',expr)
    signature,annotation=handlers.get(hm.group(1) if hm else '',('',''))
    body_match=re.search(r'Json<([^>]+)>',signature);body=None;params=[];unknown=[]
    if body_match:
     sc=rust_schema(body_match.group(1));body={'required':True,'content':{'application/json':{'schema':sc,'example':example(sc)}}}
    query_match=re.search(r'Query<([^>]+)>',signature)
    if query_match:
     model=components.get(query_match.group(1),{})
     params=[{'name':k,'in':'query','required':k in model.get('required',[]),'schema':v} for k,v in model.get('properties',{}).items()]
    summary_match=re.search(r'summary\s*=\s*"([^"]+)"',annotation)
    desc_match=re.search(r'description\s*=\s*"([^"]+)"',annotation)
    responses={}
    for rm in re.finditer(r'status\s*=\s*(\d+)\s*,\s*description\s*=\s*"([^"]+)"(?:\s*,\s*body\s*=\s*([^\)]+))?',annotation):
     status,desc,typ=rm.groups();responses[status]={'description':desc}
     if typ:responses[status]['content']={'application/json':{'schema':rust_schema(typ.strip()),'example':example(rust_schema(typ.strip()))}}
    full_path=prefix+path
    if not responses and (full_path=='/me/projects/{project}/items' and method=='post' or full_path=='/me/items/{id}' and method in ('get','patch') or full_path=='/me/items/{id}/dataset' and method=='put'):
     ok_code='201' if full_path=='/me/projects/{project}/items' else '200'
     responses={ok_code:{'description':'Owner report item detail.','content':{'application/json':{'schema':rust_schema('OwnerItemDetail'),'example':example(rust_schema('OwnerItemDetail'))}}},'401':{'description':'Unauthorized'},'403':{'description':'Forbidden'},'404':{'description':'Project, template, or item not found'},'409':{'description':'ETag precondition or duplicate idempotency key conflict'}}
    elif not responses and full_path=='/me/items/{id}' and method=='delete':
     responses={'200':{'description':'Owner report item deleted.','content':{'application/json':{'schema':rust_schema('DeleteOwnerItemOutcome'),'example':example(rust_schema('DeleteOwnerItemOutcome'))}}},'401':{'description':'Unauthorized'},'403':{'description':'Forbidden'},'404':{'description':'Item not found'},'409':{'description':'Delete requires confirmation query (?confirm=true) when referenced'}}
    if not responses:unknown.append('Dynamic Rust response shape requires central review.')
    operation('reports',full_path,method,summary_match.group(1) if summary_match else method.upper()+' '+path,desc_match.group(1) if desc_match else 'Reports operation discovered directly from route registration and handler source.',params,body,responses or None,str(f.relative_to(a.workspace))+':'+str(text[:pos].count('\n')+1),unknown=unknown)

def rust_annotations(repo):
 if not (repo/'lib/presentation/mod.rs').exists():return
 # Namespace the selected service models; common names such as Query must not
 # overwrite contracts belonging to Reports or another registered service.
 import copy
 before=copy.deepcopy(components)
 rust_models(repo,'lib')
 selected_names=['Field','Draft','Translation','WritePost','Query','Edit','ItemWrite','PreparedCertificationInput','PreparedCertificationSourceInput','PreparedCertificationConfigInput']
 selected={k:copy.deepcopy(components[k]) for k in selected_names if k in components}
 def get_refs(val):
  if isinstance(val,dict):
   ref=val.get('$ref','')
   if ref.startswith('#/components/schemas/'):yield ref.rsplit('/',1)[-1]
   for v in val.values():yield from get_refs(v)
  elif isinstance(val,list):
   for item in val:yield from get_refs(item)
 queue=list(selected.keys())
 while queue:
  model_name=queue.pop()
  for ref_name in get_refs(selected[model_name]):
   if ref_name not in selected and ref_name in components:
    selected[ref_name]=copy.deepcopy(components[ref_name]);queue.append(ref_name)
 components.clear();components.update(before)
 def namespace(value):
  if isinstance(value,dict):
   return {k:('#/components/schemas/Annotations'+v.rsplit('/',1)[-1] if k=='$ref' and v.rsplit('/',1)[-1] in selected else namespace(v)) for k,v in value.items()}
  if isinstance(value,list):return [namespace(x) for x in value]
  return value
 for name,model in selected.items():components['Annotations'+name]=namespace(model)
 for f in sorted((repo/'lib/presentation').glob('*.rs')):
  text=f.read_text()
  for match in re.finditer(r'\.route\(\s*"([^"]+)"\s*,',text):
   path=match[1];i=match.end();start=i;depth=1
   while i<len(text) and depth:
    if text[i]=='(':depth+=1
    elif text[i]==')':depth-=1
    i+=1
   expr=text[start:i-1]
   for method in re.findall(r'\b(get|post|put|patch|delete)\(',expr):
    if path in ('/posts','/posts/{key}','/admin/posts/{id}','/admin/posts/{id}/publish','/admin/images','/admin/images/{key}'):continue
    params=[];body=None
    if path=='/notes':params=[{'name':k,'in':'query','required':False,'schema':{'type':'integer' if k=='limit' else 'string'}} for k in ('q','author_id','language','tag','project_id','cursor','limit','browse_token')]
    elif path=='/notes/{note_id}':params=[{'name':'view','in':'query','schema':{'type':'string'}},{'name':'language','in':'query','schema':{'type':'string'}}]
    elif path in ('/authors/{author_id}/projects','/me/projects','/admin/projects','/me/tasks'):params=[{'name':k,'in':'query','schema':{'type':'integer' if k=='limit' else 'string'}} for k in ('cursor','limit')]
    elif path=='/models':params=[{'name':'platform','in':'query','schema':{'type':'string'}},{'name':'language','in':'query','schema':{'type':'string'}}]
    elif path=='/links/preview':params=[{'name':'url','in':'query','required':True,'schema':{'type':'string','format':'uri'}}]
    elif path in ('/me/transcriptions/{run_id}/events','/me/content_jobs/{job_id}/events'):params=[{'name':'after','in':'query','schema':{'type':'string'}}]
    elif path=='/me/model_downloads/{download_id}/content':params=[{'name':'Range','in':'header','required':False,'schema':{'type':'string'}}]
    model='Draft' if path=='/admin/schemas' and method=='post' else 'ItemWrite' if path.endswith('/items') and method=='post' else 'PreparedCertificationInput' if path.endswith('/certifications/prepared') and method=='post' else None
    if model:body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Annotations'+model}}}}
    if path=='/waitlist':body={'required':True,'content':{'application/json':{'schema':{'type':'object','required':['email'],'properties':{'email':{'type':'string','format':'email'},'message':{'type':'string','maxLength':2000}}}}}}
    if path=='/admin/catalog' and method=='put':body={'required':True,'content':{'application/json':{'schema':{'type':'object','description':'Normalized owners, channels, languages and topics collections.','properties':{key:{'type':'array','items':{'type':'object','properties':props,'required':list(props)}} for key,props in [('owners',{'id':{'type':'string'},'display_name':{'type':'string'}}),('channels',{'id':{'type':'string'},'name':{'type':'string'}}),('topics',{'id':{'type':'string'},'name':{'type':'string'}}),('languages',{'code':{'type':'string'},'label':{'type':'string'}})]}}}}}
    if method=='put' and path.endswith('/content') and '/files/' in path:
     body={'required':True,'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}}
    elif method in ('post','put','patch') and not body and path!='/admin/schemas/{name}/versions/{version}/publish':
     body={'required':True,'content':{'application/json':{'schema':{'type':'object','additionalProperties':True}}}}
    sse=method=='get' and (path=='/logs/stream' or path.endswith('/events'))
    binary=method=='get' and (path.startswith('/media/') or path.endswith('/content') or re.fullmatch(r'/instant/\{[^}]+\}/files/\{[^}]+\}',path) is not None)
    if sse:
     responses={'200':{'description':'Server-sent events stream.','content':{'text/event-stream':{'schema':{'type':'string'},'example':'id: 1\ndata: {}\n\n'}}},'401':{'description':'Authentication required.'},'404':{'description':'Resource missing or not owned by caller.'}}
    elif path=='/me/model_downloads/{download_id}/content':
     responses={'200':{'description':'Full model artifact stream.','content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}},'206':{'description':'Partial range model artifact stream.'},'416':{'description':'Requested byte range not satisfiable.'},'401':{'description':'Authentication required.'},'404':{'description':'Download missing or expired.'}}
    elif path.endswith('/certifications/prepared') and method=='post':
     responses={'201':{'description':'Prepared certification study detail.','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_StudyDetail'}}}},'401':{'description':'Authentication required.'},'404':{'description':'Note not found or caller not owner.'},'422':{'description':'Input validation failed.'}}
    else:
     responses={'200':{'description':'Current resource or operation result.','content':{'application/octet-stream' if binary else 'application/json':{'schema':{'type':'string','format':'binary'} if binary else {'type':'object','additionalProperties':True}}}},'404':{'description':'Resource missing, private, unpublished or expired.'},'422':{'description':'Input or registered document schema validation failed.'},'503':{'description':'A required storage or adapter service is unavailable.'}}
    if path=='/me/transcriptions/{run_id}/feedback':responses.update({'413':{'description':'Request body exceeds 2,000,000 bytes.'},'429':{'description':'Per-account or per-network feedback rate or concurrency limit exceeded.'}})
    if '/instant/' in path:responses.update({'409':{'description':'Stale revision; reload before editing.'},'413':{'description':'50,000,000-byte per-file or aggregate active IP quota exceeded.'},'410':{'description':'Room expired 15 minutes after creation.'}})
    src_loc=(str(f.relative_to(a.workspace)) if f.is_relative_to(a.workspace) else ('annotations_api/'+str(f.relative_to(repo))))+':'+str(text[:match.start()].count('\n')+1)
    operation('annotations',path,method,method.upper()+' '+path,'Annotations v2 service. Public routes serve published/anonymous-room resources; /me/* and /models* require a signed-in session; /admin/* and /logs/stream require administrator access. Note mutations support study_links and transcription_run_id. Direct trusted LAN calls have no service authentication.',params,body,responses,src_loc)

def rust_certifications(repo):
 if not (repo/'lib/presentation/mod.rs').exists():return
 import copy
 before=copy.deepcopy(components)
 rust_models(repo,'lib')
 selected_names=[
  'PreparedSourceRef','PreparedStudyInput','PreparedStudyConfig','CreateStudyInput','UpdateStudyInput',
  'SelectionInput','StudySummary','SourceSummary','QuotaMeter','StudyDetail',
  'AnalysisSummary','EstimateResponse','StartGenerationInput','GenerationJobSummary',
  'QuestionAlternative','QuestionVisual','AuthorQuestion','CreateQuestionInput',
  'UpdateQuestionInput','CsvImportBody','CsvImportResult','VisualRenderBody',
  'TagInfo','CatalogQuizSummary','CatalogPage','PublicQuestionPreview','PublicQuizDetail',
  'PublicQuizStats','PublishBody','TakingQuestion','AttemptView','AnswerBody',
  'ActivityEventInput','EventsBody','AttemptHistoryItem','StatsGroup','ThreeGroupStats',
  'ActivityEventRecord','ActivitySummary','ReviewedQuestion','AttemptResults',
  'HolderIdentity','IdentityBody','CertificateRecord','PublicCertificateVerification',
  'RuntimeSettingItem','UpdateSettingInput','SettingsPatchBody','OriginOverrideBody',
  'HolderUpdateBody','RevokeBody','AdminStatistics','SchemaDraftBody','SchemaStatusBody',
  'AvailableStudyTag','StudyHistoryPage','OwnerQuizSummary','AttemptHistoryPage',
  'CsvValidRow','CsvInvalidRow','PublicSourceMaterial','QuestionProvenanceStats','ScoreBandCount',
  'PrepareVisualJobInput','PreparedVisualJobResult','RenderJobDescriptor','UploadVisualInput'
 ]
 selected={k:copy.deepcopy(components[k]) for k in selected_names if k in components}
 def get_refs(val):
  if isinstance(val,dict):
   ref=val.get('$ref','')
   if ref.startswith('#/components/schemas/'):yield ref.rsplit('/',1)[-1]
   for v in val.values():yield from get_refs(v)
  elif isinstance(val,list):
   for item in val:yield from get_refs(item)
 queue=list(selected.keys())
 while queue:
  model_name=queue.pop()
  for ref_name in get_refs(selected[model_name]):
   if ref_name not in selected and ref_name in components:
    selected[ref_name]=copy.deepcopy(components[ref_name]);queue.append(ref_name)
 components.clear();components.update(before)
 def namespace(value):
  if isinstance(value,dict):
   return {k:('#/components/schemas/Certifications_'+v.rsplit('/',1)[-1] if k=='$ref' and v.rsplit('/',1)[-1] in selected else namespace(v)) for k,v in value.items()}
  if isinstance(value,list):return [namespace(x) for x in value]
  return value
 for name,model in selected.items():components['Certifications_'+name]=namespace(model)
 components['Certifications_PreparedStudyConfig']={
  'type':'object',
  'properties':{
   'language':{'type':'string','default':'en'},
   'count':{'type':'integer','default':10,'minimum':1,'maximum':20}
  },
  'additionalProperties':False
 }
 components.setdefault('Certifications_PreparedStudyInput',{'type':'object','properties':{}})
 components['Certifications_PreparedStudyInput'].setdefault('properties',{})
 components['Certifications_PreparedStudyInput']['properties']['config']={
  'anyOf':[{'$ref':'#/components/schemas/Certifications_PreparedStudyConfig'},{'type':'null'}]
 }
 components.setdefault('Certifications_StudyDetail',{'type':'object','properties':{}})
 components['Certifications_StudyDetail'].setdefault('properties',{})
 components['Certifications_StudyDetail']['properties'].setdefault('study',{'$ref':'#/components/schemas/Certifications_StudySummary'})
 components['Certifications_StudyDetail']['properties'].setdefault('sources',{'type':'array','items':{'$ref':'#/components/schemas/Certifications_SourceSummary'}})
 components['Certifications_StudyDetail']['properties'].setdefault('quota',{'$ref':'#/components/schemas/Certifications_QuotaMeter'})
 components['Certifications_StudyDetail']['properties']['config']={
  'anyOf':[{'$ref':'#/components/schemas/Certifications_PreparedStudyConfig'},{'type':'null'}]
 }
 components['Certifications_AvailableStudyTag']={
  'type':'object',
  'properties':{
   'slug':{'type':'string'},
   'label':{'type':'string'}
  },
  'required':['slug','label']
 }
 components['Certifications_StudyHistoryPage']={
  'type':'object',
  'properties':{
   'items':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_StudySummary'}},
   'total':{'type':'integer'},
   'limit':{'type':'integer'},
   'offset':{'type':'integer'},
   'available_tags':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_AvailableStudyTag'}}
  },
  'required':['items','total','limit','offset','available_tags']
 }
 components['Certifications_OwnerQuizSummary']={
  'type':'object',
  'properties':{
   'quiz_id':{'type':'string'},
   'active_version_id':{'anyOf':[{'type':'string'},{'type':'null'}]},
   'title':{'anyOf':[{'type':'string'},{'type':'null'}]},
   'question_count':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'subject':{'anyOf':[{'type':'string'},{'type':'null'}]}
  },
  'required':['quiz_id']
 }
 components['Certifications_AttemptHistoryPage']={
  'type':'object',
  'properties':{
   'items':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_AttemptHistoryItem'}},
   'total':{'type':'integer'},
   'limit':{'type':'integer'},
   'offset':{'type':'integer'}
  },
  'required':['items','total','limit','offset']
 }
 components['Certifications_PrepareVisualJobInput']={
  'type':'object',
  'properties':{
   'template_id':{'type':'string'},
   'template_version':{'type':'integer'},
   'mapping':{'type':'object','additionalProperties':{'type':'array','items':{'type':'string'}}},
   'config':{'type':'object','additionalProperties':True},
   'rows':{'type':'array','items':{'type':'object','additionalProperties':True}},
   'width':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'height':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'scale':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'ttl_seconds':{'anyOf':[{'type':'integer'},{'type':'null'}]}
  },
  'required':['template_id','template_version','mapping','config','rows']
 }
 components['Certifications_RenderJobDescriptor']={
  'type':'object',
  'properties':{
   'job_id':{'type':'string'},
   'template_id':{'type':'string'},
   'template_version':{'type':'integer'},
   'mapping':{'type':'object','additionalProperties':{'type':'array','items':{'type':'string'}}},
   'config':{'type':'object','additionalProperties':True},
   'rows':{'type':'array','items':{'type':'object','additionalProperties':True}},
   'width':{'type':'integer'},
   'height':{'type':'integer'},
   'scale':{'type':'integer'},
   'expires_at':{'type':'integer'}
  },
  'required':['job_id','template_id','template_version','mapping','config','rows','width','height','scale','expires_at']
 }
 components['Certifications_PreparedVisualJobResult']={
  'type':'object',
  'properties':{
   'question_id':{'type':'string'},
   'question_version_id':{'type':'string'},
   'render_job':{'$ref':'#/components/schemas/Certifications_RenderJobDescriptor'}
  },
  'required':['question_id','question_version_id','render_job']
 }
 components['Certifications_UploadVisualInput']={
  'type':'object',
  'properties':{
   'question_version_id':{'type':'string'},
   'render_job_id':{'type':'string'},
   'expected_width':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'expected_height':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'expected_scale':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'png_base64':{'type':'string'}
  },
  'required':['question_version_id','render_job_id','png_base64']
 }
 components['Certifications_QuestionVisual']={
  'type':'object',
  'properties':{
   'id':{'type':'string'},
   'fsm_ref':{'type':'string'},
   'mime_type':{'type':'string'},
   'created_at':{'type':'integer'}
  },
  'required':['id','fsm_ref','mime_type','created_at']
 }
 if 'Certifications_PublicQuizStats' in components:
  components['Certifications_PublicQuizStats']['properties']['score_distribution_report_view']={
   'type':'object',
   'properties':{
    'descriptor':{
     'type':'object',
     'properties':{
      'dataset_id':{'type':'string'},
      'title':{'type':'string'},
      'description':{'type':'string'},
      'equation':{'type':['string','null']},
      'fields':{'type':'array','items':{'type':'object','additionalProperties':True}},
      'filters':{'type':'array','items':{'type':'object','additionalProperties':True}},
      'data_tier':{'type':'string'},
      'can_view':{'type':'boolean'},
      'visibility':{'type':'string','enum':['public','restricted']},
      'meta':{'type':'object','additionalProperties':True}
     },
     'required':['dataset_id','title','fields','data_tier','can_view','visibility']
    },
    'rows':{'type':'array','items':{'type':'object','additionalProperties':True}},
    'offset':{'type':'integer'},
    'limit':{'type':'integer'},
    'total_rows':{'type':'integer'},
    'visual':{'type':'object','additionalProperties':True},
    'template_definition':{'type':'object','additionalProperties':True}
   }
  }
 desc='Certifications v2 service. Public routes serve catalog quizzes, reusable questions and certificate verification; /studies/*, /generations/*, /attempts/* and /me/* require a signed-in session; /admin/* and /logs/stream require administrator access.'
 for f in sorted((repo/'lib/presentation').glob('*.rs')):
  text=f.read_text()
  for match in re.finditer(r'\.route\(\s*"([^"]+)"\s*,',text):
   path=match[1];i=match.end();start=i;depth=1
   while i<len(text) and depth:
    if text[i]=='(':depth+=1
    elif text[i]==')':depth-=1
    i+=1
   expr=text[start:i-1]
   for method in re.findall(r'\b(get|post|put|patch|delete)\(',expr):
    params=[];body=None;responses={}
    for p_match in re.finditer(r'\{(\w+)\}',path):
     params.append({'name':p_match.group(1),'in':'path','required':True,'schema':{'type':'string'}})
    if path=='/studies' and method=='get':
     params.extend([
      {'name':'limit','in':'query','schema':{'type':'integer'}},
      {'name':'offset','in':'query','schema':{'type':'integer'}},
      {'name':'q','in':'query','schema':{'type':'string'}},
      {'name':'created_from','in':'query','schema':{'type':'integer'}},
      {'name':'created_to','in':'query','schema':{'type':'integer'}},
      {'name':'status','in':'query','schema':{'type':'string'}},
      {'name':'quiz_id','in':'query','schema':{'type':'string'}},
      {'name':'tag','in':'query','schema':{'type':'string'}}
     ])
    elif path=='/reports/picker':
     params.extend([{'name':'q','in':'query','schema':{'type':'string'}},{'name':'limit','in':'query','schema':{'type':'integer'}}])
    elif path=='/studies/{study_id}/estimate':
     params.extend([{'name':'language','in':'query','schema':{'type':'string'}},{'name':'count','in':'query','schema':{'type':'integer'}}])
    elif path=='/generations/{job_id}/events':
     params.append({'name':'after','in':'query','schema':{'type':'integer'}})
    elif path=='/catalog' and method=='get':
     params.extend([{'name':'q','in':'query','schema':{'type':'string'}},{'name':'language','in':'query','schema':{'type':'string'}},{'name':'tag','in':'query','schema':{'type':'string'}},{'name':'origin','in':'query','schema':{'type':'string'}},{'name':'suggest','in':'query','schema':{'type':'boolean'}},{'name':'limit','in':'query','schema':{'type':'integer'}},{'name':'offset','in':'query','schema':{'type':'integer'}}])
    elif path=='/catalog/questions':
     params.extend([{'name':'q','in':'query','schema':{'type':'string'}},{'name':'language','in':'query','schema':{'type':'string'}},{'name':'origin','in':'query','schema':{'type':'string'}},{'name':'limit','in':'query','schema':{'type':'integer'}}])
    elif path=='/attempts' and method=='get':
     params.extend([
      {'name':'limit','in':'query','schema':{'type':'integer'}},
      {'name':'offset','in':'query','schema':{'type':'integer'}},
      {'name':'q','in':'query','schema':{'type':'string'}},
      {'name':'started_from','in':'query','schema':{'type':'integer'}},
      {'name':'started_to','in':'query','schema':{'type':'integer'}},
      {'name':'quiz_id','in':'query','schema':{'type':'string'}},
      {'name':'tag','in':'query','schema':{'type':'string'}},
      {'name':'status','in':'query','schema':{'type':'string'}}
     ])
    elif path=='/admin/cleanup' and method=='get':
     params.extend([{'name':k,'in':'query','schema':{'type':'integer'}} for k in ('limit','offset')])
    elif path=='/studies/{study_id}/sources/{source_id}/content':
     params.append({'name':'Range','in':'header','schema':{'type':'string'}})
    if path=='/studies' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_CreateStudyInput'}}}}
    elif path=='/studies/prepared' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_PreparedStudyInput'}}}}
    elif path=='/studies/{study_id}' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_UpdateStudyInput'}}}}
    elif path=='/studies/{study_id}/sources' and method=='post':
     body={'required':True,'content':{'multipart/form-data':{'schema':{'type':'object','required':['file'],'properties':{'file':{'type':'string','format':'binary'},'kind':{'type':'string'},'filename':{'type':'string'},'mime_type':{'type':'string'},'content_text':{'type':'string'},'external_ref':{'type':'string'},'fsm_ref':{'type':'string'},'size_bytes':{'type':'integer'},'selection_spec':{'type':'string'},'selection_kind':{'type':'string'},'is_restricted':{'type':'boolean'}}}}}}
    elif path=='/studies/{study_id}/sources/{source_id}/selection' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_SelectionInput'}}}}
    elif path=='/studies/{study_id}/generations' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_StartGenerationInput'}}}}
    elif path=='/studies/{study_id}/questions' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_CreateQuestionInput'}}}}
    elif path=='/studies/{study_id}/questions/import' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_CsvImportBody'}}}}
    elif path=='/studies/{study_id}/questions/{question_id}' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_UpdateQuestionInput'}}}}
    elif path=='/studies/{study_id}/questions/{question_id}/visual_jobs' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_PrepareVisualJobInput'}}}}
    elif path=='/studies/{study_id}/questions/{question_id}/visuals' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_UploadVisualInput'}}}}
    elif path=='/studies/{study_id}/publication' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_PublishBody'}}}}
    elif path=='/me/identity' and method=='put':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_IdentityBody'}}}}
    elif path=='/attempts/{attempt_id}/answers/{question_id}' and method=='put':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_AnswerBody'}}}}
    elif path=='/attempts/{attempt_id}/events' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_EventsBody'}}}}
    elif path=='/admin/settings' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_SettingsPatchBody'}}}}
    elif path=='/admin/schemas/{schema_name}/versions' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_SchemaDraftBody'}}}}
    elif path=='/admin/schemas/{schema_name}/versions/{version}' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_SchemaDraftBody'}}}}
    elif path=='/admin/schemas/{schema_name}/versions/{version}/status' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_SchemaStatusBody'}}}}
    elif path=='/admin/quizzes/{quiz_id}/origin' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_OriginOverrideBody'}}}}
    elif path=='/admin/holders/{holder_id}' and method=='patch':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_HolderUpdateBody'}}}}
    elif path=='/admin/certificates/{certificate_code}/revocation' and method=='post':
     body={'required':True,'content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_RevokeBody'}}}}
    sse=method=='get' and (path=='/logs/stream' or path.endswith('/events'))
    if sse:
     responses={'200':{'description':'Server-sent events stream.','content':{'text/event-stream':{'schema':{'type':'string'},'example':'event: log\ndata: ready\n\n'}}}}
    elif path=='/certificates/{certificate_code}/files/{format}':
     responses={'200':{'description':'Rendered certificate file (PDF or SVG).','content':{'application/pdf':{'schema':{'type':'string','format':'binary'}},'image/svg+xml':{'schema':{'type':'string'}}}},'404':{'description':'Certificate not found or format unsupported.'}}
    elif path=='/studies/{study_id}/sources/{source_id}/content':
     responses={'200':{'description':'Full source artifact stream.', 'content':{'application/octet-stream':{'schema':{'type':'string','format':'binary'}}}},'206':{'description':'Partial range source artifact stream.'},'416':{'description':'Requested byte range not satisfiable.'},'404':{'description':'Source not found.'}}
    elif path=='/studies/{study_id}/questions/{question_id}/visual_jobs' and method=='post':
     responses={'201':{'description':'Prepared visual render job descriptor.','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_PreparedVisualJobResult'}}}},'401':{'description':'Authentication required.'},'403':{'description':'require_owner: caller does not own this study or question.'},'404':{'description':'Study or question not found.'},'409':{'description':'quiz_already_published or reused_question_immutable.'},'410':{'description':'study_expired: elapsed draft or expired study.'},'422':{'description':'invalid_dimensions, scale, or ttl.'},'503':{'description':'Reports service unavailable or render job preparation failed.'}}
    elif path=='/studies/{study_id}/questions/{question_id}/visuals' and method=='post':
     responses={'201':{'description':'Uploaded question visual receipt. Durable identical replay succeeds prior to job expiry lookup.','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_QuestionVisual'}}}},'400':{'description':'visual_insert_failed: newly uploaded visual blob compensation failed with no winning identical visual.'},'401':{'description':'Authentication required.'},'403':{'description':'Caller does not own this study or prepared render job owner mismatch.'},'404':{'description':'Study, question or prepared job not found.'},'409':{'description':'Study/question version mismatch, reused question conflict, or concurrent publication/hash conflict.'},'410':{'description':'study_expired: elapsed draft or expired study.'},'422':{'description':'render_job_expired or payload validation failed.'},'503':{'description':'Database, storage or Reports service unavailable.'}}
    elif path=='/studies/{study_id}/questions/{question_id}/visuals/{visual_id}' and method=='get':
     responses={'200':{'description':'Rendered question visual PNG bytes. Response is private to the study owner with a 300-second cache lifetime.','headers':{'Cache-Control':{'schema':{'type':'string','example':'private, max-age=300'}}},'content':{'image/png':{'schema':{'type':'string','format':'binary'}}}},'403':{'description':'Caller does not own this study question or visual.'},'404':{'description':'Visual not found.'},'503':{'description':'FSM visual store unavailable.'}}
    elif path=='/studies/{study_id}/questions/{question_id}/visual' and method=='post':
     responses={'403':{'description':'Caller does not own this study question.'},'404':{'description':'Question not found.'},'409':{'description':'reused_question_immutable: reused questions cannot be mutated or have visuals altered.'},'422':{'description':'deprecated_visual_endpoint: direct visual_spec rendering is obsolete; use 2-stage prepare (/visual_jobs) and upload (/visuals).'}}
    else:
     schema_map={
      ('/studies','get'):{'$ref':'#/components/schemas/Certifications_StudyHistoryPage'},
      ('/studies','post'):{'type':'object','properties':{'study':{'$ref':'#/components/schemas/Certifications_StudySummary'}}},
      ('/studies/prepared','post'):{'$ref':'#/components/schemas/Certifications_StudyDetail'},
      ('/studies/{study_id}','get'):{'$ref':'#/components/schemas/Certifications_StudyDetail'},
      ('/studies/{study_id}','patch'):{'$ref':'#/components/schemas/Certifications_StudySummary'},
      ('/studies/{study_id}/sources','post'):{'$ref':'#/components/schemas/Certifications_SourceSummary'},
      ('/studies/{study_id}/sources/{source_id}','get'):{'$ref':'#/components/schemas/Certifications_SourceSummary'},
      ('/studies/{study_id}/sources/{source_id}/selection','patch'):{'$ref':'#/components/schemas/Certifications_SourceSummary'},
      ('/studies/{study_id}/analysis','post'):{'$ref':'#/components/schemas/Certifications_AnalysisSummary'},
      ('/studies/{study_id}/analysis','get'):{'$ref':'#/components/schemas/Certifications_AnalysisSummary'},
      ('/studies/{study_id}/estimate','get'):{'$ref':'#/components/schemas/Certifications_EstimateResponse'},
      ('/studies/{study_id}/generations','post'):{'$ref':'#/components/schemas/Certifications_GenerationJobSummary'},
      ('/generations/{job_id}','get'):{'$ref':'#/components/schemas/Certifications_GenerationJobSummary'},
      ('/generations/{job_id}/stop','post'):{'$ref':'#/components/schemas/Certifications_GenerationJobSummary'},
      ('/generations/{job_id}/resume','post'):{'$ref':'#/components/schemas/Certifications_GenerationJobSummary'},
      ('/studies/{study_id}/questions','get'):{'type':'object','properties':{'questions':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_AuthorQuestion'}}}},
      ('/studies/{study_id}/questions','post'):{'$ref':'#/components/schemas/Certifications_AuthorQuestion'},
      ('/studies/{study_id}/questions/import','post'):{'$ref':'#/components/schemas/Certifications_CsvImportResult'},
      ('/studies/{study_id}/questions/{question_id}','patch'):{'$ref':'#/components/schemas/Certifications_AuthorQuestion'},
      ('/studies/{study_id}/questions/{question_id}/visual_jobs','post'):{'$ref':'#/components/schemas/Certifications_PreparedVisualJobResult'},
      ('/studies/{study_id}/questions/{question_id}/visuals','post'):{'$ref':'#/components/schemas/Certifications_QuestionVisual'},
      ('/studies/{study_id}/questions/{question_id}/visual','post'):{'$ref':'#/components/schemas/Certifications_QuestionVisual'},
      ('/catalog','get'):{'$ref':'#/components/schemas/Certifications_CatalogPage'},
      ('/catalog/questions','get'):{'type':'object','properties':{'items':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_PublicQuestionPreview'}}}},
      ('/quizzes/{quiz_id}','get'):{'$ref':'#/components/schemas/Certifications_PublicQuizDetail'},
      ('/quizzes/{quiz_id}/statistics','get'):{'$ref':'#/components/schemas/Certifications_PublicQuizStats'},
      ('/me/quizzes/{quiz_id}/statistics','get'):{'$ref':'#/components/schemas/Certifications_PublicQuizStats'},
      ('/me/quizzes/{quiz_id}/summary','get'):{'$ref':'#/components/schemas/Certifications_OwnerQuizSummary'},
      ('/studies/{study_id}/tags/suggestions','get'):{'type':'object','properties':{'suggestions':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_TagInfo'}}}},
      ('/studies/{study_id}/publication','post'):{'$ref':'#/components/schemas/Certifications_CatalogQuizSummary'},
      ('/me/identity','get'):{'$ref':'#/components/schemas/Certifications_HolderIdentity'},
      ('/me/identity','put'):{'$ref':'#/components/schemas/Certifications_HolderIdentity'},
      ('/quizzes/{quiz_id}/attempts','post'):{'$ref':'#/components/schemas/Certifications_AttemptView'},
      ('/attempts','get'):{'$ref':'#/components/schemas/Certifications_AttemptHistoryPage'},
      ('/attempts/{attempt_id}','get'):{'$ref':'#/components/schemas/Certifications_AttemptView'},
      ('/attempts/{attempt_id}/answers/{question_id}','put'):{'type':'object','properties':{'saved':{'type':'boolean'}}},
      ('/attempts/{attempt_id}/events','post'):{'type':'object','properties':{'recorded':{'type':'integer'}}},
      ('/attempts/{attempt_id}/submit','post'):{'$ref':'#/components/schemas/Certifications_AttemptResults'},
      ('/attempts/{attempt_id}/results','get'):{'$ref':'#/components/schemas/Certifications_AttemptResults'},
      ('/attempts/{attempt_id}/certificate','post'):{'$ref':'#/components/schemas/Certifications_CertificateRecord'},
      ('/certificates/{certificate_code}','get'):{'$ref':'#/components/schemas/Certifications_PublicCertificateVerification'},
      ('/admin/settings','get'):{'type':'object','properties':{'items':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_RuntimeSettingItem'}}}},
      ('/admin/settings','patch'):{'type':'object','properties':{'items':{'type':'array','items':{'$ref':'#/components/schemas/Certifications_RuntimeSettingItem'}}}},
      ('/admin/statistics','get'):{'$ref':'#/components/schemas/Certifications_AdminStatistics'},
      ('/admin/holders/{holder_id}','patch'):{'$ref':'#/components/schemas/Certifications_HolderIdentity'},
     }
     sc=schema_map.get((path,method),{'type':'object','additionalProperties':True})
     status_code='201' if method=='post' and (path.endswith('/attempts') or path.endswith('/prepared') or path.endswith('/sources') or path.endswith('/generations') or path.endswith('/certificate') or path.endswith('/visual_jobs') or path.endswith('/visuals') or path=='/studies' or path.endswith('/questions')) else '204' if method=='delete' and path.endswith('/{question_id}') else '200'
     if status_code=='204':
      responses={'204':{'description':'Operation completed. The response has no body.'}}
     else:
      responses={status_code:{'description':'Operation result.','content':{'application/json':{'schema':sc}}}}
     responses['404']={'description':'Resource not found.'}
     responses['422']={'description':'Input validation failed.'}
    deprecated=path=='/studies/{study_id}/questions/{question_id}/visual' and method=='post'
    operation('certifications',path,method,method.upper()+' '+path,desc,params,body,responses,str(f.relative_to(a.workspace))+':'+str(text[:match.start()].count('\n')+1),deprecated=deprecated)
 if ('/apps/certifications/v1/me/quizzes/{quiz_id}/statistics','get') not in seen:
  operation('certifications','/me/quizzes/{quiz_id}/statistics','get','GET /me/quizzes/{quiz_id}/statistics',desc,[{'name':'quiz_id','in':'path','required':True,'schema':{'type':'string'}}],None,{'200':{'description':'Operation result.','content':{'application/json':{'schema':{'$ref':'#/components/schemas/Certifications_PublicQuizStats'}}}},'404':{'description':'Resource not found.'},'422':{'description':'Input validation failed.'}},'lib/presentation/catalog.rs:1')

def rust_cortex(repo):
 source=repo/'src/presentation'
 if not source.exists():return set(),set()
 main=repo/'src/main.rs'
 selected=set(re.findall(r'cortex_api::presentation::(\w+)::router',main.read_text())) if main.exists() else set()
 if not selected and (source/'mod.rs').exists():
  mod_text=(source/'mod.rs').read_text()
  app_fn=mod_text[mod_text.find('pub fn app_router'):] if 'pub fn app_router' in mod_text else mod_text
  selected=set(re.findall(r'(\w+)::(?:router\w*|routes)\(',app_fn))
 if not selected:
  gaps.append({'app':'cortex','gaps':['Cortex router composition is unresolved; source review is required.']})
  return set(),set()
 # Only the public API/model source tree is inspected. DAL credentials are not models.
 texts={f:f.read_text().split('#[cfg(test)]',1)[0] for base in [source,repo/'src/domain/models'] for f in base.rglob('*.rs')}
 declarations={};names={};local={};new=set()
 def block(text,start,left='{',right='}'):
  depth=1;i=start;quoted=False
  while i<len(text) and depth:
   if text[i]=='"' and (i==0 or text[i-1]!='\\'):quoted=not quoted
   if not quoted:
    if text[i]==left:depth+=1
    elif text[i]==right:depth-=1
   i+=1
  return text[start:i-1],i
 for f,text in texts.items():
  for m in re.finditer(r'(?P<attrs>(?:(?:#\[[^\]]*\]|///[^\n]*)\s*)*)(?:pub\s+)?(?P<kind>struct|enum)\s+(?P<name>\w+)(?:<[^>]*>)?\s*\{',text):
   attrs=m['attrs']
   if 'Deserialize' not in attrs and 'Serialize' not in attrs:continue
   body,_=block(text,m.end());name=m['name'];key='Cortex_'+str(f.relative_to(repo).with_suffix('')).replace('/','_')+'_'+name
   declarations[key]=(f,m['kind'],attrs,body);local[f,name]=key;names.setdefault(name,key);new.add(key)
   components[key]={}
 def typ(value,f):
  value=re.sub(r"^&(?:'\w+\s+)?",'',value.strip())
  value=re.sub(r'\s+','',value).replace('serde_json::','')
  if value.startswith('Option<'):return {'anyOf':[typ(value[7:-1],f),{'type':'null'}]}
  if value.startswith('Vec<'):return {'type':'array','items':typ(value[4:-1],f)}
  if value in ['String','str']:return {'type':'string'}
  if value=='Uuid':return {'type':'string','format':'uuid'}
  if value.startswith('DateTime<'):return {'type':'string','format':'date-time'}
  if value in ['u8','u16','u32','u64','usize','i16','i32','i64']:return {'type':'integer'}
  if value in ['f32','f64']:return {'type':'number'}
  if value=='bool':return {'type':'boolean'}
  name=value.split('::')[-1];key=local.get((f,name),names.get(name))
  return {'$ref':'#/components/schemas/'+key} if key else {}
 for key,(f,kind,attrs,body) in declarations.items():
  if kind=='enum':
   clean=re.sub(r'#\[[^\]]*\]|//[^\n]*','',body)
   if re.fullmatch(r'[\w\s,]+',clean):
    values=[v.strip() for v in clean.split(',') if v.strip()]
    if 'rename_all = "snake_case"' in attrs:values=[re.sub(r'(?<!^)(?=[A-Z])','_',v).lower() for v in values]
    components[key]={'type':'string','enum':values}
   continue
  props={};required=[];field_attrs=''
  for line in body.splitlines():
   line=line.strip()
   if line.startswith('#['):field_attrs+=line;continue
   match=re.match(r'(?:pub\s+)?(\w+):\s*(.+),$',line)
   if not match:continue
   name,value=match.groups();rename=re.search(r'rename\s*=\s*"([^"]+)"',field_attrs)
   if rename:name=rename[1]
   if 'flatten' in field_attrs:
    # Flattened shapes cannot be claimed as an extra JSON field.
    components[key].setdefault('x-discovery-gaps',[]).append('Flattened fields need central review.')
    field_attrs='';continue
   props[name]=typ(value,f)
   if not value.startswith('Option<') and 'default' not in field_attrs:required.append(name)
   field_attrs=''
  model={'type':'object','properties':props,**({'required':required} if required else {})}
  if 'deny_unknown_fields' in attrs:model['additionalProperties']=False
  if components[key].get('x-discovery-gaps'):model['x-discovery-gaps']=components[key]['x-discovery-gaps']
  components[key]=model
 old_doc=json.loads(OUT.read_text()) if OUT.exists() else {}
 def refs(value):
  if isinstance(value,dict):
   ref=value.get('$ref','')
   if ref.startswith('#/components/schemas/'):yield ref.rsplit('/',1)[-1]
   for child in value.values():yield from refs(child)
  elif isinstance(value,list):
   for child in value:yield from refs(child)
 old=set(refs({p:v for p,v in old_doc.get('paths',{}).items() if p.startswith('/apps/cortex/v1/')}))
 pending=list(old)
 while pending:
  for ref in refs(old_doc.get('components',{}).get('schemas',{}).get(pending.pop(),{})):
   if ref not in old:old.add(ref);pending.append(ref)
 for path in list(operations):
  if path.startswith('/apps/cortex/v1/'):
   operations.pop(path);seen.difference_update({entry for entry in seen if entry[0]==path})
 for f,text in texts.items():
  if f.parent!=source or f.stem not in selected:continue
  handlers={}
  for match in re.finditer(r'async fn (\w+)\s*\(',text):
   signature,end=block(text,match.end(),'(',')');tail=text[end:text.find('{',end)];handlers[match[1]]=(signature,tail)
  for match in re.finditer(r'\.route\(\s*"([^"]+)"\s*,',text):
   path=match[1];expr,_=block(text,match.end(),'(',')')
   for method_match in re.finditer(r'\b(get|post|put|patch|delete|head|options)\(',expr):
    method=method_match[1];rest=expr[method_match.end():].lstrip();handler_match=re.match(r'(?:\w+::)*(\w+)',rest)
    signature,tail=handlers.get(handler_match[1],('','')) if handler_match else ('','')
    if rest.startswith('|'):signature=rest[1:rest.find('|',1)]
    params=[];body=None
    for name in re.findall(r'\{(\w+)\}',path):
     params.append({'name':name,'in':'path','required':True,'schema':{'type':'string',**({'format':'uuid'} if 'Path<' in signature and 'Uuid' in signature else {})}})
    query=re.search(r'Query<([^>]+)>',signature)
    if query:
     schema_ref=typ(query[1],f).get('$ref','').rsplit('/',1)[-1];model=components.get(schema_ref,{})
     params += [{'name':name,'in':'query','required':name in model.get('required',[]),'schema':value} for name,value in model.get('properties',{}).items()]
    data=re.search(r'Json<([^>]+)>',signature)
    if data:body={'required':True,'content':{'application/json':{'schema':typ(data[1],f)}}}
    if 'Multipart' in signature:
     body={'required':True,'content':{'multipart/form-data':{'schema':{'type':'object','required':['file','app_id'],'additionalProperties':False,'properties':{'file':{'type':'string','format':'binary'},'app_id':{'type':'string','example':'cortex'},'temporary':{'type':'boolean','default':False}}}}}}
    unknown=['Response data is built by Cortex code; detailed data shape requires central review.']
    responses={'200':{'description':'Cortex result in the message/data envelope. Consult the linked handler for the data shape.','content':{'application/json':{'schema':{'type':'object','required':['message','data'],'properties':{'message':{'type':'string'},'data':{}}}}}},'400':{'description':'Cortex validation or business error. data.error_number identifies the process.'},'403':{'description':'Gateway session or administrator authorization failed.'},'503':{'description':'A required service is unavailable. data.error_number identifies the process.'}}
    if method=='post':responses['201']=responses.pop('200');responses['201']['description']='Resource or chat created. A streaming chat uses an SSE response instead.'
    declared=re.search(r'Envelope<',tail)
    known=None
    if declared:
     data_type,_=block(tail,declared.end(),'<','>');known=typ(data_type,f)
    elif rest.startswith('|'):
     constructor=re.search(r'Envelope::new\(\s*"[^"]*"\s*,\s*(\w+)::(?:from|new)\(',rest)
     if constructor:known=typ(constructor[1],f)
    if known:
     for response in responses.values():
      content=response.get('content',{}).get('application/json')
      if content:content['schema']['properties']['data']=known
     unknown=[]
    if method=='post' and path=='/files':
     responses['200']={'description':'Upload could not be saved. The notice number explains why; no file_id is returned.'}
    if method=='get' and (path=='/logs/stream' or path.endswith('/events') or path.endswith('/commands')):
     responses['200']={'description':'Live SSE events. Stage streams emit session_id and output_id in the initial event and support Last-Event-ID/after/cursor resumption. Logs require administrator access.','content':{'text/event-stream':{'schema':{'type':'string'}}}};unknown=[]
    elif method=='get' and path=='/files/{file_id}/content':
     responses['200']={'description':'Stored file bytes. Content-Type follows the stored file.','content':{'*/*':{'schema':{'type':'string','format':'binary'}}}};unknown=[]
    if method=='post' and path in ['/chats','/chats/{session_id}/inputs']:
     responses['200']={'description':'When stream=true, live progress, stage (initial event emits session_id and output_id), answer and terminal SSE events.','content':{'text/event-stream':{'schema':{'type':'string'}}}}
    operation('cortex',path,method,method.upper()+' '+path,'Cortex Rust v2. The gateway owns authentication and supplies identity. Requests stay JSON except multipart file uploads. Model context format does not change the HTTP contract.',params,body,responses,str(f.relative_to(a.workspace))+':'+str(text[:match.start()].count('\n')+1),unknown=unknown)
 return new,old


registry=json.loads((ROOT/'src/core/apps.json').read_text())
for app,folder in [('gateway','api_for_apps')]+[(app,v['source']) for app,v in registry.items() if v['language']=='python']:
 repo=a.workspace/folder
 if app=='gateway' and (ROOT/'src/presentation/assets/gateway_contracts.json').exists():
  central=json.loads((ROOT/'src/presentation/assets/gateway_contracts.json').read_text());components.update(central['schemas']);operations.update(central['paths']);seen.update((path,method) for path,methods in central['paths'].items() for method in methods)
 elif repo.exists():python_app(app,repo)
 else:gaps.append({'app':app,'gaps':['Source repository not available']})
rust_reports(a.workspace/'reports')
rust_annotations(a.workspace/'annotations_api')
rust_certifications(a.workspace/'certifications_api')
cortex_new,cortex_old=rust_cortex(a.workspace/'cortex_api')
operation('gateway','/apps/api/v1/logs/stream','get','Stream gateway logs','Server-sent events from the running gateway. Only administrators can connect. Events are transient and bounded; slow consumers receive gap events. Authorization is rechecked during the connection.',[],None,{'200':{'description':'Live SSE log stream.','content':{'text/event-stream':{'schema':{'type':'string'},'example':'event: log\ndata: gateway ready\n\n'}}},'403':{'description':'Administrator authorization required.'}},'src/presentation/logs.rs')
if OVERRIDE.exists():
 for key,override in json.loads(OVERRIDE.read_text()).items():
  method,path=key.split(' ',1)
  if path in operations and method.lower() in operations[path]:operations[path][method.lower()].update(override)
# Missing sources retain centrally owned last-known contracts instead of deleting documentation.
CENTRAL_OUT=pathlib.Path(__file__).resolve().parents[1]/'src/presentation/assets/openapi.json'
previous=json.loads(OUT.read_text()) if OUT.exists() else json.loads(CENTRAL_OUT.read_text()) if CENTRAL_OUT.exists() else {}
for app,entry in registry.items():
 repo=a.workspace/entry['source']
 if not repo.exists() or entry['language']=='rust' and not (repo/('src/presentation' if app=='cortex' else 'lib/presentation/mod.rs' if app in ('annotations','certifications') else 'engine/src/presentation/api/server.rs')).exists():
  for path,ms in previous.get('paths',{}).items():
   for method,op in ms.items():
    if op.get('tags')==[app]:operations.setdefault(path,{})[method]=op
  for name,model in previous.get('components',{}).get('schemas',{}).items():components.setdefault(name,model)
  if entry['language']=='rust':gaps.append({'app':app,'gaps':['Source unavailable; retaining last central contract']})
  continue
 digest=source_hash(repo,'rs' if entry['language']=='rust' else 'py')
 for path,ms in operations.items():
  for method,op in ms.items():
   if op.get('tags')==[app]:op['x-source-tree-sha256']=digest
ACCEPTED_PRIOR_SCHEMAS={
 'Certifications_PrepareVisualJobInput':{
  'type':'object',
  'properties':{
   'template_id':{'type':'string'},
   'template_version':{'type':'integer'},
   'mapping':{'type':'object','additionalProperties':{'type':'array','items':{'type':'string'}}},
   'config':{'type':'object','additionalProperties':True},
   'rows':{'type':'array','items':{'type':'object','additionalProperties':True}},
   'width':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'height':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'scale':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'ttl_seconds':{'anyOf':[{'type':'integer'},{'type':'null'}]}
  },
  'required':['template_id','template_version','mapping','config','rows']
 },
 'Certifications_RenderJobDescriptor':{
  'type':'object',
  'properties':{
   'job_id':{'type':'string'},
   'template_id':{'type':'string'},
   'template_version':{'type':'integer'},
   'mapping':{'type':'object','additionalProperties':{'type':'array','items':{'type':'string'}}},
   'config':{'type':'object','additionalProperties':True},
   'rows':{'type':'array','items':{'type':'object','additionalProperties':True}},
   'width':{'type':'integer'},
   'height':{'type':'integer'},
   'scale':{'type':'integer'},
   'expires_at':{'type':'integer'}
  },
  'required':['job_id','template_id','template_version','mapping','config','rows','width','height','scale','expires_at']
 },
 'Certifications_PreparedVisualJobResult':{
  'type':'object',
  'properties':{
   'question_id':{'type':'string'},
   'question_version_id':{'type':'string'},
   'render_job':{'$ref':'#/components/schemas/Certifications_RenderJobDescriptor'}
  },
  'required':['question_id','question_version_id','render_job']
 },
 'Certifications_UploadVisualInput':{
  'type':'object',
  'properties':{
   'question_version_id':{'type':'string'},
   'render_job_id':{'type':'string'},
   'expected_width':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'expected_height':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'expected_scale':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'png_base64':{'type':'string'}
  },
  'required':['question_version_id','render_job_id','png_base64']
 },
 'Certifications_QuestionVisual':{
  'type':'object',
  'properties':{
   'id':{'type':'string'},
   'fsm_ref':{'type':'string'},
   'mime_type':{'type':'string'},
   'created_at':{'type':'integer'}
  },
  'required':['id','fsm_ref','mime_type','created_at']
 },
 'Certifications_VisualRenderBody':{
  'type':'object',
  'properties':{
   'visual_spec':{'type':'object','additionalProperties':True}
  },
  'required':['visual_spec']
 },
 'Certifications_CreateStudyInput':{
  'type':'object',
  'properties':{
   'title':{'type':'string'},
   'description':{'type':'string'}
  },
  'required':['title']
 },
 'Certifications_ScoreBandCount':{
  'type':'object',
  'properties':{
   'band':{'type':'string'},
   'count':{'type':'integer'},
   'percentage':{'type':'number'}
  },
  'required':['band','count','percentage']
 },
 'Certifications_QuestionProvenanceStats':{
  'type':'object',
  'properties':{
   'total_questions':{'type':'integer'},
   'generated_with_cortex_count':{'type':'integer'},
   'supplied_by_creator_count':{'type':'integer'}
  },
  'required':['total_questions','generated_with_cortex_count','supplied_by_creator_count']
 },
 'Certifications_AttemptHistoryItem':{
  'type':'object',
  'properties':{
   'id':{'type':'string'},
   'quiz_id':{'type':'string'},
   'quiz_version_id':{'type':'string'},
   'status':{'type':'string'},
   'score_correct':{'type':'integer'},
   'score_total':{'type':'integer'},
   'started_at':{'type':'integer'},
   'completed_at':{'anyOf':[{'type':'integer'},{'type':'null'}]}
  },
  'required':['id','quiz_id','quiz_version_id','status','score_correct','score_total','started_at']
 },
 'Certifications_PublicQuizStats':{
  'type':'object',
  'properties':{
   'quiz_id':{'type':'string'},
   'completed_attempt_count':{'type':'integer'},
   'distinct_participants':{'type':'integer'},
   'basis':{'type':'string'},
   'average_score_pct':{'anyOf':[{'type':'number'},{'type':'null'}]},
   'typical_duration_sec':{'anyOf':[{'type':'integer'},{'type':'null'}]}
  },
  'required':['quiz_id','completed_attempt_count','distinct_participants','basis']
 },
 'Certifications_QuotaMeter':{
  'type':'object',
  'properties':{
   'used_bytes':{'type':'integer'},
   'reserved_bytes':{'type':'integer'},
   'max_file_bytes':{'type':'integer'},
   'max_study_bytes':{'type':'integer'},
   'max_account_bytes':{'type':'integer'},
   'remaining_account_bytes':{'type':'integer'}
  },
  'required':['used_bytes','reserved_bytes','max_file_bytes','max_study_bytes','max_account_bytes','remaining_account_bytes']
 },
 'Certifications_SourceSummary':{
  'type':'object',
  'properties':{
   'id':{'type':'string'},
   'filename':{'type':'string'},
   'mime_type':{'type':'string'},
   'size_bytes':{'type':'integer'},
   'sha256':{'type':'string'},
   'fsm_ref':{'type':'string'},
   'source_kind':{'type':'string'},
   'status':{'type':'string'},
   'selection_kind':{'type':'string'},
   'selection_spec':{'type':'string'},
   'is_restricted':{'type':'boolean'},
   'external_ref':{'type':'string'},
   'created_at':{'type':'integer'},
   'updated_at':{'type':'integer'}
  },
  'required':['id','filename','mime_type','size_bytes','sha256','fsm_ref','source_kind','status','selection_kind','selection_spec','is_restricted','external_ref','created_at','updated_at']
 },
 'Certifications_StudySummary':{
  'type':'object',
  'properties':{
   'id':{'type':'string'},
   'title':{'type':'string'},
   'description':{'type':'string'},
   'source_origin':{'type':'string'},
   'status':{'type':'string'},
   'quiz_id':{'type':'string'},
   'expires_at':{'anyOf':[{'type':'integer'},{'type':'null'}]},
   'created_at':{'type':'integer'},
   'updated_at':{'type':'integer'}
  },
  'required':['id','title','description','source_origin','status','quiz_id','created_at','updated_at']
 }
}

def check_local_refs(doc):
 def find_all_refs(val):
  if isinstance(val,dict):
   for k,v in val.items():
    if k=='$ref':yield v
    else:yield from find_all_refs(v)
  elif isinstance(val,list):
   for item in val:yield from find_all_refs(item)
 schemas=doc.get('components',{}).get('schemas',{})
 dangling=[]
 for ref in sorted(set(find_all_refs(doc))):
  if ref.startswith('#/components/schemas/'):
   name=ref[len('#/components/schemas/'):]
   if name not in schemas:dangling.append(ref)
 return dangling

# Remove only obsolete Cortex models after all live operation references settle.
def component_refs(value):
 if isinstance(value,dict):
  ref=value.get('$ref','')
  if ref.startswith('#/components/schemas/'):yield ref.rsplit('/',1)[-1]
  for child in value.values():yield from component_refs(child)
 elif isinstance(value,list):
  for child in value:yield from component_refs(child)
used=set(component_refs(operations)) | set(components.keys());pending=list(used)
while pending:
 ref=pending.pop()
 if ref not in components:
  if ref in previous.get('components',{}).get('schemas',{}):
   components[ref]=previous['components']['schemas'][ref]
  elif ref in ACCEPTED_PRIOR_SCHEMAS:
   components[ref]=ACCEPTED_PRIOR_SCHEMAS[ref]
 if ref in components:
  for r in component_refs(components[ref]):
   if r not in used:
    used.add(r);pending.append(r)
for name in cortex_new|cortex_old:
 if name not in used:components.pop(name,None)
gaps=[g for g in gaps if g.get('path') not in operations or operations[g['path']].get(g.get('method',''),{}).get('x-discovery-gaps')]
result={'openapi':'3.1.0','info':{'title':'Asodya Application Gateway API','version':__import__('tomllib').loads((ROOT/'Cargo.toml').read_text())['package']['version'],'description':'Central English documentation for authentication, support, telemetry and every registered application. Documentation is public. Operation permissions remain enforced. All contracts and explanatory content are owned by api_for_apps. Source discovery never fetches downstream OpenAPI documents. Backends receive x-display-name only when account identity is attached and a first or last name exists. The value joins nonblank stored first and last names with one space and percent-encodes their UTF-8 bytes. Decode once with a UTF-8 percent decoder, not a form decoder. Client-sent copies are removed on all proxy routes. No route or setting is added.'},'servers':[{'url':'https://api.asodya.com'}],'paths':dict(sorted(operations.items())),'components':{'schemas':components,'securitySchemes':{'SessionCookie':{'type':'apiKey','in':'cookie','name':'sid'},'AdminKey':{'type':'apiKey','in':'header','name':'Authorization'}}},'x-discovery-gaps':gaps}
dangling=check_local_refs(result)
if dangling:
 raise SystemExit('Dangling schema references found ('+str(len(dangling))+'): '+', '.join(dangling))
rendered=json.dumps(result,indent=2,sort_keys=True)+'\n'
if a.check:
 if not OUT.exists() or OUT.read_text()!=rendered:raise SystemExit('Central contracts differ from source; regenerate and review')
else:OUT.write_text(rendered)
print(sum(len(x) for x in operations.values()),'operations;',len(gaps),'explicit discovery gaps')
