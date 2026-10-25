#!/usr/bin/env python3
"""Central source-only route discovery. Never reads downstream OpenAPI endpoints.
Run from api_for_apps. Reads sibling sources without importing their applications.
Unknown contracts remain marked x-discovery-gaps. Central overrides can fill them.
"""
import ast,json,pathlib,re,argparse,hashlib
ROOT=pathlib.Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--workspace',type=pathlib.Path,default=ROOT.parent);p.add_argument('--check',action='store_true');a=p.parse_args()
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
def operation(app,path,method,summary,description,params,body,responses,source,ws=False,unknown=None):
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
 if level!='public':security=[{'SessionCookie':[]},{'AdminKey':[]}]
 narrative=f'{summary}. This operation belongs to {app}. Send requests through the Asodya gateway at the path shown here. '
 narrative+= {'public':'The gateway allows anonymous access to this operation. The backend can apply additional validation.','session':'Use the sid session cookie. Mutable session requests also require the csrf cookie and matching X-CSRF-Token header.','administrator':'Administrative access is required before execution. Use the administrative credential or an authorized administrator session. Mutable session requests require CSRF validation.'}[level]
 if description:narrative+='\n\n'+description
 if ws:narrative+='\n\nThis endpoint upgrades to WebSocket. Use wss://api.asodya.com with the same path. Authorize before connecting. It streams live log entries and does not create a log archive.'
 op={'operationId':re.sub('[^a-zA-Z0-9_]','_',app+'_'+method+'_'+path),'tags':[app],'summary':summary,'description':narrative,'parameters':params,'responses':responses or {'default':{'description':'Response contract not declared in source; inspect the implementation.','content':{'application/json':{'schema':{}}}}},'security':security,'x-source':source,'x-access-level':level}
 for param in re.findall(r'\{(\w+)\}',full):
  if not any(p['name']==param and p['in']=='path' for p in op['parameters']):op['parameters'].append({'name':param,'in':'path','required':True,'schema':{'type':'string'}})
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
def rust_models(repo):
 texts=[]
 for f in (repo/'engine/src').rglob('*.rs'):
  text=f.read_text();texts.append((f,text))
  for m in re.finditer(r'pub struct (\w+)(?:<[^>]+>)?\s*\{',text):components.setdefault(m.group(1),{'type':'object'})
 for f,text in texts:
  for m in re.finditer(r'pub struct (\w+)(?:<[^>]+>)?\s*\{',text):
   end=text.find('\n}',m.end());body=text[m.end():end];props={};required=[];attrs='';doc=[]
   for line in body.splitlines():
    line=line.strip()
    if line.startswith('///'):doc.append(line[3:].strip());continue
    if line.startswith('#['):attrs+=line;continue
    fm=re.match(r'pub (\w+):\s*(.+),$',line)
    if not fm:continue
    k,typ=fm.groups();sc=rust_schema(typ)
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
    if not responses:unknown.append('Dynamic Rust response shape requires central review.')
    operation('reports',prefix+path,method,summary_match.group(1) if summary_match else method.upper()+' '+path,desc_match.group(1) if desc_match else 'Reports operation discovered directly from route registration and handler source.',params,body,responses or None,str(f.relative_to(a.workspace))+':'+str(text[:pos].count('\n')+1),unknown=unknown)
registry=json.loads((ROOT/'src/core/apps.json').read_text())
for app,folder in [('gateway','api_for_apps')]+[(app,v['source']) for app,v in registry.items() if v['language']=='python']:
 repo=a.workspace/folder
 if app=='gateway' and (ROOT/'src/presentation/assets/gateway_contracts.json').exists():
  central=json.loads((ROOT/'src/presentation/assets/gateway_contracts.json').read_text());components.update(central['schemas']);operations.update(central['paths']);seen.update((path,method) for path,methods in central['paths'].items() for method in methods)
 elif repo.exists():python_app(app,repo)
 else:gaps.append({'app':app,'gaps':['Source repository not available']})
rust_reports(a.workspace/'reports')
operation('gateway','/apps/api/v1/logs/stream','get','Stream gateway logs','Server-sent events from the running gateway. Only administrators can connect. Events are transient and bounded; slow consumers receive gap events. Authorization is rechecked during the connection.',[],None,{'200':{'description':'Live SSE log stream.','content':{'text/event-stream':{'schema':{'type':'string'},'example':'event: log\ndata: gateway ready\n\n'}}},'403':{'description':'Administrator authorization required.'}},'src/presentation/logs.rs')
if OVERRIDE.exists():
 for key,override in json.loads(OVERRIDE.read_text()).items():
  method,path=key.split(' ',1)
  if path in operations and method.lower() in operations[path]:operations[path][method.lower()].update(override)
gaps=[g for g in gaps if g.get('path') not in operations or operations[g['path']].get(g.get('method',''),{}).get('x-discovery-gaps')]
result={'openapi':'3.1.0','info':{'title':'Asodya Application Gateway API','version':'1.2.0','description':'Central English documentation for authentication, support, telemetry and every registered application. Documentation is public. Operation permissions remain enforced. All contracts and explanatory content are owned by api_for_apps. Source discovery never fetches downstream OpenAPI documents.'},'servers':[{'url':'https://api.asodya.com'}],'paths':dict(sorted(operations.items())),'components':{'schemas':components,'securitySchemes':{'SessionCookie':{'type':'apiKey','in':'cookie','name':'sid'},'AdminKey':{'type':'apiKey','in':'header','name':'Authorization'}}},'x-discovery-gaps':gaps}
rendered=json.dumps(result,indent=2)+'\n'
if a.check:
 if not OUT.exists() or OUT.read_text()!=rendered:raise SystemExit('Central contracts differ from source; regenerate and review')
else:OUT.write_text(rendered)
print(sum(len(x) for x in operations.values()),'operations;',len(gaps),'explicit discovery gaps')
