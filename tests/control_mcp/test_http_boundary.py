"""HTTP auth/ingress integration; the downstream fixture is NOT an MCP SDK."""
import asyncio
from dataclasses import replace
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


@pytest.fixture
def http_boundary(control_module):
    def build():
        auth=control_module('auth')
        transport=control_module('http_boundary')
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        pem=private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        grants={c:auth.HostGrant(subject='human-1',client_registration=c,revision=1,
                                scopes=('hermes:read',),profiles=(p,),workspaces=((p,'w1'),))
                for c,p in [('codex','p1'),('chatgpt','p2')]}
        verifier=auth.ResourceVerifier(issuer='https://issuer.invalid',resource='https://hermes.invalid/api/control/mcp',
                                      public_keys={'k1':pem},grant_lookup=lambda sub,c:grants.get(c) if sub=='human-1' else None)
        calls=[]
        async def downstream(scope,receive,send):
            await asyncio.sleep(0)
            ctx=transport.current_control_context()
            assert ctx is scope['state']['control_context']
            assert all(k not in (b'authorization', b'cookie') for k,v in scope.get('headers',[]))
            calls.append((scope['method'],ctx.client_registration))
            data=json.dumps({'client':ctx.client_registration,'profiles':ctx.profiles}).encode()
            await send({'type':'http.response.start','status':200,'headers':[(b'content-type',b'application/json')]})
            await send({'type':'http.response.body','body':data})
        app=transport.AuthenticatedControlASGI(downstream,verifier=verifier,
            allowed_hosts=('hermes.invalid',),allowed_origins=('https://chatgpt.com',),clock=lambda:100)
        def token(client='codex',**changes):
            claims={'iss':verifier.issuer,'aud':verifier.resource,'sub':'human-1','client_id':client,
                    'scope':'hermes:read','iat':90,'exp':200,'grant_revision':1,**changes}
            return jwt.encode(claims,private,algorithm='RS256',headers={'kid':'k1','typ':'at+jwt'})
        return app,calls,token,grants,transport
    return build


@pytest.mark.asyncio
@pytest.mark.parametrize('method',['GET','POST','DELETE'])
@pytest.mark.parametrize('path',['/api/control/mcp','/api/control/mcp/'])
async def test_every_mcp_method_and_slash_requires_bearer(http_boundary,method,path):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        response=await client.request(method,path,headers={'Cookie':'session=fake-dashboard-session'})
        assert response.status_code==401
        assert 'resource_metadata=' in response.headers['www-authenticate']
        assert calls==[]


@pytest.mark.asyncio
async def test_both_clients_are_scoped_in_concurrent_calls(http_boundary):
    app,calls,token,_,transport=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        async def run(name):
            return await client.post('/api/control/mcp',json={'jsonrpc':'2.0','id':1,'method':'ping'},
                                     headers={'Authorization':'Bearer '+token(name)})
        codex,chatgpt=await asyncio.gather(run('codex'),run('chatgpt'))
        assert codex.json()=={'client':'codex','profiles':['p1']}
        assert chatgpt.json()=={'client':'chatgpt','profiles':['p2']}
    with pytest.raises(Exception,match='unauthenticated'):
        transport.current_control_context()


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [{'Origin':'https://evil.invalid'}, {'Host':'evil.invalid'},
                                    {'Origin':'null'}, {'X-Forwarded-Host':'evil.invalid','Host':'evil.invalid'}])
async def test_untrusted_host_or_origin_never_reaches_tools(http_boundary,headers):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        response=await client.get('/api/control/mcp',headers={'Authorization':'Bearer '+token(),**headers})
        assert response.status_code in (400,403,421)
        assert calls==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('payload', [b'{"method":"one","method":"two"}', b'[]',b'{"v":NaN}',b'\xff',b' '*33000],ids=['duplicate','array','nonfinite','invalid-utf8','oversize'])
async def test_invalid_or_oversized_body_is_rejected_before_dispatch(http_boundary,payload):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        r=await client.post('/api/control/mcp',content=payload,
            headers={'Authorization':'Bearer '+token(),'Content-Type':'application/json'})
        assert r.status_code in (400,413)
        assert calls==[]


@pytest.mark.asyncio
async def test_revocation_applies_to_next_http_request(http_boundary):
    app,calls,token,grants,_=http_boundary()
    bearer=token()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        assert (await client.get('/api/control/mcp',headers={'Authorization':'Bearer '+bearer})).status_code==200
        grants['codex']=replace(grants['codex'],enabled=False)
        assert (await client.get('/api/control/mcp',headers={'Authorization':'Bearer '+bearer})).status_code==401
    assert len(calls)==1


@pytest.mark.asyncio
async def test_metadata_is_public_minimal_and_never_contains_keys(http_boundary):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        r=await client.get('/.well-known/oauth-protected-resource/api/control/mcp')
        assert r.status_code==200
        assert r.json()['resource']=='https://hermes.invalid/api/control/mcp'
        assert r.json()['authorization_servers']==['https://issuer.invalid']
        assert 'public_keys' not in r.text and 'human-1' not in r.text
        assert not calls


@pytest.mark.asyncio
async def test_arbitrary_subpath_and_query_tokens_are_not_forwarded(http_boundary):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        for path in ('/api/control/mcp/secret','/api/control/mcp?access_token='+token()):
            r=await client.get(path,headers={'Authorization':'Bearer '+token()})
            assert r.status_code in (400,404)
        assert not calls


@pytest.mark.asyncio
async def test_duplicate_auth_headers_are_rejected(http_boundary):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        r=await client.get('/api/control/mcp',headers=[('Authorization','Bearer '+token()),('Authorization','Bearer '+token('chatgpt'))])
        assert r.status_code==400
        assert not calls


@pytest.mark.asyncio
async def test_valid_but_oversized_json_is_413(http_boundary):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        r=await client.post('/api/control/mcp',json={'payload':'x'*33000},headers={'Authorization':'Bearer '+token()})
        assert r.status_code==413
        assert not calls


@pytest.mark.asyncio
async def test_present_but_empty_origin_is_not_native_origin_absence(http_boundary):
    app,calls,token,_,_=http_boundary()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='https://hermes.invalid') as client:
        r=await client.get('/api/control/mcp',headers={'Authorization':'Bearer '+token(),'Origin':''})
        assert r.status_code==403
        assert not calls
