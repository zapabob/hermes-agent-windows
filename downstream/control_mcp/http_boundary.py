"""ASGI ingress protection around the actual SDK transport, not an MCP emulator."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
import json
import time
from urllib.parse import urlsplit

from .contracts import ControlContext, ControlError, MAX_REQUEST_BYTES, decode_request

_current: ContextVar[ControlContext | None] = ContextVar('hermes_control_context',default=None)


def current_control_context() -> ControlContext:
    value=_current.get()
    if type(value) is not ControlContext:
        raise ControlError('unauthenticated')
    return value


async def _json(send,status,payload,*,headers=()):
    data=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    await send({'type':'http.response.start','status':status,
                'headers':[(b'content-type',b'application/json'),(b'cache-control',b'no-store'),*headers]})
    await send({'type':'http.response.body','body':data})


class AuthenticatedControlASGI:
    def __init__(self,app,*,verifier,allowed_hosts:tuple[str,...],allowed_origins:tuple[str,...],clock=time.time):
        if (not allowed_hosts or any(type(h) is not str or not h or '*' in h or '/' in h for h in allowed_hosts)
                or any(type(o) is not str or not o.startswith('https://') or '*' in o for o in allowed_origins)):
            raise ControlError('invalid_host_configuration')
        self.app,self.verifier,self.clock=app,verifier,clock
        self.hosts=frozenset(h.lower() for h in allowed_hosts)
        self.origins=frozenset(allowed_origins)
        url=urlsplit(verifier.resource)
        self.resource_scheme=url.scheme
        self.resource_authority=url.netloc.lower()
        self.path=url.path.rstrip('/')
        if not self.path:
            raise ControlError('invalid_host_configuration')
        self.metadata_path='/.well-known/oauth-protected-resource'+self.path
        self.metadata_url=f'{url.scheme}://{url.netloc}{self.metadata_path}'

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':
            return await self.app(scope,receive,send)
        headers={}
        for key,value in scope.get('headers',[]):
            key=key.lower()
            if key in headers and key in (b'host',b'origin',b'authorization',b'content-length'):
                return await _json(send,400,{'error':'ambiguous_headers'})
            headers[key]=value
        host=headers.get(b'host',b'').decode('latin-1').lower()
        origin=headers.get(b'origin',b'').decode('latin-1')
        if host not in self.hosts:
            return await _json(send,421,{'error':'invalid_host'})
        if b'origin' in headers and origin not in self.origins:
            return await _json(send,403,{'error':'invalid_origin'})
        if self.resource_scheme=='http':
            peer=(scope.get('client') or ('',0))[0]
            if (scope.get('scheme')!='http' or peer not in ('127.0.0.1','::1')
                    or host!=self.resource_authority):
                return await _json(send,403,{'error':'tls_required'})
        elif scope.get('scheme')!='https':
            return await _json(send,403,{'error':'tls_required'})
        if scope.get('query_string'):
            return await _json(send,400,{'error':'query_not_supported'})
        path=scope.get('path','')
        if path==self.metadata_path and scope['method']=='GET':
            return await _json(send,200,{'resource':self.verifier.resource,
                                        'authorization_servers':[self.verifier.issuer],
                                        'bearer_methods_supported':['header'],
                                        'scopes_supported':['hermes:read']})
        if path not in (self.path,self.path+'/'):
            return await _json(send,404,{'error':'not_found'})
        if scope['method'] not in ('GET','POST','DELETE'):
            return await _json(send,405,{'error':'method_not_allowed'})
        header=headers.get(b'authorization',b'').decode('latin-1')
        pieces=header.split(' ')
        try:
            if len(pieces)!=2 or pieces[0].lower()!='bearer' or not pieces[1]:
                raise ControlError('invalid_token')
            ctx=self.verifier.verify(pieces[1],now=self.clock())
        except ControlError as exc:
            status=503 if exc.code=='auth_unavailable' else 401
            challenge=f'Bearer resource_metadata="{self.metadata_url}"'
            return await _json(send,status,{'error':exc.code},headers=[(b'www-authenticate',challenge.encode())])
        if b'mcp-session-id' in headers:
            return await _json(send,400,{'error':'stateless_session_required'})
        body=None
        if scope['method']=='POST':
            if headers.get(b'content-encoding',b'identity')!=b'identity':
                return await _json(send,415,{'error':'content_encoding_not_supported'})
            if headers.get(b'content-type',b'').split(b';')[0].strip()!=b'application/json':
                return await _json(send,415,{'error':'json_required'})
            collected=bytearray()
            try:
                async with asyncio.timeout(10):
                    while True:
                        event=await receive()
                        if event['type']=='http.disconnect':
                            return
                        collected.extend(event.get('body',b''))
                        if len(collected)>MAX_REQUEST_BYTES:
                            raise ControlError('request_too_large')
                        if not event.get('more_body',False):
                            break
                body=bytes(collected)
                decode_request(body)
            except (ControlError,TimeoutError) as exc:
                code=exc.code if isinstance(exc,ControlError) else 'request_timeout'
                return await _json(send,413 if code=='request_too_large' else 400,{'error':code})
        delivered=False
        async def replay():
            nonlocal delivered
            if body is not None and not delivered:
                delivered=True
                return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        # The SDK/tool context needs verified identity, not the bearer or cookie.
        clean=dict(scope)
        clean['state']={**scope.get('state',{}),'control_context':ctx}
        clean['headers']=[(k,v) for k,v in scope.get('headers',[]) if k.lower() not in (b'authorization',b'cookie')]
        binding=_current.set(ctx)
        try:
            await self.app(clean,replay,send)
        finally:
            _current.reset(binding)
