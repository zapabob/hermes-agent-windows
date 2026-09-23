"""Dedicated MCP-resource JWT validation; provider/dashboard tokens are not grants.

Keys and grants are supplied by the existing trusted host's operator-approved
configuration. No token store, dynamic discovery, network fetch, provider login
or secret refresh is performed. Test issuers do not establish client acceptance.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from urllib.parse import urlsplit

import jwt

from .contracts import ControlContext, ControlError, decode_request, valid_id


@dataclass(frozen=True)
class HostGrant:
    subject: str
    client_registration: str
    revision: int
    scopes: tuple[str, ...]
    profiles: tuple[str, ...]
    workspaces: tuple[tuple[str, str], ...]
    enabled: bool = True

    def __post_init__(self):
        # Reuse the strict credential-free identity shape; this is not a token.
        ControlContext(self.subject, self.client_registration, 'host', 'host',
                       self.revision, 0, self.scopes, self.profiles, self.workspaces)
        if type(self.enabled) is not bool:
            raise ControlError('invalid_host_configuration')


def _https_url(value: object) -> bool:
    if type(value) is not str or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return False
    parsed = urlsplit(value)
    return (parsed.scheme == 'https' and bool(parsed.hostname) and not parsed.username
            and not parsed.password and not parsed.fragment and not parsed.query)


class ResourceVerifier:
    def __init__(self, *, issuer: str, resource: str, public_keys: dict[str, bytes],
                 grant_lookup, max_token_lifetime: int = 3600):
        if (not _https_url(issuer) or not _https_url(resource) or not public_keys
                or type(max_token_lifetime) is not int or not 1 <= max_token_lifetime <= 3600):
            raise ControlError('invalid_host_configuration')
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        parsed_keys = {}
        try:
            for key_id, pem in public_keys.items():
                if not valid_id(key_id) or type(pem) is not bytes or b'PRIVATE' in pem:
                    raise ValueError('invalid_key')
                key = serialization.load_pem_public_key(pem)
                if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                    raise ValueError('invalid_key')
                parsed_keys[key_id] = key
        except (TypeError, ValueError):
            raise ControlError('invalid_host_configuration') from None
        self.issuer, self.resource = issuer, resource
        self._keys = MappingProxyType(parsed_keys)
        self._grant_lookup = grant_lookup
        self.max_token_lifetime = max_token_lifetime

    def _grant(self, subject, client) -> HostGrant:
        try:
            grant = self._grant_lookup(subject, client)
        except Exception:
            raise ControlError('auth_unavailable') from None
        if (type(grant) is not HostGrant or not grant.enabled or grant.subject != subject
                or grant.client_registration != client):
            raise ControlError('invalid_token')
        return grant

    def verify(self, token: str, *, now: float) -> ControlContext:
        if (type(token) is not str or not 1 <= len(token) <= 16_384
                or type(now) not in (int, float) or not math.isfinite(now)):
            raise ControlError('invalid_token')
        try:
            parts = token.split('.')
            if len(parts) != 3:
                raise ValueError('invalid_segments')
            header = decode_request(jwt.utils.base64url_decode(parts[0].encode()), limit=4096)
            # Strict JSON BEFORE validation prevents duplicate claim ambiguity.
            strict_claims = decode_request(jwt.utils.base64url_decode(parts[1].encode()), limit=16_384)
            if (set(header) - {'alg', 'kid', 'typ'} or header.get('alg') != 'RS256'
                    or header.get('typ') not in {'at+jwt', 'JWT'}
                    or header.get('kid') not in self._keys):
                raise ValueError('invalid_header')
            claims = jwt.decode(token, self._keys[header['kid']], algorithms=['RS256'],
                                issuer=self.issuer, audience=self.resource,
                                options={'require': ['iss','aud','sub','client_id','exp','iat','scope','grant_revision'],
                                         'verify_exp': False, 'verify_iat': False, 'verify_nbf': False})
            if claims != strict_claims or claims['aud'] != self.resource:
                raise ValueError('ambiguous_claims')
            exp, issued, nbf = claims['exp'], claims['iat'], claims.get('nbf', claims['iat'])
            if (any(type(v) is not int for v in (exp, issued, nbf, claims['grant_revision']))
                    or issued > now or nbf > now or now >= exp or exp <= issued
                    or exp - issued > self.max_token_lifetime):
                raise ValueError('invalid_time')
            if not valid_id(claims['sub']) or not valid_id(claims['client_id']):
                raise ValueError('invalid_identity')
            if type(claims['scope']) is not str:
                raise ValueError('invalid_scope')
            scopes = tuple(claims['scope'].split())
            if len(scopes) > 64 or not all(valid_id(v) for v in scopes):
                raise ValueError('invalid_scope')
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError):
            raise ControlError('invalid_token') from None
        grant = self._grant(claims['sub'], claims['client_id'])
        allowed = tuple(v for v in grant.scopes if v in scopes)
        if claims['grant_revision'] != grant.revision or 'hermes:read' not in allowed:
            raise ControlError('invalid_token')
        return ControlContext(grant.subject, grant.client_registration, self.issuer, self.resource,
                              grant.revision, exp, allowed, grant.profiles, grant.workspaces)

    def revalidate(self, ctx: ControlContext, *, now: float) -> None:
        """Recheck a live grant before an approved side effect, without token export."""
        if (type(ctx) is not ControlContext or ctx.issuer != self.issuer or ctx.resource != self.resource
                or type(now) not in (int, float) or not math.isfinite(now) or now >= ctx.expires_at):
            raise ControlError('expired_grant')
        grant = self._grant(ctx.subject, ctx.client_registration)
        if (grant.revision != ctx.grant_revision or not set(ctx.scopes) <= set(grant.scopes)
                or ctx.profiles != grant.profiles or ctx.workspaces != grant.workspaces):
            raise ControlError('revoked_grant')
