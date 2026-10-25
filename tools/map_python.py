#!/usr/bin/env python3
"""Read Python source without importing services; produce a local migration inventory."""
import ast,json,pathlib,argparse
p=argparse.ArgumentParser();p.add_argument('--source',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
r=[]
for f in sorted(a.source.rglob('*.py')):
 if any(x.startswith('.') or x in ('docs','target','build','dist') for x in f.relative_to(a.source).parts):continue
 t=ast.parse(f.read_text()); classes={}
 for node in ast.walk(t):
  if isinstance(node,ast.ClassDef):
   for c in node.body:classes[id(c)]=node.name
 for n in ast.walk(t):
  if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
  r.append({'file':str(f.relative_to(a.source)),'line':n.lineno,'symbol':classes.get(id(n),'')+'.'+n.name,'async':isinstance(n,ast.AsyncFunctionDef),'arguments':ast.unparse(n.args),'purpose':ast.get_docstring(n),'decorators':[ast.unparse(d) for d in n.decorator_list],'calls':sorted({ast.unparse(x.func) for x in ast.walk(n) if isinstance(x,ast.Call)})})
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(r,indent=2));print(len(r),'function definitions inventoried')
