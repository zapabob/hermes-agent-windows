"""Throwaway TLS material for fake OAuth servers (subset of upstream's ``tests.fakes.providers.oauth_token_server``).

Only :func:`make_test_ca` is ported: plugin OAuth endpoints are https-only, so the fake IdP needs a certificate
a test can trust through an ``ssl.SSLContext`` (no real trust store is touched).
"""

from __future__ import annotations

import datetime
import ipaddress
from dataclasses import dataclass
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True)
class TestCA:
    """Paths of a freshly minted CA and the server leaf it signed (PEM files under the requested directory)."""

    __test__ = False  # not a pytest test class

    ca_pem: Path
    leaf_pem: Path
    leaf_key: Path


def _san(name: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(name))
    except ValueError:
        return x509.DNSName(name)


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_test_ca(directory: Path, names: list[str]) -> TestCA:
    """Write ``ca.pem``, ``leaf.pem`` and ``leaf.key`` under *directory*; the leaf is valid for *names*
    (DNS names or IP literals) and verifies under Python's strict X.509 checks."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    window = {"not_valid_before": now - datetime.timedelta(minutes=5), "not_valid_after": now + datetime.timedelta(days=1)}

    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_subject = _name("Hermes test CA")
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_subject).issuer_name(ca_subject).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(window["not_valid_before"]).not_valid_after(window["not_valid_after"])
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
            key_encipherment=False, data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(_name(names[0])).issuer_name(ca_subject).public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(window["not_valid_before"]).not_valid_after(window["not_valid_after"])
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([_san(n) for n in names]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    paths = TestCA(directory / "ca.pem", directory / "leaf.pem", directory / "leaf.key")
    paths.ca_pem.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    paths.leaf_pem.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    paths.leaf_key.write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return paths
