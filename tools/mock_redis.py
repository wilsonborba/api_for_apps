"""Loopback RESP2 test double. No persistence and no external connections."""
import asyncio,time
values={};exp={}
async def read(r):
 line=await r.readline()
 if not line:raise EOFError
 if line[:1]==b'*':return [await read(r) for _ in range(int(line[1:]))]
 if line[:1]==b'$':
  n=int(line[1:]);v=await r.readexactly(n+2);return v[:-2]
 return line[1:-2]
def encode(v):
 if v is None:return b'$-1\r\n'
 if isinstance(v,int):return b':'+str(v).encode()+b'\r\n'
 if isinstance(v,list):return b'*'+str(len(v)).encode()+b'\r\n'+b''.join(encode(x) for x in v)
 return b'$'+str(len(v)).encode()+b'\r\n'+v+b'\r\n'
async def handle(r,w):
 try:
  while True:
   args=await read(r);cmd=args[0].upper();args=args[1:];now=time.monotonic()
   for k in list(exp):
    if exp[k]<=now:values.pop(k,None);exp.pop(k,None)
   key=args[0] if args else None
   if cmd==b'HELLO':out=b'%7\r\n+server\r\n+redis\r\n+version\r\n+7.2.0\r\n+proto\r\n:3\r\n+id\r\n:1\r\n+mode\r\n+standalone\r\n+role\r\n+master\r\n+modules\r\n*0\r\n'
   elif cmd in (b'CLIENT',b'AUTH',b'SELECT'):out=b'+OK\r\n'
   elif cmd==b'PING':out=b'+PONG\r\n'
   elif cmd==b'GET':out=encode(values.get(key))
   elif cmd==b'GETDEL':out=encode(values.pop(key,None));exp.pop(key,None)
   elif cmd==b'SET':
    if b'NX' in args and key in values:out=encode(None)
    else:
     values[key]=args[1]
     if b'EX' in args:exp[key]=now+int(args[args.index(b'EX')+1])
     out=b'+OK\r\n'
   elif cmd==b'INCR':n=int(values.get(key,b'0'))+1;values[key]=str(n).encode();out=encode(n)
   elif cmd==b'EXPIRE':exp[key]=now+int(args[1]);out=encode(int(key in values))
   elif cmd==b'TTL':out=encode(int(exp[key]-now) if key in exp else -1 if key in values else -2)
   elif cmd==b'DEL':n=sum(k in values for k in args);[values.pop(k,None) for k in args];out=encode(n)
   elif cmd==b'EXISTS':out=encode(sum(k in values for k in args))
   elif cmd==b'QUIT':break
   else:out=b'-ERR unsupported fixture command\r\n'
   w.write(out);await w.drain()
 except (EOFError,asyncio.IncompleteReadError,ConnectionError):pass
 finally:w.close();await w.wait_closed()
async def main():
 server=await asyncio.start_server(handle,'127.0.0.1',18191)
 async with server:await server.serve_forever()
asyncio.run(main())
