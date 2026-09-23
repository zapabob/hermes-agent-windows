"""Real asymmetric JWTs through the resource verifier; no production credentials."""
from dataclasses import replace
import json

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


@pytest.fixture(scope='module')
def keys():
    private = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def setup(control_module, keys, *, grant_changes=None):
    auth=control_module('auth')
    grant=auth.HostGrant(subject='human-1', client_registration='codex', revision=1,
                        scopes=('hermes:read','hermes:run:start'), profiles=('p1',),
                        workspaces=(('p1','w1'),))
    if grant_changes:
        grant=replace(grant, **grant_changes)
    verifier=auth.ResourceVerifier(issuer='https://issuer.invalid', resource='https://hermes.invalid/control/mcp',
                                  public_keys={'key-1':keys[1]}, grant_lookup=lambda sub,client: grant if (sub,client)==('human-1','codex') else None)
    return verifier,grant


def sign(keys, **changes):
    claims={'iss':'https://issuer.invalid','aud':'https://hermes.invalid/control/mcp',
            'sub':'human-1','client_id':'codex','iat':90,'nbf':90,'exp':200,
            'scope':'hermes:read hermes:run:start','grant_revision':1}
    claims.update(changes)
    return jwt.encode(claims,keys[0],algorithm='RS256',headers={'kid':'key-1','typ':'at+jwt'})


def test_valid_signed_resource_grant_and_server_scope_intersection(control_module,keys):
    verifier,_=setup(control_module,keys,grant_changes={'scopes':('hermes:read',)})
    token=sign(keys,scope='hermes:read hermes:run:start hermes:repo:merge')
    ctx=verifier.verify(token,now=100)
    assert ctx.scopes==('hermes:read',)
    assert ctx.workspaces == (('p1','w1'),)
    assert token not in repr(ctx)
    assert 'access_token' not in vars(ctx)


@pytest.mark.parametrize('changes', [
    {'aud':'https://dashboard.invalid'}, {'iss':'https://evil.invalid'}, {'exp':100},
    {'exp':True}, {'exp':'200'}, {'iat':110}, {'nbf':110}, {'client_id':'chatgpt'},
    {'grant_revision':0}, {'grant_revision':True}, {'scope':''}, {'scope':['hermes:read']},
    {'aud':['https://hermes.invalid/control/mcp','https://elsewhere.invalid']},
    {'sub':'foreign'}, {'exp':50000},
])
def test_invalid_claims_fail_closed(control_module,keys,changes):
    verifier,_=setup(control_module,keys)
    with pytest.raises(control_module('contracts').ControlError):
        verifier.verify(sign(keys,**changes),now=100)


@pytest.mark.parametrize('headers',[{'kid':'unknown'}, {'jku':'https://evil.invalid/keys'},
                                    {'jwk':{'kty':'oct','k':'bad'}}, {'alg':'HS256'}, {'crit':['something']}])
def test_header_cannot_choose_key_source_or_algorithm(control_module,keys,headers):
    verifier,_=setup(control_module,keys)
    payload=jwt.decode(sign(keys),options={'verify_signature':False})
    values={'kid':'key-1','typ':'at+jwt',**headers}
    key=keys[0] if values.get('alg','RS256')=='RS256' else b'test-only-secret-32-byte-key-00000000'
    token=jwt.encode(payload,key,algorithm=values.get('alg','RS256'),headers=values)
    with pytest.raises(control_module('contracts').ControlError):
        verifier.verify(token,now=100)


def test_revoked_grant_checked_on_every_request(control_module,keys):
    auth=control_module('auth')
    _,grant=setup(control_module,keys)
    current=[grant]
    verifier=auth.ResourceVerifier(issuer='https://issuer.invalid',resource='https://hermes.invalid/control/mcp',
                                  public_keys={'key-1':keys[1]},grant_lookup=lambda *a:current[0])
    assert verifier.verify(sign(keys),now=100)
    current[0]=replace(grant,enabled=False)
    with pytest.raises(control_module('contracts').ControlError):
        verifier.verify(sign(keys),now=100)
    current[0]=replace(grant,revision=2)
    with pytest.raises(control_module('contracts').ControlError):
        verifier.verify(sign(keys),now=100)


def test_unsigned_and_wrong_signature_never_authenticate(control_module,keys):
    verifier,_=setup(control_module,keys)
    values=jwt.decode(sign(keys),options={'verify_signature':False})
    for token in (jwt.encode(values,key='',algorithm='none'), sign((rsa.generate_private_key(public_exponent=65537,key_size=2048),keys[1]))):
        with pytest.raises(control_module('contracts').ControlError):
            verifier.verify(token,now=100)


def test_duplicate_claims_rejected_even_when_signature_is_valid(control_module,keys):
    from jwt.api_jws import PyJWS
    verifier,_=setup(control_module,keys)
    values=jwt.decode(sign(keys),options={'verify_signature':False})
    payload=json.dumps(values).replace('{','{"sub":"ignored",',1).encode()
    token=PyJWS().encode(payload,keys[0],algorithm='RS256',headers={'kid':'key-1','typ':'at+jwt'})
    with pytest.raises(control_module('contracts').ControlError):
        verifier.verify(token,now=100)


def test_error_messages_never_echo_bearer_or_provider_exception(control_module,keys):
    verifier,_=setup(control_module,keys)
    for token in ('synthetic-super-secret','x'*17000):
        with pytest.raises(control_module('contracts').ControlError) as caught:
            verifier.verify(token,now=100)
        assert token not in str(caught.value)


def test_in_process_expiry_scope_context_revalidated(control_module,keys):
    verifier,_=setup(control_module,keys)
    ctx=verifier.verify(sign(keys),now=100)
    verifier.revalidate(ctx,now=199)
    with pytest.raises(control_module('contracts').ControlError):
        verifier.revalidate(ctx,now=200)
